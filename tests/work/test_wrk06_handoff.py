"""WRK-06 evidence rehearsal over the public FND/WRK assessment ports.

This is deliberately one disposable local fixture.  It emits the observed
references/counters to ``/tmp/wrk06-evidence.json`` for handoff assembly; it
does not invoke a model or add a persistence surface.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import pytest

from herzchen.content import ContentCommandHandler
from herzchen.contracts import AuthenticatedActor, CommandEnvelope, EventCursor, ReferenceBinding, ResourceRef, TransactionContext
from herzchen.domains.assessment import AssessmentModule, Verdict
from herzchen.domains.work import WorkGraph
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.decisions import DecisionsModule
from herzchen.kernel import LimitService, Store
from herzchen.packs.templates import TemplateEngine, work_protocol, work_template


EVIDENCE_PATH = Path("/tmp/wrk06-evidence.json")


def _json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return _json(value.to_dict())
    if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
        return value.value
    return repr(value)


def _ref(value: Any) -> Any:
    return _json(value)


def _counts(store: Store, pool_ref: ResourceRef) -> dict[str, Any]:
    query = store.connection.execute
    pool = LimitService(store).get_pool(pool_ref)
    return {
        "identities": query("SELECT COUNT(*) FROM identities").fetchone()[0],
        "receipts": query("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
        "events": query("SELECT COUNT(*) FROM events").fetchone()[0],
        "references": query("SELECT COUNT(*) FROM record_references").fetchone()[0],
        "event_sequences": [dict(row) for row in query("SELECT stream,next_sequence FROM event_sequences ORDER BY stream").fetchall()],
        "pool": {
            "held_units": pool.held_units,
            "cumulative_used_units": pool.cumulative_used_units,
            "remaining_allowance_units": pool.remaining_allowance_units,
        },
    }


def _receipt(store: Store, key: str) -> Any:
    return _json(store.get_receipt(key))


def _events_for(store: Store, key: str) -> dict[str, Any]:
    receipt = store.get_receipt(key)
    if receipt is None:
        return {"request_key": key, "receipt": None}
    wanted = set(receipt.event_ids)
    events = [event for event in store.list_events() if event.event_id in wanted]
    return {
        "request_key": key,
        "receipt_id": receipt.transaction_id,
        "status": receipt.status.value,
        "event_ids": list(receipt.event_ids),
        "result_ref": _ref(receipt.result_ref),
        "replayed": receipt.replayed,
        "events": [{"event_id": e.event_id, "stream": e.stream, "sequence": e.sequence, "event_type": e.event_type} for e in events],
    }


def _admit(store: Store, kind: str, ident: str, value: str) -> ResourceRef:
    ref = ResourceRef(store.authority, kind, ident, "rev-1")
    store.put_identity(ref, {"record_type": kind, "value": value}, version=1)
    store.put_reference(ref)
    return ref


def _revise_fixture(store: Store, ref: ResourceRef, value: str, key: str, actor: AuthenticatedActor) -> ResourceRef:
    current = store.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
    assert current is not None
    envelope = CommandEnvelope(
        "fixture.revise", "fixture.v1", ResourceRef(ref.authority, ref.kind, ref.id),
        TransactionContext(actor, key, "a" * 64, expected_revision=current.ref.revision, expected_version=current.version),
        {"record_type": ref.kind, "value": value},
    )
    receipt = store.mutate(
        envelope, event_type="fixture.revised",
        result_ref=ResourceRef(ref.authority, ref.kind, ref.id, f"rev-{current.version + 1}"),
        effects={"changed": True}, stream=f"fixture:{ref.id}",
    )
    assert receipt.result_ref is not None
    return receipt.result_ref


def _rejection(store: Store, pool_ref: ResourceRef, call: Any) -> dict[str, Any]:
    before = _counts(store, pool_ref)
    with pytest.raises(Exception) as caught:
        call()
    after = _counts(store, pool_ref)
    return {
        "error_type": type(caught.value).__name__, "message": str(caught.value),
        "before": before, "after": after,
        "receipt_delta": after["receipts"] - before["receipts"],
        "event_delta": after["events"] - before["events"],
    }


def test_wrk06_public_handoff_rehearsal(tmp_path: Path) -> None:
    db = tmp_path / "wrk06.sqlite"
    authority = "wrk06-evidence"
    actor = AuthenticatedActor(authority, "manager", "credential")
    store = Store.create(db, authority=authority)
    graph = WorkGraph(store, actor=actor); graph.register()
    assessment = AssessmentModule(store, actor=actor); assessment.register()
    decisions = DecisionsModule(store, assessment=assessment, actor=actor); decisions.register()
    expected_domains = store.registered_domains()
    project = graph.create_project(title="WRK-06 evidence", outcome="bounded handoff", logical_request_key="project")
    parent = graph.create_task(project, title="Assessment obligation", logical_request_key="parent")
    criterion = graph.create_criterion(parent, title="Exact criterion", logical_request_key="criterion")
    source = _admit(store, "fixture.source", "source", "source-v1")
    artifact = _admit(store, "fixture.artifact", "artifact", "artifact-v1")
    spec = _admit(store, "fixture.spec", "spec", "spec-v1")
    pool = LimitService(store).create_pool(ResourceRef(authority, "limit", "review-pool"), 2, 50, logical_request_key="pool", actor=actor)

    scope = assessment.declare_scope(ResourceRef(authority, "assessment.scope", "megado-scope"), parent_obligation=parent, protocol="megado.delivery", criteria=(criterion,), designated_approver="manager", authority="review-board", logical_request_key="scope-megado")
    packet = assessment.freeze_input(scope, packet={"candidate": "A", "facts": ["local fake reviewer"]}, consumed_refs=(source,), logical_request_key="packet-megado")
    candidate_a = decisions.create_candidate("candidate-A", parent_obligation=parent, artifact=artifact, source=source, spec=spec, criteria=(criterion,), consumed_inputs=(source,), owner="owner", role="implementation", provenance={"fixture": "local-fake-reviewer"}, logical_request_key="candidate-A")
    candidate_b = decisions.create_candidate("candidate-B", parent_obligation=parent, artifact=artifact, source=source, spec=spec, criteria=(criterion,), consumed_inputs=(source,), owner="owner", role="implementation", provenance={"fixture": "local-fake-reviewer"}, logical_request_key="candidate-B")
    selection = assessment.select_candidate(scope, candidate=candidate_a, criterion=criterion, rationale="A selected for bounded fake review", logical_request_key="selection-A")
    result_a = assessment.assess(scope, candidate=candidate_a, criterion=criterion, input_packet=packet, verdict=Verdict.PASS, guidance={"next": "inspect"}, protocol_result={"fixture": "deterministic-local-fake-reviewer", "model_invoked": False}, limit_pool=pool.ref, declared_units=2, actual_units=1, route="normal", role="review", logical_request_key="assessment-A")
    replay_a = assessment.assess(scope, candidate=candidate_a, criterion=criterion, input_packet=packet, verdict=Verdict.PASS, guidance={"next": "inspect"}, protocol_result={"fixture": "deterministic-local-fake-reviewer", "model_invoked": False}, limit_pool=pool.ref, declared_units=2, actual_units=1, route="normal", role="review", logical_request_key="assessment-A")
    alias_replay_a = assessment.assess_candidate(scope, candidate=candidate_a, criterion=criterion, input_packet=packet, verdict=Verdict.PASS, guidance={"next": "inspect"}, protocol_result={"fixture": "deterministic-local-fake-reviewer", "model_invoked": False}, limit_pool=pool.ref, declared_units=2, actual_units=1, route="normal", role="review", logical_request_key="assessment-A")
    resume_replay_a = assessment.resume(scope, candidate=candidate_a, criterion=criterion, input_packet=packet, verdict=Verdict.PASS, guidance={"next": "inspect"}, protocol_result={"fixture": "deterministic-local-fake-reviewer", "model_invoked": False}, limit_pool=pool.ref, declared_units=2, actual_units=1, route="normal", role="review", logical_request_key="assessment-A")
    decision_a = assessment.accept(result_a, authority="review-board", rationale="A PASS with local fake-review evidence", evidence_refs=(artifact,), logical_request_key="accept-A")
    assert replay_a.ref == result_a.ref

    atomic: dict[str, Any] = {}
    for phase in ("after-invocation", "after-finding", "after-parent"):
        key = "crash-" + phase.replace("-", "_")
        before = _counts(store, pool.ref)
        with pytest.raises(RuntimeError, match="injected"):
            assessment.assess(scope, candidate=candidate_b, criterion=criterion, input_packet=packet, verdict=Verdict.PASS, guidance={"phase": phase}, protocol_result={"fixture": "deterministic-local-fake-reviewer", "model_invoked": False}, findings=(({"summary": "atomic child"},) if phase == "after-finding" else ()), limit_pool=pool.ref, declared_units=1, actual_units=1, logical_request_key=key, failure_injector=lambda point, expected=phase: (_ for _ in ()).throw(RuntimeError("injected-" + point)) if point == expected else None)
        failed = _counts(store, pool.ref)
        assert failed == before and store.get_receipt(key) is None
        assert store.get_identity(ResourceRef(authority, "assessment.result", key)) is None
        assert store.get_identity(ResourceRef(authority, "assessment.invocation", key)) is None
        assert store.get_identity(ResourceRef(authority, "reservation", key + "-reservation")) is None
        store.close(); store = Store.open(db, authority=authority, expected_domains=expected_domains)
        graph = WorkGraph(store, actor=actor)
        assessment = AssessmentModule(store, actor=actor)
        decisions = DecisionsModule(store, assessment=assessment, actor=actor)
        retry = assessment.assess(scope, candidate=candidate_b, criterion=criterion, input_packet=packet, verdict=Verdict.PASS, guidance={"phase": phase}, protocol_result={"fixture": "deterministic-local-fake-reviewer", "model_invoked": False}, findings=(({"summary": "atomic child"},) if phase == "after-finding" else ()), limit_pool=pool.ref, declared_units=1, actual_units=1, logical_request_key=key)
        atomic[phase] = {"before": before, "after_failure": failed, "retry_result_ref": _ref(retry.ref), "retry_receipt": _events_for(store, key), "after_retry": _counts(store, pool.ref)}

    scene_scope = assessment.declare_scope(ResourceRef(authority, "assessment.scope", "scene-scope"), parent_obligation=parent, protocol="scene.production", criteria=(criterion,), designated_approver="manager", authority="review-board", logical_request_key="scope-scene")
    scene_packet = assessment.freeze_input(scene_scope, packet={"shot": "take-2", "brief": "uneasy"}, consumed_refs=(source,), logical_request_key="packet-scene")
    creative = assessment.assess(scene_scope, candidate=candidate_b, criterion=criterion, input_packet=scene_packet, verdict=Verdict.REWORK, guidance={"next": "revise composition"}, protocol_result={"protocol": "scene.production", "fixture": "local-fake-reviewer", "model_invoked": False}, findings=({"summary": "composition does not meet the brief", "severity": "high", "subjective": True},), limit_pool=pool.ref, declared_units=1, actual_units=1, route="creative", role="critic", logical_request_key="creative-rework")
    correction = assessment.create_correction(creative, instruction="revise the exact edit to match the brief", logical_request_key="creative-correction")
    creative_rejection = _rejection(store, pool.ref, lambda: assessment.close_finding(creative.findings[0], test_only=True, evidence_refs=(artifact,), logical_request_key="creative-test-only-close"))

    permissive = assessment.declare_scope(ResourceRef(authority, "assessment.scope", "no-review-scope"), parent_obligation=parent, protocol="scene.production", criteria=(criterion,), review_required=False, allow_no_review=True, designated_approver="manager", authority="review-board", logical_request_key="scope-no-review")
    no_review_before = _counts(store, pool.ref)
    no_review = assessment.accept_without_review(permissive, candidate=candidate_b, criterion=criterion, rationale="evidence-only policy permits this", evidence_refs=(artifact,), authority="review-board", logical_request_key="accept-without-review")
    no_review_after = _counts(store, pool.ref)
    required = assessment.declare_scope(ResourceRef(authority, "assessment.scope", "review-required-scope"), parent_obligation=parent, protocol="scene.production", criteria=(criterion,), review_required=True, allow_no_review=True, designated_approver="manager", authority="review-board", logical_request_key="scope-required")
    no_review_rejection = _rejection(store, pool.ref, lambda: assessment.accept_without_review(required, candidate=candidate_b, criterion=criterion, rationale="should be rejected", logical_request_key="reject-without-review"))

    annotation = decisions.annotate_candidate(candidate_a, {"note": "irrelevant annotation"}, logical_request_key="annotation-A")
    applicable_annotation = decisions.check_applicability(candidate_a, annotation_refs=(annotation,))
    mismatch = _rejection(store, pool.ref, lambda: decisions.record_decision(parent, candidate=candidate_b, criterion=criterion, evidence_refs=(artifact,), evidence_basis={"review": "A"}, author="manager", authority="review-board", rationale="mismatched candidate must fail", disposition="approved", return_condition="source changes", assessment_result=result_a, required_approval=True, logical_request_key="mismatched-B-result-A"))
    source_before = candidate_a.source_ref
    source_after = _revise_fixture(store, source, "source-v2", "source-revision", actor)
    applicable_source = decisions.check_applicability(candidate_a)
    historical_decision = assessment.get_decision(decision_a.ref)

    assignment = ResponsibilityAssignments(store, actor=actor).assign(parent, role="manager", principal="manager", logical_request_key="assignment-wait")
    wait_decision = decisions.record_decision(parent, candidate=candidate_b, criterion=criterion, authority="review-board", rationale="manager decision required", disposition="defer", return_condition="manager revisits", logical_request_key="wait-decision")
    wait = decisions.record_wait(parent, missing_obligation="real manager decision", owner=assignment.ref, awaited_ref=wait_decision.ref, revisit_condition="when awaited revision or attention changes", required_decision_ref=wait_decision.ref, residual_risk={"choice": "hold"}, metadata={"note": "attention only"}, logical_request_key="wait-1")
    store.close(); store = Store.open(db, authority=authority, expected_domains=expected_domains)
    graph = WorkGraph(store, actor=actor)
    assessment = AssessmentModule(store, actor=actor); decisions = DecisionsModule(store, assessment=assessment, actor=actor)
    wait_reopened = decisions.get_wait(wait.ref)
    decisions.record_wait(parent, missing_obligation="real manager decision", owner=assignment.ref, awaited_ref=wait_decision.ref, revisit_condition="when awaited revision or attention changes", required_decision_ref=wait_decision.ref, residual_risk={"choice": "hold"}, metadata={"note": "attention only"}, logical_request_key="wait-2")
    stream = "attention:" + parent.ref.id
    events = store.list_events(stream=stream)
    page1 = decisions.reconcile_notifications(stream, limit=1)
    page2 = decisions.reconcile_notifications(stream, cursor=page1.cursor, limit=10)
    duplicate = decisions.observe_notification(EventCursor(authority, stream, events[0].sequence, events[0].event_id), events[0])
    reordered = decisions.observe_notification(EventCursor(authority, stream, events[1].sequence, events[1].event_id), events[0])
    bypass = _rejection(store, pool.ref, lambda: decisions.record_wait(parent, missing_obligation="renamed review bypass", owner="manager", awaited_ref=wait_decision.ref, required_decision_ref=wait_decision.ref, equivalent_review_name="renamed-review", logical_request_key="bypass-wait"))

    root = Path(__file__).resolve().parents[2]
    megado_protocol_data = json.loads((root / "packs/megado/protocols/megado.json").read_text())
    delivery_bytes = (root / "packs/megado/templates/delivery.json").read_bytes()
    delivery_sha256 = hashlib.sha256(delivery_bytes).hexdigest()
    delivery_data = json.loads(delivery_bytes)
    scene_protocol_data = json.loads((root / "packs/scene-production/protocols/scene.json").read_text())
    megado_protocol = work_protocol(megado_protocol_data["id"], str(megado_protocol_data["schema_version"]), definition=megado_protocol_data, source_ref=ResourceRef("pack", "work_protocol", megado_protocol_data["id"], str(megado_protocol_data["schema_version"])))
    delivery = work_template(delivery_data["id"], delivery_data["version"], parameters=delivery_data["parameters"], seed=delivery_data["seed"], source_ref=ResourceRef("pack", "work_template", delivery_data["id"], delivery_data["version"]))
    import_project = graph.create_project(title="Imported Megado project", outcome="imported structure", logical_request_key="import-project")
    engine = TemplateEngine(store, graph=graph, actor=actor, resources=(delivery, megado_protocol))
    import_before = _counts(store, pool.ref)
    import_parameters = {"title": "Imported effort", "outcome": "Implement", "proof": "Demonstrate"}
    import_key = "megado-import"
    direct_import = engine.instantiate(delivery, import_parameters, project=import_project, logical_request_key=import_key)
    direct_after = _counts(store, pool.ref)
    assert set(direct_import.local_refs) == {"effort", "implement", "verify", "criterion"}
    assert len(direct_import.records) == 4
    direct_by_local = {record.payload["fields"]["template_origin"]["local_id"]: record for record in direct_import.records}
    assert direct_by_local["effort"].title == "Imported effort"
    assert direct_by_local["effort"].payload["fields"]["outcome"] == "Implement"
    assert direct_by_local["effort"].payload["fields"]["status"] == "planning_only"
    assert direct_by_local["implement"].title == "Deliver the specified outcome"
    assert direct_by_local["implement"].payload["fields"]["outcome"] == "Implement"
    assert direct_by_local["implement"].payload["fields"]["custom"] == {"megado": {"execution_class": "normal"}}
    assert direct_by_local["verify"].title == "Demonstrate the outcome"
    assert direct_by_local["verify"].payload["fields"]["outcome"] == "Demonstrate"
    assert direct_by_local["verify"].payload["fields"]["custom"] == {"megado": {"execution_class": "normal"}}
    assert direct_by_local["criterion"].title == "Required observable behavior"
    assert direct_by_local["criterion"].payload["fields"]["outcome"] == "Demonstrate"
    assert direct_by_local["effort"].payload["fields"]["documents"] == [{"local_id": "goal", "title": "Bounded goal", "content": "Implement"}]
    assert direct_by_local["effort"].payload["fields"]["document_links"] == delivery_data["seed"]["document_links"]
    assert direct_after["pool"] == import_before["pool"]
    assert direct_by_local["effort"].parent.id == direct_import.project.id
    assert all(direct_by_local[name].parent.id == direct_by_local["effort"].id for name in ("implement", "verify", "criterion"))
    assert direct_by_local["verify"].dependencies == (ResourceRef(direct_by_local["implement"].ref.authority, direct_by_local["implement"].ref.kind, direct_by_local["implement"].ref.id),)
    assert direct_by_local["implement"].dependencies == ()
    assert direct_by_local["criterion"].ref.id not in {dependency.id for dependency in direct_by_local["implement"].dependencies}
    assert direct_by_local["implement"].payload["fields"]["links"] == [{
        "from": {"$local": "implement"}, "to": {"$local": "criterion"}, "relation": "covers",
    }]
    assert direct_by_local["verify"].payload["fields"]["links"] == [{
        "from": {"$local": "verify"}, "to": {"$local": "implement"}, "relation": "requires",
    }]
    direct_content = ContentCommandHandler(store)
    direct_document_read = direct_content.read(direct_import.document_refs["goal"])
    direct_association_read = direct_content.read(direct_import.association_refs["effort:megado:goal"])
    assert direct_import.rendered.seed["documents"][0]["content"] == "Implement"
    assert direct_document_read["identity"] == direct_import.document_refs["goal"]
    assert direct_document_read["current_revision"]["revision"] == direct_document_read["revision"]["revision"]
    assert direct_document_read["revision"]["initial"] is True
    assert direct_document_read["revision"]["content"] == "Implement"
    binding = ReferenceBinding.from_dict(direct_association_read["payload"]["association"]["document"])
    assert isinstance(binding, ReferenceBinding)
    assert binding.mode == "current" and binding.ref == direct_import.document_refs["goal"]
    assert direct_association_read["payload"]["association"]["document"]["ref"] == direct_import.document_refs["goal"].to_dict()
    assert direct_association_read["payload"]["association"]["document"]["mode"] == "current"
    assert direct_association_read["payload"]["active"] is True
    assert len(direct_import.receipts) == 6
    assert all(receipt.status.value == "committed" and receipt.event_ids for receipt in direct_import.receipts)
    store.close()
    store = Store.open(db, authority=authority, expected_domains=expected_domains)
    graph = WorkGraph(store, actor=actor)
    direct_reopened_content = ContentCommandHandler(store)
    reopened_document_read = direct_reopened_content.read(direct_import.document_refs["goal"])
    reopened_association_read = direct_reopened_content.read(direct_import.association_refs["effort:megado:goal"])
    assert reopened_document_read["revision"]["content"] == "Implement"
    assert reopened_association_read["payload"]["association"]["document"]["mode"] == "current"
    engine = TemplateEngine(store, graph=graph, actor=actor, resources=(delivery, megado_protocol))
    direct_replay = engine.instantiate(delivery, import_parameters, project=direct_import.project, logical_request_key=import_key)
    direct_replay_after = _counts(store, pool.ref)
    assert direct_replay.project.ref == direct_import.project.ref
    assert [record.ref for record in direct_replay.records] == [record.ref for record in direct_import.records]
    assert direct_replay.local_refs == direct_import.local_refs
    assert direct_replay.document_refs == direct_import.document_refs
    assert direct_replay.association_refs == direct_import.association_refs
    assert direct_replay.receipts == direct_import.receipts
    assert direct_replay_after == direct_after
    assert direct_reopened_content.read(direct_import.document_refs["goal"])["revision"]["content"] == "Implement"
    assert direct_reopened_content.read(direct_import.association_refs["effort:megado:goal"])["payload"]["active"] is True
    second_project = graph.create_project(title="Independent scene project", outcome="scene protocol", logical_request_key="scene-project")
    scene_protocol = work_protocol(scene_protocol_data["id"], str(scene_protocol_data["schema_version"]), definition=scene_protocol_data, source_ref=ResourceRef("pack", "work_protocol", scene_protocol_data["id"], str(scene_protocol_data["schema_version"])))
    scene_engine = TemplateEngine(store, graph=graph, actor=actor, resources=(scene_protocol,))
    scene_project = scene_engine.adopt_protocol(second_project, scene_protocol, logical_request_key="scene-adopt")

    imported_records = []
    for record in direct_import.records:
        fields = record.payload.get("fields", {})
        imported_records.append({"local_id": fields.get("template_origin", {}).get("local_id"), "kind": record.kind.value, "id": record.id, "title": record.title, "outcome": fields.get("outcome"), "custom": fields.get("custom"), "status": fields.get("status"), "namespace": fields.get("namespace"), "key": fields.get("key"), "ref": _ref(record.ref), "parent_ref": _ref(record.parent), "dependencies": [_ref(x) for x in record.dependencies], "links": fields.get("links", []), "documents": fields.get("documents", []), "document_links": fields.get("document_links", []), "template_origin": fields.get("template_origin")})

    evidence = {
        "db_path": str(db), "authority": authority,
        "normal": {"scope_ref": _ref(scope.ref), "input_ref": _ref(packet.ref), "candidate_a": {"ref": _ref(candidate_a.ref), "pin": _json(candidate_a.pin)}, "candidate_b": {"ref": _ref(candidate_b.ref), "pin": _json(candidate_b.pin)}, "selection_ref": _ref(selection.ref), "result_ref": _ref(result_a.ref), "invocation_ref": _ref(result_a.invocation.ref), "operation_ref": _ref(result_a.invocation.operation_ref), "reservation_ref": _ref(result_a.invocation.reservation_ref), "declared_units": result_a.invocation.declared_units, "actual_units": result_a.invocation.actual_units, "charged_units": LimitService(store).get_reservation(result_a.invocation.reservation_ref).charged_units, "state": result_a.invocation.state, "replay_same_result": replay_a.ref == result_a.ref, "assess_candidate_alias_same_result": alias_replay_a.ref == result_a.ref, "resume_alias_same_result": resume_replay_a.ref == result_a.ref, "acceptance_property": result_a.accepted, "decision_ref": _ref(decision_a.ref), "decision_receipt": _events_for(store, "accept-A")},
        "atomicity": atomic,
        "creative": {"scope_ref": _ref(scene_scope.ref), "protocol": "scene.production", "role": "critic", "result_ref": _ref(creative.ref), "verdict": creative.verdict.value, "finding_ref": _ref(creative.findings[0].ref), "subjective": creative.findings[0].subjective, "correction_ref": _ref(correction.ref), "correction_parent_ref": _ref(correction.parent_obligation_ref), "test_only_rejection": creative_rejection, "acceptance_property": creative.accepted},
        "no_review": {"positive": {"decision_ref": _ref(no_review.ref), "result_ref": _ref(no_review.result_ref), "no_review": no_review.payload["no_review"], "before": no_review_before, "after": no_review_after, "receipt": _events_for(store, "accept-without-review")}, "negative": no_review_rejection},
        "candidate_boundary": {"mismatch_rejection": mismatch, "annotation_ref": _ref(annotation), "after_annotation": {"status": applicable_annotation.status.value, "affected_refs": [_ref(x) for x in applicable_annotation.affected_refs]}, "source_before": _ref(source_before), "source_after": _ref(source_after), "after_source": {"status": applicable_source.status.value, "affected_refs": [_ref(x) for x in applicable_source.affected_refs]}, "historical_decision": {"ref": _ref(historical_decision.ref), "candidate_ref": _ref(historical_decision.candidate_ref), "disposition": historical_decision.disposition}},
        "waiting": {"assignment_ref": _ref(assignment.ref), "wait_ref": _ref(wait.ref), "receipt": _events_for(store, "wait-1"), "owner_ref": _ref(wait_reopened.owner_ref), "awaited_ref": _ref(wait_reopened.awaited_ref), "awaited_revision": wait_reopened.awaited_revision, "current_revision": wait_reopened.current_revision, "attention_event_id": wait_reopened.attention_event_id, "dispatch": wait_reopened.dispatch, "reservation_ref": wait_reopened.payload["reservation_ref"], "restart_readback": wait_reopened.ref == wait.ref, "stream": stream, "events": [{"event_id": e.event_id, "sequence": e.sequence, "event_type": e.event_type} for e in events], "page1": {"events": [e.event_id for e in page1.page.events], "cursor": _json(page1.cursor), "work_ready": page1.work_ready, "business_dispatches": page1.business_dispatches}, "page2": {"events": [e.event_id for e in page2.page.events], "cursor": _json(page2.cursor), "work_ready": page2.work_ready, "business_dispatches": page2.business_dispatches}, "duplicate": _json(duplicate), "reordered": _json(reordered), "bypass_rejection": bypass},
        "import": {
            "resources": {
                "megado_protocol_ref": _ref(megado_protocol.ref),
                "delivery_template_ref": _ref(delivery.ref),
                "delivery_source_path": str(root / "packs/megado/templates/delivery.json"),
                "delivery_sha256": delivery_sha256,
                "megado_role_slots": megado_protocol_data["role_slots"],
                "megado_routes": megado_protocol_data["routes"],
            },
            "direct_shipped_resource": {
                "request_key": import_key,
                "parameters": import_parameters,
                "owner_project_ref": _ref(direct_import.project.ref),
                "before": import_before,
                "after": direct_after,
                "replay_after_reopen": direct_replay_after,
                "fresh_store_open_expected_domains": [domain.domain_id for domain in expected_domains],
                "records": len(direct_import.records),
                "replay_records": len(direct_replay.records),
                "ids_by_local_ref": {name: _ref(value) for name, value in direct_import.local_refs.items()},
                "replay_same_ids": direct_replay.local_refs == direct_import.local_refs,
                "dependencies": {
                    "verify": [_ref(value) for value in direct_by_local["verify"].dependencies],
                    "implement": [_ref(value) for value in direct_by_local["implement"].dependencies],
                },
                "records_detail": imported_records,
                "rendered_seed_work": direct_import.rendered.seed["work"],
                "rendered_goal_content": direct_import.rendered.seed["documents"][0]["content"],
                "document_ref": _ref(direct_import.document_refs["goal"]),
                "document_read": _json(direct_document_read),
                "reopened_document_read": _json(reopened_document_read),
                "association_ref": _ref(direct_import.association_refs["effort:megado:goal"]),
                "association_read": _json(direct_association_read),
                "reopened_association_read": _json(reopened_association_read),
                "receipts": [_events_for(store, import_key + ":" + name) for name in ("effort", "criterion", "implement", "verify")] + [_events_for(store, import_key + ":document:goal"), _events_for(store, import_key + ":link:effort:megado:goal")],
                "no_duplicate_receipts_events_references_counters": direct_replay_after == direct_after,
                "requires_only_dependency_projection": direct_by_local["verify"].dependencies[0].id == direct_import.local_refs["implement"].id and direct_by_local["implement"].dependencies == (),
                "gate_ids": [],
                "model_invocations": 0,
                "new_allowance_units": 0,
                "new_scheduler_state": False,
                "new_review_pool": False,
                "new_dispatches": 0,
            },
            "rollback_proof": {
                "focused_tests": ["tests/packs/test_task_templates.py::test_invalid_shipped_shape_writes_nothing", "tests/packs/test_task_templates.py::test_document_association_failure_rolls_back_work_and_dat_savepoints"],
                "claim": "The focused PKG tests prove malformed shipped resources and failed DAT association leave the complete transaction unchanged; this rehearsal cites them without duplicating the broad failure suites.",
            },
        },
        "second_protocol": {"scene_protocol_ref": _ref(scene_protocol.ref), "role_slots": scene_protocol_data["role_slots"], "routes": scene_protocol_data["routes"], "project_ref": _ref(scene_project.ref), "protocol_ref": scene_project.payload.get("fields", {}).get("protocol_ref"), "separate_from_import": scene_project.ref != direct_import.project.ref, "receipt": _events_for(store, "scene-adopt")},
        "receipt_index": {key: _events_for(store, key) for key in ("assessment-A", "accept-A", "creative-rework", "creative-correction", "accept-without-review", "annotation-A", "source-revision", "assignment-wait", "wait-decision", "wait-1", "wait-2", "megado-import", "scene-adopt")},
        "final_counters": _counts(store, pool.ref),
        "registered_domains": [item.domain_id for item in store.registered_domains()],
    }
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True))
    store.close()
