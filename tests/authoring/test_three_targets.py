"""EDT-05 conformance across the real DAT, WRK, and PKG owner APIs."""

from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from herzchen.authoring import AuthoringLifecycle, AuthoringTarget
from herzchen.authoring.snapshots import DurableSnapshotAdapter
from herzchen.authoring.sessions import AuthoringSessionService, InvalidSessionError
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision
from herzchen.content.authoring import DocumentAuthoringHandler, ScopeAuthorizationError
from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
from herzchen.domains.work import WorkGraph
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.model import WorkValidationError
from herzchen.kernel import Store
from herzchen.packs.authoring import (
    ExecutionPin,
    ManagedPack,
    ManagedPackAuthoringHandler,
    ManagedResource,
    ManagedSourceIdentity,
)


def _actor(name: str) -> AuthenticatedActor:
    return AuthenticatedActor("edt05-auth", name, "credential-" + name)


def _ref(authority: str, kind: str, ident: str, revision: str | None = None) -> ResourceRef:
    return ResourceRef(authority, kind, ident, revision)


def _json_file(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _document(authority: str, ident: str, *, scope: ResourceRef | None = None, imported: bool = False) -> ContentDocument:
    if imported:
        source = _ref("external", "runtime.document", ident, "source-1")
        return ContentDocument(
            _ref(authority, "project.specification", ident), "specification", "shared", "read",
            "external", source_ref=source, import_mode="pinned", writable=False,
        )
    return ContentDocument(
        _ref(authority, "project.specification", ident), "specification", "private", "append",
        "owner", authoring_scope=scope,
    )


def _pack(tmp_path: Path, authority: str) -> ManagedPack:
    root = tmp_path / "managed-pack"
    root.mkdir()
    manifest = root / "pack.yaml"
    manifest.write_text("schema_version: 2\nid: edt05-pack\nversion: 1.0.0\n", encoding="utf-8")
    content = b"one"
    resource = ManagedResource(
        "content/body.txt", "opaque", content, hashlib.sha256(content).hexdigest(),
        _ref("managed", "pack.resource", "body", "source-1"),
    )
    source = ManagedSourceIdentity(
        "edt05-pack", "managed", "a" * 40, "b" * 64, "c" * 64, "d" * 64,
        str(root), str(manifest),
    )
    return ManagedPack(
        "edt05-pack", "1.0.0", source, {"schema_version": 2}, (resource,),
        (ExecutionPin("edt05-pack/content/body.txt", "opaque", "a" * 40, resource.source_digest),), (),
    )


def test_all_real_targets_share_finish_idle_cleanup_and_owner_application(tmp_path: Path):
    store = Store.create(tmp_path / "all.sqlite", authority="edt05")
    graph = WorkGraph(store, actor=_actor("manager"))
    graph.register()
    batches = ProjectBatches(store, actor=_actor("manager"))
    content = ContentCommandHandler(store)
    pack_handler = ManagedPackAuthoringHandler(store)
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store))
    document_handler = DocumentAuthoringHandler(store, authoring=lifecycle.service)
    try:
        assert lifecycle.finish_adapter is lifecycle.idle.finish_adapter
        assert lifecycle.cleanup is lifecycle.idle._cleanup

        project = graph.create_project(title="EDT project", logical_request_key="project-create", actor=_actor("manager"))
        project_root = tmp_path / "project-checkout"
        project_root.mkdir()
        _json_file(project_root, "project.json", {"tasks": [{"id": "task-a", "title": "First"}]})
        opened_project = lifecycle.open(
            project.ref, _actor("manager"), request_id="project-open", target_kind="project-sheet",
            base_revision=project.revision, initial_content=b"{}",
        )
        project_finish = lifecycle.finish(
            opened_project, request_id="project-finish", mode="manual", checkout_root=project_root,
            registered_files=["project.json"], handler=batches.lifecycle_handler(project, authoring=lifecycle.service, handle=opened_project.handle, request_id="project-domain"),
        )
        assert project_finish.status == "finished", project_finish.finish.error
        assert project_finish.cleanup is not None and project_finish.cleanup.complete
        assert not (project_root / "project.json").exists()
        assert graph.list(project=project)
        assert graph.list(project=project)[0].title == "First"

        # Fresh replay has the same response and no second domain application.
        replay = lifecycle.finish(
            opened_project, request_id="project-finish", mode="manual", checkout_root=project_root,
            registered_files=[], handler=batches.lifecycle_handler(project, authoring=lifecycle.service, handle=opened_project.handle, request_id="project-domain"), cleanup=False,
        )
        assert replay.status == "replayed"

        doc = _document(store.authority, "doc-1", scope=project.ref)
        seed = ContentRevision(doc.ref, "rev-1", {"body": "before", "untouched": True}, _actor("seed"), initial=True)
        seed_context = TransactionContext(_actor("seed"), "doc-seed", "1" * 64, expected_version=0)
        content.execute(content.build_create_document(seed_context, doc, seed))
        document_root = tmp_path / "document-checkout"
        document_root.mkdir()
        _json_file(document_root, "document.json", {"content": {"body": "after", "untouched": True}})
        document_materialisation = document_handler.materialise(
            doc.ref, _actor("doc-author"), request_id="document-open",
            parent_scope=project.ref, base_revision="rev-1", initial_content=b"{}",
        )
        opened_document = AuthoringTarget(doc.ref, document_materialisation.scope, document_materialisation.open_result)
        document_owner = document_handler.lifecycle_handler(document_materialisation, request_id="document-domain")
        document_finish = lifecycle.finish(
            opened_document, request_id="document-finish", mode="manual", checkout_root=document_root,
            registered_files=["document.json"], handler=document_owner,
        )
        assert document_finish.status == "finished"
        assert document_handler.read(doc.ref)["content"]["revision"]["content"] == {"body": "after", "untouched": True}
        assert not (document_root / "document.json").exists()

        pack = _pack(tmp_path, store.authority)
        first = pack_handler.author(pack, {"content/body.txt": b"prior"}, logical_request_key="pack-prior", actor=_actor("pack-seed"))
        pack_root = tmp_path / "pack-checkout"
        pack_root.mkdir()
        _json_file(pack_root, "pack-content.json", {"updates": {"content/body.txt": base64.b64encode(b"current").decode("ascii")}})
        opened_pack = lifecycle.open(
            _ref(store.authority, "managed_pack", pack.pack_id), _actor("pack-author"),
            request_id="pack-open", target_kind="managed-pack", base_revision=first.revision,
            initial_content=b"{}",
        )
        pack_finish = lifecycle.finish(
            opened_pack, request_id="pack-finish", mode="manual", checkout_root=pack_root,
            registered_files=["pack-content.json"], handler=pack_handler.lifecycle_handler(pack, request_id="pack-domain"),
        )
        assert pack_finish.status == "finished"
        assert not (pack_root / "pack-content.json").exists()
        fresh = pack_handler.read(pack.pack_id)
        prior = pack_handler.read(pack.pack_id, revision=first.revision)
        assert fresh["execution_pins"] == prior["execution_pins"]
        assert prior["resources"]["content/body.txt"]["content_b64"] == base64.b64encode(b"prior").decode("ascii")
    finally:
        store.close()


def test_project_creation_and_reopen_share_handler_and_untouched_pending_is_retained(tmp_path: Path):
    store = Store.create(tmp_path / "pending.sqlite", authority="edt05-pending")
    actor = _actor("pending")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    batches = ProjectBatches(store, actor=actor)
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store))
    try:
        created = batches.create_pending_project(title="Blank", logical_request_key="blank-create", actor=actor)
        root = tmp_path / "blank-checkout"
        root.mkdir()
        _json_file(root, "project.json", {})
        opened = lifecycle.open(created.project.ref, actor, request_id="blank-open", target_kind="project-sheet", base_revision=created.project.revision, initial_content=b"{}", pending=True)
        result = lifecycle.idle_close(
            opened, request_id="blank-idle", checkout_root=root, registered_files=["project.json"],
            handler=batches.lifecycle_handler(created.project, authoring=lifecycle.service, handle=opened.handle, request_id="blank-domain"), inactivity_seconds=1,
            last_content_edit=0, now=10, quiesce=lambda: True, writer_check=lambda: True,
        )
        assert result.status == "closed_cleaned"
        assert not (root / "project.json").exists()
        saved = graph.get(created.project.ref)
        assert saved.payload["tasks"] == []
        assert saved.revision == created.project.revision

        # Existing/direct reopen uses the same lifecycle and an ordinary sheet.
        reopen_root = tmp_path / "reopen-checkout"
        reopen_root.mkdir()
        _json_file(reopen_root, "project.json", {"tasks": [{"id": "reopened", "title": "Reopened"}]})
        reopened = lifecycle.open(created.project.ref, actor, request_id="project-reopen", target_kind="project-sheet", base_revision=saved.revision, initial_content=b"{}")
        finished = lifecycle.finish(
            reopened, request_id="project-reopen-finish", mode="manual", checkout_root=reopen_root,
            registered_files=["project.json"], handler=batches.lifecycle_handler(created.project, authoring=lifecycle.service, handle=reopened.handle, request_id="reopen-domain"),
        )
        assert finished.status == "finished"
        assert graph.list(project=created.project)[0].title == "Reopened"
    finally:
        store.close()


def test_document_scope_rules_external_attachment_rejection_and_closed_fence(tmp_path: Path):
    store = Store.create(tmp_path / "scope.sqlite", authority="edt05-scope")
    content = ContentCommandHandler(store)
    service = AuthoringSessionService(store)
    document_handler = DocumentAuthoringHandler(store, authoring=service)
    lifecycle = AuthoringLifecycle(service)
    try:
        parent = _ref(store.authority, "work.project", "parent")
        private = _document(store.authority, "private", scope=parent)
        external = _document(store.authority, "external", imported=True)
        for doc in (private, external):
            revision = ContentRevision(doc.ref, "rev-1", {"body": "read"}, _actor("seed"), initial=True) if doc.import_mode == "owned" else None
            if revision:
                context = TransactionContext(_actor("seed"), "seed-" + doc.ref.id, "2" * 64, expected_version=0)
                content.execute(content.build_create_document(context, doc, revision))
        private_open = lifecycle.open(private.ref, _actor("private"), request_id="private-open", target_kind="document", scope=parent, base_revision="rev-1", initial_content=b"{}")
        assert private_open.scope == parent
        standalone = _document(store.authority, "standalone")
        standalone_revision = ContentRevision(standalone.ref, "rev-1", {"body": "standalone"}, _actor("seed"), initial=True)
        content.execute(content.build_create_document(TransactionContext(_actor("seed"), "seed-standalone", "3" * 64, expected_version=0), standalone, standalone_revision))
        assert document_handler.resolve_scope(standalone.ref) == _ref(store.authority, "document", "standalone")
        occupied = lifecycle.open(standalone.ref, _actor("private"), request_id="same-actor-second-scope", target_kind="document", base_revision="rev-1")
        assert occupied.opened.status == "actor_occupied"
        with pytest.raises(ScopeAuthorizationError):
            document_handler.materialise(private.ref, _actor("wrong"), request_id="wrong-parent", parent_scope=_ref(store.authority, "work.project", "other"), base_revision="rev-1")
        with pytest.raises(ScopeAuthorizationError, match="read-only"):
            document_handler.materialise(external, _actor("external"), request_id="external-open")
        service.release(private_open.handle, request_id="private-release")
        with pytest.raises(InvalidSessionError):
            service.authorize_mutation(private_open.handle, private.ref, token=private_open.handle.token, fence=private_open.handle.fence, expected_base_revision="rev-1")
    finally:
        store.close()


def test_wrk_direct_and_sheet_owner_path_reject_replay_and_preserve_unrelated_fields(tmp_path: Path):
    store = Store.create(tmp_path / "wrk.sqlite", authority="edt05-wrk")
    actor = _actor("wrk")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    batches = ProjectBatches(store, actor=actor)
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store))
    try:
        project = graph.create_project(title="WRK", logical_request_key="wrk-project", actor=actor)
        task = graph.create_task(project, title="Keep", fields={"untouched": "yes"}, logical_request_key="wrk-task", actor=actor)
        bad = {"tasks": [{"id": task.id, "title": ""}]}
        root = tmp_path / "wrk-checkout"
        root.mkdir()
        _json_file(root, "project.json", {"tasks": [{"id": task.id, "title": "Changed"}]})
        opened = lifecycle.open(project.ref, actor, request_id="wrk-open", target_kind="project-sheet", base_revision=project.revision, initial_content=b"{}")
        with pytest.raises(WorkValidationError):
            batches.apply_authoring_command(
                project, bad, authoring=lifecycle.service, handle=opened.handle,
                logical_request_key="bad-direct", actor=actor,
            )
        with pytest.raises(InvalidSessionError):
            batches.apply_authoring_command(
                project, {"tasks": [{"id": task.id, "title": "forged"}]},
                authoring=lifecycle.service, handle=replace(opened.handle, token="stale"),
                logical_request_key="bad-owner", actor=actor,
            )
        before = graph.get(task.ref)
        result = lifecycle.finish(
            opened, request_id="wrk-finish", mode="manual", checkout_root=root,
            registered_files=["project.json"],
            handler=batches.lifecycle_handler(project, authoring=lifecycle.service, handle=opened.handle, request_id="wrk-domain"),
        )
        assert result.status == "finished"
        after = graph.get(task.ref)
        assert after.title == "Changed"
        assert after.payload["fields"] == before.payload["fields"]
        replay = lifecycle.finish(
            opened, request_id="wrk-finish", mode="manual", checkout_root=root,
            registered_files=[], handler=batches.lifecycle_handler(project, authoring=lifecycle.service, handle=opened.handle, request_id="wrk-domain"), cleanup=False,
        )
        assert replay.status == "replayed"
        assert graph.get(task.ref).title == "Changed"
    finally:
        store.close()


def test_rejected_bytes_are_durable_and_no_success_receipt_or_unowned_change(tmp_path: Path):
    store = Store.create(tmp_path / "reject.sqlite", authority="edt05-reject")
    lifecycle = AuthoringLifecycle(AuthoringSessionService(store))
    actor = _actor("reject")
    root = tmp_path / "reject-checkout"
    root.mkdir()
    raw = b'{"updates":{"not-admitted":"bad"}}'
    (root / "pack-content.json").write_bytes(raw)
    pack = _pack(tmp_path, store.authority)
    handler = ManagedPackAuthoringHandler(store)
    opened = lifecycle.open(_ref(store.authority, "managed_pack", pack.pack_id), actor, request_id="reject-open", target_kind="managed-pack", base_revision="initial", initial_content=b"{}")
    try:
        result = lifecycle.finish(opened, request_id="reject-finish", mode="manual", checkout_root=root, registered_files=["pack-content.json"], handler=handler.lifecycle_handler(pack, request_id="reject-domain"))
        assert result.status == "rejected"
        assert result.finish.finish is not None and result.finish.finish.receipt is None
        assert (root / "pack-content.json").exists() is False
        snapshot = result.finish.snapshot
        assert snapshot is not None and snapshot.file_bytes("pack-content.json") == raw
        durable = DurableSnapshotAdapter(lifecycle.service).read(result.finish.finish.final_snapshot.ref)  # type: ignore[union-attr]
        assert durable.file_bytes("pack-content.json") == raw
        assert store.get_identity(_ref(store.authority, "managed_pack", pack.pack_id)) is None
    finally:
        store.close()


def test_shared_adapter_is_neutral_and_reuses_one_finish_boundary(tmp_path: Path):
    from herzchen.authoring import integration

    source = Path(integration.__file__).read_text(encoding="utf-8")
    assert "import sqlite3" not in source
    assert "CREATE TABLE" not in source
    assert "append_event" not in source
    assert "herzchen.content" not in source
    assert "herzchen.domains" not in source
    assert "herzchen.packs" not in source
    store = Store.create(tmp_path / "boundary.sqlite", authority="edt05-boundary")
    try:
        lifecycle = AuthoringLifecycle(AuthoringSessionService(store))
        assert lifecycle.finish_adapter is lifecycle.idle_service.finish_adapter
        assert lifecycle.cleanup is lifecycle.idle_service._cleanup
    finally:
        store.close()
