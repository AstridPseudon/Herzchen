"""Candidate-bound decisions and actionable waiting for the work domain.

This module is deliberately a small projection over the accepted FND Store,
WRK-04 assessment records, and FND-05 event/cursor/interval ports.  It owns no
database tables, allowance ledger, scheduler, or review vocabulary.  A
candidate pin is immutable evidence; a decision and a wait are observations
which never accept or dispatch their parent obligation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import uuid
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    EventCursor,
    ResourceRef,
    TransactionContext,
    canonical_json,
    validate_replay,
)
from herzchen.kernel import (
    EventCursorReader,
    EventFilter,
    EventPage,
    INTERVAL_KIND,
    IntervalController,
    IntervalDecision,
    Store,
    TargetMismatchError,
)


DOMAIN_ID = "herzchen.work.decisions"
DOMAIN_VERSION = "1.0"
DOMAIN_OWNER = "wrk"
SCHEMA_REVISION = "work.decisions.v1"
CANDIDATE_KIND = "wrk.candidate"
CANDIDATE_ANNOTATION_KIND = "wrk.candidate.annotation"
DECISION_KIND = "wrk.decision"
WAIT_KIND = "wrk.wait"
MANAGER_CHOICE_KIND = "wrk.manager-choice"
WAIT_STREAM_PREFIX = "attention:"


class DecisionError(ValueError):
    """Base error for candidate, decision, and waiting validation."""


class CandidateNotFoundError(DecisionError):
    pass


class DecisionNotFoundError(DecisionError):
    pass


class WaitingNotFoundError(DecisionError):
    pass


class StaleCandidateError(DecisionError):
    """A candidate pin no longer denotes the current candidate identity."""


class StaleCriterionError(DecisionError):
    """A required criterion pin no longer denotes the current criterion."""


class DecisionAuthorityError(DecisionError):
    pass


class WaitingError(DecisionError):
    pass


class ManagerChoiceError(DecisionError):
    pass


class Applicability(str, Enum):
    APPLICABLE = "applicable"
    STALE = "stale"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class CandidatePin:
    """The exact references consumed by one candidate."""

    artifact_ref: ResourceRef
    source_ref: ResourceRef
    spec_ref: ResourceRef
    criteria_refs: Tuple[ResourceRef, ...]
    consumed_refs: Tuple[ResourceRef, ...]

    @property
    def criterion_ref(self) -> Optional[ResourceRef]:
        return self.criteria_refs[0] if self.criteria_refs else None

    @property
    def all_refs(self) -> Tuple[ResourceRef, ...]:
        return (self.artifact_ref, self.source_ref, self.spec_ref) + self.criteria_refs + self.consumed_refs

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ref": self.artifact_ref.to_dict(),
            "source_ref": self.source_ref.to_dict(),
            "spec_ref": self.spec_ref.to_dict(),
            "criteria_refs": [ref.to_dict() for ref in self.criteria_refs],
            "consumed_refs": [ref.to_dict() for ref in self.consumed_refs],
        }


@dataclass(frozen=True)
class CandidateRecord:
    ref: ResourceRef
    parent_obligation_ref: ResourceRef
    pin: CandidatePin
    owner: str
    role: str
    provenance: Mapping[str, Any]
    annotations: Mapping[str, Any]
    version: int
    payload: Mapping[str, Any]
    receipt: Any = None

    @property
    def candidate_ref(self) -> ResourceRef:
        return self.ref

    @property
    def artifact_ref(self) -> ResourceRef:
        return self.pin.artifact_ref

    @property
    def source_ref(self) -> ResourceRef:
        return self.pin.source_ref

    @property
    def spec_ref(self) -> ResourceRef:
        return self.pin.spec_ref

    @property
    def criterion_ref(self) -> Optional[ResourceRef]:
        return self.pin.criterion_ref


@dataclass(frozen=True)
class ApplicabilityReport:
    candidate_ref: ResourceRef
    candidate_pin: CandidatePin
    status: Applicability
    affected_refs: Tuple[ResourceRef, ...]
    semantic_judgment: Any
    annotation_refs_ignored: Tuple[ResourceRef, ...] = ()

    @property
    def applicable(self) -> bool:
        return self.status is Applicability.APPLICABLE


@dataclass(frozen=True)
class DecisionRecord:
    ref: ResourceRef
    subject_ref: ResourceRef
    candidate_ref: ResourceRef
    candidate_pin: CandidatePin
    criterion_ref: Optional[ResourceRef]
    evidence_refs: Tuple[ResourceRef, ...]
    evidence_basis: Mapping[str, Any]
    author: str
    authority: str
    rationale: str
    disposition: str
    return_condition: Optional[str]
    applicability: Applicability
    assessment_result_ref: Optional[ResourceRef]
    completion_contract: Mapping[str, Any]
    required_decision_refs: Tuple[ResourceRef, ...]
    version: int
    payload: Mapping[str, Any]
    receipt: Any = None

    @property
    def subject(self) -> ResourceRef:
        return self.subject_ref

    @property
    def accepted(self) -> bool:
        return bool(self.payload.get("accepted", False))

    @property
    def obligation_closed(self) -> bool:
        return False


@dataclass(frozen=True)
class WaitingExplanation:
    ref: ResourceRef
    subject_ref: ResourceRef
    missing_obligation: str
    owner: str
    owner_ref: Optional[ResourceRef]
    awaited_ref: ResourceRef
    awaited_revision: Optional[str]
    current_revision: Optional[str]
    revisit_condition: str
    attention_event_id: Optional[str]
    attention_key: str
    required_decision_ref: Optional[ResourceRef]
    cap_reached: bool
    residual_risk: Any
    verification_choice: Any
    metadata: Mapping[str, Any]
    version: int
    payload: Mapping[str, Any]
    receipt: Any = None

    @property
    def revisit_signal(self) -> str:
        return self.revisit_condition

    @property
    def dispatch(self) -> bool:
        return False


@dataclass(frozen=True)
class AttentionReconciliation:
    page: EventPage
    cursor: Optional[str]
    duplicate: bool
    reordered: bool
    missed: bool
    business_dispatches: int = 0
    work_ready: bool = False

    @property
    def unhandled_preserved(self) -> bool:
        return not self.work_ready and self.business_dispatches == 0


@dataclass(frozen=True)
class NotificationObservation:
    cursor: EventCursor
    duplicate: bool
    reordered: bool
    missed: bool
    business_dispatches: int = 0
    work_ready: bool = False


@dataclass(frozen=True)
class ManagerChoice:
    ref: ResourceRef
    subject_ref: ResourceRef
    manager: str
    action: str
    available_actions: Tuple[str, ...]
    context: Mapping[str, Any]
    residual_risk: Any
    verification_choice: Any
    automatic_dispatch: bool
    version: int
    payload: Mapping[str, Any]
    receipt: Any = None


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise DecisionError(f"{field} must be a non-blank opaque identifier")
    return value


def _ref(value: Any, field: str) -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
        return value.ref
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except (TypeError, ValueError) as exc:
            raise DecisionError(f"{field} must be a typed ResourceRef") from exc
    raise DecisionError(f"{field} must be a typed ResourceRef")


def contribution() -> DomainContribution:
    ports = (
        ("work.candidate.create", CANDIDATE_KIND, "work.candidate.created"),
        ("work.candidate.annotate", CANDIDATE_ANNOTATION_KIND, "work.candidate.annotated"),
        ("work.decision.record", DECISION_KIND, "work.decision.recorded"),
        ("work.wait.record", WAIT_KIND, "work.wait.recorded"),
        ("work.manager-choice.record", MANAGER_CHOICE_KIND, "work.manager-choice.recorded"),
    )
    return DomainContribution(
        domain_id=DOMAIN_ID,
        version=DOMAIN_VERSION,
        owner=DOMAIN_OWNER,
        resource_types=(CANDIDATE_KIND, CANDIDATE_ANNOTATION_KIND, DECISION_KIND, WAIT_KIND, MANAGER_CHOICE_KIND),
        document_types=(),
        namespace_types=("work.decisions", "work.attention"),
        operation_types=(
            "work.candidate.create", "work.candidate.annotate", "work.decision.record",
            "work.wait.record", "work.manager-choice.record",
        ),
        event_types=(
            "work.candidate.created", "work.candidate.annotated", "work.decision.recorded",
            "work.wait.recorded", "work.manager-choice.recorded",
        ),
        schema_revision=SCHEMA_REVISION,
        composition_bindings=(
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "fnd-05.cursors", "fnd-05.intervals", "wrk-03.assignments", "wrk-04.assessment", "dat-04.documents",
            "handler-required",
        ) + tuple("mutation-port:{}|{}|{}|{}".format(SCHEMA_REVISION, *port) for port in ports),
    )


class DecisionsModule:
    """Typed candidate/decision/waiting operations over one FND Store."""

    def __init__(self, store: Store, *, assessment: Any = None, actor: Optional[AuthenticatedActor] = None) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        from .module import work_handler
        self.store = work_handler(store)
        self._kernel_store = getattr(self.store, "_owner", store)
        self.assessment = assessment
        self.default_actor = actor

    def register(self) -> DomainContribution:
        from .module import contribution as structural_contribution
        return structural_contribution()

    # ---- candidates -----------------------------------------------------------

    def create_candidate(
        self,
        candidate: Any = None,
        *,
        candidate_ref: Any = None,
        parent_obligation: Any,
        artifact: Any,
        source: Any,
        spec: Any,
        criteria: Sequence[Any] = (),
        consumed_inputs: Sequence[Any] = (),
        owner: str,
        role: str = "candidate",
        provenance: Optional[Mapping[str, Any]] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> CandidateRecord:
        key = self._key(logical_request_key, "candidate")
        supplied_candidate = candidate_ref if candidate_ref is not None else candidate
        if isinstance(supplied_candidate, str):
            candidate_id = supplied_candidate
        elif supplied_candidate is not None:
            candidate_id = _ref(supplied_candidate, "candidate_ref").id
        else:
            candidate_id = key
        target = self._new_target(candidate_id, CANDIDATE_KIND)
        parent_ref = self._current_ref(_ref(parent_obligation, "parent_obligation"), "parent_obligation")
        pin = CandidatePin(
            self._pin_reference(artifact, "artifact"),
            self._pin_reference(source, "source"),
            self._pin_reference(spec, "spec"),
            tuple(self._pin_reference(value, "criterion") for value in criteria),
            tuple(self._pin_reference(value, "consumed input") for value in consumed_inputs),
        )
        if not pin.criteria_refs:
            raise DecisionError("at least one exact criterion reference is required")
        owner = _opaque(owner, "owner")
        role = _opaque(role, "role")
        payload = {
            "record_type": CANDIDATE_KIND, "schema_revision": SCHEMA_REVISION,
            "candidate_id": target.id, "parent_obligation_ref": parent_ref,
            "pin": pin.to_dict(), "owner": owner, "role": role,
            "provenance": _safe(dict(provenance or {})), "annotations": {},
            "pin_digest": _digest(pin.to_dict()), "accepts_obligation": False,
        }
        with self.store.transaction() as tx:
            receipt = self.store.mutate(
                self._envelope("work.candidate.create", target, payload, key, actor, expected_version=0,
                               digest_payload={"candidate": target, "payload": payload}),
                event_type="work.candidate.created", result_ref=self._rev(target, 1),
                before_refs=(parent_ref,) + pin.all_refs,
                effects={"candidate_ref": self._rev(target, 1), "pin": pin.to_dict(), "accepts_obligation": False},
                stream="candidate:" + target.id, transaction=tx,
            )
            if failure_injector is not None:
                failure_injector("after-candidate")
        return self.get_candidate(receipt.result_ref or target)

    create = create_candidate
    describe_candidate = create_candidate

    def get_candidate(self, target: Any) -> CandidateRecord:
        identity = self._identity(target, CANDIDATE_KIND, CandidateNotFoundError)
        payload = identity.payload
        pin_payload = payload["pin"]
        pin = CandidatePin(
            _ref(pin_payload["artifact_ref"], "artifact_ref"), _ref(pin_payload["source_ref"], "source_ref"),
            _ref(pin_payload["spec_ref"], "spec_ref"),
            tuple(_ref(value, "criteria_refs") for value in pin_payload.get("criteria_refs", ())),
            tuple(_ref(value, "consumed_refs") for value in pin_payload.get("consumed_refs", ())),
        )
        return CandidateRecord(identity.ref, _ref(payload["parent_obligation_ref"], "parent_obligation_ref"), pin,
                               payload["owner"], payload.get("role", "candidate"), payload.get("provenance", {}),
                               payload.get("annotations", {}), identity.version, payload, self._receipt_for_target(identity.ref))

    describe = get_candidate
    read_candidate = get_candidate

    def annotate_candidate(
        self, candidate: Any, annotation: Mapping[str, Any], *, logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> ResourceRef:
        current = self.get_candidate(candidate)
        if not isinstance(annotation, Mapping):
            raise DecisionError("annotation must be a mapping")
        key = self._key(logical_request_key, "candidate-annotation")
        target = self._new_target(key, CANDIDATE_ANNOTATION_KIND)
        payload = {"record_type": CANDIDATE_ANNOTATION_KIND, "schema_revision": SCHEMA_REVISION,
                   "candidate_ref": current.ref, "annotation": _safe(dict(annotation))}
        with self.store.transaction() as tx:
            receipt = self.store.mutate(self._envelope("work.candidate.annotate", target, payload, key, actor, expected_version=0),
                                        event_type="work.candidate.annotated", result_ref=self._rev(target, 1),
                                        before_refs=(current.ref,), effects={"candidate_ref": current.ref, "annotation_only": True, "invalidates": ()},
                                        stream="candidate:" + current.ref.id, transaction=tx)
        return receipt.result_ref or target

    def check_applicability(
        self, candidate: Any, *, semantic_judgment: Any = None,
        annotation_refs: Sequence[Any] = (),
    ) -> ApplicabilityReport:
        current = self.get_candidate(candidate)
        affected: list[ResourceRef] = []
        for pinned in current.pin.all_refs:
            identity = self.store.get_identity(ResourceRef(pinned.authority, pinned.kind, pinned.id))
            if identity is None or identity.ref.revision != pinned.revision:
                affected.append(pinned)
        ignored = tuple(_ref(value, "annotation") for value in annotation_refs)
        return ApplicabilityReport(current.ref, current.pin,
                                   Applicability.STALE if affected else Applicability.APPLICABLE,
                                   tuple(affected), semantic_judgment, ignored)

    applicability = check_applicability

    # ---- decisions ------------------------------------------------------------

    def record_decision(
        self,
        subject: Any,
        *,
        candidate: Any,
        criterion: Any = None,
        evidence_refs: Sequence[Any] = (),
        evidence_basis: Optional[Mapping[str, Any]] = None,
        author: Optional[str] = None,
        authority: str,
        rationale: str,
        disposition: str,
        return_condition: Optional[str] = None,
        assessment_result: Any = None,
        required_approval: bool = False,
        required_authority: Optional[str] = None,
        required_approver: Optional[str] = None,
        semantic_judgment: Any = None,
        completion_contract: Optional[Mapping[str, Any]] = None,
        required_decision_refs: Sequence[Any] = (),
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> DecisionRecord:
        subject_ref = self._current_ref(_ref(subject, "subject"), "subject")
        candidate_record = self.get_candidate(candidate)
        candidate_ref = self._current_candidate_ref(candidate_record.ref, "candidate")
        criterion_ref = None if criterion is None else self._current_ref(_ref(criterion, "criterion"), "criterion")
        if criterion_ref is not None and criterion_ref not in candidate_record.pin.criteria_refs:
            raise DecisionError("criterion is not one of the candidate's exact criterion pins")
        if criterion_ref is None:
            criterion_ref = candidate_record.criterion_ref
        selected_actor = self._actor(actor)
        selected_author = _opaque(author or selected_actor.actor, "author")
        authority = _opaque(authority, "authority")
        if required_authority is not None and authority != _opaque(required_authority, "required_authority"):
            raise DecisionAuthorityError("decision authority is not the required authority")
        if required_approver is not None and selected_author != _opaque(required_approver, "required_approver"):
            raise DecisionAuthorityError("decision author is not the designated approver")
        result_ref = None
        if assessment_result is not None:
            if self.assessment is None:
                raise DecisionError("assessment_result requires the accepted WRK-04 assessment port")
            result = self.assessment.get_result(assessment_result)
            result_ref = result.ref
            if result.parent_obligation_ref != subject_ref:
                raise DecisionError("assessment result belongs to a different parent obligation")
            if result.candidate_ref != candidate_ref:
                raise StaleCandidateError("decision candidate is not the exact assessment candidate")
            if criterion_ref != result.criterion_ref:
                raise StaleCriterionError("decision criterion is not the exact assessment criterion")
            scope = self.assessment.get_scope(result.scope_ref)
            if required_approval or self._approval(disposition):
                if result.verdict.value != "PASS":
                    raise DecisionError("only a PASS assessment can support approval")
                if scope.designated_approver is not None and selected_author != scope.designated_approver:
                    raise DecisionAuthorityError("decision author is not the designated approver")
                if scope.authority is not None and authority != scope.authority:
                    raise DecisionAuthorityError("decision authority is not the designated authority")
        if required_approval and not self._approval(disposition):
            raise DecisionError("required approval needs an approval disposition")
        if not isinstance(evidence_basis or {}, Mapping):
            raise DecisionError("evidence_basis must be typed mapping data")
        evidence = tuple(self._pin_reference(value, "evidence") for value in evidence_refs)
        required_decisions = tuple(self._current_ref(_ref(value, "required_decision_ref"), "required_decision_ref") for value in required_decision_refs)
        if any(ref.kind != DECISION_KIND for ref in required_decisions):
            raise DecisionError("required_decision_refs must identify work decisions")
        if not isinstance(completion_contract or {}, Mapping):
            raise DecisionError("completion_contract must be typed mapping data")
        applicability = self.check_applicability(candidate_record, semantic_judgment=semantic_judgment).status
        if required_approval and applicability is not Applicability.APPLICABLE:
            raise DecisionError("approval cannot certify a candidate with stale consumed inputs")
        if required_approval and not return_condition:
            raise DecisionError("required approval must carry an explicit return condition")
        if required_approval and not evidence and not evidence_basis:
            raise DecisionError("required approval must carry an evidence basis")
        key = self._key(logical_request_key, "decision")
        target = self._new_target(key, DECISION_KIND)
        payload = {
            "record_type": DECISION_KIND, "schema_revision": SCHEMA_REVISION,
            "subject_ref": subject_ref, "candidate_ref": candidate_ref, "candidate_pin": candidate_record.pin.to_dict(),
            "criterion_ref": criterion_ref, "evidence_refs": evidence, "evidence_basis": _safe(dict(evidence_basis or {})),
            "author": selected_author, "authority": authority, "rationale": _opaque(rationale, "rationale"),
            "disposition": _opaque(disposition, "disposition"), "return_condition": return_condition,
            "applicability": applicability.value, "semantic_judgment": _safe(semantic_judgment),
            "assessment_result_ref": result_ref, "required_approval": bool(required_approval),
            "completion_contract": _safe(dict(completion_contract or {})), "required_decision_refs": required_decisions,
            "accepted": False, "accepts_obligation": False, "obligation_closed": False,
        }
        with self.store.transaction() as tx:
            receipt = self.store.mutate(self._envelope("work.decision.record", target, payload, key, selected_actor, expected_version=0,
                                                       digest_payload={"subject": subject_ref, "candidate": candidate_ref, "criterion": criterion_ref,
                                                                       "payload": payload}),
                                        event_type="work.decision.recorded", result_ref=self._rev(target, 1),
                                        before_refs=(subject_ref, candidate_ref) + ((criterion_ref,) if criterion_ref else ()) + evidence,
                                        effects={"candidate_ref": candidate_ref, "criterion_ref": criterion_ref, "applicability": applicability.value,
                                                 "accepted": False, "accepts_obligation": False}, stream="decision:" + subject_ref.id, transaction=tx)
            if failure_injector is not None:
                failure_injector("after-decision")
        return self.get_decision(receipt.result_ref or target)

    record = record_decision
    approve = record_decision

    def get_decision(self, target: Any) -> DecisionRecord:
        identity = self._identity(target, DECISION_KIND, DecisionNotFoundError)
        payload = identity.payload
        pin = self._pin_from_payload(payload["candidate_pin"])
        return DecisionRecord(identity.ref, _ref(payload["subject_ref"], "subject_ref"), _ref(payload["candidate_ref"], "candidate_ref"),
                              pin, _ref(payload["criterion_ref"], "criterion_ref") if payload.get("criterion_ref") else None,
                              tuple(_ref(value, "evidence_refs") for value in payload.get("evidence_refs", ())),
                              payload.get("evidence_basis", {}), payload["author"], payload["authority"], payload["rationale"],
                              payload["disposition"], payload.get("return_condition"), Applicability(payload.get("applicability", "applicable")),
                              _ref(payload["assessment_result_ref"], "assessment_result_ref") if payload.get("assessment_result_ref") else None,
                              payload.get("completion_contract", {}), tuple(_ref(value, "required_decision_refs") for value in payload.get("required_decision_refs", ())),
                              identity.version, payload, self._receipt_for_target(identity.ref))

    inspect_decision = get_decision
    read_decision = get_decision

    def list_decisions(self, *, subject: Any = None) -> Tuple[DecisionRecord, ...]:
        rows = self.store.connection.execute("SELECT authority, kind, id FROM identities WHERE authority = ? AND kind = ? ORDER BY id",
                                             (self.store.authority, DECISION_KIND)).fetchall()
        values = tuple(self.get_decision(ResourceRef(row["authority"], row["kind"], row["id"])) for row in rows)
        if subject is None:
            return values
        wanted = self._current_ref(_ref(subject, "subject"), "subject")
        return tuple(value for value in values if value.subject_ref == wanted)

    # ---- waiting and recovery -------------------------------------------------

    def record_wait(
        self,
        subject: Any,
        *,
        missing_obligation: str,
        owner: Any,
        awaited_ref: Any,
        revisit_condition: Optional[str] = None,
        required_decision_ref: Any = None,
        cap_reached: bool = False,
        residual_risk: Any = None,
        verification_choice: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
        equivalent_review_name: Optional[str] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> WaitingExplanation:
        if equivalent_review_name is not None:
            raise WaitingError("a cap must wait for the real decision, not an equivalent renamed review")
        subject_ref = self._current_ref(_ref(subject, "subject"), "subject")
        awaited = self._pin_reference(awaited_ref, "awaited_ref")
        awaited_identity = self.store.get_identity(ResourceRef(awaited.authority, awaited.kind, awaited.id))
        current_revision = awaited_identity.ref.revision if awaited_identity is not None else awaited.revision
        required = None if required_decision_ref is None else self._current_ref(_ref(required_decision_ref, "required_decision_ref"), "required_decision_ref")
        if cap_reached and required is None:
            raise WaitingError("cap_reached requires the real unresolved decision reference")
        missing = _opaque(missing_obligation, "missing_obligation")
        revisit = _opaque(revisit_condition or "revisit when the awaited reference or attention changes", "revisit_condition")
        owner_ref = None
        if isinstance(owner, (ResourceRef, Mapping)) or hasattr(owner, "ref"):
            owner_ref = self._current_ref(_ref(owner, "owner"), "owner")
            owner_text = owner_ref.to_json()
        else:
            owner_text = _opaque(owner, "owner")
        meta = dict(metadata or {})
        forbidden = {"allowance", "budget", "reservation", "dispatch", "launch", "next_action", "workflow_score"}
        if forbidden.intersection(meta):
            raise WaitingError("waiting metadata cannot grant allowance, reserve, dispatch, or choose work")
        key = self._key(logical_request_key, "wait")
        target = self._new_target(key, WAIT_KIND)
        attention_key = "attention-" + hashlib.sha256((subject_ref.to_json() + ":" + key).encode()).hexdigest()[:28]
        payload = {
            "record_type": WAIT_KIND, "schema_revision": SCHEMA_REVISION, "subject_ref": subject_ref,
            "missing_obligation": missing, "owner": owner_text, "owner_ref": owner_ref,
            "awaited_ref": awaited, "awaited_revision": awaited.revision, "current_revision": current_revision,
            "revisit_condition": revisit, "attention_key": attention_key, "required_decision_ref": required,
            "cap_reached": bool(cap_reached), "residual_risk": _safe(residual_risk),
            "verification_choice": _safe(verification_choice), "metadata": _safe(meta),
            "dispatch": False, "allowance": None, "reservation_ref": None, "launch": False,
        }
        with self.store.transaction() as tx:
            receipt = self.store.mutate(self._envelope("work.wait.record", target, payload, key, actor, expected_version=0),
                                        event_type="work.wait.recorded", result_ref=self._rev(target, 1),
                                        before_refs=(subject_ref, awaited) + ((required,) if required else ()),
                                        effects={"attention_key": attention_key, "attention_only": True, "dispatch": False,
                                                 "missing_obligation": missing, "awaited_ref": awaited, "current_revision": current_revision},
                                        stream=WAIT_STREAM_PREFIX + subject_ref.id, transaction=tx)
            if failure_injector is not None:
                failure_injector("after-wait")
        return self.get_wait(receipt.result_ref or target)

    wait = record_wait
    explain_readiness = record_wait

    def get_wait(self, target: Any) -> WaitingExplanation:
        identity = self._identity(target, WAIT_KIND, WaitingNotFoundError)
        payload = identity.payload
        receipt = self._receipt_for_target(identity.ref)
        event_id = receipt.event_ids[0] if receipt is not None and receipt.event_ids else None
        return WaitingExplanation(identity.ref, _ref(payload["subject_ref"], "subject_ref"), payload["missing_obligation"],
                                  payload["owner"], _ref(payload["owner_ref"], "owner_ref") if payload.get("owner_ref") else None,
                                  _ref(payload["awaited_ref"], "awaited_ref"), payload.get("awaited_revision"), payload.get("current_revision"),
                                  payload["revisit_condition"], event_id, payload["attention_key"],
                                  _ref(payload["required_decision_ref"], "required_decision_ref") if payload.get("required_decision_ref") else None,
                                  bool(payload.get("cap_reached", False)), payload.get("residual_risk"), payload.get("verification_choice"),
                                  payload.get("metadata", {}), identity.version, payload, receipt)

    inspect_wait = get_wait
    read_wait = get_wait

    def reconcile_notifications(
        self, stream: str, *, cursor: Optional[str] = None, event_filter: Optional[EventFilter] = None, limit: int = 100,
    ) -> AttentionReconciliation:
        page = EventCursorReader(self._kernel_store).catch_up(stream, cursor=cursor, event_filter=event_filter, limit=limit)
        return AttentionReconciliation(page, page.cursor, False, False, page.status == "gap")

    reconcile_attention = reconcile_notifications

    def observe_notification(self, cursor: EventCursor, event: Any) -> NotificationObservation:
        if not isinstance(cursor, EventCursor):
            raise TypeError("cursor must be an EventCursor")
        next_cursor = cursor.observe(event)
        return NotificationObservation(next_cursor, next_cursor.state.value == "duplicate", next_cursor.state.value == "reordered",
                                       next_cursor.state.value == "gap")

    def advance_timer(
        self, interval: Any, *, interval_seconds: int, now: Any = None, actor: Optional[AuthenticatedActor] = None,
    ) -> IntervalDecision:
        ref = _ref(interval, "interval")
        if ref.authority != self.store.authority or ref.kind != INTERVAL_KIND or ref.revision is not None:
            raise WaitingError("interval must be an unpinned attention-interval identity in this Store")
        controller = IntervalController(self._kernel_store, ref, interval_seconds, actor=actor or self.default_actor)
        return controller.poll(now=now)

    # ---- explicit manager action ---------------------------------------------

    def choose_next_action(
        self, subject: Any, *, action: str, available_actions: Sequence[str], context: Optional[Mapping[str, Any]] = None,
        manager: Optional[str] = None, residual_risk: Any = None, verification_choice: Any = None,
        logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None,
    ) -> ManagerChoice:
        subject_ref = self._current_ref(_ref(subject, "subject"), "subject")
        actions = tuple(_opaque(value, "available_action") for value in available_actions)
        action = _opaque(action, "action")
        if action not in actions:
            raise ManagerChoiceError("manager action must be one of the explicitly available actions")
        selected_actor = self._actor(actor)
        manager = _opaque(manager or selected_actor.actor, "manager")
        ctx = dict(context or {})
        key = self._key(logical_request_key, "manager-choice")
        target = self._new_target(key, MANAGER_CHOICE_KIND)
        payload = {"record_type": MANAGER_CHOICE_KIND, "schema_revision": SCHEMA_REVISION, "subject_ref": subject_ref,
                   "manager": manager, "action": action, "available_actions": actions, "context": _safe(ctx),
                   "residual_risk": _safe(residual_risk), "verification_choice": _safe(verification_choice),
                   "automatic_dispatch": False, "next_task": None, "workflow_score": None}
        with self.store.transaction() as tx:
            receipt = self.store.mutate(self._envelope("work.manager-choice.record", target, payload, key, selected_actor, expected_version=0),
                                        event_type="work.manager-choice.recorded", result_ref=self._rev(target, 1),
                                        before_refs=(subject_ref,), effects={"manager": manager, "action": action, "automatic_dispatch": False,
                                                                              "next_task": None}, stream="manager-choice:" + subject_ref.id, transaction=tx)
        return self.get_manager_choice(receipt.result_ref or target)

    record_manager_choice = choose_next_action

    def get_manager_choice(self, target: Any) -> ManagerChoice:
        identity = self._identity(target, MANAGER_CHOICE_KIND, ManagerChoiceError)
        payload = identity.payload
        return ManagerChoice(identity.ref, _ref(payload["subject_ref"], "subject_ref"), payload["manager"], payload["action"],
                              tuple(payload.get("available_actions", ())), payload.get("context", {}), payload.get("residual_risk"),
                              payload.get("verification_choice"), bool(payload.get("automatic_dispatch", False)), identity.version, payload,
                              self._receipt_for_target(identity.ref))

    inspect_manager_choice = get_manager_choice

    # ---- neutral helpers ------------------------------------------------------

    def _actor(self, actor: Optional[AuthenticatedActor]) -> AuthenticatedActor:
        selected = actor or self.default_actor or AuthenticatedActor("herzchen.work", "work-decisions", "herzchen.work")
        if not isinstance(selected, AuthenticatedActor):
            raise TypeError("actor must be an AuthenticatedActor")
        return selected

    def _key(self, value: Optional[str], prefix: str) -> str:
        return _opaque(value or prefix + "-" + uuid.uuid4().hex, "logical_request_key")

    def _new_target(self, ident: Any, kind: str) -> ResourceRef:
        return ResourceRef(self.store.authority, kind, _opaque(ident, kind + " id"))

    @staticmethod
    def _rev(ref: ResourceRef, version: int) -> ResourceRef:
        return ResourceRef(ref.authority, ref.kind, ref.id, "rev-" + str(version))

    def _current_ref(self, ref: ResourceRef, field: str) -> ResourceRef:
        if ref.authority != self.store.authority:
            raise TargetMismatchError(f"{field} authority does not belong to this Store")
        identity = self.store.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
        if identity is None:
            raise DecisionError(f"{field} identity is not admitted")
        if ref.revision is not None and ref.revision != identity.ref.revision:
            raise StaleCriterionError(f"{field} reference is stale") if field == "criterion" else StaleCandidateError(f"{field} reference is stale")
        return identity.ref

    def _pin_reference(self, value: Any, field: str) -> ResourceRef:
        ref = _ref(value, field)
        if ref.authority != self.store.authority:
            raise TargetMismatchError(f"{field} authority does not belong to this Store")
        identity = self.store.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
        if identity is None:
            raise DecisionError(f"{field} identity is not admitted")
        if ref.revision is not None:
            if self.store.get_reference(ref) is None and identity.ref.revision != ref.revision:
                raise DecisionError(f"{field} pinned revision is not retained")
            return ref
        return identity.ref

    def _current_candidate_ref(self, ref: ResourceRef, field: str) -> ResourceRef:
        current = self._current_ref(ref, field)
        if current.kind != CANDIDATE_KIND:
            raise DecisionError("candidate must be a work candidate identity")
        return current

    def _identity(self, target: Any, kind: str, error: type[Exception]) -> Any:
        ref = _ref(target, kind)
        identity = self.store.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
        if identity is None or identity.ref.kind != kind:
            raise error(f"{kind} not found: {target!r}")
        if ref.revision is not None and ref.revision != identity.ref.revision:
            raise StaleCandidateError(f"{kind} reference is stale")
        return identity

    def _pin_from_payload(self, payload: Mapping[str, Any]) -> CandidatePin:
        return CandidatePin(_ref(payload["artifact_ref"], "artifact_ref"), _ref(payload["source_ref"], "source_ref"),
                            _ref(payload["spec_ref"], "spec_ref"), tuple(_ref(value, "criteria_refs") for value in payload.get("criteria_refs", ())),
                            tuple(_ref(value, "consumed_refs") for value in payload.get("consumed_refs", ())))

    def _envelope(self, operation: str, target: ResourceRef, payload: Mapping[str, Any], key: str,
                  actor: Optional[AuthenticatedActor], *, expected_version: Optional[int] = None,
                  expected_revision: Optional[str] = None, digest_payload: Optional[Mapping[str, Any]] = None) -> CommandEnvelope:
        return CommandEnvelope(operation, SCHEMA_REVISION, target,
                               TransactionContext(self._actor(actor), key, _digest(digest_payload or payload),
                                                  expected_revision=expected_revision, expected_version=expected_version),
                               dict(payload))

    def _receipt_for_target(self, target: ResourceRef) -> Any:
        rows = self.store.connection.execute("SELECT logical_request_key FROM command_receipts WHERE target_authority = ? AND target_kind = ? AND target_id = ? ORDER BY rowid DESC LIMIT 1",
                                             (target.authority, target.kind, target.id)).fetchall()
        return None if not rows else self.store.get_receipt(rows[0]["logical_request_key"])

    @staticmethod
    def _approval(value: str) -> bool:
        return str(value).strip().lower() in {"approve", "approved", "accept", "accepted", "accept-with-risk"}


DecisionStore = DecisionsModule
DecisionModule = DecisionsModule
WorkDecisions = DecisionsModule


__all__ = [
    "Applicability", "ApplicabilityReport", "CandidateNotFoundError", "CandidatePin", "CandidateRecord",
    "DecisionAuthorityError", "DecisionError", "DecisionModule", "DecisionNotFoundError", "DecisionRecord",
    "DecisionStore", "DecisionsModule", "DOMAIN_ID", "DOMAIN_OWNER", "DOMAIN_VERSION", "MANAGER_CHOICE_KIND",
    "ManagerChoice", "ManagerChoiceError", "NotificationObservation", "SCHEMA_REVISION", "StaleCandidateError",
    "StaleCriterionError", "WAIT_KIND", "WaitingError", "WaitingExplanation", "WaitingNotFoundError", "WorkDecisions",
    "contribution",
]
