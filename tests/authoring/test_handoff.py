"""EDT-06 executable handoff evidence over the accepted EDT-05 mechanics."""

from __future__ import annotations

import json
import os
from base64 import b64decode
from pathlib import Path
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from herzchen.authoring import AuthoringLifecycle, CallableSemanticHandler
from herzchen.authoring.cleanup import CleanupPathError, CleanupStatus, RegisteredFile, cleanup_registered_files
from herzchen.authoring.sessions import AuthoringSessionService
from herzchen.authoring.snapshots import DurableSnapshotAdapter
from herzchen.contracts import AuthenticatedActor, AuthoringState, ResourceRef
from herzchen.kernel import Store


def _actor(name: str) -> AuthenticatedActor:
    return AuthenticatedActor("edt06-auth", name, "credential-" + name)


class _Handler:
    def __init__(self) -> None:
        self.applied = 0

    def validate(self, snapshot, checkout, checkout_root):
        return True

    def apply(self, snapshot, checkout, tx, writer):
        self.applied += 1
        return {"digest": snapshot.digest}


def _target(authority: str, ident: str) -> ResourceRef:
    return ResourceRef(authority, "handoff-target", ident, "base-1")


def test_deterministic_idle_clock_and_actual_timer_fixture(tmp_path: Path) -> None:
    db = tmp_path / "timer.sqlite"
    store = Store.create(db, authority="edt06-timer")
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store))
    actor = _actor("timer")
    target = _target(store.authority, "timer-target")
    root = tmp_path / "timer-checkout"
    root.mkdir()
    (root / "draft.txt").write_bytes(b"timer bytes")
    try:
        opened = lifecycle.open(target, actor, request_id="timer-open", target_kind="document", initial_content=b"initial")
        deterministic = lifecycle.idle.close_if_idle(
            opened.handle,
            request_id="timer-not-idle",
            checkout_root=root,
            registered_files=["draft.txt"],
            handler=_Handler(),
            last_content_edit=100.0,
            now=105.0,
            inactivity_seconds=10.0,
            quiesce=lambda: True,
            writer_check=lambda: True,
        )
        assert deterministic.status == "not_idle"
        assert deterministic.idle_seconds == 5.0
        assert (root / "draft.txt").exists()

        done = threading.Event()
        holder = {}

        def timer_close() -> None:
            holder["result"] = lifecycle.idle.close_if_idle(
                opened.handle,
                request_id="timer-actual-close",
                checkout_root=root,
                registered_files=["draft.txt"],
                handler=_Handler(),
                last_content_edit=time.time() - 1.0,
                inactivity_seconds=0.01,
                quiesce=lambda: True,
                writer_check=lambda: True,
            )
            done.set()

        timer = threading.Timer(0.05, timer_close)
        timer.start()
        assert done.wait(2.0)
        timer.join(2.0)
        result = holder["result"]
        assert result.status == "closed_cleaned", result.error
        assert result.cleanup is not None and result.cleanup.status == CleanupStatus.COMPLETE
        assert not (root / "draft.txt").exists()
        assert store.get_identity(opened.handle.scope).payload["checkout"]["state"] == AuthoringState.FINISHED.value
    finally:
        store.close()


def test_failed_cleanup_is_durable_and_retry_removes_only_registered_files(tmp_path: Path) -> None:
    db = tmp_path / "recovery.sqlite"
    store = Store.create(db, authority="edt06-recovery")
    service = AuthoringSessionService(store)
    lifecycle = AuthoringLifecycle(service)
    actor = _actor("recovery")
    target = _target(store.authority, "recovery-target")
    root = tmp_path / "recovery-checkout"
    root.mkdir()
    registered = root / "registered.tmp"
    unmanaged = root / "unmanaged.tmp"
    registered.write_bytes(b"durable registered bytes")
    try:
        opened = lifecycle.open(target, actor, request_id="recovery-open", target_kind="document", initial_content=b"initial")
        finished = lifecycle.finish(
            opened,
            request_id="recovery-finish",
            mode="manual",
            checkout_root=root,
            registered_files=["registered.tmp"],
            handler=CallableSemanticHandler(_Handler().validate, _Handler().apply),
            writer_check=lambda: "active",
        )
        assert finished.status == "finished"
        assert finished.cleanup is not None
        assert finished.cleanup.status == CleanupStatus.UNSAFE
        assert finished.durable_cleanup is not None
        assert finished.durable_cleanup.cleanup == CleanupStatus.UNSAFE
        assert registered.read_bytes() == b"durable registered bytes"
        record = store.get_identity(opened.handle.scope)
        assert record.payload["checkout"]["state"] == AuthoringState.FINISHED.value
        assert record.payload["cleanup_outcome"] == CleanupStatus.UNSAFE.value

        unmanaged.write_bytes(b"unmanaged execution materialisation")
        # The first retry is fail-closed because an unmanaged file remains.
        blocked = lifecycle.cleanup_released(
            opened,
            request_id="recovery-retry-blocked",
            checkout_root=root,
            registered_files=["registered.tmp"],
            writer_check=lambda: True,
        )
        assert blocked.status == CleanupStatus.UNSAFE
        assert registered.exists() and unmanaged.exists()

        unmanaged.unlink()
        recovered = lifecycle.cleanup_released(
            opened,
            request_id="recovery-retry-complete",
            checkout_root=root,
            registered_files=["registered.tmp"],
            writer_check=lambda: True,
        )
        assert recovered.status == CleanupStatus.COMPLETE
        assert not registered.exists()
        assert not unmanaged.exists()
        after = store.get_identity(opened.handle.scope)
        assert after.payload["checkout"]["cleanup"] == CleanupStatus.COMPLETE.value
        final_ref = finished.finish.finish.final_snapshot.ref
        store.close()
        restarted = Store.open(db, authority="edt06-recovery")
        restarted_service = AuthoringSessionService(restarted)
        assert restarted_service.read(target).status == "available"
        restarted_record = restarted.get_identity(opened.handle.scope)
        assert restarted_record.payload["cleanup_outcome"] == CleanupStatus.COMPLETE.value
        assert DurableSnapshotAdapter(restarted_service).read(final_ref).file_bytes("registered.tmp") == b"durable registered bytes"

        # The public API persists opening/autosave/final bytes only; a
        # consumer's unsubmitted in-memory buffer is not recoverable.
        unsaved_target = _target(restarted.authority, "unsaved-target")
        unsaved = restarted_service.open(
            unsaved_target,
            actor,
            request_id="unsaved-open",
            target_kind="document",
            initial_content=b"opening bytes",
        )
        restarted.close()
        reopened_unsaved = Store.open(db, authority="edt06-recovery")
        unsaved_service = AuthoringSessionService(reopened_unsaved)
        unsaved_record = reopened_unsaved.get_identity(unsaved.handle.scope)
        assert unsaved_service.read(unsaved_target).status == "occupied"
        assert b64decode(unsaved_record.payload["draft_bytes_b64"]) == b"opening bytes"
        assert b"memory-only edit" not in b64decode(unsaved_record.payload["draft_bytes_b64"])
        unsaved_service.release(unsaved.handle, request_id="unsaved-release")
        store = reopened_unsaved

        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"outside")
        symlink = root / "pinned-execution.bin"
        symlink.symlink_to(outside)
        with pytest.raises(CleanupPathError):
            cleanup_registered_files(root, ["../outside.bin"])
        unsafe = cleanup_registered_files(root, [RegisteredFile("pinned-execution.bin", "0" * 64, 0)], writer_check=lambda: True)
        assert unsafe.status == CleanupStatus.UNSAFE
        assert symlink.is_symlink()
        assert outside.read_bytes() == b"outside"
    finally:
        store.close()


@pytest.mark.skipif("site-packages" not in str(Path(__import__("herzchen").__file__).resolve()), reason="fresh-process proof runs in the disposable installed wheel")
def test_fresh_consumer_process_and_restart_read_exact_durable_links(tmp_path: Path) -> None:
    db = tmp_path / "process.sqlite"
    root = tmp_path / "process-checkout"
    root.mkdir()
    writer_code = textwrap.dedent(
        """
        import json, sys
        from pathlib import Path
        from herzchen.authoring import AuthoringLifecycle
        from herzchen.authoring.sessions import AuthoringSessionService
        from herzchen.contracts import AuthenticatedActor, ResourceRef
        from herzchen.kernel import Store

        class Handler:
            def validate(self, snapshot, checkout, checkout_root):
                return True
            def apply(self, snapshot, checkout, tx, writer):
                return {"accepted": snapshot.digest}

        db, root = map(Path, sys.argv[1:])
        store = Store.create(db, authority="edt06-process")
        service = AuthoringSessionService(store)
        lifecycle = AuthoringLifecycle(service)
        actor = AuthenticatedActor("edt06-auth", "process-writer", "credential-process-writer")
        target = ResourceRef("edt06-process", "handoff-target", "process-target", "base-1")
        opened = lifecycle.open(target, actor, request_id="process-open", target_kind="document", initial_content=b"initial")
        (root / "registered.tmp").write_bytes(b"persisted process bytes")
        result = lifecycle.finish(opened, request_id="process-finish", mode="manual", checkout_root=root, registered_files=["registered.tmp"], handler=Handler(), writer_check=lambda: True)
        receipt = result.receipt
        final = result.finish.finish.final_snapshot
        record = store.get_identity(opened.handle.scope)
        events = store.list_events(stream="authoring:" + opened.handle.scope.id)
        print(json.dumps({
            "status": result.status,
            "cleanup": result.cleanup.status,
            "state": record.payload["checkout"]["state"],
            "path_exists": (root / "registered.tmp").exists(),
            "snapshot_ref": final.ref.to_dict(),
            "snapshot_digest": final.digest,
            "receipt": receipt.to_dict(),
            "receipt_event_ids": list(receipt.event_ids),
            "event_ids": [event.event_id for event in events],
            "receipt_event_after_refs": [
                ref.to_dict() for event in events if event.event_id == receipt.event_ids[0] for ref in event.after_refs
            ],
        }, sort_keys=True))
        store.close()
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    writer = subprocess.run(
        [sys.executable, "-B", "-c", writer_code, str(db), str(root)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    written = json.loads(writer.stdout)
    assert written["status"] == "finished"
    assert written["cleanup"] == "complete"
    assert written["state"] == AuthoringState.FINISHED.value
    assert written["path_exists"] is False
    assert written["receipt_event_ids"][0] in written["event_ids"]

    reader_code = textwrap.dedent(
        """
        import json, sys
        from pathlib import Path
        from herzchen.authoring.snapshots import DurableSnapshotAdapter
        from herzchen.authoring.sessions import AuthoringSessionService
        from herzchen.contracts import ResourceRef
        from herzchen.kernel import Store

        db = Path(sys.argv[1])
        snapshot_ref = ResourceRef.from_dict(json.loads(sys.argv[2]))
        scope = ResourceRef("edt06-process", "handoff-target", "process-target", "base-1")
        store = Store.open(db, authority="edt06-process")
        service = AuthoringSessionService(store)
        read = service.read(scope)
        record = store.get_identity(ResourceRef("edt06-process", "authoring-scope", scope.id))
        snapshot = DurableSnapshotAdapter(service).read(snapshot_ref)
        receipt = store.get_receipt("process-finish")
        events = store.list_events(stream="authoring:" + scope.id)
        print(json.dumps({
            "read_status": read.status,
            "state": record.payload["checkout"]["state"],
            "cleanup": record.payload["cleanup_outcome"],
            "snapshot_bytes": snapshot.file_bytes("registered.tmp").decode("utf-8"),
            "snapshot_ref": snapshot.ref.to_dict(),
            "receipt_status": receipt.status.value,
            "receipt_event_ids": list(receipt.event_ids),
            "event_ids": [event.event_id for event in events],
            "receipt_event_after_refs": [
                ref.to_dict() for event in events if event.event_id == receipt.event_ids[0] for ref in event.after_refs
            ],
        }, sort_keys=True))
        store.close()
        """
    )
    reader = subprocess.run(
        [sys.executable, "-B", "-c", reader_code, str(db), json.dumps(written["snapshot_ref"], sort_keys=True)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    reread = json.loads(reader.stdout)
    assert reread["read_status"] == "available"
    assert reread["state"] == AuthoringState.FINISHED.value
    assert reread["cleanup"] == CleanupStatus.COMPLETE.value
    assert reread["snapshot_bytes"] == "persisted process bytes"
    assert reread["snapshot_ref"] == written["snapshot_ref"]
    assert reread["receipt_status"] == "committed"
    assert reread["receipt_event_ids"] == written["receipt_event_ids"]
    assert reread["event_ids"] == written["event_ids"]
    assert reread["receipt_event_after_refs"] == written["receipt_event_after_refs"]
