"""WRK-04 focused proof: common assessment primitives and bounded accounting."""

from __future__ import annotations

import pytest

from herzchen.contracts import AuthenticatedActor, CommandEnvelope, ResourceRef, TransactionContext
from herzchen.domains.assessment import (
    AssessmentAuthorityError,
    AssessmentModule,
    AssessmentStateError,
    Disposition,
    StaleAssessmentError,
    Verdict,
    contribution,
)
from herzchen.domains.work import WorkGraph
from herzchen.kernel import (
    AllowanceExhaustedError,
    CapacityExhaustedError,
    LimitService,
    ReservationStatus,
    Store,
)


@pytest.fixture
def context(tmp_path):
    store = Store.create(tmp_path / "assessment.sqlite", authority="assessment-test")
    actor = AuthenticatedActor("assessment-test", "approver", "credential")
    graph = WorkGraph(store, actor=actor)
    parent = graph.create_task(graph.create_project(logical_request_key="project"), title="Parent obligation", logical_request_key="parent")
    criterion = graph.create_criterion(parent, title="Criterion", logical_request_key="criterion")

    def admit(kind: str, ident: str, payload: dict) -> ResourceRef:
        ref = ResourceRef(store.authority, kind, ident, "rev-1")
        store.put_identity(ref, payload, version=1)
        store.put_reference(ref)
        return ref

    source = admit("fixture.source", "source", {"record_type": "source", "value": "original"})
    artifact = admit("fixture.artifact", "artifact", {"record_type": "artifact", "value": "image"})
    spec = admit("fixture.spec", "spec", {"record_type": "spec", "value": "spec-v1"})
    annotation = admit("fixture.annotation", "annotation", {"record_type": "annotation", "value": "director note"})
    candidate = admit(
        "fixture.candidate",
        "candidate",
        {
            "record_type": "candidate",
            "artifact_ref": artifact,
            "source_ref": source,
            "spec_ref": spec,
            "consumed_refs": (source,),
            "annotation_ref": annotation,
        },
    )
    assessment = AssessmentModule(store, actor=actor)
    assessment.register()
    scope = assessment.declare_scope(
        ResourceRef(store.authority, "assessment.scope", "scope"),
        parent_obligation=parent,
        protocol="megado.delivery",
        criteria=(criterion,),
        designated_approver=actor.actor,
        authority="review-board",
        logical_request_key="scope",
    )
    packet = assessment.freeze_input(scope, packet={"candidate": candidate, "facts": ["original"]}, consumed_refs=(source,), logical_request_key="packet")
    pool = LimitService(store).create_pool(ResourceRef(store.authority, "limit", "pool"), 1, 3, logical_request_key="pool", actor=actor)
    try:
        yield {
            "store": store, "actor": actor, "graph": graph, "assessment": assessment,
            "parent": parent, "criterion": criterion, "source": source, "artifact": artifact,
            "spec": spec, "annotation": annotation, "candidate": candidate, "scope": scope,
            "packet": packet, "pool": pool,
        }
    finally:
        store.close()


def revise_fixture(store: Store, ref: ResourceRef, payload: dict, key: str) -> ResourceRef:
    current = store.get_identity(ref)
    assert current is not None
    actor = AuthenticatedActor("assessment-test", "fixture", "fixture-credential")
    envelope = CommandEnvelope(
        "fixture.revise", "fixture.v1", ref, TransactionContext(actor, key, "a" * 64, expected_revision=current.ref.revision, expected_version=current.version),
        payload,
    )
    receipt = store.mutate(envelope, event_type="fixture.revised", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-" + str(current.version + 1)), effects={"changed": True}, stream="fixture:" + ref.id)
    assert receipt.result_ref is not None
    return receipt.result_ref


def run_assessment(ctx, *, key: str, verdict: Verdict, route: str = "normal", role: str = "review", findings=(), actual_units=1, **extra):
    return ctx["assessment"].assess(
        ctx["scope"], candidate=ctx["candidate"], criterion=ctx["criterion"], input_packet=ctx["packet"],
        verdict=verdict, guidance={"next": "inspect"}, protocol_result={"protocol": "shared"}, findings=findings,
        limit_pool=ctx["pool"].ref, declared_units=1, actual_units=actual_units, route=route, role=role,
        logical_request_key=key, **extra,
    )


def test_megado_and_creative_lenses_share_scope_input_invocation_result_primitives(context):
    ctx = context
    megado = run_assessment(ctx, key="megado-review", verdict=Verdict.PASS)
    creative = run_assessment(ctx, key="creative-review", verdict=Verdict.REWORK, route="creative", role="review", actual_units=1)

    assert megado.scope_ref == creative.scope_ref == ctx["scope"].ref
    assert megado.input_packet_ref == creative.input_packet_ref == ctx["packet"].ref
    assert megado.invocation.ref.kind == creative.invocation.ref.kind == "assessment.invocation"
    assert megado.verdict is Verdict.PASS
    assert creative.verdict is Verdict.REWORK
    assert creative.guidance["next"] == "inspect"
    assert megado.invocation.operation_ref != creative.invocation.operation_ref
    assert not any(identity.ref.kind == "assessment.review-stage" for identity in ())


def test_unknown_is_distinct_charged_and_explicitly_disposed(context):
    ctx = context
    result = run_assessment(ctx, key="unknown-review", verdict=Verdict.UNKNOWN, actual_units=2)
    reservation = ctx["assessment"].limits.get_reservation(result.invocation.reservation_ref)
    assert result.verdict is Verdict.UNKNOWN
    assert result.invocation.state == "unknown"
    assert reservation is not None and reservation.status is ReservationStatus.CONSUMED
    assert reservation.charged_units == 2
    with pytest.raises(AssessmentAuthorityError):
        ctx["assessment"].dispose_unknown(result, disposition=Disposition.DEFER, authority="wrong-board", rationale="wait", logical_request_key="bad-disposition")
    decision = ctx["assessment"].dispose_unknown(result, disposition=Disposition.DEFER, authority="review-board", rationale="wait for external fact", logical_request_key="unknown-disposition")
    assert decision.payload["unknown_disposition"] is True


def test_exact_pins_changed_consumed_input_invalidates_but_annotation_change_does_not(context):
    ctx = context
    revise_fixture(ctx["store"], ctx["annotation"], {"record_type": "annotation", "value": "new note"}, "annotation-change")
    result = run_assessment(ctx, key="annotation-preserved", verdict=Verdict.PASS)
    assert result.candidate_ref == ctx["candidate"]
    assert result.criterion_ref == ctx["criterion"].ref

    revise_fixture(ctx["store"], ctx["source"], {"record_type": "source", "value": "changed"}, "source-change")
    before = len(ctx["store"].list_events())
    with pytest.raises(StaleAssessmentError):
        run_assessment(ctx, key="stale-source", verdict=Verdict.PASS)
    assert len(ctx["store"].list_events()) == before
    assert ctx["store"].get_receipt("stale-source") is None


def test_selection_assessment_acceptance_are_separate_and_approval_binds_exact_refs(context):
    ctx = context
    selection = ctx["assessment"].select_candidate(ctx["scope"], candidate=ctx["candidate"], criterion=ctx["criterion"], rationale="reversible and observable", logical_request_key="selection")
    assert selection.payload["accepts"] is False
    result = run_assessment(ctx, key="pass-review", verdict=Verdict.PASS)
    assert not result.accepted
    with pytest.raises(AssessmentAuthorityError):
        ctx["assessment"].accept(result, authority="wrong-board", rationale="approve", logical_request_key="bad-approval")
    decision = ctx["assessment"].accept(result, authority="review-board", rationale="review evidence binds the selected candidate", evidence_refs=(ctx["artifact"],), logical_request_key="approval")
    assert decision.candidate_ref == ctx["candidate"]
    assert decision.criterion_ref == ctx["criterion"].ref
    assert ctx["assessment"].list_decisions(parent_obligation=ctx["parent"])[0].ref == decision.ref


def test_invocation_success_does_not_close_parent_and_rework_keeps_parent_lineage(context):
    ctx = context
    rework = run_assessment(ctx, key="rework-review", verdict=Verdict.REWORK, findings=({"summary": "composition needs correction", "subjective": True},))
    with pytest.raises(AssessmentStateError):
        ctx["assessment"].accept(rework, authority="review-board", rationale="too early", logical_request_key="reject-rework")
    correction = ctx["assessment"].create_correction(rework, instruction="adjust the composition", logical_request_key="correction")
    assert correction.parent_obligation_ref == ctx["parent"].ref
    assert correction.result_ref.id == rework.ref.id
    with pytest.raises(AssessmentAuthorityError):
        ctx["assessment"].close_finding(rework.findings[0], test_only=True, evidence_refs=(ctx["artifact"],), logical_request_key="test-only-clear")

    fresh = run_assessment(ctx, key="post-correction-review", verdict=Verdict.PASS)
    decision = ctx["assessment"].accept(fresh, authority="review-board", rationale="later review accepted", logical_request_key="later-approval")
    assert decision.parent_obligation_ref == ctx["parent"].ref


def test_route_change_resume_unknown_and_overrun_do_not_refill_allowance(context):
    ctx = context
    first = run_assessment(ctx, key="route-normal", verdict=Verdict.PASS, actual_units=1)
    second = run_assessment(ctx, key="route-xhard", verdict=Verdict.UNKNOWN, route="xhard", actual_units=2)
    pool = ctx["assessment"].limits.get_pool(ctx["pool"].ref)
    assert pool is not None and pool.cumulative_used_units == 3
    assert pool.held_units == 0
    with pytest.raises(AllowanceExhaustedError):
        run_assessment(ctx, key="exhausted", verdict=Verdict.PASS, route="normal", actual_units=1)
    assert first.invocation.route != second.invocation.route
    assert ctx["store"].get_receipt("exhausted-reserve") is None


def test_atomic_whole_assessment_rolls_back_children_operation_receipts_and_reservation(context):
    ctx = context
    store = ctx["store"]
    before_identity_count = store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0]
    before_event_count = len(store.list_events())
    before_receipt_count = store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]
    with pytest.raises(RuntimeError, match="injected"):
        run_assessment(ctx, key="atomic-failure", verdict=Verdict.PASS, findings=({"summary": "child"},), failure_injector=lambda phase: (_ for _ in ()).throw(RuntimeError("injected")) if phase == "after-finding" else None)
    assert store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0] == before_identity_count
    assert len(store.list_events()) == before_event_count
    assert store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0] == before_receipt_count
    assert store.get_receipt("atomic-failure") is None
    assert store.get_identity(ResourceRef(store.authority, "assessment.result", "atomic-failure")) is None
    assert store.get_identity(ResourceRef(store.authority, "assessment.invocation", "atomic-failure")) is None
    assert store.get_identity(ResourceRef(store.authority, "reservation", "atomic-failure-reservation")) is None


def test_stale_criterion_rejects_and_no_review_is_policy_bound(context):
    ctx = context
    new_criterion = ctx["graph"].revise(ctx["criterion"], title="Changed criterion", logical_request_key="criterion-revision")
    with pytest.raises(StaleAssessmentError):
        run_assessment(ctx, key="stale-criterion", verdict=Verdict.PASS)
    no_review = AssessmentModule(ctx["store"], actor=ctx["actor"])
    permissive = no_review.declare_scope(ResourceRef(ctx["store"].authority, "assessment.scope", "permissive"), parent_obligation=ctx["parent"], protocol="scene.production", criteria=(new_criterion,), review_required=False, allow_no_review=True, designated_approver=ctx["actor"].actor, authority="review-board", logical_request_key="permissive-scope")
    decision = no_review.accept_without_review(permissive, candidate=ctx["candidate"], criterion=new_criterion, rationale="policy permits evidence-only acceptance", evidence_refs=(ctx["artifact"],), authority="review-board", logical_request_key="evidence-only")
    assert decision.payload["no_review"] is True
    required = ctx["assessment"].declare_scope(ResourceRef(ctx["store"].authority, "assessment.scope", "required"), parent_obligation=ctx["parent"], protocol="scene.production", criteria=(new_criterion,), review_required=True, allow_no_review=True, designated_approver=ctx["actor"].actor, authority="review-board", logical_request_key="required-scope")
    with pytest.raises(AssessmentAuthorityError):
        no_review.accept_without_review(required, candidate=ctx["candidate"], criterion=new_criterion, rationale="not permitted", logical_request_key="forbidden-evidence-only")


def test_history_is_readable_and_loop_facts_do_not_infer_progress_or_create_stage(context):
    ctx = context
    result = run_assessment(ctx, key="history-pass", verdict=Verdict.PASS)
    decision = ctx["assessment"].accept(result, authority="review-board", rationale="accepted", logical_request_key="history-approval")
    assert ctx["assessment"].get_decision(decision.ref).ref == decision.ref
    facts_ref = ctx["assessment"].record_loop_facts(ctx["parent"], attempt_count=2, unresolved_findings=0, exhausted_allowance=False, required_approver="approver", logical_request_key="facts")
    facts = ctx["store"].get_identity(facts_ref)
    assert facts is not None and facts.payload["inference"] is None
    kinds = {row[0] for row in ctx["store"].connection.execute("SELECT DISTINCT kind FROM identities")}
    assert "assessment.review-stage" not in kinds
