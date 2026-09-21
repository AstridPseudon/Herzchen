"""Focused WRK-03 whole-project batch and pending-project proof."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef
from herzchen.domains.work import Lifecycle, WorkGraph, WorkNotFoundError
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.kernel import Store, VersionConflictError


@pytest.fixture
def environment(tmp_path: Path):
    store = Store.create(tmp_path / "batches.sqlite", authority="wrk-test")
    actor = AuthenticatedActor("wrk-test", "manager", "credential")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(title="Batch proof", logical_request_key="project")
    try:
        yield store, actor, graph, project
    finally:
        store.close()


def test_parent_sheet_is_atomic_replay_safe_and_retains_observations(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    assignments = ResponsibilityAssignments(store, actor=actor)
    task = graph.create_task(project, title="Existing", fields={"keep": True}, logical_request_key="existing")
    assignment = assignments.assign(task, role="execution", principal="worker", logical_request_key="assignment")
    result = assignments.append_result(assignment, {"worker": "result"}, logical_request_key="result")
    sheet = {
        "metadata": {"namespace_key": "retained"},
        "metadata_namespace": {"review": {"required": True}},
        "document_changes": [{"document": "spec", "revision": "r1", "content": {"body": "exact"}, "scope": project.id}],
        "documents": [{"namespace": "work", "key": "spec", "document_ref": "spec", "binding": "pinned", "revision_ref": {"authority": store.authority, "kind": "dat.content.document", "id": "spec", "revision": "r1"}}],
        "tasks": [
            {"id": task.id, "title": "Existing revised", "fields": {"new": "value"}, "order": 2},
            {"id": "new-task", "title": "New task", "body": {"instructions": "do"}, "order": 1, "dependencies": [task.id]},
        ],
    }
    applied = batches.apply_project_sheet(project, sheet, logical_request_key="sheet")
    assert applied.receipt.logical_request_key == "sheet"
    assert len(applied.mappings) == 2
    assert applied.project.payload["metadata"]["namespace_key"] == "retained"
    assert applied.project.payload["metadata_namespaces"]["review"]["required"] is True
    revised = graph.get(task.ref)
    assert revised.title == "Existing revised"
    assert revised.payload["fields"] == {"keep": True, "new": "value"}
    assert assignments.list_observations(assignment)[0].value == result.value

    replay = batches.apply_project_sheet(project, sheet, logical_request_key="sheet")
    assert replay.project.ref == applied.project.ref
    assert len(store.list_events()) == 5  # child rows are composed under the one parent event
    with pytest.raises(ReplayConflictError):
        batches.apply_project_sheet(project, {"tasks": [{"id": task.id, "title": "changed"}]}, logical_request_key="sheet")
    assert store.get_receipt("sheet") is not None


def test_sheet_replay_precedes_stale_base_after_advance_and_changed_base_has_no_effect(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    sheet = {"tasks": [{"id": "replay-task", "title": "Original"}]}
    original_base = project.ref.revision
    applied = batches.apply_project_sheet(
        project,
        sheet,
        logical_request_key="advance-replay",
        base_revision=original_base,
    )
    batch_event = next(event for event in store.list_events() if event.event_id in applied.receipt.event_ids)
    assert batch_event.effects["request_context"]["expected_revision"] == original_base
    advanced = graph.revise(applied.project, outcome="intervening state", logical_request_key="intervening")
    before = store.consumer().snapshot_counts()

    replay = batches.apply_project_sheet(
        project,
        sheet,
        logical_request_key="advance-replay",
        base_revision=original_base,
    )
    assert replay.receipt == applied.receipt
    assert replay.mappings == applied.mappings
    assert store.consumer().snapshot_counts() == before

    with pytest.raises(ReplayConflictError):
        batches.apply_project_sheet(
            project,
            sheet,
            logical_request_key="advance-replay",
            base_revision=advanced.ref.revision,
        )
    assert store.consumer().snapshot_counts() == before
    assert store.get_receipt("advance-replay") == applied.receipt


def test_semantic_authoring_uses_original_checkout_base_for_project_cas(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    base = project.ref.revision
    handle = SimpleNamespace(base_revision=base, token="token", fence="fence")

    class Authoring:
        def authorize_mutation(self, *_args, **_kwargs):
            return SimpleNamespace(base_revision=base)

    graph.revise(project, outcome="concurrent owner edit", logical_request_key="concurrent-project")
    before = graph.get(project.ref)
    with pytest.raises(VersionConflictError, match="stale"):
        batches.apply_authoring_command(
            project,
            {"approach": "must reject"},
            authoring=Authoring(),
            handle=handle,
            logical_request_key="stale-semantic-finish",
        )
    assert graph.get(project.ref).payload == before.payload


def test_semantic_authoring_rejects_child_only_revision_after_checkout(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    task = graph.create_task(project, title="Pinned child", logical_request_key="pinned-child")
    base_tasks = {task.id: task.revision}
    handle = SimpleNamespace(base_revision=project.ref.revision, token="token", fence="fence")

    class Authoring:
        def authorize_mutation(self, *_args, **_kwargs):
            return SimpleNamespace(base_revision=project.ref.revision)

    graph.revise(task, title="Concurrent child edit", logical_request_key="concurrent-child")
    before = graph.get(task.ref)
    with pytest.raises(VersionConflictError, match="task bases"):
        batches.apply_authoring_command(
            project, {"approach": "must reject"}, authoring=Authoring(), handle=handle,
            base_task_revisions=base_tasks, logical_request_key="stale-child-finish",
        )
    assert graph.get(task.ref).payload == before.payload


def test_invalid_child_rolls_back_all_rows_events_and_receipt(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    before = (len(store.list_events()), store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0])
    bad_sheet = {
        "tasks": [{"id": "will-rollback", "title": "created"}],
        "document_changes": [
            {"document": "broken", "revision": "same", "content": {"n": 1}, "scope": project.id},
            {"document": "broken", "revision": "same", "content": {"n": 2}, "scope": project.id},
        ],
    }
    with pytest.raises(Exception):
        batches.apply_project_sheet(project, bad_sheet, logical_request_key="invalid-child")
    assert len(store.list_events()) == before[0]
    assert store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0] == before[1]
    assert store.get_receipt("invalid-child") is None
    with pytest.raises(WorkNotFoundError):
        graph.resolve("will-rollback")


def test_injected_child_failure_rolls_back_revisions_associations_and_parent_boundary(environment, monkeypatch):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    task = graph.create_task(project, title="Existing", logical_request_key="rollback-task")
    before = {
        "identities": store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0],
        "references": store.connection.execute("SELECT COUNT(*) FROM record_references").fetchone()[0],
        "events": len(store.list_events()),
    }
    original_put_reference = store.put_reference

    def fail_association_reference(ref, *, transaction=None):
        if ref.kind == "dat.content.association" and ref.revision == "rev-2":
            raise RuntimeError("injected association child failure")
        return original_put_reference(ref, transaction=transaction)

    monkeypatch.setattr(store, "put_reference", fail_association_reference)
    sheet = {
        "tasks": [{"id": task.id, "title": "Revised then rolled back"}],
        "document_changes": [{"document": "spec", "revision": "r1", "content": {"body": "rolled back"}, "scope": project.id}],
        "documents": [
            {"namespace": "work", "key": "spec", "document_ref": "spec", "binding": "pinned", "revision": "r1"},
            {"namespace": "work", "key": "spec", "document_ref": "spec", "binding": "pinned", "revision": "r1"},
        ],
    }
    with pytest.raises(RuntimeError, match="injected association child failure"):
        batches.apply_project_sheet(project, sheet, logical_request_key="injected-child")

    assert store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0] == before["identities"]
    assert store.connection.execute("SELECT COUNT(*) FROM record_references").fetchone()[0] == before["references"]
    assert len(store.list_events()) == before["events"]
    assert store.get_receipt("injected-child") is None
    current_task = store.get_identity(task.ref)
    assert current_task is not None and current_task.ref == task.ref and current_task.version == task.version
    assert store.get_identity(ResourceRef(store.authority, "dat.content.document", "spec")) is None
    assert store.connection.execute(
        "SELECT COUNT(*) FROM identities WHERE kind = 'dat.content.association'"
    ).fetchone()[0] == 0


def test_existing_task_document_head_and_association_revise_through_fnd(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    task = graph.create_task(project, title="Existing", logical_request_key="typed-task")
    first = {
        "tasks": [{"id": task.id, "title": "First sheet"}],
        "document_changes": [{"document": "spec", "revision": "r1", "content": {"body": "one"}, "scope": project.id}],
        "documents": [
            {"namespace": "work", "key": "spec", "document_ref": "spec", "binding": "pinned", "revision": "r1"},
            {"namespace": "work", "key": "spec", "document_ref": "spec", "binding": "pinned", "revision": "r1"},
        ],
    }
    batches.apply_project_sheet(project, first, logical_request_key="typed-first")

    second = {
        "tasks": [{"id": task.id, "title": "Second sheet"}],
        "document_changes": [{"document": "spec", "revision": "r2", "content": {"body": "two"}, "scope": project.id}],
        "documents": [{"namespace": "work", "key": "spec", "document_ref": "spec", "binding": "pinned", "revision": "r1"}],
    }
    batches.apply_project_sheet(project, second, logical_request_key="typed-second")

    task_identity = store.get_identity(task.ref)
    document_identity = store.get_identity(ResourceRef(store.authority, "dat.content.document", "spec"))
    associations = store.connection.execute(
        "SELECT * FROM identities WHERE authority = ? AND kind = 'dat.content.association'",
        (store.authority,),
    ).fetchall()
    assert task_identity is not None and task_identity.ref.revision == "rev-3"
    assert document_identity is not None and document_identity.ref.revision == "rev-2"
    assert sorted(row["current_revision"] for row in associations) == ["rev-1", "rev-2"]
    assert store.get_reference(ResourceRef(store.authority, task.ref.kind, task.id, "rev-2")) is not None
    assert store.get_reference(ResourceRef(store.authority, "dat.content.document", "spec", "rev-2")) is not None


def test_pending_creation_commits_before_materialisation_and_activation_is_explicit(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    opened = []

    def fail(_project):
        raise OSError("editor unavailable")

    pending = batches.create_pending_project(curator="curator", reserve_authoring=True, logical_request_key="pending", materializer=fail)
    assert pending.status == "saved; editing not opened"
    assert pending.project.lifecycle is Lifecycle.PENDING
    assert pending.project.payload["tasks"] == []
    saved_id = pending.project.id
    retry = batches.retry_materialisation(pending, lambda value: opened.append(value.id))
    assert retry.status == "editable"
    assert opened == [saved_id]
    active = batches.activate_project(pending.project, manager="manager", logical_request_key="activate")
    assert active.lifecycle is Lifecycle.ACTIVE
    assert active.payload["readiness"]["dispatch"] is False
    readiness = batches.observe_readiness(active, {"ready": True, "cause": "dependency-satisfied"}, logical_request_key="readiness")
    assert readiness.kind == "wrk.readiness"
    assert graph.get(active.ref).lifecycle is Lifecycle.ACTIVE
    assert not graph.get(active.ref).payload["readiness"]["dispatch"]


def test_cross_scope_partial_and_manager_selected_action_are_explicit(environment):
    store, actor, graph, project = environment
    batches = ProjectBatches(store, actor=actor)
    other = graph.create_project(title="Other", logical_request_key="other")
    task = graph.create_task(project, title="Alternative", logical_request_key="alt-task")
    chosen = batches.choose_next_action(project, "correction", [task], logical_request_key="choice")
    assert chosen.project.payload["last_batch"]["manager_action"] == "correction"
    partial = batches.cross_scope_amendment(
        project,
        other,
        {"tasks": [{"id": task.id, "title": "Alternative"}]},
        second_sheet={"tasks": [{"id": "invalid", "title": ""}]},
        logical_request_key="cross",
    )
    assert partial.status == "partial"
    assert partial.links
    assert len(partial.receipts) == 2  # first scope plus explicit partial-link receipt
