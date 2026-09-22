"""Bounded actor-attributed PM closeout coverage."""

from pathlib import Path

import pytest

from herzchen.contracts import AuthenticatedActor
from herzchen.domains.work import ProjectLifecycle, ProjectLifecycleError, register_work
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.sheet import ProjectSheet
from herzchen.kernel import Store


@pytest.fixture
def pm_fixture(tmp_path: Path):
    store = Store.create(tmp_path / "pm-closeout.sqlite", authority="pm-closeout-owner")
    register_work(store)
    actor = AuthenticatedActor(store.authority, "owner", "pm-credential")
    sheet = ProjectSheet(store, actor=actor)
    project = sheet.create_pending(title="PM closeout", logical_request_key="project", actor=actor).project
    project = sheet.apply(project, {"tasks": [{"id": "pm01", "title": "PM01"}]}, logical_request_key="tasks", actor=actor).project
    task = sheet.graph.list(project=project)[0]
    assignments = ResponsibilityAssignments(store, actor=actor)
    manager = assignments.assign(project.ref, role="manager", principal=actor.actor, logical_request_key="manager", actor=actor)
    assignments.complete(
        task.ref,
        project=project.ref,
        assignment=manager.ref,
        expected_generation=1,
        expected_project_revision=project.ref.revision,
        expected_task_revision=task.ref.revision,
        disposition="completed",
        evidence_refs=(project.ref,),
        evidence_hashes=["pm01-evidence"],
        gate_refs=(project.ref,),
        logical_request_key="pm01-complete",
        actor=actor,
    )
    task = sheet.graph.get(task.ref)
    project = sheet.graph.get(project.ref)
    lifecycle = ProjectLifecycle(store, actor=actor, delegation_issuer=actor)
    try:
        yield store, sheet, lifecycle, actor, project, task, manager
    finally:
        store.close()


def test_pm_closeout_is_owner_attributed_atomic_and_replayable(pm_fixture):
    store, sheet, lifecycle, actor, project, task, manager = pm_fixture
    bind_args = {
        "action": "pm-bind-existing",
        "logical_request_key": "otto-project-management-followup-20260922:closeout:20260922T0642Z-v1:bind-existing-root",
        "expected_project_revision": project.ref.revision,
        "expected_project_version": project.version,
        "generation": 1,
        "manager_assignment": manager.ref,
        "orchestrator_principal": "01a09c66-a6df-7140-a7b4-63dad5082d45",
        "task_refs": (task.ref,),
        "owner_attribution": {"orchestrator": {"principal": "01a09c66-a6df-7140-a7b4-63dad5082d45"}},
        "actor": actor,
    }
    bound = lifecycle.transition(project.ref, **bind_args)
    replay = lifecycle.transition(project.ref, **bind_args)
    assert bound["outcome"] == "transitioned"
    assert replay["outcome"] == "replayed"
    assert replay["receipt"] == bound["receipt"]
    assert bound["read"]["lifecycle"] == "pending"
    assert bound["attribution_digest"]

    current = sheet.graph.get(project.ref)
    close_key = "otto-project-management-followup-20260922:closeout:20260922T0642Z-v1:manager-close-request"
    close = lifecycle.transition(
        current.ref,
        action="pm-manager-close-request",
        logical_request_key=close_key,
        expected_project_revision=current.ref.revision,
        expected_project_version=current.version,
        generation=1,
        manager_assignment=manager.ref,
        orchestrator_assignment=bound["orchestrator_assignment_ref"],
        attribution_digest=bound["attribution_digest"],
        task_refs=(task.ref,),
        actor=actor,
    )
    assert close["read"]["lifecycle"] == "pending"
    assert close["read"]["close_request"]

    current = sheet.graph.get(project.ref)
    task_before = sheet.graph.get(task.ref).payload
    evidence = {
        "project_ref": current.ref.to_dict(),
        "acceptance": {"status": "passed"},
        "publication": {"status": "verified"},
        "remote": {"status": "verified"},
        "runtime": {"status": "qualified"},
    }
    terminal = lifecycle.transition(
        current.ref,
        action="pm-orchestrator-close",
        logical_request_key="otto-project-management-followup-20260922:closeout:20260922T0642Z-v1:orchestrator-close",
        expected_project_revision=current.ref.revision,
        expected_project_version=current.version,
        generation=1,
        manager_assignment=manager.ref,
        orchestrator_assignment=bound["orchestrator_assignment_ref"],
        attribution_digest=bound["attribution_digest"],
        task_refs=(task.ref,),
        evidence=evidence,
        actor=actor,
    )
    assert terminal["read"]["lifecycle"] == "completed"
    assert sheet.graph.get(task.ref).payload == task_before

    current = sheet.graph.get(project.ref)
    reconciled = lifecycle.transition(
        current.ref,
        action="pm-reconcile-no-owned-schedule",
        logical_request_key="otto-project-management-followup-20260922:closeout:20260922T0642Z-v1:reconcile-no-pm-schedule",
        expected_project_revision=current.ref.revision,
        expected_project_version=current.version,
        generation=1,
        manager_assignment=manager.ref,
        orchestrator_assignment=bound["orchestrator_assignment_ref"],
        attribution_digest=bound["attribution_digest"],
        task_refs=(task.ref,),
        schedule_observation={
            "mode": "no-owned-schedule",
            "coverage": {"owner_due_records": 1, "host_automation_ids": [], "read_surfaces": ["test"]},
            "pm_owned_schedule_ids": [],
            "shared_records": [],
            "inventory_digest": "inventory",
            "host_effects": [],
        },
        actor=actor,
    )
    assert reconciled["read"]["reconciliation"]["mode"] == "no-owned-schedule"
    assert reconciled["read"]["reconciliation"]["host_effects"] == []


def test_pm_closeout_requires_injected_owner_and_holds_unknown_schedule(pm_fixture):
    store, sheet, _lifecycle, actor, project, task, manager = pm_fixture
    no_delegation = ProjectLifecycle(store, actor=actor)
    with pytest.raises(ProjectLifecycleError, match="injected owner delegation"):
        no_delegation.transition(
            project.ref,
            action="pm-bind-existing",
            logical_request_key="pm-bind-without-owner",
            expected_project_revision=project.ref.revision,
            expected_project_version=project.version,
            generation=1,
            manager_assignment=manager.ref,
            orchestrator_principal="root",
            task_refs=(task.ref,),
            owner_attribution={"orchestrator": {"principal": "root"}},
            actor=actor,
        )
