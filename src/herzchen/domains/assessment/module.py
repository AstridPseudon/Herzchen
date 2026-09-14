"""Shared bounded assessment operations over the supplied FND ports.

There is no assessment table or private writer here.  A parent operation is a
single FND command/receipt.  Child projections are deterministic identities in
that same transaction, and a failure rolls back the parent, children, events,
receipts, operation identity, and reservation together.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from herzchen.command_ports import command_facade

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    ResourceRef,
    TransactionContext,
    canonical_json,
    canonical_request_digest,
    validate_replay,
)
from herzchen.kernel import (
    AllowanceExhaustedError,
    LimitService,
    OperationManager,
    OperationRequest,
    OperationState,
    ReservationRecord,
    Store,
    TargetMismatchError,
    VersionConflictError,
)

from .model import (
    AssessmentAuthorityError,
    AssessmentError,
    AssessmentNotFoundError,
    AssessmentResult,
    AssessmentScope,
    AssessmentStateError,
    CandidateSelection,
    Correction,
    Decision,
    Disposition,
    Finding,
    InputPacket,
    Invocation,
    StaleAssessmentError,
    Verdict,
)


DOMAIN_ID = "herzchen.assessment"
DOMAIN_VERSION = "1.0"
DOMAIN_OWNER = "wrk"
SCHEMA_REVISION = "assessment.v1"
SCOPE_KIND = "assessment.scope"
CRITERION_KIND = "assessment.criterion"
INPUT_KIND = "assessment.input"
SELECTION_KIND = "assessment.selection"
RESULT_KIND = "assessment.result"
INVOCATION_KIND = "assessment.invocation"
FINDING_KIND = "assessment.finding"
CORRECTION_KIND = "assessment.correction"
DECISION_KIND = "assessment.decision"
LOOP_FACTS_KIND = "assessment.loop-facts"
ASSESSMENT_STREAM = "assessment"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _ref(value: Any, field: str = "reference") -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
        return value.ref
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except Exception as exc:  # pragma: no cover - contract supplies detail
            raise AssessmentError(f"{field} must be a typed ResourceRef") from exc
    if isinstance(value, str) and value.strip():
        raise AssessmentError(f"{field} must be a typed ResourceRef, not an untyped id")
    raise AssessmentError(f"{field} must be a typed ResourceRef")


def _ref_dict(value: Optional[ResourceRef]) -> Optional[dict[str, Any]]:
    return None if value is None else value.to_dict()


def _safe(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    return value


def _logical_ref(value: Any, field: str) -> ResourceRef:
    """Normalize only projection objects; explicit refs retain their pins."""
    ref = _ref(value, field)
    if isinstance(value, (AssessmentResult, Finding)):
        return ResourceRef(ref.authority, ref.kind, ref.id)
    return ref


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise AssessmentError(f"{field} must be a non-blank opaque identifier")
    return value


def contribution() -> DomainContribution:
    return DomainContribution(
        domain_id=DOMAIN_ID,
        version=DOMAIN_VERSION,
        owner=DOMAIN_OWNER,
        resource_types=(
            SCOPE_KIND, CRITERION_KIND, INPUT_KIND, SELECTION_KIND, RESULT_KIND,
            INVOCATION_KIND, FINDING_KIND, CORRECTION_KIND, DECISION_KIND,
            LOOP_FACTS_KIND,
        ),
        document_types=(),
        namespace_types=("assessment", "assessment.guidance", "assessment.protocol"),
        operation_types=(
            "assessment.scope.declare", "assessment.input.freeze", "assessment.candidate.select",
            "assessment.run", "assessment.correction.create", "assessment.finding.close",
            "assessment.accept", "assessment.unknown.disposition", "assessment.loop-facts.record",
            "assessment.result.link-correction",
        ),
        event_types=(
            "assessment.scope.declared", "assessment.input.frozen", "assessment.candidate.selected",
            "assessment.completed", "assessment.correction.created", "assessment.finding.closed",
            "assessment.accepted", "assessment.unknown.disposed", "assessment.loop-facts.recorded",
            "assessment.result.correction-linked",
        ),
        schema_revision=SCHEMA_REVISION,
        composition_bindings=(
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "fnd-04.limits", "fnd-04.operations", "handler-required",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.scope.declare|" + SCOPE_KIND + "|assessment.scope.declared",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.input.freeze|" + INPUT_KIND + "|assessment.input.frozen",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.candidate.select|" + SELECTION_KIND + "|assessment.candidate.selected",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.run|" + RESULT_KIND + "|assessment.completed",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.correction.create|" + CORRECTION_KIND + "|assessment.correction.created",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.finding.close|" + FINDING_KIND + "|assessment.finding.closed",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.accept|" + DECISION_KIND + "|assessment.accepted",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.unknown.disposition|" + DECISION_KIND + "|assessment.unknown.disposed",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.loop-facts.record|" + LOOP_FACTS_KIND + "|assessment.loop-facts.recorded",
            "mutation-port:" + SCHEMA_REVISION + "|assessment.result.link-correction|" + RESULT_KIND + "|assessment.result.correction-linked",
        ),
    )


class _AssessmentModuleEngine:
    """One shared assessment surface for Megado and creative protocols."""

    def __init__(self, store: Store, *, actor: Optional[AuthenticatedActor] = None) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be the supplied FND Store")
        try:
            self.__writer = store.domain_handler((contribution(),))
        except Exception:
            self.__writer = store
        self.reader = self.__writer.consumer()
        self.default_actor = actor
        self.limits = LimitService(store)
        self.operations = OperationManager(store)

    def register(self) -> DomainContribution:
        descriptor = contribution()
        self.__writer = self.__writer.register_domain_handler((descriptor,))
        self.reader = self.__writer.consumer()
        return descriptor

    # ---- scope and frozen input -------------------------------------------------

    def declare_scope(
        self,
        scope: Any,
        *,
        parent_obligation: Any,
        protocol: str,
        criteria: Sequence[Any] = (),
        review_required: bool = True,
        allow_no_review: bool = False,
        designated_approver: Optional[str] = None,
        authority: Optional[str] = None,
        policy: Optional[Mapping[str, Any]] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> AssessmentScope:
        scope_ref = self._stable_local(scope, SCOPE_KIND)
        parent_ref = self._current_ref(_ref(parent_obligation, "parent_obligation"), "parent_obligation")
        protocol = _opaque(protocol, "protocol")
        if not isinstance(criteria, (tuple, list)):
            raise AssessmentError("criteria must be a sequence of typed references or mappings")
        request_key = self._key(logical_request_key, "scope")
        selected_actor = self._actor(actor)
        criterion_specs = tuple(criteria)
        criterion_refs: list[ResourceRef] = []
        child_specs: list[tuple[ResourceRef, Mapping[str, Any]]] = []
        for index, value in enumerate(criterion_specs):
            if isinstance(value, ResourceRef) or hasattr(value, "ref"):
                criterion_refs.append(self._current_ref(_ref(value, "criterion"), "criterion"))
            elif isinstance(value, Mapping):
                criterion_id = _opaque(value.get("id", f"{request_key}-criterion-{index}"), "criterion id")
                criterion_ref = ResourceRef(self.__writer.authority, CRITERION_KIND, criterion_id, "rev-1")
                criterion_refs.append(criterion_ref)
                child_specs.append((criterion_ref, {"record_type": CRITERION_KIND, "id": criterion_id, "definition": _safe(dict(value)), "schema_revision": SCHEMA_REVISION}))
            else:
                raise AssessmentError("criteria must contain typed ResourceRef values or criterion mappings")
        payload = {
            "record_type": SCOPE_KIND,
            "schema_revision": SCHEMA_REVISION,
            "parent_obligation_ref": parent_ref,
            "protocol": protocol,
            "criterion_refs": tuple(criterion_refs),
            "review_required": bool(review_required),
            "allow_no_review": bool(allow_no_review),
            "designated_approver": designated_approver,
            "authority": authority,
            "policy": dict(policy or {}),
        }
        with self.__writer.transaction() as tx:
            envelope = self._envelope("assessment.scope.declare", scope_ref, payload, request_key, selected_actor, expected_version=0)
            prior = self.__writer.get_receipt(request_key)
            receipt = self.__writer.mutate(envelope, event_type="assessment.scope.declared", result_ref=ResourceRef(scope_ref.authority, scope_ref.kind, scope_ref.id, "rev-1"), before_refs=(parent_ref,), effects={"criterion_refs": tuple(criterion_refs), "protocol": protocol, "logical_parent": True}, stream=ASSESSMENT_STREAM, transaction=tx)
            if prior is None:
                for child_ref, child_payload in child_specs:
                    self.__writer.put_identity(child_ref, child_payload, version=1, transaction=tx)
                    self.__writer.put_reference(child_ref, transaction=tx)
        return self.get_scope(scope_ref)

    create_scope = declare_scope

    def freeze_input(
        self,
        scope: Any,
        *,
        packet: Mapping[str, Any],
        consumed_refs: Sequence[Any] = (),
        input_ref: Any = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> InputPacket:
        scope_record = self.get_scope(scope)
        if not isinstance(packet, Mapping):
            raise AssessmentError("packet must be a mapping")
        consumed = tuple(self._current_ref(_ref(value, "consumed input"), "consumed input") for value in consumed_refs)
        request_key = self._key(logical_request_key, "input")
        ref = self._stable_local(input_ref or request_key, INPUT_KIND)
        payload = {"record_type": INPUT_KIND, "schema_revision": SCHEMA_REVISION, "scope_ref": scope_record.ref, "consumed_refs": consumed, "packet": _safe(dict(packet)), "packet_digest": _digest(packet)}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.input.freeze", ref, payload, request_key, self._actor(actor), expected_version=0), event_type="assessment.input.frozen", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), before_refs=(scope_record.ref,), effects={"scope_ref": scope_record.ref, "consumed_refs": consumed}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_input(receipt.result_ref or ref)

    create_input_packet = freeze_input

    # ---- selection and assessment ------------------------------------------------

    def select_candidate(
        self,
        scope: Any,
        *,
        candidate: Any,
        criterion: Any,
        rationale: str,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> CandidateSelection:
        scope_record = self.get_scope(scope)
        candidate_ref = self._current_ref(_ref(candidate, "candidate"), "candidate")
        candidate_identity = self.__writer.get_identity(candidate_ref)
        if candidate_identity is None:  # pragma: no cover - guarded by _current_ref
            raise AssessmentNotFoundError("candidate identity is not admitted")
        self._validate_candidate(candidate_identity.payload)
        criterion_ref = self._current_ref(_ref(criterion, "criterion"), "criterion")
        self._require_criterion(scope_record, criterion_ref)
        request_key = self._key(logical_request_key, "selection")
        ref = self._stable_local(request_key, SELECTION_KIND)
        payload = {"record_type": SELECTION_KIND, "schema_revision": SCHEMA_REVISION, "scope_ref": scope_record.ref, "candidate_ref": candidate_ref, "criterion_ref": criterion_ref, "rationale": _opaque(rationale, "rationale"), "author": self._actor(actor).actor, "accepts": False}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.candidate.select", ref, payload, request_key, self._actor(actor), expected_version=0), event_type="assessment.candidate.selected", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), before_refs=(scope_record.ref, candidate_ref, criterion_ref), effects={"selection_only": True, "accepts": False}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_selection(receipt.result_ref or ref)

    choose_candidate = select_candidate

    def assess(
        self,
        scope: Any,
        *,
        candidate: Any,
        criterion: Any,
        input_packet: Any,
        verdict: Any,
        guidance: Optional[Mapping[str, Any]] = None,
        protocol_result: Optional[Mapping[str, Any]] = None,
        findings: Sequence[Mapping[str, Any]] = (),
        limit_pool: Any,
        declared_units: int = 1,
        actual_units: Optional[int] = None,
        route: str = "normal",
        role: str = "review",
        operation_payload: Optional[Mapping[str, Any]] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> AssessmentResult:
        scope_record = self.get_scope(scope)
        candidate_ref = self._current_ref(_ref(candidate, "candidate"), "candidate")
        candidate_identity = self.__writer.get_identity(candidate_ref)
        if candidate_identity is None:  # pragma: no cover - guarded by _current_ref
            raise AssessmentNotFoundError("candidate identity is not admitted")
        self._validate_candidate(candidate_identity.payload)
        criterion_ref = self._current_ref(_ref(criterion, "criterion"), "criterion")
        self._require_criterion(scope_record, criterion_ref)
        packet = self.get_input(input_packet)
        self._validate_input_packet(packet)
        selected_verdict = verdict if isinstance(verdict, Verdict) else Verdict(str(verdict).upper())
        route = _opaque(route, "route")
        role = _opaque(role, "role")
        request_key = self._key(logical_request_key, "assessment")
        result_ref = ResourceRef(self.__writer.authority, RESULT_KIND, request_key)
        parent_ref = scope_record.parent_obligation_ref
        pool_ref = self._stable_local(limit_pool, "limit") if isinstance(limit_pool, str) else _ref(limit_pool, "limit pool")
        pool_ref = ResourceRef(pool_ref.authority, pool_ref.kind, pool_ref.id)
        reservation_ref = ResourceRef(self.__writer.authority, "reservation", request_key + "-reservation")
        operation_key = request_key + "-invocation"
        invocation_ref = ResourceRef(self.__writer.authority, INVOCATION_KIND, request_key)
        body_for_digest = {"scope": scope_record.ref, "candidate": candidate_ref, "criterion": criterion_ref, "input": packet.ref, "verdict": selected_verdict.value, "guidance": dict(guidance or {}), "protocol_result": dict(protocol_result or {}), "findings": [_safe(item) for item in findings], "pool": pool_ref, "declared_units": declared_units, "actual_units": actual_units, "route": route, "role": role, "operation_payload": dict(operation_payload or {})}
        selected_actor = self._actor(actor)
        parent_payload = {"record_type": RESULT_KIND, "schema_revision": SCHEMA_REVISION, "scope_ref": scope_record.ref, "parent_obligation_ref": parent_ref, "criterion_ref": criterion_ref, "candidate_ref": candidate_ref, "input_packet_ref": packet.ref, "verdict": selected_verdict.value, "guidance": _safe(dict(guidance or {})), "protocol_result": _safe(dict(protocol_result or {})), "route": route, "role": role, "invocation_ref": invocation_ref, "reservation_ref": reservation_ref, "finding_refs": (), "correction_refs": (), "accepted": False}
        with self.__writer.transaction() as tx:
            envelope = self._envelope("assessment.run", result_ref, body_for_digest, request_key, selected_actor, expected_version=0)
            prior = self.__writer.get_receipt(request_key)
            if prior is not None:
                validate_replay(prior, envelope)
                return self.get_result(prior.result_ref or result_ref)
            reservation = self.limits.reserve(pool_ref, reservation_ref, declared_units, logical_request_key=request_key + "-reserve", actor=selected_actor, transaction=tx)
            request = OperationRequest("assessment.invocation", "assessment.invocation.v1", ResourceRef(self.__writer.authority, "assessment-adapter", route), selected_actor, operation_key, _digest({"operation": operation_key, "payload": body_for_digest}), {"assessment_ref": result_ref, "route": route, "role": role, **dict(operation_payload or {})}, invocation_ref, parent_ref)
            operation = self.operations.prepare(request, transaction=tx)
            state = OperationState.UNKNOWN if selected_verdict is Verdict.UNKNOWN else (OperationState.FAILED if selected_verdict is Verdict.REWORK and bool((protocol_result or {}).get("invocation_failed")) else OperationState.COMMITTED)
            if state is OperationState.UNKNOWN:
                operation = self.operations.record_outcome(operation, state, {"verdict": selected_verdict.value, "guidance": dict(guidance or {})}, transition_key=operation_key + "-unknown", transaction=tx)
            else:
                operation = self.operations.record_outcome(operation, state, {"verdict": selected_verdict.value, "protocol_result": dict(protocol_result or {})}, transition_key=operation_key + "-outcome", transaction=tx)
            charged = declared_units if actual_units is None else actual_units
            settled = self.limits.settle(reservation, charged, logical_request_key=request_key + "-settle", actor=selected_actor, transaction=tx)
            reservation_stable = ResourceRef(self.__writer.authority, "reservation", reservation_ref.id)
            invocation_payload = {"record_type": INVOCATION_KIND, "schema_revision": SCHEMA_REVISION, "operation_ref": operation.operation_ref, "reservation_ref": reservation_stable, "route": route, "role": role, "state": operation.state.value, "declared_units": declared_units, "actual_units": charged, "result": _safe(operation.result), "parent_obligation_ref": parent_ref}
            self.__writer.put_identity(invocation_ref, invocation_payload, version=1, transaction=tx)
            self.__writer.put_reference(invocation_ref, transaction=tx)
            if failure_injector is not None:
                failure_injector("after-invocation")
            finding_refs: list[ResourceRef] = []
            for index, spec in enumerate(findings):
                finding_refs.append(self._write_finding(tx, result_ref, parent_ref, index, spec, selected_verdict))
                if failure_injector is not None:
                    failure_injector("after-finding")
            parent_payload["invocation_ref"] = invocation_ref
            parent_payload["finding_refs"] = tuple(finding_refs)
            # Rebuild the envelope after composing children: CommandEnvelope
            # copies its payload, so a pre-child envelope would lose the
            # finding links even though the transaction remained atomic.
            envelope = self._envelope("assessment.run", result_ref, body_for_digest, request_key, selected_actor, expected_version=0)
            receipt = self.__writer.mutate(envelope, identity_payload=parent_payload, event_type="assessment.completed", result_ref=ResourceRef(self.__writer.authority, RESULT_KIND, result_ref.id, "rev-1"), before_refs=(scope_record.ref, parent_ref, candidate_ref, criterion_ref, packet.ref), effects={"logical_parent": True, "invocation_ref": invocation_ref, "reservation_ref": reservation_stable, "finding_refs": tuple(finding_refs), "verdict": selected_verdict.value, "protocol": scope_record.protocol}, stream=ASSESSMENT_STREAM, transaction=tx)
            if failure_injector is not None:
                failure_injector("after-parent")
        return self.get_result(receipt.result_ref or result_ref)

    run = assess
    assess_candidate = assess
    resume = assess

    # ---- corrections, findings, decisions --------------------------------------

    def create_correction(
        self,
        result: Any,
        *,
        instruction: str,
        finding_refs: Sequence[Any] = (),
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Correction:
        key = self._key(logical_request_key, "correction")
        selected_actor = self._actor(actor)
        request_payload = {
            "result": _safe(_logical_ref(result, "result")),
            "instruction": instruction,
            "finding_refs": tuple(_safe(_logical_ref(value, "finding")) for value in finding_refs),
        }
        prior = self.__writer.get_receipt(key)
        if prior is not None:
            replay_target = prior.target
            envelope = self._envelope(
                "assessment.correction.create", replay_target, request_payload, key,
                selected_actor, expected_version=0, expected_revision=replay_target.revision,
            )
            receipt = self.__writer.mutate(
                envelope, event_type="assessment.correction.created", result_ref=prior.result_ref,
                stream=ASSESSMENT_STREAM,
            )
            link_key = key + "-result"
            link_prior = self.__writer.get_receipt(link_key)
            if link_prior is not None:
                link_event = next((event for event in self.__writer.list_events(stream=ASSESSMENT_STREAM) if event.event_id in link_prior.event_ids), None)
                link_payload = {} if link_event is None else link_event.effects.get("request_payload", {})
                link_target = link_prior.target
                link_version = self._replay_version(link_target.revision, link_prior.result_ref)
                link_envelope = self._envelope(
                    "assessment.result.link-correction", link_target, link_payload, link_key,
                    selected_actor, expected_version=link_version, expected_revision=link_target.revision,
                )
                self.__writer.mutate(
                    link_envelope, event_type="assessment.result.correction-linked", result_ref=link_prior.result_ref,
                    stream=ASSESSMENT_STREAM,
                )
            correction_target = prior.result_ref or replay_target
            return self.get_correction(ResourceRef(correction_target.authority, correction_target.kind, correction_target.id))
        current = self.get_result(result)
        if current.verdict is not Verdict.REWORK:
            raise AssessmentStateError("only a REWORK result creates a correction")
        refs = tuple(_ref(value, "finding") for value in finding_refs) or tuple(finding.ref for finding in current.findings if not finding.resolved)
        for finding_ref in refs:
            finding = self.get_finding(finding_ref)
            if finding.result_ref.id != current.ref.id:
                raise AssessmentError("correction finding belongs to another result")
        correction_ref = ResourceRef(self.__writer.authority, CORRECTION_KIND, key)
        payload = {"record_type": CORRECTION_KIND, "schema_revision": SCHEMA_REVISION, "result_ref": current.ref, "parent_obligation_ref": current.parent_obligation_ref, "finding_refs": refs, "instruction": _opaque(instruction, "instruction"), "status": "open"}
        result_payload = dict(current.payload)
        result_payload["correction_refs"] = tuple(list(result_payload.get("correction_refs", ())) + [correction_ref])
        link_payload = {"result": _safe(_logical_ref(current, "result")), "correction": _safe(correction_ref)}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.correction.create", correction_ref, request_payload, key, selected_actor, expected_version=0), identity_payload=payload, event_type="assessment.correction.created", result_ref=ResourceRef(self.__writer.authority, CORRECTION_KIND, key, "rev-1"), before_refs=(current.ref, current.parent_obligation_ref), effects={"result_ref": current.ref, "finding_refs": refs, "parent_obligation_ref": current.parent_obligation_ref, "request_payload": request_payload}, stream=ASSESSMENT_STREAM, transaction=tx)
            self.__writer.mutate(self._envelope("assessment.result.link-correction", current.ref, link_payload, key + "-result", selected_actor, expected_version=current.version, expected_revision=current.ref.revision), identity_payload=result_payload, event_type="assessment.result.correction-linked", effects={"correction_ref": correction_ref, "parent_obligation_ref": current.parent_obligation_ref, "request_payload": link_payload}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_correction(receipt.result_ref or correction_ref)

    request_correction = create_correction

    def close_finding(
        self,
        finding: Any,
        *,
        evidence_refs: Sequence[Any] = (),
        test_only: bool = False,
        rationale: str = "",
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Finding:
        key = self._key(logical_request_key, "finding-close")
        selected_actor = self._actor(actor)
        request_payload = {
            "finding": _safe(_logical_ref(finding, "finding")),
            "evidence_refs": tuple(_safe(_logical_ref(value, "evidence")) for value in evidence_refs),
            "test_only": bool(test_only),
            "rationale": rationale,
        }
        prior = self.__writer.get_receipt(key)
        if prior is not None:
            replay_target = prior.target
            replay_version = None
            if replay_target.revision is not None and replay_target.revision.startswith("rev-"):
                try:
                    replay_version = int(replay_target.revision.removeprefix("rev-"))
                except ValueError:
                    replay_version = None
            if replay_version is None and prior.result_ref is not None and prior.result_ref.revision and prior.result_ref.revision.startswith("rev-"):
                try:
                    replay_version = max(0, int(prior.result_ref.revision.removeprefix("rev-")) - 1)
                except ValueError:
                    replay_version = None
            envelope = self._envelope(
                "assessment.finding.close", replay_target, request_payload, key, selected_actor,
                expected_version=replay_version, expected_revision=replay_target.revision,
            )
            receipt = self.__writer.mutate(
                envelope, event_type="assessment.finding.closed", result_ref=prior.result_ref,
                stream=ASSESSMENT_STREAM,
            )
            unpinned = ResourceRef(replay_target.authority, replay_target.kind, replay_target.id)
            return self.get_finding(unpinned)
        current = self.get_finding(finding)
        result = self.get_result(current.result_ref)
        if current.subjective and test_only:
            raise AssessmentAuthorityError("test-only evidence cannot clear a subjective finding")
        if result.verdict is Verdict.UNKNOWN and test_only:
            raise AssessmentAuthorityError("test-only evidence cannot clear an UNKNOWN result")
        refs = tuple(self._current_ref(_ref(value, "evidence"), "evidence") for value in evidence_refs)
        payload = dict(current.payload)
        payload.update({"status": "closed", "evidence_refs": refs, "closure_rationale": rationale, "closure_test_only": bool(test_only)})
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.finding.close", current.ref, request_payload, key, selected_actor, expected_version=current.version, expected_revision=current.ref.revision), identity_payload=payload, event_type="assessment.finding.closed", effects={"finding_ref": current.ref, "evidence_refs": refs, "test_only": bool(test_only)}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_finding(receipt.result_ref or current.ref)

    resolve_finding = close_finding

    def accept(
        self,
        result: Any,
        *,
        author: Optional[str] = None,
        authority: Optional[str] = None,
        rationale: str,
        disposition: Any = Disposition.ACCEPT,
        evidence_refs: Sequence[Any] = (),
        return_condition: Optional[str] = None,
        candidate: Any = None,
        criterion: Any = None,
        review_evidence: Sequence[Any] = (),
        test_only: bool = False,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Decision:
        current = self.get_result(result)
        scope = self.get_scope(current.scope_ref)
        if candidate is not None and self._current_ref(_ref(candidate, "candidate"), "candidate") != current.candidate_ref:
            raise StaleAssessmentError("approval candidate is not the exact consumed candidate revision")
        if criterion is not None and self._current_ref(_ref(criterion, "criterion"), "criterion") != current.criterion_ref:
            raise StaleAssessmentError("approval criterion is not the exact consumed criterion revision")
        if current.verdict is not Verdict.PASS:
            raise AssessmentStateError("only PASS can be accepted; REWORK and UNKNOWN remain open")
        if any(not finding.resolved for finding in current.findings):
            raise AssessmentStateError("all objective and subjective findings must be closed before acceptance")
        selected_actor = self._actor(actor)
        approver = author or selected_actor.actor
        self._check_approver(scope, approver, authority or selected_actor.authority)
        review_refs = tuple(self._current_ref(_ref(value, "review evidence"), "review evidence") for value in review_evidence)
        if scope.review_required and current.payload.get("role") != "review" and not review_refs:
            raise AssessmentAuthorityError("required review evidence is missing")
        if test_only and current.findings:
            raise AssessmentAuthorityError("test-only evidence cannot clear subjective or unresolved findings")
        decision_value = disposition if isinstance(disposition, Disposition) else Disposition(str(disposition))
        key = self._key(logical_request_key, "accept")
        decision_ref = ResourceRef(self.__writer.authority, DECISION_KIND, key)
        evidence = tuple(self._current_ref(_ref(value, "evidence"), "evidence") for value in evidence_refs)
        payload = {"record_type": DECISION_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": current.parent_obligation_ref, "result_ref": current.ref, "candidate_ref": current.candidate_ref, "criterion_ref": current.criterion_ref, "author": approver, "authority": authority or selected_actor.authority, "rationale": _opaque(rationale, "rationale"), "disposition": decision_value.value, "evidence_refs": evidence, "review_evidence": review_refs, "return_condition": return_condition}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.accept", decision_ref, payload, key, selected_actor, expected_version=0), event_type="assessment.accepted", before_refs=(current.ref, current.parent_obligation_ref, current.candidate_ref, current.criterion_ref), effects={"accepted": decision_value in (Disposition.ACCEPT, Disposition.ACCEPT_WITH_RISK), "candidate_ref": current.candidate_ref, "criterion_ref": current.criterion_ref, "authority": authority or selected_actor.authority}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_decision(receipt.result_ref or decision_ref)

    approve = accept

    def accept_without_review(
        self,
        scope: Any,
        *,
        candidate: Any,
        criterion: Any,
        rationale: str,
        evidence_refs: Sequence[Any] = (),
        author: Optional[str] = None,
        authority: Optional[str] = None,
        return_condition: Optional[str] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Decision:
        scope_record = self.get_scope(scope)
        if scope_record.review_required or not scope_record.allow_no_review:
            raise AssessmentAuthorityError("policy requires a review; no-review evidence is not admissible")
        candidate_ref = self._current_ref(_ref(candidate, "candidate"), "candidate")
        criterion_ref = self._current_ref(_ref(criterion, "criterion"), "criterion")
        self._require_criterion(scope_record, criterion_ref)
        selected_actor = self._actor(actor)
        approver = author or selected_actor.actor
        self._check_approver(scope_record, approver, authority or selected_actor.authority)
        key = self._key(logical_request_key, "no-review-accept")
        decision_ref = ResourceRef(self.__writer.authority, DECISION_KIND, key)
        evidence = tuple(self._current_ref(_ref(value, "evidence"), "evidence") for value in evidence_refs)
        payload = {"record_type": DECISION_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": scope_record.parent_obligation_ref, "result_ref": None, "candidate_ref": candidate_ref, "criterion_ref": criterion_ref, "author": approver, "authority": authority or selected_actor.authority, "rationale": _opaque(rationale, "rationale"), "disposition": Disposition.ACCEPT.value, "evidence_refs": evidence, "review_evidence": (), "return_condition": return_condition, "no_review": True}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.accept", decision_ref, payload, key, selected_actor, expected_version=0), event_type="assessment.accepted", before_refs=(scope_record.parent_obligation_ref, candidate_ref, criterion_ref), effects={"accepted": True, "no_review": True, "candidate_ref": candidate_ref, "criterion_ref": criterion_ref}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_decision(receipt.result_ref or decision_ref)

    def dispose_unknown(
        self,
        result: Any,
        *,
        disposition: Any,
        authority: str,
        rationale: str,
        return_condition: Optional[str] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Decision:
        current = self.get_result(result)
        if current.verdict is not Verdict.UNKNOWN:
            raise AssessmentStateError("only UNKNOWN results need an explicit disposition")
        scope = self.get_scope(current.scope_ref)
        selected_actor = self._actor(actor)
        self._check_approver(scope, selected_actor.actor, authority)
        value = disposition if isinstance(disposition, Disposition) else Disposition(str(disposition))
        key = self._key(logical_request_key, "unknown-disposition")
        decision_ref = ResourceRef(self.__writer.authority, DECISION_KIND, key)
        payload = {"record_type": DECISION_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": current.parent_obligation_ref, "result_ref": current.ref, "candidate_ref": current.candidate_ref, "criterion_ref": current.criterion_ref, "author": selected_actor.actor, "authority": authority, "rationale": _opaque(rationale, "rationale"), "disposition": value.value, "evidence_refs": (), "review_evidence": (), "return_condition": return_condition, "unknown_disposition": True}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.unknown.disposition", decision_ref, payload, key, selected_actor, expected_version=0), event_type="assessment.unknown.disposed", before_refs=(current.ref, current.parent_obligation_ref, current.candidate_ref, current.criterion_ref), effects={"unknown": True, "disposition": value.value, "authority": authority}, stream=ASSESSMENT_STREAM, transaction=tx)
        return self.get_decision(receipt.result_ref or decision_ref)

    resolve_unknown = dispose_unknown

    def record_loop_facts(
        self,
        parent_obligation: Any,
        *,
        attempt_count: int,
        unresolved_findings: int,
        exhausted_allowance: bool,
        required_approver: Optional[str] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> ResourceRef:
        if min(attempt_count, unresolved_findings) < 0:
            raise AssessmentError("loop facts counts must be non-negative")
        parent = self._current_ref(_ref(parent_obligation, "parent_obligation"), "parent_obligation")
        key = self._key(logical_request_key, "loop-facts")
        target = ResourceRef(self.__writer.authority, LOOP_FACTS_KIND, key)
        payload = {"record_type": LOOP_FACTS_KIND, "schema_revision": SCHEMA_REVISION, "parent_obligation_ref": parent, "attempt_count": attempt_count, "unresolved_findings": unresolved_findings, "exhausted_allowance": bool(exhausted_allowance), "required_approver": required_approver, "inference": None}
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(self._envelope("assessment.loop-facts.record", target, payload, key, self._actor(actor), expected_version=0), event_type="assessment.loop-facts.recorded", before_refs=(parent,), effects={"facts_only": True, "inference": None}, stream=ASSESSMENT_STREAM, transaction=tx)
        return receipt.result_ref or target

    # ---- typed reads -------------------------------------------------------------

    def get_scope(self, target: Any) -> AssessmentScope:
        identity = self._identity(target, SCOPE_KIND)
        payload = identity.payload
        return AssessmentScope(identity.ref, self._payload_ref(payload["parent_obligation_ref"]), payload["protocol"], tuple(self._payload_ref(value) for value in payload.get("criterion_refs", ())), bool(payload.get("review_required", True)), bool(payload.get("allow_no_review", False)), payload.get("designated_approver"), payload.get("authority"), dict(payload.get("policy", {})), identity.version, payload)

    def get_input(self, target: Any) -> InputPacket:
        identity = self._identity(target, INPUT_KIND)
        payload = identity.payload
        return InputPacket(identity.ref, self._payload_ref(payload["scope_ref"]), tuple(self._payload_ref(value) for value in payload.get("consumed_refs", ())), payload.get("packet", {}), identity.version, payload)

    def get_selection(self, target: Any) -> CandidateSelection:
        identity = self._identity(target, SELECTION_KIND)
        payload = identity.payload
        return CandidateSelection(identity.ref, self._payload_ref(payload["scope_ref"]), self._payload_ref(payload["candidate_ref"]), self._payload_ref(payload["criterion_ref"]), payload["rationale"], payload["author"], identity.version, payload)

    def get_invocation(self, target: Any) -> Invocation:
        identity = self._identity(target, INVOCATION_KIND)
        payload = identity.payload
        return Invocation(identity.ref, self._payload_ref(payload["operation_ref"]), self._payload_ref(payload["reservation_ref"]), payload["route"], payload["role"], payload["state"], int(payload["declared_units"]), int(payload["actual_units"]), payload.get("result", {}), identity.version, payload)

    def get_finding(self, target: Any) -> Finding:
        identity = self._identity(target, FINDING_KIND)
        payload = identity.payload
        return Finding(identity.ref, self._payload_ref(payload["result_ref"]), self._payload_ref(payload["parent_obligation_ref"]), payload["summary"], payload.get("severity", "normal"), bool(payload.get("subjective", False)), payload.get("status", "open"), self._payload_ref(payload.get("correction_ref")) if payload.get("correction_ref") else None, tuple(self._payload_ref(value) for value in payload.get("evidence_refs", ())), identity.version, payload)

    def get_result(self, target: Any) -> AssessmentResult:
        identity = self._identity(target, RESULT_KIND)
        payload = identity.payload
        invocation = self.get_invocation(payload["invocation_ref"])
        findings = tuple(self.get_finding(value) for value in payload.get("finding_refs", ()))
        return AssessmentResult(identity.ref, self._payload_ref(payload["scope_ref"]), self._payload_ref(payload["parent_obligation_ref"]), self._payload_ref(payload["criterion_ref"]), self._payload_ref(payload["candidate_ref"]), self._payload_ref(payload["input_packet_ref"]), Verdict(payload["verdict"]), payload.get("guidance", {}), payload.get("protocol_result", {}), invocation, findings, tuple(self._payload_ref(value) for value in payload.get("correction_refs", ())), identity.version, payload)

    def get_correction(self, target: Any) -> Correction:
        identity = self._identity(target, CORRECTION_KIND)
        payload = identity.payload
        return Correction(identity.ref, self._payload_ref(payload["result_ref"]), self._payload_ref(payload["parent_obligation_ref"]), tuple(self._payload_ref(value) for value in payload.get("finding_refs", ())), payload["instruction"], payload["status"], identity.version, payload)

    def get_decision(self, target: Any) -> Decision:
        identity = self._identity(target, DECISION_KIND)
        payload = identity.payload
        result_value = payload.get("result_ref")
        return Decision(identity.ref, self._payload_ref(payload["parent_obligation_ref"]), self._payload_ref(result_value) if result_value else None, self._payload_ref(payload["candidate_ref"]), self._payload_ref(payload["criterion_ref"]), payload["author"], payload["authority"], payload["rationale"], payload["disposition"], tuple(self._payload_ref(value) for value in payload.get("evidence_refs", ())), payload.get("return_condition"), identity.version, payload)

    def list_decisions(self, *, parent_obligation: Any = None) -> Tuple[Decision, ...]:
        parent_id = None if parent_obligation is None else self._current_ref(_ref(parent_obligation, "parent_obligation"), "parent_obligation").id
        rows = self.__writer.connection.execute("SELECT * FROM identities WHERE authority = ? AND kind = ? ORDER BY id", (self.__writer.authority, DECISION_KIND)).fetchall()
        decisions = tuple(self.get_decision(ResourceRef(row["authority"], row["kind"], row["id"])) for row in rows)
        if parent_id is not None:
            decisions = tuple(item for item in decisions if item.parent_obligation_ref.id == parent_id)
        return decisions

    # ---- internal FND helpers ----------------------------------------------------

    def _write_finding(self, tx: Any, result_ref: ResourceRef, parent_ref: ResourceRef, index: int, spec: Mapping[str, Any], verdict: Verdict) -> ResourceRef:
        if not isinstance(spec, Mapping):
            raise AssessmentError("finding specifications must be mappings")
        summary = _opaque(spec.get("summary", f"finding-{index}"), "finding summary")
        finding_id = result_ref.id + "-finding-" + str(index)
        # Findings are stable child identities.  Their current revision is
        # read through the unpinned identity ref so closing a finding does not
        # make the parent result's child link stale.
        finding_ref = ResourceRef(self.__writer.authority, FINDING_KIND, finding_id)
        payload = {"record_type": FINDING_KIND, "schema_revision": SCHEMA_REVISION, "result_ref": result_ref, "parent_obligation_ref": parent_ref, "summary": summary, "severity": _opaque(spec.get("severity", "normal"), "finding severity"), "subjective": bool(spec.get("subjective", False)), "status": "open", "correction_ref": None, "evidence_refs": (), "verdict": verdict.value}
        self.__writer.put_identity(finding_ref, payload, version=1, transaction=tx)
        self.__writer.put_reference(finding_ref, transaction=tx)
        return finding_ref

    def _envelope(self, operation: str, target: ResourceRef, payload: Mapping[str, Any], key: str, actor: AuthenticatedActor, *, expected_version: Optional[int] = None, expected_revision: Optional[str] = None, digest_payload: Optional[Mapping[str, Any]] = None) -> CommandEnvelope:
        envelope_payload = dict(payload)
        context = TransactionContext(
            actor,
            key,
            "0" * 64,
            expected_revision=expected_revision,
            expected_version=expected_version,
        )
        digest = canonical_request_digest(
            logical_request_key=key, operation=operation, schema_revision=SCHEMA_REVISION,
            target=target, actor=actor, payload=envelope_payload, context=context,
        )
        return CommandEnvelope(operation, SCHEMA_REVISION, target, TransactionContext(actor, key, digest, expected_revision=expected_revision, expected_version=expected_version), envelope_payload)

    def _actor(self, actor: Optional[AuthenticatedActor]) -> AuthenticatedActor:
        value = actor or self.default_actor or AuthenticatedActor("herzchen.assessment", "assessment-module", "herzchen.assessment")
        if not isinstance(value, AuthenticatedActor):
            raise TypeError("actor must be an AuthenticatedActor")
        return value

    @staticmethod
    def _replay_version(target_revision: Optional[str], result_ref: Optional[ResourceRef]) -> Optional[int]:
        revision = target_revision
        if revision is None and result_ref is not None:
            revision = result_ref.revision
            if revision is not None and revision.startswith("rev-"):
                try:
                    return max(0, int(revision.removeprefix("rev-")) - 1)
                except ValueError:
                    return None
        if revision is None or not revision.startswith("rev-"):
            return None
        try:
            return int(revision.removeprefix("rev-"))
        except ValueError:
            return None

    def _key(self, value: Optional[str], prefix: str) -> str:
        return _opaque(value or prefix + "-" + uuid.uuid4().hex, "logical_request_key")

    def _stable_local(self, value: Any, kind: str) -> ResourceRef:
        if isinstance(value, ResourceRef):
            if value.authority != self.__writer.authority or value.kind != kind or value.revision is not None:
                raise AssessmentError(f"{kind} target must be an unpinned local ResourceRef")
            return value
        if isinstance(value, str):
            return ResourceRef(self.__writer.authority, kind, _opaque(value, kind + " id"))
        raise AssessmentError(f"{kind} target must be an unpinned local ResourceRef")

    def _identity(self, target: Any, kind: str) -> Any:
        ref = _ref(target, kind)
        identity = self.__writer.get_identity(ref)
        if identity is None or identity.ref.kind != kind:
            raise AssessmentNotFoundError(f"{kind} not found: {target!r}")
        if ref.revision is not None and identity.ref.revision != ref.revision:
            raise StaleAssessmentError(f"{kind} reference is stale")
        return identity

    def _current_ref(self, ref: ResourceRef, field: str) -> ResourceRef:
        identity = self.__writer.get_identity(ref)
        if identity is None:
            raise AssessmentNotFoundError(f"{field} identity is not admitted")
        if ref.revision is not None and identity.ref.revision != ref.revision:
            raise StaleAssessmentError(f"{field} reference is stale")
        return identity.ref

    def _payload_ref(self, value: Any) -> ResourceRef:
        return value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)

    def _require_criterion(self, scope: AssessmentScope, criterion: ResourceRef) -> None:
        if scope.criterion_refs and criterion not in scope.criterion_refs:
            raise AssessmentError("criterion is not declared in the assessment scope")

    def _validate_input_packet(self, packet: InputPacket) -> None:
        for ref in packet.consumed_refs:
            self._current_ref(ref, "consumed input")

    def _validate_candidate(self, payload: Mapping[str, Any]) -> None:
        """Validate only inputs that the candidate declares as consumed.

        Annotation refs are intentionally not inspected here.  A protocol can
        add an annotation without invalidating a historical result; artifact,
        source, specification, and explicitly consumed input refs are the
        applicability boundary.
        """
        for field in ("artifact_ref", "source_ref", "spec_ref"):
            if field in payload and payload[field] is not None:
                self._current_ref(_ref(payload[field], field), field)
        for field in ("consumed_refs", "input_refs"):
            for value in payload.get(field, ()):
                self._current_ref(_ref(value, field), field)

    def _check_approver(self, scope: AssessmentScope, approver: str, authority: str) -> None:
        if scope.designated_approver is not None and approver != scope.designated_approver:
            raise AssessmentAuthorityError("actor is not the designated approver")
        if scope.authority is not None and authority != scope.authority:
            raise AssessmentAuthorityError("approval authority is not the designated authority")


AssessmentModule = command_facade(_AssessmentModuleEngine, DOMAIN_ID)
AssessmentStore = AssessmentModule
Assessment = AssessmentModule


__all__ = [
    "ASSESSMENT_STREAM", "Assessment", "AssessmentModule", "AssessmentStore", "CRITERION_KIND",
    "DOMAIN_ID", "DOMAIN_OWNER", "DOMAIN_VERSION", "SCHEMA_REVISION", "contribution",
]
