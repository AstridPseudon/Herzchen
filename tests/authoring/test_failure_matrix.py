from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest

from herzchen.authoring.cleanup import RegisteredFile, cleanup_registered_files
from herzchen.authoring.finish import SemanticFinishAdapter, ValidationResult
from herzchen.authoring.idle import IdleCloseService
from herzchen.authoring.sessions import AuthoringSessionService, InvalidSessionError, register_authoring
from herzchen.authoring.snapshots import DurableSnapshotAdapter
from herzchen.contracts import AuthenticatedActor, AuthoringState, CleanupStatus, ResourceRef
from herzchen.kernel import Store


class Handler:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.applied = 0

    def validate(self, snapshot, checkout, checkout_root):
        return ValidationResult(self.valid, {"diagnostic": "draft is invalid"} if not self.valid else None)

    def apply(self, snapshot, checkout, tx, writer):
        self.applied += 1
        return {"digest": snapshot.digest}


class FailureMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.root = self.base / "checkout"
        self.root.mkdir()
        self.db = self.base / "store.sqlite3"
        self.store = Store.create(self.db)
        register_authoring(self.store)
        self.service = AuthoringSessionService(self.store)
        self.finish = SemanticFinishAdapter(self.service)
        self.clock_value = 100.0
        self.idle = IdleCloseService(self.finish, clock=lambda: self.clock_value)
        self.actor = AuthenticatedActor("auth", "edt04-actor", "credential")
        self.scope = ResourceRef("neutral-store", "project", "edt04-project", "base-1")

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def open(self, *, initial=b"blank", pending=True):
        return self.service.open(
            self.scope,
            self.actor,
            request_id="open-" + str(self.clock_value),
            target_kind="project",
            base_revision="base-1",
            initial_content=initial,
            pending=pending,
        )

    @staticmethod
    def exact(path: str, data: bytes) -> RegisteredFile:
        return RegisteredFile(path, hashlib.sha256(data).hexdigest(), len(data))

    def test_idle_uses_last_content_edit_not_polling_and_untouched_blank_is_retained(self) -> None:
        (self.root / "draft.txt").write_bytes(b"blank")
        opened = self.open()
        self.assertEqual(self.idle.close_if_idle(
            opened.handle,
            request_id="idle-early",
            checkout_root=self.root,
            registered_files=["draft.txt"],
            last_content_edit=90,
            now=95,
            inactivity_seconds=10,
            quiesce=lambda: True,
            writer_check=lambda: True,
        ).status, "not_idle")
        result = self.idle.close_if_idle(
            opened.handle,
            request_id="idle-blank",
            checkout_root=self.root,
            registered_files=["draft.txt"],
            last_content_edit=90,
            now=101,
            inactivity_seconds=10,
            quiesce=lambda: True,
            writer_check=lambda: True,
        )
        self.assertEqual(result.status, "closed_cleaned")
        self.assertEqual(result.finish.finish.status, "pending_released")
        self.assertFalse((self.root / "draft.txt").exists())
        self.assertEqual(self.service.read(self.scope).status, "available")
        record = self.store.get_identity(opened.handle.scope)
        self.assertEqual(record.payload["checkout"]["state"], AuthoringState.RELEASED.value)
        self.assertEqual(record.payload["cleanup_outcome"], CleanupStatus.COMPLETE.value)

    def test_declared_content_edit_time_is_persisted_and_polling_does_not_refresh_it(self) -> None:
        opened = self.open()
        declared = self.idle.declare_content_edit(opened.handle, timestamp=40, request_id="edit-time")
        self.assertEqual(declared, 40.0)
        self.assertEqual(self.store.get_identity(opened.handle.scope).payload["last_content_edit_at"], 40.0)
        result = self.idle.close_if_idle(
            opened.handle,
            request_id="idle-time-check",
            checkout_root=self.root,
            registered_files=[],
            now=45,
            inactivity_seconds=10,
            quiesce=lambda: True,
            writer_check=lambda: True,
        )
        self.assertEqual(result.status, "not_idle")
        self.assertEqual(result.last_content_edit, 40.0)

    def test_edited_blank_follows_common_finish_and_late_token_is_fenced(self) -> None:
        (self.root / "draft.txt").write_bytes(b"edited blank")
        opened = self.open()
        handler = Handler()
        result = self.idle.close_if_idle(
            opened.handle,
            request_id="idle-edited",
            checkout_root=self.root,
            registered_files=["draft.txt"],
            handler=handler,
            last_content_edit=1,
            now=20,
            inactivity_seconds=10,
            quiesce=lambda: True,
            writer_check=lambda: True,
        )
        self.assertEqual(result.status, "closed_cleaned")
        self.assertEqual(result.finish.finish.status, "finished")
        self.assertEqual(handler.applied, 1)
        self.assertFalse((self.root / "draft.txt").exists())
        with self.assertRaises(InvalidSessionError):
            self.service.autosave(opened.handle, request_id="late", snapshot=b"late bytes")
        reopened = self.service.open(self.scope, self.actor, request_id="reopen", target_kind="project", base_revision="base-1", initial_content=b"new turn")
        self.assertEqual(reopened.status, "opened")
        self.assertNotEqual(reopened.handle.token, opened.handle.token)

    def test_cross_service_finish_loser_reconciles_durable_winner(self) -> None:
        """Separate service/adapter instances share one durable finish claim."""
        (self.root / "draft.txt").write_bytes(b"cross-service draft")
        opened = self.open(initial=b"initial", pending=False)
        service_a = AuthoringSessionService(self.store)
        service_b = AuthoringSessionService(self.store)
        adapter_a = SemanticFinishAdapter(service_a)
        adapter_b = SemanticFinishAdapter(service_b)
        validation_barrier = threading.Barrier(2)
        application_lock = threading.Lock()
        applied = []

        class ConcurrentHandler(Handler):
            def validate(self, snapshot, checkout, checkout_root):
                value = super().validate(snapshot, checkout, checkout_root)
                validation_barrier.wait(timeout=5)
                return value

            def apply(self, snapshot, checkout, tx, writer):
                with application_lock:
                    applied.append(snapshot.digest)
                return super().apply(snapshot, checkout, tx, writer)

        handler = ConcurrentHandler()
        results = []
        results_lock = threading.Lock()

        def contender(adapter, mode):
            result = adapter.finish(
                opened.handle,
                request_id="cross-service-" + mode,
                mode=mode,
                checkout_root=self.root,
                registered_files=["draft.txt"],
                handler=handler,
            )
            with results_lock:
                results.append((mode, result))

        first = threading.Thread(target=contender, args=(adapter_a, "manual"))
        second = threading.Thread(target=contender, args=(adapter_b, "idle"))
        first.start()
        second.start()
        first.join(10)
        second.join(10)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(sorted(result.status for _, result in results), ["already_finished", "finished"])
        self.assertEqual(len(applied), 1)

        record = self.store.get_identity(opened.handle.scope)
        checkout = record.payload["checkout"]
        self.assertEqual(checkout["state"], AuthoringState.FINISHED.value)
        self.assertEqual(checkout["finish_claim"]["finalization_identity"], "finish-" + opened.handle.session_id)
        self.assertEqual(record.payload["final_digest"], applied[0])
        self.assertEqual(record.payload["finish_request_id"], next(mode_result[1].finish.receipt.logical_request_key for mode_result in results if mode_result[1].status == "finished"))
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM command_receipts WHERE operation = 'finish'").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM events WHERE event_type = 'authoring.finish'").fetchone()[0], 1)

        winner_mode, winner = next(mode_result for mode_result in results if mode_result[1].status == "finished")
        replay = (adapter_a if winner_mode == "manual" else adapter_b).finish(
            opened.handle,
            request_id=winner.finish.receipt.logical_request_key,
            mode=winner_mode,
            checkout_root=self.root,
            registered_files=["draft.txt"],
            handler=handler,
        )
        self.assertEqual(replay.status, "replayed")

        (self.root / "draft.txt").write_bytes(b"changed input")
        changed = adapter_a.finish(
            opened.handle,
            request_id="cross-service-changed",
            mode="manual",
            checkout_root=self.root,
            registered_files=["draft.txt"],
            handler=handler,
        )
        self.assertNotIn(changed.status, {"finished", "already_finished"})
        self.assertTrue(changed.recovery_pending)

        (self.root / "draft.txt").write_bytes(b"cross-service draft")
        stale = replace(opened.handle, token="stale-token")
        stale_result = adapter_b.finish(
            stale,
            request_id="cross-service-stale",
            mode="idle",
            checkout_root=self.root,
            registered_files=["draft.txt"],
            handler=handler,
        )
        self.assertNotIn(stale_result.status, {"finished", "already_finished"})
        self.assertTrue(stale_result.recovery_pending)
        self.assertEqual(len(applied), 1)

    def test_invalid_idle_draft_is_durable_exact_and_cleanup_is_after_release(self) -> None:
        raw = b"malformed\x00draft"
        (self.root / "draft.txt").write_bytes(raw)
        opened = self.open(initial=b"initial")
        result = self.idle.close_if_idle(
            opened.handle,
            request_id="idle-invalid",
            checkout_root=self.root,
            registered_files=["draft.txt"],
            handler=Handler(valid=False),
            last_content_edit=1,
            now=20,
            inactivity_seconds=10,
            quiesce=lambda: True,
            writer_check=lambda: True,
        )
        self.assertEqual(result.status, "closed_cleaned")
        self.assertEqual(result.finish.finish.status, "rejected")
        self.assertIn("draft is invalid", result.error)
        self.assertFalse((self.root / "draft.txt").exists())
        snapshot = DurableSnapshotAdapter(self.service).read(result.finish.finish.final_snapshot.ref)
        self.assertEqual(snapshot.file_bytes("draft.txt"), raw)
        self.assertEqual(self.service.read(self.scope).status, "available")
        self.assertEqual(self.store.get_identity(opened.handle.scope).payload["checkout"]["state"], AuthoringState.REJECTED.value)

    def test_writer_uncertainty_and_capture_failure_preserve_files_and_slot_is_not_reacquired(self) -> None:
        (self.root / "draft.txt").write_bytes(b"raw bytes")
        opened = self.open(initial=b"initial")
        active = self.idle.close_if_idle(
            opened.handle,
            request_id="idle-active",
            checkout_root=self.root,
            registered_files=["draft.txt"],
            last_content_edit=1,
            now=20,
            inactivity_seconds=10,
            quiesce=lambda: "unknown",
            writer_check=lambda: "unknown",
        )
        self.assertEqual(active.status, "writer_active")
        self.assertTrue((self.root / "draft.txt").exists())
        failed = self.idle.close_if_idle(
            opened.handle,
            request_id="idle-capture-fail",
            checkout_root=self.root,
            registered_files=["missing.txt"],
            last_content_edit=1,
            now=20,
            inactivity_seconds=10,
            quiesce=lambda: True,
            writer_check=lambda: True,
        )
        self.assertEqual(failed.status, "recovery_pending")
        self.assertTrue(failed.recovery_pending)
        self.assertTrue((self.root / "draft.txt").exists())
        self.assertEqual(self.service.read(self.scope).status, "occupied")

    def test_cleanup_rejects_unexpected_files_symlink_and_parent_swap(self) -> None:
        (self.root / "one.tmp").write_bytes(b"one")
        (self.root / "unexpected.tmp").write_bytes(b"keep")
        unexpected = cleanup_registered_files(self.root, [self.exact("one.tmp", b"one")], writer_check=lambda: True)
        self.assertEqual(unexpected.status, CleanupStatus.UNSAFE)
        self.assertTrue((self.root / "one.tmp").exists())
        (self.root / "unexpected.tmp").unlink()
        outside = self.base / "outside.txt"
        outside.write_bytes(b"outside")
        (self.root / "link.tmp").symlink_to(outside)
        symlink = cleanup_registered_files(self.root, [self.exact("link.tmp", b"outside")], writer_check=lambda: True)
        self.assertEqual(symlink.status, CleanupStatus.UNSAFE)
        self.assertTrue((self.root / "link.tmp").is_symlink())
        (self.root / "link.tmp").unlink()

        original = self.root
        moved = self.base / "moved-checkout"
        def swap(_):
            original.rename(moved)
            original.symlink_to(moved, target_is_directory=True)
            return True
        parent_swap = cleanup_registered_files(original, [self.exact("one.tmp", b"one")], writer_check=lambda: True, before_delete=swap)
        self.assertEqual(parent_swap.status, CleanupStatus.UNSAFE)
        self.assertTrue((moved / "one.tmp").exists())
        original.unlink()
        moved.rename(original)

    def test_partial_cleanup_is_retryable_and_does_not_mark_complete(self) -> None:
        (self.root / "one.tmp").write_bytes(b"one")
        (self.root / "two.tmp").write_bytes(b"two")
        def fail_second(path):
            return path != "two.tmp"
        partial = cleanup_registered_files(
            self.root,
            [self.exact("one.tmp", b"one"), self.exact("two.tmp", b"two")],
            writer_check=lambda: True,
            before_delete=fail_second,
        )
        self.assertEqual(partial.status, CleanupStatus.UNSAFE)
        self.assertEqual(partial.deleted, ("one.tmp",))
        self.assertEqual(partial.remaining, ("two.tmp",))
        retry = cleanup_registered_files(self.root, [self.exact("two.tmp", b"two")], writer_check=lambda: True)
        self.assertEqual(retry.status, CleanupStatus.COMPLETE)
        self.assertFalse((self.root / "two.tmp").exists())

if __name__ == "__main__":
    unittest.main()
