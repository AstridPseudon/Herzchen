from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from herzchen.authoring.cleanup import cleanup_registered_files
from herzchen.authoring.finish import SemanticFinishAdapter, ValidationResult
from herzchen.authoring.idle import IdleCloseService
from herzchen.authoring.sessions import AuthoringSessionService, InvalidSessionError
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
        unexpected = cleanup_registered_files(self.root, ["one.tmp"], writer_check=lambda: True)
        self.assertEqual(unexpected.status, CleanupStatus.UNSAFE)
        self.assertTrue((self.root / "one.tmp").exists())
        (self.root / "unexpected.tmp").unlink()
        outside = self.base / "outside.txt"
        outside.write_bytes(b"outside")
        (self.root / "link.tmp").symlink_to(outside)
        symlink = cleanup_registered_files(self.root, ["link.tmp"], writer_check=lambda: True)
        self.assertEqual(symlink.status, CleanupStatus.UNSAFE)
        self.assertTrue((self.root / "link.tmp").is_symlink())
        (self.root / "link.tmp").unlink()

        original = self.root
        moved = self.base / "moved-checkout"
        def swap(_):
            original.rename(moved)
            original.symlink_to(moved, target_is_directory=True)
            return True
        parent_swap = cleanup_registered_files(original, ["one.tmp"], writer_check=lambda: True, before_delete=swap)
        self.assertEqual(parent_swap.status, CleanupStatus.UNSAFE)
        self.assertTrue((moved / "one.tmp").exists())
        original.unlink()
        moved.rename(original)

    def test_partial_cleanup_is_retryable_and_does_not_mark_complete(self) -> None:
        (self.root / "one.tmp").write_bytes(b"one")
        (self.root / "two.tmp").write_bytes(b"two")
        def fail_second(path):
            return path != "two.tmp"
        partial = cleanup_registered_files(self.root, ["one.tmp", "two.tmp"], writer_check=lambda: True, before_delete=fail_second)
        self.assertEqual(partial.status, CleanupStatus.UNSAFE)
        self.assertEqual(partial.deleted, ("one.tmp",))
        self.assertEqual(partial.remaining, ("two.tmp",))
        retry = cleanup_registered_files(self.root, ["two.tmp"], writer_check=lambda: True)
        self.assertEqual(retry.status, CleanupStatus.COMPLETE)
        self.assertFalse((self.root / "two.tmp").exists())

if __name__ == "__main__":
    unittest.main()
