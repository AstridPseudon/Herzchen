"""WRK-02 identity/graph proof against the installed FND-03 writer."""

from __future__ import annotations

from pathlib import Path

import pytest

from herzchen.contracts import AuthenticatedActor  # noqa: E402
from herzchen.kernel import Store  # noqa: E402
from herzchen.domains.work import (  # noqa: E402
    GraphCycleError,
    Lifecycle,
    WorkGraph,
    WorkKind,
    contribution,
    contributions,
)


@pytest.fixture
def work_store(tmp_path):
    store = Store.create(tmp_path / "work.sqlite", authority="test-work")
    try:
        yield store
    finally:
        store.close()


def actor() -> AuthenticatedActor:
    return AuthenticatedActor("test", "curator", "test-credential")


def test_contribution_is_typed_and_uses_only_fnd_composition(work_store):
    graph = WorkGraph(work_store, actor=actor())
    descriptor = graph.register()

    assert descriptor.domain_id == "herzchen.work"
    assert descriptor.resource_types == (
        "work.project",
        "work.effort",
        "work.task",
        "work.criterion",
        "work.scenario",
        "work.gate",
    )
    assert descriptor.document_types == ()
    assert descriptor.operation_types == (
        "work.create",
        "work.revise",
        "work.link-parent",
        "work.link-dependency",
        "work.withdraw",
        "work.state-view",
    )
    assert descriptor.event_types == (
        "work.created",
        "work.revised",
        "work.parent-linked",
        "work.dependency-linked",
        "work.withdrawn",
        "work.state-changed",
    )
    assert not hasattr(WorkGraph, "apply_project_sheet")
    assert descriptor.namespace_types == ("work", "work.metadata")
    assert "fnd-03.identities" in descriptor.composition_bindings
    assert work_store.registered_domains()[0].domain_id == descriptor.domain_id


def test_pending_project_is_durable_sparse_and_replay_safe(work_store, tmp_path):
    graph = WorkGraph(work_store, actor=actor())
    graph.register()
    project = graph.create_project(logical_request_key="project-create")

    assert project.title == "Untitled project"
    assert project.payload["outcome"] == ""
    assert project.payload["acceptance"] == {}
    assert project.payload["tasks"] == []
    for field in ("protocol", "manager", "gate", "budget", "worker", "execution", "external_action"):
        assert project.payload[field] is None
    assert project.lifecycle is Lifecycle.PENDING
    assert project.payload["readiness"]["dispatch"] is False
    assert project.payload["provenance"]["creator"] == actor().to_dict()

    # Same request/key and exact inputs returns the same durable identity.
    replay = graph.create_project(logical_request_key="project-create")
    assert replay.ref == project.ref
    assert len(work_store.list_events()) == 1

    with pytest.raises(Exception):
        graph.create_project(title="changed", logical_request_key="project-create")
    assert graph.get(project.ref).ref == project.ref

    work_store.close()
    reopened = Store.open(tmp_path / "work.sqlite", authority="test-work", expected_domains=tuple(sorted(contributions(), key=lambda item: item.domain_id)))
    try:
        reopened_graph = WorkGraph(reopened, actor=actor())
        fresh = reopened_graph.get(project.ref)
        assert fresh.ref == project.ref
        assert fresh.payload["tasks"] == []
    finally:
        reopened.close()


def test_aliases_and_revisions_preserve_identity_and_omission_does_not_delete(work_store):
    graph = WorkGraph(work_store, actor=actor())
    graph.register()
    project = graph.create_project(title="Project", alias="p-local", logical_request_key="p")
    task = graph.create_task(
        project,
        title="First task",
        alias="task-local",
        fields={"owner": "original", "nested": {"retained": True}},
        logical_request_key="task",
    )

    revised = graph.revise(task, title="Renamed task", add_alias="old-task", logical_request_key="rename")
    assert revised.ref.id == task.ref.id
    assert revised.ref.revision != task.ref.revision
    assert set(revised.aliases) == {"task-local", "old-task"}
    assert graph.get("old-task").ref.id == task.ref.id
    # Omitted fields are retained by a single-record revise; no projection or
    # delete operation is part of the WRK-02 surface.
    assert revised.payload["fields"] == {"owner": "original", "nested": {"retained": True}}
    assert len(graph.list(project=project, kind=WorkKind.TASK)) == 1


def test_parent_and_dependency_cycles_reject_atomically(work_store):
    graph = WorkGraph(work_store, actor=actor())
    graph.register()
    project = graph.create_project(logical_request_key="p")
    effort = graph.create_effort(project, logical_request_key="e")
    task = graph.create_task(project, parent=effort, logical_request_key="t")
    criterion = graph.create_criterion(project, parent=task, logical_request_key="c")
    graph.link_dependency(task, criterion, logical_request_key="valid-dependency")
    before_events = len(work_store.list_events())

    with pytest.raises(GraphCycleError):
        graph.link_dependency(criterion, task, logical_request_key="bad-dependency")
    assert len(work_store.list_events()) == before_events
    assert graph.get(criterion).dependencies == ()

    with pytest.raises(GraphCycleError):
        graph.link_parent(effort, task, logical_request_key="bad-parent")
    assert len(work_store.list_events()) == before_events
    assert graph.get(effort).parent is project.ref or graph.get(effort).parent.id == project.ref.id


def test_valid_single_record_links_state_and_lifecycle_keep_boundaries(work_store):
    graph = WorkGraph(work_store, actor=actor())
    graph.register()
    project = graph.create_project(title="Structural", logical_request_key="p")
    effort = graph.create_effort(project, title="Bounded effort", logical_request_key="e")
    task = graph.create_task(project, title="Do the work", logical_request_key="t")
    revised_project = graph.revise(project, outcome="A bounded outcome", logical_request_key="revise-project")
    task = graph.link_parent(task, effort, logical_request_key="link-parent")
    task = graph.link_dependency(task, effort, logical_request_key="link-dependency")

    assert revised_project.payload["outcome"] == "A bounded outcome"
    assert task.kind is WorkKind.TASK
    assert task.project_ref.id == project.ref.id
    assert task.parent.id == effort.ref.id
    assert [dependency.id for dependency in task.dependencies] == [effort.ref.id]

    view = graph.state_view(project)
    assert view.lifecycle is Lifecycle.PENDING
    assert view.ready is False
    updated = graph.set_readiness(project, {"status": "prerequisite-satisfied", "ready": True}, logical_request_key="observe")
    assert updated.lifecycle is Lifecycle.PENDING
    assert updated.readiness["ready"] is True
    assert updated.readiness["dispatch"] is False
    assert graph.withdraw(project, logical_request_key="withdraw").lifecycle is Lifecycle.WITHDRAWN


def test_module_has_no_product_or_runtime_dependency():
    source = Path(__file__).parents[2] / "src/herzchen/domains/work"
    text = "\n".join(path.read_text() for path in source.glob("*.py"))
    assert "import runtime" not in text.lower()
    assert "import astrid" not in text.lower()
    assert "sqlite3" not in text
    assert "CREATE TABLE" not in text
