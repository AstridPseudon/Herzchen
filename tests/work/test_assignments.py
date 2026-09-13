"""Focused WRK-03 responsibility and observation proof."""

from pathlib import Path

import pytest

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.work import WorkGraph
from herzchen.domains.work.assignments import (
    ResponsibilityAssignments,
    StaleAssignmentError,
)
from herzchen.kernel import Store


@pytest.fixture
def environment(tmp_path: Path):
    store = Store.create(tmp_path / "assignments.sqlite", authority="wrk-test")
    actor = AuthenticatedActor("wrk-test", "manager", "credential")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(title="Assignment proof", logical_request_key="project")
    try:
        yield store, actor, graph, project
    finally:
        store.close()


def test_one_generic_assignment_separates_reporter_launcher_and_fences_stale_writer(environment):
    store, actor, _graph, project = environment
    service = ResponsibilityAssignments(store, actor=actor)
    assigned = service.assign(
        project,
        role="review",
        principal="review-manager",
        reporter="reporter",
        launcher="physical-launcher",
        agent="agent-a",
        session="session-a",
        manager="manager-principal",
        logical_request_key="assign",
    )

    replaced = service.reassign(
        assigned,
        principal="replacement",
        agent="agent-b",
        session="session-b",
        expected_generation=1,
        logical_request_key="reassign",
    )
    assert replaced.role == "review"
    assert replaced.reporter == "reporter"
    assert replaced.launcher == "physical-launcher"
    assert replaced.history[-1]["principal"] == "replacement"
    assert replaced.history[-1]["session"] == "session-b"
    with pytest.raises(StaleAssignmentError):
        service.append_result(assigned, {"old": True}, expected_generation=1, logical_request_key="stale")

    report = service.append_report(replaced, {"observed": "kept"}, expected_generation=2, logical_request_key="report")
    assert report.kind == "report"
    assert service.list_observations(replaced)[0].value == {"observed": "kept"}
    # Auxiliary assignment/observation identities do not become structural
    # WorkKind vertices, and the manager identity is not tied to a session.
    assert all(item.kind.value != "assignment" for item in _graph.list())


def test_current_input_is_pinned_at_dispatch_and_explicit_action_is_preserved(environment):
    store, actor, graph, project = environment
    task = graph.create_task(project, title="Dispatch input", logical_request_key="task")
    service = ResponsibilityAssignments(store, actor=actor)
    assigned = service.assign(project, role="execution", principal="worker", logical_request_key="assign")
    dispatch = service.dispatch(
        assigned,
        input_refs=(ResourceRef(store.authority, task.ref.kind, task.id),),
        action="investigate",
        expected_generation=1,
        logical_request_key="dispatch",
    )
    assert dispatch.pinned_inputs[0].revision == task.revision
    assert dispatch.action == "investigate"
    assert len(store.list_events()) == 4  # project, task, assignment, dispatch
