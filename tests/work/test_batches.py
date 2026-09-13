"""Focused WRK-03 whole-project batch and pending-project proof."""

from pathlib import Path

import pytest

from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef
from herzchen.domains.work import Lifecycle, WorkGraph
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.kernel import Store


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
    assert graph._resolve("will-rollback") is None


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
