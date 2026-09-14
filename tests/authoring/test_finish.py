from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from herzchen.authoring.finish import SemanticFinishAdapter, ValidationResult
from herzchen.authoring.sessions import AuthoringSessionService, Snapshot, register_authoring
from herzchen.authoring.snapshots import DurableSnapshotAdapter
from herzchen.authoring.writer_lease import FileWriterLeaseAuthority
from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef
from herzchen.kernel import Store


class Handler:
    def __init__(self, valid: bool = True, fail_apply: bool = False) -> None:
        self.valid = valid
        self.fail_apply = fail_apply
        self.validated = 0
        self.applied = 0

    def validate(self, snapshot, checkout, checkout_root):
        self.validated += 1
        return ValidationResult(self.valid, {"error": "invalid draft"} if not self.valid else None)

    def apply(self, snapshot, checkout, tx, writer):
        self.applied += 1
        if self.fail_apply:
            raise RuntimeError("domain delta failed")
        return {"tree_digest": snapshot.tree_digest, "revision_ref": checkout.target_scope}


class FinishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "checkout"
        self.root.mkdir()
        (self.root / "project.json").write_bytes(b"{\"title\":\"draft\"}")
        self.db = Path(self.tempdir.name) / "store.sqlite3"
        self.store = Store.create(self.db)
        register_authoring(self.store)
        self.service = AuthoringSessionService(self.store)
        self.scope = ResourceRef("neutral-store", "project", "finish-project", "base-1")
        self.actor = AuthenticatedActor("auth", "finish-actor", "credential")
        self.writer_leases = FileWriterLeaseAuthority(
            Path(self.tempdir.name) / "locks", authority="finish-host",
            secret=b"finish-test-writer-authority-key!", writer_identities=("editor",),
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def test_valid_handler_applies_once_and_manual_idle_share_finish_boundary(self) -> None:
        opened = self.service.open(self.scope, self.actor, request_id="open", target_kind="project", base_revision="base-1", initial_content=b"initial")
        handler = Handler()
        adapter = SemanticFinishAdapter(self.service)
        with self.writer_leases.hold_retirement(self.root, owner_identity="editor") as guard:
            finished = adapter.finish(
                opened.handle,
                request_id="finish-manual", mode="manual", checkout_root=self.root,
                registered_files=["project.json"], handler=handler, retirement_guard=guard,
            )
            idle_loser = adapter.finish(
                opened.handle,
                request_id="finish-idle", mode="idle", checkout_root=self.root,
                registered_files=["project.json"], handler=Handler(), retirement_guard=guard,
            )
            replay = adapter.finish(
                opened.handle,
                request_id="finish-manual", mode="manual", checkout_root=self.root,
                registered_files=["project.json"], handler=handler, retirement_guard=guard,
            )
        self.assertEqual(finished.status, "finished")
        self.assertEqual(handler.applied, 1)
        self.assertEqual(idle_loser.status, "already_finished")
        self.assertEqual(replay.status, "replayed")
        self.assertEqual(handler.applied, 1)
        self.assertIsNotNone(finished.finish.receipt)

    def test_concurrent_manual_idle_race_has_one_application(self) -> None:
        opened = self.service.open(self.scope, self.actor, request_id="open", target_kind="project", base_revision="base-1", initial_content=b"initial")
        adapter = SemanticFinishAdapter(self.service)
        handler = Handler()
        barrier = threading.Barrier(2)
        results = []

        def contender(mode: str) -> None:
            barrier.wait()
            results.append(adapter.finish(
                opened.handle,
                request_id="race-" + mode,
                mode=mode,
                checkout_root=self.root,
                registered_files=["project.json"],
                handler=handler,
                retirement_guard=guard,
            ))

        with self.writer_leases.hold_retirement(self.root, owner_identity="editor") as guard:
            first = threading.Thread(target=contender, args=("manual",))
            second = threading.Thread(target=contender, args=("idle",))
            first.start()
            second.start()
            first.join(2)
            second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(sorted(result.status for result in results), ["already_finished", "finished"])
        self.assertEqual(handler.applied, 1)

    def test_validation_failure_preserves_rejected_bytes_and_diagnostics(self) -> None:
        opened = self.service.open(self.scope, self.actor, request_id="open", target_kind="project", base_revision="base-1", initial_content=b"initial")
        handler = Handler(valid=False)
        with self.writer_leases.hold_retirement(self.root, owner_identity="editor") as guard:
            result = SemanticFinishAdapter(self.service).finish(
                opened.handle, request_id="reject", mode="manual", checkout_root=self.root,
                registered_files=["project.json"], handler=handler, retirement_guard=guard,
            )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(handler.applied, 0)
        self.assertIn("invalid draft", result.error)
        self.assertEqual(self.service.read(self.scope).status, "available")
        self.assertEqual(DurableSnapshotAdapter(self.service).read(result.finish.final_snapshot.ref).file_bytes("project.json"), b"{\"title\":\"draft\"}")

    def test_application_failure_is_recovery_pending_without_success_receipt(self) -> None:
        opened = self.service.open(self.scope, self.actor, request_id="open", target_kind="project", base_revision="base-1", initial_content=b"initial")
        with self.writer_leases.hold_retirement(self.root, owner_identity="editor") as guard:
            result = SemanticFinishAdapter(self.service).finish(
                opened.handle, request_id="apply-fails", mode="manual", checkout_root=self.root,
                registered_files=["project.json"], handler=Handler(fail_apply=True), retirement_guard=guard,
            )
        self.assertEqual(result.status, "recovery_pending")
        self.assertTrue(result.recovery_pending)
        self.assertIsNone(self.store.get_receipt("apply-fails"))
        self.assertEqual(DurableSnapshotAdapter(self.service).read(result.finish.final_snapshot.ref).file_bytes("project.json"), b"{\"title\":\"draft\"}")

    def test_capture_failure_does_not_write_a_false_success(self) -> None:
        opened = self.service.open(self.scope, self.actor, request_id="open", target_kind="project", base_revision="base-1", initial_content=b"initial")
        with self.writer_leases.hold_retirement(self.root, owner_identity="editor") as guard:
            result = SemanticFinishAdapter(self.service).finish(
                opened.handle, request_id="capture-fails", mode="manual", checkout_root=self.root,
                registered_files=["missing.json"], handler=Handler(), retirement_guard=guard,
            )
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.recovery_pending)
        self.assertIsNone(self.store.get_receipt("capture-fails"))
        self.assertEqual(self.service.read(self.scope).status, "occupied")

    def test_direct_capture_failure_returns_actual_recovery_receipt(self) -> None:
        opened = self.service.open(self.scope, self.actor, request_id="direct-open", target_kind="project", base_revision="base-1", initial_content=b"initial")

        def fail_capture(*_args, **_kwargs):
            raise RuntimeError("direct capture failed")

        result = self.service.finish(opened.handle, request_id="direct-fails", mode="manual", capture=fail_capture)
        recovery_key = "direct-fails:capture-failure"
        recovery_receipt = self.store.get_receipt(recovery_key)
        self.assertEqual(result.status, "recovery_pending")
        self.assertTrue(result.recovery_pending)
        self.assertIsNotNone(result.receipt)
        self.assertEqual(result.receipt, recovery_receipt)
        self.assertIsNotNone(recovery_receipt)
        self.assertEqual(recovery_receipt.operation, "finish.recovery")
        self.assertIsNone(self.store.get_receipt("direct-fails"))
        self.assertTrue(any(event.event_id in recovery_receipt.event_ids and event.operation == "finish.recovery" for event in self.store.list_events()))

    def test_cleanup_refresh_replays_without_hashing_projection_or_fence(self) -> None:
        opened = self.service.open(self.scope, self.actor, request_id="refresh-open", target_kind="project", base_revision="base-1", initial_content=b"initial")
        self.service.release(opened.handle, request_id="refresh-release")
        refresh_root = Path(self.tempdir.name) / "refresh-checkout"
        refresh_root.mkdir()
        (refresh_root / "draft.txt").write_bytes(b"refresh bytes")
        snapshot_adapter = DurableSnapshotAdapter(self.service)
        captured = snapshot_adapter.capture(refresh_root, ["draft.txt"])
        snapshot = captured.as_session_snapshot(ResourceRef(self.store.authority, "authoring-snapshot", "refresh-final"))

        with self.writer_leases.hold_retirement(refresh_root, owner_identity="editor") as guard:
            first = self.service.refresh_final_snapshot(opened.handle, request_id="refresh", snapshot=snapshot, retirement_guard=guard)
            receipt = self.store.get_receipt("refresh")
            self.assertIsNotNone(receipt)
            before = (
                self.store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0],
                self.store.connection.execute("SELECT COUNT(*) FROM record_references").fetchone()[0],
                self.store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
                len(self.store.list_events()),
            )
            replay = self.service.refresh_final_snapshot(opened.handle, request_id="refresh", snapshot=snapshot, retirement_guard=guard)
            self.assertEqual(replay, first)
            self.assertEqual(self.store.get_receipt("refresh"), receipt)
            self.assertEqual((
                self.store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0],
                self.store.connection.execute("SELECT COUNT(*) FROM record_references").fetchone()[0],
                self.store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
                len(self.store.list_events()),
            ), before)
            with self.assertRaises(ReplayConflictError):
                self.service.refresh_final_snapshot(
                    opened.handle, request_id="refresh",
                    snapshot=Snapshot(snapshot.ref, b"changed bytes", snapshot.manifest),
                    retirement_guard=guard,
                )
            self.assertEqual((
                self.store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0],
                self.store.connection.execute("SELECT COUNT(*) FROM record_references").fetchone()[0],
                self.store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
                len(self.store.list_events()),
            ), before)


if __name__ == "__main__":
    unittest.main()
