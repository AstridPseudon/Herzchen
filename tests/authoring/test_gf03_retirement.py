from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from herzchen.authoring import AuthoringLifecycle, FileWriterLeaseAuthority, WriterLeaseError
from herzchen.authoring.cleanup import CleanupIdentityError, RegisteredFile, cleanup_registered_files
from herzchen.authoring.finish import ValidationResult
from herzchen.authoring.sessions import AuthoringSessionService, domain_contribution, register_authoring
from herzchen.authoring.snapshots import DurableSnapshotAdapter
from herzchen.contracts import AuthenticatedActor, AuthoringState, CleanupStatus, ResourceRef, canonical_json
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


def _exact(path: str, data: bytes) -> RegisteredFile:
    return RegisteredFile(path, hashlib.sha256(data).hexdigest(), len(data))


def _open(lifecycle: AuthoringLifecycle, target: ResourceRef, request_id: str):
    return lifecycle.open(target, _actor(), request_id=request_id, target_kind="project", base_revision="base-1", initial_content=b"initial")


def _authority(tmp_path: Path, *, secret: bytes = b"gf03-test-writer-authority-key!!") -> FileWriterLeaseAuthority:
    return FileWriterLeaseAuthority(
        tmp_path / "writer-locks", authority="gf03-host", secret=secret,
        writer_identities=("gf03-editor",),
    )


def _lifecycle(store: Store, tmp_path: Path, **kwargs) -> AuthoringLifecycle:
    return AuthoringLifecycle(
        AuthoringSessionService(store), writer_leases=_authority(tmp_path),
        writer_identity="gf03-editor", **kwargs,
    )


def _tamper_scope(store: Store, scope: ResourceRef, mutate) -> None:
    record = store.get_identity(scope)
    payload = json.loads(json.dumps(record.payload))
    mutate(payload)
    store.connection.execute(
        "UPDATE identities SET payload_json = ? WHERE authority = ? AND kind = ? AND id = ?",
        (canonical_json(payload), scope.authority, scope.kind, scope.id),
    )
    store.connection.commit()


def test_manual_late_write_is_recovery_and_fresh_retry_durably_preserves_it(tmp_path: Path):
    store = Store.create(tmp_path / "manual.sqlite", authority="gf03-store")
    register_authoring(store)
    lifecycle = _lifecycle(store, tmp_path)
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
    register_authoring(store)
    lifecycle = _lifecycle(store, tmp_path, clock=lambda: 100.0)
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

        retry = lifecycle.idle_close(
            opened,
            request_id="idle-retry-fresh-capture",
            checkout_root=root,
            registered_files=["draft.txt"],
            handler=_Handler(),
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
    register_authoring(store)
    lifecycle = _lifecycle(store, tmp_path, cleanup=cleanup)
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


def test_public_cleanup_without_writer_callback_blocks_exact_deletion(tmp_path: Path):
    root = tmp_path / "writer-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"keep")
    blocked = cleanup_registered_files(root, [_exact("draft.txt", b"keep")])
    assert blocked.status == CleanupStatus.UNSAFE
    assert blocked.remaining == ("draft.txt",)
    assert file.read_bytes() == b"keep"


def test_public_cleanup_with_unknown_writer_state_blocks_deletion(tmp_path: Path):
    root = tmp_path / "writer-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"keep")
    unknown = cleanup_registered_files(root, [_exact("draft.txt", b"keep")], writer_check=lambda: None)
    assert unknown.status == CleanupStatus.UNSAFE
    assert file.exists()


def test_public_cleanup_with_active_or_raising_writer_state_blocks_deletion(tmp_path: Path):
    for label, writer_check in (("active", lambda: "active"), ("raises", lambda: (_ for _ in ()).throw(RuntimeError("writer probe failed")))):
        root = tmp_path / ("writer-" + label)
        root.mkdir()
        file = root / "draft.txt"
        file.write_bytes(b"keep")
        blocked = cleanup_registered_files(root, [_exact("draft.txt", b"keep")], writer_check=writer_check)
        assert blocked.status == CleanupStatus.UNSAFE
        assert blocked.remaining == ("draft.txt",)
        assert file.read_bytes() == b"keep"


def test_public_cleanup_rejects_bare_or_partial_metadata_even_when_writer_quiescent(tmp_path: Path):
    for label, entry in (
        ("bare", "draft.txt"),
        ("missing-size", RegisteredFile("draft.txt", hashlib.sha256(b"keep").hexdigest(), None)),
        ("missing-digest", RegisteredFile("draft.txt", None, 4)),
    ):
        root = tmp_path / ("metadata-" + label)
        root.mkdir()
        file = root / "draft.txt"
        file.write_bytes(b"keep")
        with pytest.raises(CleanupIdentityError):
            cleanup_registered_files(root, [entry], writer_check=lambda: True)
        assert file.read_bytes() == b"keep"


def test_public_cleanup_deletes_only_exact_manifest_with_quiescent_writer(tmp_path: Path):
    root = tmp_path / "exact-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"exact")
    with _authority(tmp_path).hold_retirement(root, owner_identity="gf03-editor") as guard:
        entry = _exact("draft.txt", b"exact")
        manifest = (canonical_json({"relative_path": entry.relative_path, "size": entry.size, "sha256": entry.sha256}),)
        handle = SimpleNamespace(session_id="public", token="token", fence="fence")
        fence = guard.issue_fence(handle, manifest, snapshot_digest=entry.sha256)
        guard.authenticate_fence(fence, handle=handle, manifest=manifest, snapshot_digest=entry.sha256)
        result = cleanup_registered_files(
            root, [entry], retirement_guard=guard,
            writer_check=lambda: True,
        )
    assert result.status == CleanupStatus.COMPLETE, result.error
    assert result.deleted == ("draft.txt",)
    assert not file.exists()


def test_public_cleanup_with_held_but_unbound_guard_preserves_file(tmp_path: Path):
    root = tmp_path / "unbound-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"keep unbound")
    with _authority(tmp_path).hold_retirement(root, owner_identity="gf03-editor") as guard:
        result = cleanup_registered_files(
            root, [_exact("draft.txt", b"keep unbound")], retirement_guard=guard,
            writer_check=lambda: True,
        )
    assert result.status == CleanupStatus.UNSAFE
    assert file.read_bytes() == b"keep unbound"


def test_boolean_or_noop_object_cannot_impersonate_a_held_lease(tmp_path: Path):
    class _NoopGuard:
        def assert_held(self, *_):
            return None

        def assert_cleanup_manifest(self, *_):
            return None

    root = tmp_path / "forged-guard-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"keep forged")
    result = cleanup_registered_files(
        root, [_exact("draft.txt", b"keep forged")], retirement_guard=_NoopGuard(),
        writer_check=lambda: True,
    )
    assert result.status == CleanupStatus.UNSAFE
    assert file.read_bytes() == b"keep forged"


def test_unchanged_manual_and_idle_finish_still_persist_and_clean(tmp_path: Path):
    store = Store.create(tmp_path / "normal.sqlite", authority="gf03-store")
    register_authoring(store)
    lifecycle = _lifecycle(store, tmp_path, clock=lambda: 100.0)
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


@pytest.mark.parametrize(
    "label,tamper",
    (
        ("absent-manifest", lambda payload: payload.pop("retirement_manifest", None)),
        ("absent-fence", lambda payload: payload.pop("retirement_fence", None)),
        (
            "partial-manifest",
            lambda payload: payload.__setitem__(
                "retirement_manifest",
                [canonical_json({"relative_path": "draft.txt", "sha256": "0" * 64})],
            ),
        ),
        (
            "mismatched-fence",
            lambda payload: payload["retirement_fence"].__setitem__("session_id", "different-session"),
        ),
        (
            "partial-fence",
            lambda payload: payload["retirement_fence"].pop("manifest_count", None),
        ),
        (
            "unauthenticated-fence",
            lambda payload: payload["retirement_fence"].__setitem__("authentication", "0" * 64),
        ),
    ),
)
def test_invalid_durable_retirement_handoffs_never_complete_or_delete(tmp_path: Path, label, tamper):
    case = tmp_path / label
    case.mkdir()
    store = Store.create(case / "store.sqlite", authority="gf03-store")
    register_authoring(store)
    lifecycle = _lifecycle(store, case)
    root = case / "checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"durably captured")
    opened = _open(lifecycle, _target(label), "open-" + label)
    try:
        finished = lifecycle.finish(
            opened, request_id="finish-" + label, mode="manual", checkout_root=root,
            registered_files=["draft.txt"], handler=_Handler(), cleanup=False,
        )
        assert finished.status == "finished"
        _tamper_scope(store, opened.handle.scope, tamper)
        outcome = lifecycle.cleanup_released(
            opened, request_id="cleanup-" + label, checkout_root=root,
            registered_files=["draft.txt"],
        )
        assert outcome.status == CleanupStatus.UNSAFE
        assert file.read_bytes() == b"durably captured"
        assert store.get_identity(opened.handle.scope).payload["checkout"]["cleanup"] != CleanupStatus.COMPLETE.value
    finally:
        store.close()


def test_authentic_but_stale_fence_preserves_checkout(tmp_path: Path):
    now = {"value": 100.0}
    authority = FileWriterLeaseAuthority(
        tmp_path / "writer-locks", authority="stale-host",
        secret=b"stale-test-writer-authority-key!!", writer_identities=("editor",),
        fence_ttl_seconds=1.0, clock=lambda: now["value"],
    )
    store = Store.create(tmp_path / "stale.sqlite", authority="gf03-store")
    register_authoring(store)
    lifecycle = AuthoringLifecycle(
        AuthoringSessionService(store), writer_leases=authority, writer_identity="editor",
    )
    root = tmp_path / "stale-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"stale bytes")
    opened = _open(lifecycle, _target("stale"), "stale-open")
    try:
        assert lifecycle.finish(
            opened, request_id="stale-finish", mode="manual", checkout_root=root,
            registered_files=["draft.txt"], handler=_Handler(), cleanup=False,
        ).status == "finished"
        now["value"] = 102.0
        outcome = lifecycle.cleanup_released(
            opened, request_id="stale-cleanup", checkout_root=root,
            registered_files=["draft.txt"],
        )
        assert outcome.status == CleanupStatus.UNSAFE
        assert file.read_bytes() == b"stale bytes"
    finally:
        store.close()


def test_declared_unknown_or_unmanaged_writer_forces_unsafe_cleanup(tmp_path: Path):
    store = Store.create(tmp_path / "unmanaged.sqlite", authority="gf03-store")
    register_authoring(store)
    lifecycle = _lifecycle(store, tmp_path)
    root = tmp_path / "unmanaged-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"unmanaged bytes")
    opened = lifecycle.open(
        _target("unmanaged"), _actor(), request_id="unmanaged-open",
        target_kind="project", base_revision="base-1", initial_content=b"initial",
        unmanaged_writers=True,
    )
    try:
        result = lifecycle.finish(
            opened, request_id="unmanaged-finish", mode="manual", checkout_root=root,
            registered_files=["draft.txt"], handler=_Handler(),
        )
        assert result.status == "finished"
        assert result.cleanup is not None and result.cleanup.status == CleanupStatus.UNSAFE
        assert result.durable_cleanup is not None and result.durable_cleanup.cleanup == CleanupStatus.UNSAFE
        assert file.read_bytes() == b"unmanaged bytes"
    finally:
        store.close()


def test_restart_reacquisition_failure_is_explicit_and_preserves_bytes(tmp_path: Path):
    secret = b"restart-test-writer-authority-key!"
    authority = FileWriterLeaseAuthority(
        tmp_path / "writer-locks", authority="restart-host", secret=secret,
        writer_identities=("editor",),
    )
    db = tmp_path / "restart.sqlite"
    store = Store.create(db, authority="gf03-store")
    register_authoring(store)
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store), writer_leases=authority, writer_identity="editor")
    root = tmp_path / "restart-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"restart bytes")
    opened = _open(lifecycle, _target("restart"), "restart-open")
    assert lifecycle.finish(
        opened, request_id="restart-finish", mode="manual", checkout_root=root,
        registered_files=["draft.txt"], handler=_Handler(), cleanup=False,
    ).status == "finished"
    store.close()

    restarted = Store.open(db, authority="gf03-store", expected_domains=(domain_contribution(),))
    restarted_lifecycle = AuthoringLifecycle(
        AuthoringSessionService(restarted), writer_leases=authority, writer_identity="editor",
    )
    try:
        with authority.hold_retirement(root, owner_identity="editor"):
            blocked = restarted_lifecycle.cleanup_released(
                opened.handle, request_id="restart-blocked", checkout_root=root,
                registered_files=["draft.txt"],
            )
        assert blocked.status == CleanupStatus.UNSAFE
        assert "active" in (blocked.error or "") or "owned" in (blocked.error or "")
        assert file.read_bytes() == b"restart bytes"
    finally:
        restarted.close()


def test_restart_reestablishes_same_authenticated_authority_before_unlink(tmp_path: Path):
    secret = b"restart-success-writer-authority!"
    authority = FileWriterLeaseAuthority(
        tmp_path / "writer-locks", authority="restart-success-host", secret=secret,
        writer_identities=("editor",),
    )
    db = tmp_path / "restart-success.sqlite"
    store = Store.create(db, authority="gf03-store")
    register_authoring(store)
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store), writer_leases=authority, writer_identity="editor")
    root = tmp_path / "restart-success-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"restart success bytes")
    opened = _open(lifecycle, _target("restart-success"), "restart-success-open")
    assert lifecycle.finish(
        opened, request_id="restart-success-finish", mode="manual", checkout_root=root,
        registered_files=["draft.txt"], handler=_Handler(), cleanup=False,
    ).status == "finished"
    old_lease = store.get_identity(opened.handle.scope).payload["retirement_fence"]["lease_id"]
    store.close()

    restarted = Store.open(db, authority="gf03-store", expected_domains=(domain_contribution(),))
    try:
        recreated_authority = FileWriterLeaseAuthority(
            tmp_path / "writer-locks", authority="restart-success-host", secret=secret,
            writer_identities=("editor",),
        )
        recovered = AuthoringLifecycle(
            AuthoringSessionService(restarted), writer_leases=recreated_authority,
            writer_identity="editor",
        ).cleanup_released(
            opened.handle, request_id="restart-success-cleanup", checkout_root=root,
            registered_files=["draft.txt"],
        )
        assert recovered.status == CleanupStatus.COMPLETE, recovered.error
        assert not file.exists()
        record = restarted.get_identity(opened.handle.scope)
        assert record.payload["retirement_fence"]["lease_id"] != old_lease
        assert record.payload["checkout"]["cleanup"] == CleanupStatus.COMPLETE.value
    finally:
        restarted.close()


def test_cross_process_already_open_managed_descriptor_is_blocked_at_unlink_boundary(tmp_path: Path):
    secret = b"boundary-test-writer-authority-key"
    authority = FileWriterLeaseAuthority(
        tmp_path / "writer-locks", authority="boundary-host", secret=secret,
        writer_identities=("editor",),
    )
    root = tmp_path / "boundary-checkout"
    root.mkdir()
    file = root / "draft.txt"
    file.write_bytes(b"captured boundary bytes")
    child_code = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from herzchen.authoring import FileWriterLeaseAuthority, WriterLeaseError
        root, locks, secret_hex = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
        authority = FileWriterLeaseAuthority(locks, authority="boundary-host", secret=bytes.fromhex(secret_hex), writer_identities=("editor",))
        descriptor = authority.open_writer(root, "draft.txt", writer_identity="editor", flags=os.O_WRONLY)
        print("READY", flush=True)
        input()
        descriptor.seek(0)
        try:
            descriptor.write(b"late bytes that must not vanish")
            print("WROTE", flush=True)
        except WriterLeaseError as exc:
            print("BLOCKED:" + exc.__class__.__name__, flush=True)
        input()
        try:
            descriptor.seek(0)
            descriptor.write(b"post-retirement late bytes")
            print("WROTE_AFTER", flush=True)
        except WriterLeaseError as exc:
            print("REVOKED:" + exc.__class__.__name__, flush=True)
        descriptor.close()
        """
    )
    env = os.environ.copy()
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", child_code, str(root), str(tmp_path / "writer-locks"), secret.hex()],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    assert process.stdout.readline().strip() == "READY"
    observed = []

    def cleanup(root_value, entries, **kwargs):
        def boundary(_path):
            process.stdin.write("write\n")
            process.stdin.flush()
            observed.append(process.stdout.readline().strip())
            return True
        return cleanup_registered_files(root_value, entries, before_unlink=boundary, **kwargs)

    store = Store.create(tmp_path / "boundary.sqlite", authority="gf03-store")
    register_authoring(store)
    lifecycle = AuthoringLifecycle(
        AuthoringSessionService(store), cleanup=cleanup, writer_leases=authority,
        writer_identity="editor",
    )
    opened = _open(lifecycle, _target("boundary"), "boundary-open")
    try:
        result = lifecycle.finish(
            opened, request_id="boundary-finish", mode="manual", checkout_root=root,
            registered_files=["draft.txt"], handler=_Handler(),
        )
        assert result.cleanup is not None and result.cleanup.status == CleanupStatus.COMPLETE
        assert observed == ["BLOCKED:WriterLeaseUnavailable"]
        snapshot = DurableSnapshotAdapter(lifecycle.service).read(result.finish.finish.final_snapshot.ref)
        assert snapshot.file_bytes("draft.txt") == b"captured boundary bytes"
        process.stdin.write("retry\n")
        process.stdin.flush()
        assert process.stdout.readline().strip() == "REVOKED:WriterLeaseRevokedError"
        assert not file.exists()
    finally:
        process.stdin.close()
        process.wait(timeout=5)
        store.close()
