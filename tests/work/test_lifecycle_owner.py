"""Focused canonical owner lifecycle and projection settlement proof."""

from uuid import uuid4

from herzchen.contracts import AuthenticatedActor
from herzchen.domains.work import ProjectLifecycle, WorkGraph, contributions
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.kernel import Store


def _fixture(tmp_path):
    store = Store.create(tmp_path / "lifecycle.sqlite", authority="lifecycle-owner")
    store.register_domain_handler(contributions())
    actor = AuthenticatedActor("lifecycle-owner", "manager", "credential")
    graph = WorkGraph(store, actor=actor)
    project = graph.create_project(title="Lifecycle", logical_request_key="project")
    assignments = ResponsibilityAssignments(store, actor=actor)
    manager = assignments.assign(project.ref, role="manager", principal="manager", logical_request_key="manager", actor=actor)
    orchestrator_actor = AuthenticatedActor("lifecycle-owner", "orchestrator", "credential")
    orchestrator = assignments.assign(project.ref, role="orchestrator", principal="orchestrator", logical_request_key="orchestrator", actor=actor)
    return store, graph, ProjectLifecycle(store, actor=actor), project, manager, orchestrator, orchestrator_actor


def test_completed_project_reconcile_settles_exact_projection_without_reopen(tmp_path):
    store, graph, lifecycle, project, manager, orchestrator, orchestrator_actor = _fixture(tmp_path)
    manager_actor = AuthenticatedActor("lifecycle-owner", "manager", "credential")
    packet = {role: {key: str(uuid4()) for key in ("effect_id", "readback_id", "ack_id")} for role in ("manager", "portfolio")}
    activated = lifecycle.transition(
        project.ref,
        action="activate",
        logical_request_key="activate",
        expected_project_revision=project.ref.revision,
        generation=1,
        manager_assignment=manager.ref,
        effect_packet=packet,
        actor=manager_actor,
    )
    current = graph.get(project.ref)
    close = lifecycle.transition(
        current.ref,
        action="manager-close-request",
        logical_request_key="close",
        expected_project_revision=current.ref.revision,
        generation=1,
        manager_assignment=manager.ref,
        actor=manager_actor,
    )
    current = graph.get(project.ref)
    evidence = {"project_ref": current.ref.to_dict(), "acceptance": {"status": "passed"}, "publication": {"status": "verified"}, "remote": {"status": "verified"}, "runtime": {"status": "qualified"}}
    terminal = lifecycle.transition(
        current.ref,
        action="orchestrator-close",
        logical_request_key="terminal",
        expected_project_revision=current.ref.revision,
        generation=1,
        orchestrator_assignment=orchestrator.ref,
        evidence=evidence,
        actor=orchestrator_actor,
    )
    current = graph.get(project.ref)
    config = {"automation_id": "automation-portfolio", "status": "ACTIVE"}
    settlement = {"status": "reconciled", "effect_id": packet["portfolio"]["effect_id"], "request_id": "host-reconcile", "config": config, "readback": {"request_id": "host-reconcile", "config": config, "status": "ACTIVE"}, "acknowledgment": {"outcome": "reconciled", "readback_exact": True}}
    reconciled = lifecycle.transition(current.ref, action="reconcile", logical_request_key="reconcile", expected_project_revision=current.ref.revision, generation=1, orchestrator_assignment=orchestrator.ref, effect_packet=packet, settlement=settlement, actor=orchestrator_actor)
    assert activated["read"]["lifecycle"] == "active"
    assert close["read"]["lifecycle"] == "active"
    assert terminal["read"]["lifecycle"] == "completed"
    assert reconciled["read"]["lifecycle"] == "completed"
    assert reconciled["read"]["reconciliation"]["status"] == "reconciled"
    replay = lifecycle.transition(current.ref, action="reconcile", logical_request_key="reconcile", expected_project_revision=current.ref.revision, generation=1, orchestrator_assignment=orchestrator.ref, effect_packet=packet, settlement=settlement, actor=orchestrator_actor)
    assert replay["outcome"] == "replayed"
    assert graph.get(project.ref).lifecycle.value == "completed"
    store.close()
