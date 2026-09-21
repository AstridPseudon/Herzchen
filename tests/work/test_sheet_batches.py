"""WRK-05 project-sheet interpretation and policy-binding proofs."""

from pathlib import Path

import pytest

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.work import WorkGraph, WorkNotFoundError, WorkValidationError
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.decisions import DecisionsModule
from herzchen.domains.work.sheet import (
    PolicyAuthorityError,
    ProtectedFieldError,
    ProjectSheet,
    SheetApplication,
)
from herzchen.kernel import Store, VersionConflictError
from herzchen.packs.templates import work_template


@pytest.fixture
def environment(tmp_path: Path):
    store = Store.create(tmp_path / "sheet.sqlite", authority="sheet-test")
    actor = AuthenticatedActor("sheet-test", "manager", "credential")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(title="Sheet project", logical_request_key="project")
    service = ProjectSheet(store, actor=actor)
    try:
        yield store, actor, graph, project, service
    finally:
        store.close()


def test_blank_pending_starter_is_durable_and_uses_shared_definitions(environment):
    store, actor, graph, _project, service = environment
    pending = service.create_pending(logical_request_key="blank")
    view = service.export(pending.project)
    assert pending.project.lifecycle.value == "pending"
    assert view.tasks == ()
    assert view.project["authored"]["outcome"] == ""
    assert view.project["observed"]["manager"] is None
    assert view.project["observed"]["budget"] is None
    assert view.definitions.project_editable == service.definitions.project_editable
    # A pending edit is an ordinary plan revision, not admission or dispatch.
    edited = service.apply(pending.project, {"approach": "fill later"}, logical_request_key="blank-edit")
    assert edited.project.lifecycle.value == "pending"
    assert edited.project.payload["readiness"]["dispatch"] is False
    assert graph.get(edited.project.ref).payload.get("admitted") is None


def test_full_selected_view_separates_authored_facts_and_generated_decision_wait_context(environment):
    store, actor, graph, project, service = environment
    task = graph.create_task(project, title="Review task", logical_request_key="task")
    assignment = ResponsibilityAssignments(store, actor=actor).assign(task, role="manager", principal="manager", logical_request_key="assignment")
    decisions = DecisionsModule(store, actor=actor)
    candidate = decisions.create_candidate(
        "candidate", parent_obligation=task, artifact=_admit(store, "artifact"), source=_admit(store, "source"),
        spec=_admit(store, "spec"), criteria=(task,), owner="owner", logical_request_key="candidate",
    )
    decision = decisions.record_decision(
        task, candidate=candidate, criterion=task, authority="review-board", author="manager",
        rationale="hold", disposition="defer", return_condition="manager revisits", logical_request_key="decision",
    )
    wait = decisions.record_wait(
        task, missing_obligation="manager decision", owner=assignment.ref, awaited_ref=decision.ref,
        required_decision_ref=decision.ref, revisit_condition="when manager revisits", logical_request_key="wait",
    )
    service.apply(project, {"tasks": [{"id": task.id, "body": {"instructions": "inspect"}, "acceptance": {"must": "explain"}}]}, logical_request_key="plan")
    view = service.export(project, task_refs=[task.id])
    assert len(view.tasks) == 1
    assert view.tasks[0]["authored"]["body"] == {"instructions": "inspect"}
    assert view.tasks[0]["observed"]["assignments"]
    context = view.decision_context[0]
    assert context["candidates"][0]["ref"] == candidate.ref.to_dict()
    assert context["decisions"][0]["return_condition"] == "manager revisits"
    assert context["waiting"][0]["awaited_ref"] == wait.awaited_ref.to_dict()
    assert context["read_only"] is True


def test_aliases_dependencies_order_custom_values_and_documents_round_trip_atomically(environment):
    store, actor, graph, project, service = environment
    sheet = {
        "metadata_namespace": {"team": {"integer": 3, "enabled": True}},
        "tasks": [
            {"id": "second", "alias": "second", "title": "Second", "order": 2, "dependencies": ["first"], "custom": {"rank": 2, "enabled": True}},
            {"id": "first", "alias": "first", "aliases": ["source-first"], "title": "First", "order": 1, "body": {"steps": [1, 2]}},
        ],
        "document_changes": [{"document": "spec", "revision": "r1", "content": {"kind": "spec", "n": 1}, "scope": project.id}],
        "documents": [{"document_ref": "spec", "namespace": "work", "key": "spec", "binding": "pinned", "revision": "r1"}],
    }
    applied = service.apply(project, sheet, logical_request_key="atomic", with_view=True)
    assert isinstance(applied, SheetApplication)
    assert list(applied.mappings) == ["second", "first"]
    fresh = service.export(project)
    assert [item["authored"]["title"] for item in fresh.tasks] == ["First", "Second"]
    assert fresh.tasks[1]["authored"]["dependencies"][0]["id"] == applied.mappings["first"].id
    assert fresh.tasks[1]["authored"]["custom"] == {"rank": 2, "enabled": True}
    assert fresh.documents[0]["binding"]["mode"] == "pinned"
    assert fresh.documents[0]["current_revision"]["content"] == {"kind": "spec", "n": 1}
    current = service.apply(project, {"documents": [{"document_ref": "spec", "namespace": "work", "key": "current-spec", "binding": "current"}]}, logical_request_key="current-link")
    current_view = service.export(project)
    assert any(item["binding"]["mode"] == "current" for item in current_view.documents)
    assert len([event for event in store.list_events() if event.event_type == "work.project-sheet.applied"]) == 2


def test_public_nested_document_association_projects_into_fresh_sheet_and_detaches_without_loss(environment):
    """DAT's public association payload remains visible through ProjectSheet."""
    from hashlib import sha256

    from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, DocumentAssociation, domain_contribution
    from herzchen.contracts import ReferenceBinding, TransactionContext

    store, actor, graph, project, service = environment
    task = graph.create_task(project, title="Pinned task", logical_request_key="gf01-task")
    assignments = ResponsibilityAssignments(store, actor=actor)
    assignment = assignments.assign(
        task,
        role="execution",
        principal="worker",
        pins=(task.ref,),
        logical_request_key="gf01-assignment",
    )
    assignment_before = dict(assignments.get(assignment.ref).payload)

    store.register_domain_handler((domain_contribution(),))
    content = ContentCommandHandler(store)
    document = ContentDocument(
        ResourceRef(store.authority, "document", "gf01-document"),
        "evidence",
        "shared",
        "append",
        "manager",
        project.ref,
    )
    revision = ContentRevision(
        document.ref,
        "gf01-revision-1",
        {"body": "public Otto evidence", "n": 1},
        actor,
        initial=True,
    )
    create_context = TransactionContext(actor, "gf01-create", sha256(b"gf01-create").hexdigest())
    content.execute(content.build_create_document(create_context, document, revision))
    association = DocumentAssociation(
        project.ref,
        "project.documents",
        "evidence",
        ReferenceBinding(revision.ref, "pinned"),
    )
    link_context = TransactionContext(actor, "gf01-link", sha256(b"gf01-link").hexdigest())
    linked = content.build_link(link_context, association)
    first_link = content.execute(linked)
    replay_link = content.execute(linked)
    assert first_link.to_dict() == replay_link.to_dict()

    fresh = service.export(project)
    assert len(fresh.documents) == 1
    assert fresh.documents[0]["association"]["id"] == association.identity
    assert fresh.documents[0]["binding"]["ref"]["id"] == document.ref.id
    assert fresh.documents[0]["binding"]["mode"] == "pinned"
    assert fresh.documents[0]["binding"]["ref"]["revision"] == revision.ref.revision
    assert content.read(revision.ref)["content"] == {"body": "public Otto evidence", "n": 1}

    unlink_context = TransactionContext(actor, "gf01-unlink", sha256(b"gf01-unlink").hexdigest())
    unlink = content.build_unlink(unlink_context, association)
    first_unlink = content.execute(unlink)
    replay_unlink = content.execute(unlink)
    assert first_unlink.to_dict() == replay_unlink.to_dict()
    detached = service.export(project)
    assert detached.documents == ()
    assert store.get_identity(ResourceRef(store.authority, "document-association", association.identity)) is not None
    assert store.get_identity(document.ref).payload["current_revision"]["revision"] == revision.ref.revision
    assert assignments.get(assignment.ref).payload == assignment_before


def test_omission_preserves_task_documents_namespace_result_and_inflight_assignment(environment):
    store, actor, graph, project, service = environment
    task = graph.create_task(project, title="Keep", logical_request_key="keep")
    assignments = ResponsibilityAssignments(store, actor=actor)
    assignment = assignments.assign(task, role="execution", principal="worker", pins=(task.ref,), logical_request_key="assign")
    result = assignments.append_result(assignment, {"observed": "keep"}, logical_request_key="result")
    service.apply(project, {"tasks": [{"id": task.id, "title": "Revised", "custom": {"new": "value"}}], "metadata_namespace": {"x": {"keep": True}}}, logical_request_key="first")
    service.apply(project, {"approach": "new approach"}, logical_request_key="omission")
    assert graph.get(task.ref).title == "Revised"
    assert graph.get(project.ref).payload["metadata_namespaces"]["x"]["keep"] is True
    assert assignments.list_observations(assignment)[0].value == result.value
    assert service.export(project).tasks[0]["observed"]["assignments"]


def test_protected_fields_reject_without_receipt_and_direct_revise_uses_same_guard(environment):
    store, actor, graph, project, service = environment
    task = graph.create_task(project, title="Protected", logical_request_key="protected")
    before = (len(store.list_events()), graph.get(task.ref).payload)
    for bad in ({"budget": 10}, {"custom": {"spend": 2}}, {"tasks": [{"id": task.id, "results": ["replace"]}]}):
        with pytest.raises(ProtectedFieldError):
            service.apply(project, bad, logical_request_key="bad-" + str(len(store.list_events())))
    with pytest.raises(ProtectedFieldError):
        service.revise(task, results=["replace"], logical_request_key="direct-bad")
    assert len(store.list_events()) == before[0]
    assert graph.get(task.ref).payload == before[1]


def test_stale_base_rejects_sheet_and_direct_surface_without_partial_mutation(environment):
    store, actor, graph, project, service = environment
    stale = project.ref.revision
    service.apply(project, {"approach": "first"}, logical_request_key="first")
    before = (len(store.list_events()), graph.get(project.ref).payload)
    with pytest.raises(VersionConflictError):
        service.apply(project, {"tasks": [{"id": "new", "title": "must not exist"}]}, base_revision=stale, logical_request_key="stale-sheet")
    with pytest.raises(VersionConflictError):
        service.revise(project, approach="must not apply", base_revision=stale, logical_request_key="stale-direct")
    assert len(store.list_events()) == before[0]
    assert graph.get(project.ref).payload == before[1]
    with pytest.raises(WorkNotFoundError):
        graph.resolve("new")


def test_completed_task_protection_covers_direct_and_sheet_owner_paths(environment):
    store, actor, graph, project, service = environment
    task = graph.create_task(project, title="Completed input", logical_request_key="completed")
    completed = graph.revise(task, lifecycle="completed", logical_request_key="complete")
    before = graph.get(completed.ref)

    with pytest.raises(WorkValidationError, match="completed task"):
        graph.revise(completed, title="rewritten", logical_request_key="direct-edit")
    with pytest.raises(WorkValidationError, match="completed task"):
        service.apply(project, {"tasks": [{"id": completed.id, "body": {"changed": True}}]}, logical_request_key="sheet-edit")

    after = graph.get(completed.ref)
    assert after.ref == before.ref
    assert after.payload == before.payload


def test_completed_task_round_trip_preserves_parent_and_revision(environment):
    store, actor, graph, project, service = environment
    parent = graph.create_task(project, title="Parent", logical_request_key="nested-parent")
    child = graph.create_task(project, parent=parent, title="Completed child", logical_request_key="nested-child")
    completed = graph.revise(child, lifecycle="completed", logical_request_key="nested-complete")
    sibling = graph.create_task(project, title="Sibling", logical_request_key="nested-sibling")
    before = graph.get(completed.ref)

    applied = service.apply(
        project,
        {"tasks": [{"id": completed.id}, {"id": sibling.id, "title": "Sibling revised"}]},
        logical_request_key="nested-round-trip",
    )

    retained = graph.get(completed.ref)
    assert retained.ref == before.ref
    assert retained.parent.id == parent.id
    assert graph.get(sibling.ref).title == "Sibling revised"
    assert applied.project.payload["tasks"]


def test_withdraw_and_assignment_route_are_explicit_and_per_assignment(environment):
    store, actor, graph, project, service = environment
    first = graph.create_task(project, title="One", logical_request_key="one")
    second = graph.create_task(project, title="Two", logical_request_key="two")
    assignments = ResponsibilityAssignments(store, actor=actor)
    one = assignments.assign(first, role="execution", principal="one", logical_request_key="one-assignment")
    two = assignments.assign(second, role="execution", principal="two", logical_request_key="two-assignment")
    route = service.pin_assignment_route(one, {"name": "xhard", "reason": "specific assignment"}, logical_request_key="route")
    assert route.assignment.payload["route_binding"] == {"name": "xhard", "reason": "specific assignment"}
    assert assignments.get(two.ref).payload.get("route_binding") is None
    withdrawn = service.withdraw(first, logical_request_key="withdraw")
    assert withdrawn.project.payload["lifecycle"] == "pending"
    assert graph.get(first.ref).lifecycle.value == "withdrawn"
    assert graph.get(second.ref).lifecycle.value == "pending"


def test_policy_amendment_requires_exact_authority_base_and_decision(environment):
    store, actor, graph, project, service = environment
    decisions = DecisionsModule(store, actor=actor)
    artifact, source, spec = (_admit(store, name) for name in ("artifact", "source", "spec"))
    task = graph.create_task(project, title="Policy subject", logical_request_key="policy-task")
    candidate = decisions.create_candidate("candidate", parent_obligation=project, artifact=artifact, source=source, spec=spec, criteria=(task,), owner="owner", logical_request_key="policy-candidate")
    decision = decisions.record_decision(project, candidate=candidate, criterion=task, authority="review-board", author="manager", rationale="approve policy", disposition="approved", return_condition="source changes", logical_request_key="policy-decision")
    base = graph.get(project.ref).ref.revision
    result = service.amend_policy(project, {"review": "required"}, authority="review-board", base_revision=base, decision_ref=decision.ref, logical_request_key="policy")
    assert result.project.payload["metadata_namespaces"]["work.policy"]["decision_ref"]["id"] == decision.ref.id
    with pytest.raises(PolicyAuthorityError):
        service.amend_policy(project, {"review": "bad"}, authority="wrong", base_revision=result.project.ref.revision, decision_ref=decision.ref, logical_request_key="policy-wrong")


def test_adoption_is_distinct_passive_and_preserves_unknowns_without_cloning_execution_state(environment):
    store, actor, graph, project, service = environment
    source = {
        "id": "external-effort", "external_budget_refs": [{"id": "budget-7"}],
        "tasks": [{"id": "legacy-a", "alias": "legacy-a", "aliases": ["stable-a"], "title": "Legacy meaning", "criterion": "exact", "results": [{"value": "prior"}], "unknown_field": {"x": 1}, "assignments": [{"id": "old-assignment"}]}],
        "responsibilities": [{"id": "old-responsibility", "principal": "old-owner"}],
    }
    adopted = service.adopt_existing_effort(source, project=project, logical_request_key="adopt")
    task = graph.get(adopted.mappings["legacy-a"])
    adoption = adopted.project.payload["metadata_namespaces"]["work.adoption"]
    assert "stable-a" in task.payload["aliases"]
    assert adoption["external_budget_refs"] == [{"id": "budget-7"}]
    assert adoption["observed"][0]["results"] == [{"value": "prior"}]
    assert adoption["unknown_fields"][0]["unknown_field"] == {"x": 1}
    assert adoption["quiescent"] is True and adoption["dispatch"] is False
    assert not store.connection.execute("SELECT 1 FROM identities WHERE kind = 'wrk.assignment'").fetchone()


def test_instantiate_new_template_is_distinct_authored_pending_import(environment):
    store, actor, graph, project, service = environment
    template = work_template(
        "sheet-template", revision="t1",
        seed={"project": {"title": "Templated", "outcome": "literal outcome"}, "tasks": [{
            "local_id": "build", "title": "Build", "namespace": "named.tasks", "review_choice": "normal",
        }]},
    )
    applied = service.instantiate_new_template(template, project=project, logical_request_key="template")
    assert graph.get(project.ref).lifecycle.value == "pending"
    assert applied.project.payload["metadata_namespaces"]["work.template"]["template_id"] == "sheet-template"
    task = graph.get(applied.mappings["build"])
    assert task.payload["fields"]["namespace"] == "named.tasks"
    assert task.payload["fields"]["review_choice"] == "normal"
    assert not any(event.event_type == "work.assignment.dispatched" for event in store.list_events())


def _admit(store: Store, ident: str) -> ResourceRef:
    ref = ResourceRef(store.authority, "fixture." + ident, ident, "rev-1")
    store.put_identity(ref, {"record_type": ref.kind, "id": ident}, version=1)
    store.put_reference(ref)
    return ref
