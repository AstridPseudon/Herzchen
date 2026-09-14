from __future__ import annotations

from pathlib import Path

from herzchen.authoring import AuthoringLifecycle
from herzchen.authoring.cleanup import cleanup_registered_files
from herzchen.authoring.finish import ValidationResult
from herzchen.authoring.sessions import AuthoringSessionService
from herzchen.authoring.snapshots import DurableSnapshotAdapter
from herzchen.contracts import AuthenticatedActor, AuthoringState, CleanupStatus, ResourceRef
from herzchen.kernel import Store


class _Handler:
    def validate(self, snapshot, checkout, checkout_root):
        return ValidationResult(True)

    def apply(self, snapshot, checkout, tx, writer):
        return {"digest": snapshot.digest}


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor("gf03-auth", "gf03-worker", "credential")


def _target(identifier: str) -> ResourceRef:
    return ResourceRef("gf03-store", "project", identifier, "base-1")


def _open(lifecycle: AuthoringLifecycle, target: ResourceRef, request_id: str):
    return lifecycle.open(target, _actor(), request_id=request_id, target_kind="project", base_revision="base-1", initial_content=b"initial")


def test_manual_late_write_is_recovery_and_fresh_retry_durably_preserves_it(tmp_path: Path):
    store = Store.create(tmp_path / "manual.sqlite", authority="gf03-store")
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store))
    root = tmp_path / "manual-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"captured")
    opened = _open(lifecycle, _target("manual"), "manual-open")

    def late_write(snapshot, **_):
        file.write_bytes(b"late-manual-bytes")

    try:
        result = lifecycle.finish(
            opened,
            request_id="manual-finish",
            mode="manual",
            checkout_root=root,
            registered_files=["draft.txt"],
            handler=_Handler(),
            quiesce=lambda: True,
            writer_check=lambda: True,
            capture_barrier=late_write,
        )
        assert result.finish.status == "recovery_pending"
        assert result.finish.recovery_pending
        assert result.cleanup is None
        assert file.read_bytes() == b"late-manual-bytes"
        record = store.get_identity(opened.handle.scope)
        assert record.payload["checkout"]["state"] == AuthoringState.RELEASED.value

        blocked = lifecycle.cleanup_released(
            opened,
            request_id="manual-retry-old-manifest",
            checkout_root=root,
            registered_files=["draft.txt"],
            writer_check=lambda: True,
        )
        assert blocked.status == CleanupStatus.UNSAFE
        assert file.read_bytes() == b"late-manual-bytes"

        recovered = lifecycle.cleanup_released(
            opened,
            request_id="manual-retry-fresh-capture",
            checkout_root=root,
            registered_files=["draft.txt"],
            quiesce=lambda: True,
            writer_check=lambda: True,
            fresh_capture=True,
        )
        assert recovered.status == CleanupStatus.COMPLETE, recovered.error
        assert not file.exists()
        record = store.get_identity(opened.handle.scope)
        assert record.payload["checkout"]["cleanup"] == CleanupStatus.COMPLETE.value
        final = DurableSnapshotAdapter(lifecycle.service).read(ResourceRef.from_dict(record.payload["final_snapshot_ref"]))
        assert final.file_bytes("draft.txt") == b"late-manual-bytes"
    finally:
        store.close()


def test_idle_late_write_uses_same_recovery_barrier_and_keeps_file(tmp_path: Path):
    store = Store.create(tmp_path / "idle.sqlite", authority="gf03-store")
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store), clock=lambda: 100.0)
    root = tmp_path / "idle-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"captured")
    opened = _open(lifecycle, _target("idle"), "idle-open")

    def late_write(snapshot, **_):
        file.write_bytes(b"late-idle-bytes")

    try:
        result = lifecycle.idle_close(
            opened,
            request_id="idle-finish",
            checkout_root=root,
            registered_files=["draft.txt"],
            handler=_Handler(),
            last_content_edit=1,
            now=100,
            inactivity_seconds=10,
            quiesce=lambda: True,
            writer_check=lambda: True,
            capture_barrier=late_write,
        )
        assert result.status == "recovery_pending"
        assert result.finish is not None and result.finish.finish.status == "recovery_pending"
        assert file.read_bytes() == b"late-idle-bytes"
        assert store.get_identity(opened.handle.scope).payload["checkout"]["cleanup"] == CleanupStatus.PENDING.value

        retry = lifecycle.idle.close_if_idle(
            opened.handle,
            request_id="idle-retry-fresh-capture",
            checkout_root=root,
            registered_files=["draft.txt"],
            quiesce=lambda: True,
            writer_check=lambda: True,
            fresh_capture=True,
        )
        assert retry.status == "closed_cleaned", retry.error
        assert not file.exists()
        record = store.get_identity(opened.handle.scope)
        final = DurableSnapshotAdapter(lifecycle.service).read(ResourceRef.from_dict(record.payload["final_snapshot_ref"]))
        assert final.file_bytes("draft.txt") == b"late-idle-bytes"
    finally:
        store.close()


def test_exact_manifest_rejects_in_place_late_write_during_cleanup(tmp_path: Path):
    late = {"enabled": False}

    def cleanup(root, entries, **kwargs):
        if not late["enabled"]:
            late["enabled"] = True
            (Path(root) / "draft.txt").write_bytes(b"late-after-commit")
        return cleanup_registered_files(root, entries, **kwargs)

    store = Store.create(tmp_path / "manifest.sqlite", authority="gf03-store")
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store), cleanup=cleanup)
    root = tmp_path / "manifest-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"old-captured")
    opened = _open(lifecycle, _target("manifest"), "manifest-open")
    try:
        result = lifecycle.finish(
            opened,
            request_id="manifest-finish",
            mode="manual",
            checkout_root=root,
            registered_files=["draft.txt"],
            handler=_Handler(),
            writer_check=lambda: True,
        )
        assert result.finish.status == "finished"
        assert result.cleanup is not None and result.cleanup.status == CleanupStatus.UNSAFE
        assert file.read_bytes() == b"late-after-commit"
        assert result.durable_cleanup is not None and result.durable_cleanup.cleanup == CleanupStatus.UNSAFE
    finally:
        store.close()


def test_missing_or_unknown_writer_state_blocks_deletion(tmp_path: Path):
    root = tmp_path / "writer-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"keep")
    unknown = cleanup_registered_files(root, [{"relative_path": "draft.txt", "sha256": "e" * 64, "size": 4}], writer_check=lambda: None)
    assert unknown.status == CleanupStatus.UNSAFE
    assert file.exists()


def test_unchanged_manual_and_idle_finish_still_persist_and_clean(tmp_path: Path):
    store = Store.create(tmp_path / "normal.sqlite", authority="gf03-store")
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store), clock=lambda: 100.0)
    try:
        for mode in ("manual", "idle"):
            root = tmp_path / (mode + "-normal")
            root.mkdir()
            file = root / "draft.txt"
            file.write_bytes((mode + " bytes").encode())
            opened = _open(lifecycle, _target("normal-" + mode), "normal-open-" + mode)
            if mode == "manual":
                result = lifecycle.finish(
                    opened, request_id="normal-finish-manual", mode=mode,
                    checkout_root=root, registered_files=["draft.txt"], handler=_Handler(),
                    quiesce=lambda: True, writer_check=lambda: True,
                )
                assert result.status == "finished"
                assert result.cleanup is not None and result.cleanup.status == CleanupStatus.COMPLETE
            else:
                result = lifecycle.idle_close(
                    opened, request_id="normal-finish-idle", checkout_root=root,
                    registered_files=["draft.txt"], handler=_Handler(), last_content_edit=1,
                    now=100, inactivity_seconds=10, quiesce=lambda: True,
                    writer_check=lambda: True,
                )
                assert result.status == "closed_cleaned"
                assert result.cleanup is not None and result.cleanup.status == CleanupStatus.COMPLETE
            assert not file.exists()
            assert store.get_identity(opened.handle.scope).payload["checkout"]["cleanup"] == CleanupStatus.COMPLETE.value
    finally:
        store.close()
