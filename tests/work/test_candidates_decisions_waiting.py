"""Focused WRK-07 proof: candidate pins, decisions, waiting and attention."""

from pathlib import Path
from datetime import timedelta

import pytest

from herzchen.contracts import AuthenticatedActor, CommandEnvelope, EventCursor, ResourceRef, TransactionContext
from herzchen.domains.assessment import AssessmentModule, Verdict
from herzchen.domains.work import WorkGraph
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.decisions import (
    Applicability, DecisionAuthorityError, DecisionsModule, StaleCandidateError,
    StaleCriterionError, WaitingError,
)
from herzchen.kernel import IntervalController, LimitService, Store


def _admit(store: Store, kind: str, ident: str, value: str = "original") -> ResourceRef:
    ref = ResourceRef(store.authority, kind, ident, "rev-1")
    store.put_identity(ref, {"record_type": kind, "value": value}, version=1)
    store.put_reference(ref)
    return ref


def _revise(store: Store, ref: ResourceRef, value: str, key: str) -> ResourceRef:
    current = store.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
    assert current is not None
    revised = store.revise_identity(
        current.ref, {"record_type": ref.kind, "value": value},
        revision="rev-" + str(current.version + 1),
        expected_revision=current.ref.revision, expected_version=current.version,
    )
    return revised.ref


@pytest.fixture
def context(tmp_path: Path):
    store = Store.create(tmp_path / "decisions.sqlite", authority="wrk07-test")
    actor = AuthenticatedActor("wrk07-test", "manager", "credential")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(title="WRK-07", logical_request_key="project")
    parent = graph.create_task(project, title="Parent obligation", logical_request_key="parent")
    criterion = graph.create_criterion(parent, title="Exact criterion", logical_request_key="criterion")
    artifact = _admit(store, "fixture.artifact", "artifact")
    source = _admit(store, "fixture.source", "source")
    spec = _admit(store, "fixture.spec", "spec")
    assessment = AssessmentModule(store, actor=actor)
    assessment.register()
    scope = assessment.declare_scope(
        ResourceRef(store.authority, "assessment.scope", "scope"),
        parent_obligation=parent, protocol="megado.delivery", criteria=(criterion,),
        designated_approver=actor.actor, authority="review-board", logical_request_key="scope",
    )
    packet = assessment.freeze_input(
        scope, packet={"facts": ["original"]}, consumed_refs=(source,), logical_request_key="packet",
    )
    pool = LimitService(store).create_pool(
        ResourceRef(store.authority, "limit", "pool"), 1, 4, logical_request_key="pool", actor=actor,
    )
    decisions = DecisionsModule(store, assessment=assessment, actor=actor)
    decisions.register()
    try:
        yield locals()
    finally:
        store.close()


def _candidate(ctx, ident: str):
    return ctx["decisions"].create_candidate(
        ident, parent_obligation=ctx["parent"], artifact=ctx["artifact"], source=ctx["source"],
        spec=ctx["spec"], criteria=(ctx["criterion"],), consumed_inputs=(ctx["source"],),
        owner="owner", role="implementation", provenance={"fixture": "candidate_decision"},
        logical_request_key="candidate-" + ident,
    )


def _assessment(ctx, candidate, key="assessment"):
    return ctx["assessment"].assess(
        ctx["scope"], candidate=candidate, criterion=ctx["criterion"], input_packet=ctx["packet"],
        verdict=Verdict.PASS, guidance={"next": "inspect"}, protocol_result={"protocol": "shared"},
        limit_pool=ctx["pool"].ref, role="review", logical_request_key=key,
    )


def test_candidates_are_distinct_immutable_pins_and_decisions_are_historical(context):
    a = _candidate(context, "candidate-A")
    b = _candidate(context, "candidate-B")
    assert a.ref != b.ref
    assert a.pin.artifact_ref.revision == "rev-1"
    assert a.pin.source_ref.revision == "rev-1"
    assert a.pin.spec_ref.revision == "rev-1"
    assert all(ref.revision is not None for ref in a.pin.all_refs)
    decision = context["decisions"].record_decision(
        context["parent"], candidate=a, criterion=context["criterion"], evidence_refs=(context["artifact"],),
        evidence_basis={"basis": "pinned artifact"}, author="manager", authority="review-board",
        rationale="A is the selected candidate", disposition="approved", return_condition="source changes",
        logical_request_key="decision-A",
    )
    assert decision.candidate_ref == a.ref
    assert decision.criterion_ref == context["criterion"].ref
    assert decision.evidence_basis["basis"] == "pinned artifact"
    assert not decision.accepted and not decision.obligation_closed
    assert context["decisions"].get_decision(decision.ref).rationale == decision.rationale
    newer = context["decisions"].record_decision(
        context["parent"], candidate=b, criterion=context["criterion"], author="manager",
        authority="review-board", rationale="B is a later option", disposition="defer",
        return_condition="manager revisits", logical_request_key="decision-B",
    )
    assert context["decisions"].get_decision(decision.ref).candidate_ref == a.ref
    assert {item.ref.id for item in context["decisions"].list_decisions(subject=context["parent"])} == {decision.ref.id, newer.ref.id}


def test_required_approval_is_bound_to_assessment_candidate_criterion_authority_and_evidence(context):
    a = _candidate(context, "candidate-A")
    b = _candidate(context, "candidate-B")
    result = _assessment(context, a, "assessment-A")
    kwargs = dict(
        subject=context["parent"], criterion=context["criterion"], evidence_refs=(context["artifact"],),
        evidence_basis={"review": "PASS"}, author="manager", authority="review-board", rationale="approved",
        disposition="approved", return_condition="new source revision", assessment_result=result,
        required_approval=True,
    )
    approved = context["decisions"].record_decision(candidate=a, logical_request_key="approval-A", **kwargs)
    assert approved.candidate_ref == a.ref and approved.assessment_result_ref == result.ref
    assert not approved.accepted
    before = len(context["store"].list_events())
    with pytest.raises(StaleCandidateError):
        context["decisions"].record_decision(candidate=b, logical_request_key="approval-B", **kwargs)
    wrong = {key: value for key, value in kwargs.items() if key != "authority"}
    with pytest.raises(DecisionAuthorityError):
        context["decisions"].record_decision(candidate=a, authority="wrong-board", logical_request_key="approval-wrong-authority", **wrong)
    assert context["store"].get_receipt("approval-B") is None
    assert context["store"].get_receipt("approval-wrong-authority") is None
    assert len(context["store"].list_events()) == before
    old_criterion = context["criterion"].ref
    _revise(context["store"], old_criterion, "criterion-v2", "criterion-revision")
    stale = {key: value for key, value in kwargs.items() if key != "criterion"}
    with pytest.raises(StaleCriterionError):
        context["decisions"].record_decision(candidate=a, criterion=old_criterion, logical_request_key="approval-stale-criterion", **stale)
    assert context["store"].get_receipt("approval-stale-criterion") is None


def test_consumed_input_only_invalidation_and_unsupported_vocab_is_data(context):
    a = _candidate(context, "candidate-A")
    decision = context["decisions"].record_decision(
        context["parent"], candidate=a, criterion=context["criterion"], authority="review-board", rationale="hold",
        disposition="unsupported-review-vocabulary", return_condition="manager interprets it",
        semantic_judgment={"by": "agent"}, logical_request_key="unsupported-vocab",
    )
    annotation = _admit(context["store"], "fixture.annotation", "annotation")
    context["decisions"].annotate_candidate(a, {"annotation_ref": annotation}, logical_request_key="annotation")
    unchanged = context["decisions"].check_applicability(
        a, annotation_refs=(annotation,), semantic_judgment={"by": "domain"},
    )
    assert unchanged.status is Applicability.APPLICABLE
    assert unchanged.semantic_judgment == {"by": "domain"}
    _revise(context["store"], context["source"], "source-v2", "source-revision")
    changed = context["decisions"].check_applicability(
        a, annotation_refs=(annotation,), semantic_judgment="not inferred",
    )
    assert changed.status is Applicability.STALE
    assert context["source"] in changed.affected_refs
    assert context["decisions"].get_decision(decision.ref).disposition == "unsupported-review-vocabulary"


def test_wait_explains_owner_current_pin_revisit_and_attention_without_dispatch(context):
    assignment = ResponsibilityAssignments(context["store"], actor=context["actor"]).assign(
        context["parent"], role="manager", principal="manager", logical_request_key="assignment",
    )
    decision = context["decisions"].record_decision(
        context["parent"], candidate=_candidate(context, "candidate-A"), criterion=context["criterion"],
        authority="review-board", rationale="needs manager", disposition="defer",
        return_condition="manager decides", logical_request_key="wait-decision",
    )
    wait = context["decisions"].record_wait(
        context["parent"], missing_obligation="real manager decision", owner=assignment.ref,
        awaited_ref=context["criterion"], revisit_condition="when criterion revision or attention changes",
        required_decision_ref=decision, residual_risk={"choice": "hold"},
        verification_choice={"check": "inspect"}, metadata={"note": "attention only"},
        logical_request_key="wait-1",
    )
    assert wait.owner_ref == assignment.ref
    assert wait.awaited_ref == context["criterion"].ref
    assert wait.current_revision == context["criterion"].ref.revision
    assert wait.attention_event_id and wait.receipt.event_ids == (wait.attention_event_id,)
    assert wait.dispatch is False and wait.payload["reservation_ref"] is None and wait.payload["allowance"] is None
    assert context["store"].get_identity(ResourceRef(context["store"].authority, "reservation", "wait-1")) is None


def test_wait_recovery_is_cursor_based_and_never_ready_or_duplicate_dispatch(context):
    dm = context["decisions"]
    a = _candidate(context, "candidate-A")
    decision = dm.record_decision(
        context["parent"], candidate=a, criterion=context["criterion"], authority="review-board",
        rationale="hold", disposition="defer", return_condition="revisit", logical_request_key="recovery-decision",
    )
    first = dm.record_wait(
        context["parent"], missing_obligation="decision", owner="manager", awaited_ref=decision.ref,
        required_decision_ref=decision.ref, logical_request_key="recovery-wait-1",
    )
    second = dm.record_wait(
        context["parent"], missing_obligation="decision", owner="manager", awaited_ref=decision.ref,
        required_decision_ref=decision.ref, logical_request_key="recovery-wait-2",
    )
    stream = "attention:" + context["parent"].ref.id
    events = context["store"].list_events(stream=stream)
    page = dm.reconcile_notifications(stream, limit=1)
    assert page.page.events == (events[0],) and page.page.next_cursor
    resumed = dm.reconcile_notifications(stream, cursor=page.cursor, limit=10)
    assert resumed.page.events == (events[1],) and resumed.business_dispatches == 0 and not resumed.work_ready
    cursor = EventCursor(context["store"].authority, stream, events[0].sequence, events[0].event_id)
    duplicate = dm.observe_notification(cursor, events[0])
    assert duplicate.duplicate and duplicate.business_dispatches == 0
    assert first.attention_event_id != second.attention_event_id
    synthetic = type(events[1])(
        events[1].event_id + "-gap", events[1].store_authority, events[1].stream, events[1].subject,
        events[1].schema_revision, events[1].event_type, events[1].sequence + 2, events[1].actor,
        events[1].operation, events[1].correlation_id, events[1].causation_id, events[1].recorded_at,
        events[1].occurred_at, events[1].before_refs, events[1].after_refs, events[1].effects,
    )
    gap = dm.observe_notification(cursor, synthetic)
    assert gap.missed and gap.business_dispatches == 0 and not gap.work_ready


def test_cap_wait_and_timer_do_not_close_parent_grant_budget_or_choose_action(context):
    dm = context["decisions"]
    a = _candidate(context, "candidate-A")
    decision = dm.record_decision(
        context["parent"], candidate=a, criterion=context["criterion"], authority="review-board",
        rationale="cap needs decision", disposition="defer", return_condition="manager revisits",
        logical_request_key="cap-decision",
    )
    capped = dm.record_wait(
        context["parent"], missing_obligation="unresolved decision at cap", owner="manager",
        awaited_ref=decision.ref, required_decision_ref=decision.ref, cap_reached=True, logical_request_key="cap-wait",
    )
    assert capped.cap_reached and capped.payload["dispatch"] is False
    with pytest.raises(WaitingError):
        dm.record_wait(
            context["parent"], missing_obligation="unresolved decision at cap", owner="manager",
            awaited_ref=decision.ref, required_decision_ref=decision.ref, cap_reached=True,
            equivalent_review_name="renamed-review", logical_request_key="renamed-review",
        )
    interval_ref = ResourceRef(context["store"].authority, "attention-interval", "timer")
    interval = IntervalController(context["store"], interval_ref, 10, actor=context["actor"])
    interval.start(request_key="timer-start")
    polled = dm.advance_timer(interval_ref, interval_seconds=10, now=interval.clock() + timedelta(seconds=20))
    assert polled.due and polled.request_id
    assert not context["store"].connection.execute("SELECT 1 FROM identities WHERE kind = 'reservation'").fetchone()


def test_explicit_manager_choice_is_receipted_but_not_auto_dispatched(context):
    dm = context["decisions"]
    choice = dm.choose_next_action(
        context["parent"], action="hold-for-owner", available_actions=("implement-change", "hold-for-owner"),
        context={"source": "manager inspected current evidence"}, residual_risk={"risk": "known"},
        verification_choice={"check": "run tests"}, logical_request_key="manager-choice",
    )
    assert choice.action == "hold-for-owner"
    assert choice.receipt.event_ids and not choice.automatic_dispatch
    assert choice.payload["next_task"] is None and choice.payload["workflow_score"] is None


def test_failed_candidate_command_rolls_back_all_owned_state(context):
    store = context["store"]
    before = (
        len(store.list_events()),
        store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0],
        store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
    )
    with pytest.raises(RuntimeError):
        context["decisions"].create_candidate(
            "rollback-candidate", parent_obligation=context["parent"], artifact=context["artifact"],
            source=context["source"], spec=context["spec"], criteria=(context["criterion"],),
            consumed_inputs=(context["source"],), owner="owner", logical_request_key="rollback-candidate",
            failure_injector=lambda phase: (_ for _ in ()).throw(RuntimeError(phase)),
        )
    assert (
        len(store.list_events()),
        store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0],
        store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
    ) == before
