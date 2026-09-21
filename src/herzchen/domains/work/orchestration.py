"""Bounded owner-side orchestration placement over the WRK transaction.

This module adds one finite placement boundary.  It deliberately composes the
existing assignment and project-batch engines on the same owner transaction;
it does not expose a Store, SQL, a generic transaction API, a scheduler, or a
second relationship ledger to consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping, Optional, Sequence, Tuple

from herzchen.command_ports import command_facade
from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
    canonical_request_digest,
    validate_replay,
)

from .assignments import AssignmentStatus, ResponsibilityAssignment, _ResponsibilityAssignmentsEngine
from .batches import BatchResult, _ProjectBatchesEngine
from .model import Lifecycle, WorkNotFoundError, WorkValidationError
from .module import KIND_PREFIX, SCHEMA_REVISION, work_handler


ORCHESTRATION_SCHEMA_REVISION = "work.orchestration.v1"
ORCHESTRATION_DOMAIN_ID = "herzchen.work.orchestration"
DEFAULT_KIND = "wrk.orchestrator-default"
PORTFOLIO_KIND = "wrk.portfolio"
SUPERVISION_KEY = "otto_orchestrator"
PLACEMENT_EVENT = "work.project.supervised-created"
DEFAULT_CREATED_EVENT = "work.orchestrator-default.created"
DEFAULT_CHANGED_EVENT = "work.orchestrator-default.changed"
TRANSFER_EVENT = "work.project.supervision-transferred"
_RETIRED = frozenset({"retired", "stopped", "cancelled", "completed"})


def _safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise WorkValidationError(f"{field} must be a non-blank opaque identifier")
    return value


def _revision(value: Any, field: str) -> str:
    return _opaque(value, field)


def _revision_version(value: Optional[str]) -> int:
    if not isinstance(value, str) or not value.startswith("rev-"):
        return 0
    try:
        return int(value[4:])
    except ValueError:
        return 0


def _current_revision(record: Any) -> str:
    ref = getattr(record, "ref", None)
    revision = getattr(ref, "revision", None)
    return revision if isinstance(revision, str) and revision else "rev-" + str(getattr(record, "version", 0))


def _same_identity(left: Any, right: Any) -> bool:
    return (
        getattr(left, "authority", None), getattr(left, "kind", None), getattr(left, "id", None)
    ) == (
        getattr(right, "authority", None), getattr(right, "kind", None), getattr(right, "id", None)
    )


def _ref(value: Any, *, authority: str, kind: str, field: str, revision: Optional[str] = None) -> ResourceRef:
    if isinstance(value, ResourceRef):
        result = value
    elif isinstance(value, Mapping):
        try:
            result = ResourceRef.from_dict(value)
        except (TypeError, ValueError, KeyError) as exc:
            raise WorkValidationError(f"{field} is malformed") from exc
    else:
        raise WorkValidationError(f"{field} must be a typed reference")
    if result.authority != authority or result.kind != kind or not isinstance(result.id, str) or not result.id.strip():
        raise WorkValidationError(f"{field} has the wrong authority, kind, or id")
    if revision is not None and result.revision != revision:
        raise WorkValidationError(f"{field} revision is stale")
    return result


def _maybe_ref(value: Any, *, authority: str, kind: str, field: str) -> Optional[ResourceRef]:
    if value is None:
        return None
    return _ref(value, authority=authority, kind=kind, field=field)


def _assignment_status(assignment: ResponsibilityAssignment) -> str:
    status = assignment.status
    return str(getattr(status, "value", status)).strip().lower()


def contribution() -> DomainContribution:
    return DomainContribution(
        ORCHESTRATION_DOMAIN_ID,
        "1.0",
        "wrk",
        (DEFAULT_KIND,),
        (),
        ("work.orchestration",),
        (
            "work.create_pending_with_supervisor",
            "work.orchestrator-default.set",
            "work.project.supervision.transfer",
        ),
        (PLACEMENT_EVENT, DEFAULT_CREATED_EVENT, DEFAULT_CHANGED_EVENT, TRANSFER_EVENT),
        ORCHESTRATION_SCHEMA_REVISION,
        (
            "fnd-03.identities",
            "fnd-03.record_references",
            "fnd-03.transaction",
            "handler-required",
            "mutation-resource:" + DEFAULT_KIND,
            "mutation-resource:work.project",
            "mutation-port:{}|work.create_pending_with_supervisor|work.project|{}".format(ORCHESTRATION_SCHEMA_REVISION, PLACEMENT_EVENT),
            "mutation-port:{}|work.orchestrator-default.set|{}|{}".format(ORCHESTRATION_SCHEMA_REVISION, DEFAULT_KIND, DEFAULT_CREATED_EVENT),
            "mutation-port:{}|work.orchestrator-default.set|{}|{}".format(ORCHESTRATION_SCHEMA_REVISION, DEFAULT_KIND, DEFAULT_CHANGED_EVENT),
            "mutation-port:{}|work.project.supervision.transfer|work.project|{}".format(ORCHESTRATION_SCHEMA_REVISION, TRANSFER_EVENT),
        ),
    )


@dataclass(frozen=True)
class PlacementResult:
    project: Any
    receipt: Any
    default_ref: ResourceRef
    assignment: ResponsibilityAssignment
    relation: Mapping[str, Any]
    project_receipt: Any


class _OrchestrationEngine:
    """Finite owner engine; all writes use the existing WRK/FND writer."""

    def __init__(
        self,
        store: Any,
        *,
        actor: Optional[AuthenticatedActor] = None,
        portfolio_ref: Any,
        main_assignment_ref: Any = None,
        allowed_creator_ids: Sequence[str] = (),
        privileged_actor_ids: Sequence[str] = (),
        expected_main_principal: Optional[str] = None,
    ) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("owner actor must be an AuthenticatedActor")
        self._writer = work_handler(store)
        self.reader = self._writer.consumer()
        self.default_actor = actor
        self.portfolio_ref = _ref(portfolio_ref, authority=self._writer.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        self.main_assignment_ref = _maybe_ref(main_assignment_ref, authority=self._writer.authority, kind="wrk.assignment", field="main_assignment_ref")
        creators = tuple(_opaque(value, "allowed_creator_id") for value in allowed_creator_ids)
        privileged = tuple(_opaque(value, "privileged_actor_id") for value in privileged_actor_ids)
        self.allowed_creator_ids = tuple(dict.fromkeys((actor.actor,) + creators))
        self.privileged_actor_ids = tuple(dict.fromkeys((actor.actor,) + privileged))
        self.expected_main_principal = None if expected_main_principal is None else _opaque(expected_main_principal, "expected_main_principal")
        # These are owner-local engines, not consumer ports.  Their nested
        # transaction contexts become savepoints of this engine's transaction.
        self.assignments = _ResponsibilityAssignmentsEngine(store, actor=actor)
        self.batches = _ProjectBatchesEngine(store, actor=actor)

    @property
    def authority(self) -> str:
        return self._writer.authority

    def _actor(self, value: Any, *, privileged: bool = False) -> AuthenticatedActor:
        if not isinstance(value, AuthenticatedActor):
            raise WorkValidationError("actor must be an authenticated owner actor")
        if value.authority != self.authority or not value.authenticated:
            raise WorkValidationError("actor is not authenticated by this owner")
        allowed = self.privileged_actor_ids if privileged else self.allowed_creator_ids
        if value.actor not in allowed:
            raise WorkValidationError("actor is not authorized for this portfolio")
        return value

    def _default_ref(self) -> ResourceRef:
        ident = "default-" + hashlib.sha256(canonical_json(self.portfolio_ref.to_dict()).encode("utf-8")).hexdigest()[:28]
        return ResourceRef(self.authority, DEFAULT_KIND, ident)

    def _project_ref(self, request_key: str) -> ResourceRef:
        ident = "project-" + hashlib.sha256((self.authority + ":" + request_key).encode("utf-8")).hexdigest()[:28]
        return ResourceRef(self.authority, KIND_PREFIX[next(kind for kind in KIND_PREFIX if kind.value == "project")], ident)

    def _envelope(self, operation: str, target: ResourceRef, payload: Mapping[str, Any], request_key: str, actor: AuthenticatedActor, *, expected_version: Optional[int] = None, expected_revision: Optional[str] = None) -> CommandEnvelope:
        context = TransactionContext(actor, request_key, "0" * 64, expected_revision=expected_revision, expected_version=expected_version)
        digest = canonical_request_digest(
            logical_request_key=request_key,
            operation=operation,
            schema_revision=ORCHESTRATION_SCHEMA_REVISION,
            target=target,
            actor=actor,
            payload=payload,
            context=context,
        )
        return CommandEnvelope(
            operation,
            ORCHESTRATION_SCHEMA_REVISION,
            target,
            replace(context, request_digest=digest),
            dict(payload),
        )

    def _lookup_replay(self, envelope: CommandEnvelope) -> Any:
        """Use the existing WRK receipt read and kernel replay validator."""
        prior = self._writer.get_receipt(envelope.context.logical_request_key)
        if prior is not None:
            validate_replay(prior, envelope)
        return prior

    def _assignment(self, target: ResourceRef, *, expected_revision: Optional[str], expected_generation: Optional[int], field: str) -> ResponsibilityAssignment:
        assignment = self.assignments.get(target)
        if assignment.ref.authority != self.authority or assignment.ref.kind != "wrk.assignment" or assignment.ref.id != target.id:
            raise WorkValidationError(f"{field} identity is not owned by this portfolio")
        scope = assignment.scope
        if not _same_identity(scope, self.portfolio_ref):
            raise WorkValidationError(f"{field} is outside the exact portfolio scope")
        if assignment.role != "orchestrator":
            raise WorkValidationError(f"{field} is not an orchestrator assignment")
        if _assignment_status(assignment) in _RETIRED:
            raise WorkValidationError(f"{field} is retired")
        current_revision = _current_revision(assignment)
        if expected_revision is not None and expected_revision != current_revision:
            raise WorkValidationError(f"{field} revision is stale")
        if expected_generation is not None and int(expected_generation) != int(assignment.generation):
            raise WorkValidationError(f"{field} generation is stale")
        return assignment

    def _validate_caller_assignment(self, actor: AuthenticatedActor, ref: Any, revision: Any, generation: Any) -> None:
        if ref is None:
            if revision is not None or generation is not None:
                raise WorkValidationError("caller assignment pins require a caller assignment")
            return
        caller_ref = _ref(ref, authority=self.authority, kind="wrk.assignment", field="caller_assignment_ref")
        if revision is None or generation is None:
            raise WorkValidationError("caller assignment requires revision and generation pins")
        assignment = self._assignment(caller_ref, expected_revision=_revision(revision, "caller_assignment_revision"), expected_generation=int(generation), field="caller_assignment_ref")
        if assignment.principal != actor.actor:
            raise WorkValidationError("caller assignment principal does not authenticate this actor")

    def _relation(self, *, default_ref: ResourceRef, assignment: ResponsibilityAssignment, request_key: str) -> dict[str, Any]:
        return {
            "schema": "otto.orchestrator.supervision.v2",
            "portfolio_ref": self.portfolio_ref.to_dict(),
            "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id, _current_revision(assignment)).to_dict(),
            "assignment_revision": _current_revision(assignment),
            "generation": int(assignment.generation),
            "default_ref": ResourceRef(self.authority, DEFAULT_KIND, default_ref.id, _current_revision(self._writer.get_identity(default_ref))).to_dict(),
            "default_revision": _current_revision(self._writer.get_identity(default_ref)),
            "request_id": request_key,
        }

    def _pointer_payload(self, assignment: ResponsibilityAssignment, *, validate_main_binding: bool = False) -> dict[str, Any]:
        if validate_main_binding and self.expected_main_principal is not None and assignment.principal != self.expected_main_principal:
            raise WorkValidationError("supplied main assignment is not the trusted owner binding")
        return {
            "record_type": "work.orchestrator-default",
            "schema_revision": ORCHESTRATION_SCHEMA_REVISION,
            "portfolio_ref": self.portfolio_ref.to_dict(),
            "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id).to_dict(),
            "assignment_role": assignment.role,
            "assignment_revision": _current_revision(assignment),
            "generation": int(assignment.generation),
        }

    def _resolve_default(self, *, tx: Any, actor: AuthenticatedActor, supplied_ref: Optional[ResourceRef], supplied_revision: Optional[str], supplied_generation: Optional[int], expected_default_revision: Optional[str]) -> tuple[ResourceRef, ResponsibilityAssignment, str]:
        pointer_ref = self._default_ref()
        identity = self._writer.get_identity(pointer_ref)
        if identity is None:
            target = supplied_ref or self.main_assignment_ref
            if target is None:
                raise WorkValidationError("portfolio has no trusted main assignment seed")
            assignment = self._assignment(target, expected_revision=supplied_revision, expected_generation=supplied_generation, field="assignment_ref")
            if expected_default_revision not in (None, "initial"):
                raise WorkValidationError("default pointer is absent but expected_default_revision is not initial")
            self._writer.mutate(
                self._envelope("work.orchestrator-default.set", pointer_ref, self._pointer_payload(assignment, validate_main_binding=True), "default:" + pointer_ref.id, actor, expected_version=0),
                identity_payload=self._pointer_payload(assignment, validate_main_binding=True),
                event_type=DEFAULT_CREATED_EVENT,
                result_ref=ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, "rev-1"),
                after_refs=(assignment.ref,),
                effects={"portfolio_ref": self.portfolio_ref.to_dict(), "assignment_ref": assignment.ref.to_dict()},
                stream="orchestrator-default:" + pointer_ref.id,
                transaction=tx,
            )
            return pointer_ref, assignment, "rev-1"
        pointer_revision = _current_revision(identity)
        if expected_default_revision is not None and expected_default_revision != pointer_revision:
            raise WorkValidationError("default pointer revision is stale")
        payload = identity.payload
        stored_portfolio = _ref(payload.get("portfolio_ref"), authority=self.authority, kind=PORTFOLIO_KIND, field="stored portfolio_ref")
        stored_assignment = _ref(payload.get("assignment_ref"), authority=self.authority, kind="wrk.assignment", field="stored assignment_ref")
        if not _same_identity(stored_portfolio, self.portfolio_ref):
            raise WorkValidationError("default pointer portfolio scope is foreign")
        if supplied_ref is not None and not _same_identity(supplied_ref, stored_assignment):
            raise WorkValidationError("supplied assignment is not the current default")
        assignment = self._assignment(stored_assignment, expected_revision=supplied_revision, expected_generation=supplied_generation, field="default assignment")
        return pointer_ref, assignment, pointer_revision

    def create_pending_with_supervisor(
        self,
        *,
        actor: Any,
        request_id: str,
        portfolio_ref: Any,
        title: Optional[str] = None,
        outcome: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
        sheet: Optional[Mapping[str, Any]] = None,
        assignment_ref: Any = None,
        assignment_revision: Optional[str] = None,
        assignment_generation: Optional[int] = None,
        caller_assignment_ref: Any = None,
        caller_assignment_revision: Optional[str] = None,
        caller_assignment_generation: Optional[int] = None,
        expected_default_revision: Optional[str] = None,
        expected_project_version: int = 0,
    ) -> Mapping[str, Any]:
        actor_value = self._actor(actor)
        request_key = _opaque(request_id, "request_id")
        supplied_portfolio = _ref(portfolio_ref, authority=self.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        if not _same_identity(supplied_portfolio, self.portfolio_ref):
            raise WorkValidationError("portfolio_ref does not match the trusted owner binding")
        if not isinstance(expected_project_version, int) or isinstance(expected_project_version, bool) or expected_project_version != 0:
            raise WorkValidationError("new supervised project requires expected_project_version=0")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise WorkValidationError("metadata must be a mapping")
        if isinstance(metadata, Mapping) and SUPERVISION_KEY in metadata:
            raise WorkValidationError("reserved supervision metadata is owner-controlled")
        if sheet is not None and not isinstance(sheet, Mapping):
            raise WorkValidationError("sheet must be a mapping")
        caller_ref = None if caller_assignment_ref is None else _ref(caller_assignment_ref, authority=self.authority, kind="wrk.assignment", field="caller_assignment_ref")
        target_ref = None if assignment_ref is None else _ref(assignment_ref, authority=self.authority, kind="wrk.assignment", field="assignment_ref")
        payload = {
            "portfolio_ref": supplied_portfolio.to_dict(),
            "title": title,
            "outcome": outcome,
            "metadata": _safe(metadata or {}),
            "sheet": _safe(sheet),
            "assignment_ref": None if target_ref is None else target_ref.to_dict(),
            "assignment_revision": assignment_revision,
            "assignment_generation": assignment_generation,
            "caller_assignment_ref": None if caller_ref is None else caller_ref.to_dict(),
            "caller_assignment_revision": caller_assignment_revision,
            "caller_assignment_generation": caller_assignment_generation,
            "expected_default_revision": expected_default_revision,
            "expected_project_version": expected_project_version,
        }
        project_key = request_key + ":project"
        project_ref = self._project_ref(project_key)
        with self._writer.transaction() as tx:
            # The project identity is created by the composed batch operation
            # before this parent receipt is recorded.  The request payload
            # still pins the caller's expected project version at zero; the
            # envelope must not re-apply that pre-create CAS to the now
            # materialized identity.
            envelope = self._envelope("work.create_pending_with_supervisor", project_ref, payload, request_key, actor_value)
            prior = self._lookup_replay(envelope)
            if prior is not None:
                receipt = self._writer.mutate(envelope, event_type=PLACEMENT_EVENT, result_ref=prior.result_ref, stream="work:" + project_ref.id, transaction=tx)
                project = self.batches.graph.get(prior.result_ref or project_ref)
                relation = dict(project.payload.get("metadata", {}).get(SUPERVISION_KEY, {}))
                return {"outcome": "replayed", "project_ref": project.ref.to_dict(), "project": project.payload, "receipt": receipt.to_dict(), "supervision": relation, "replayed": True, "event_ids": list(receipt.event_ids), "executable": False}

            self._validate_caller_assignment(actor_value, caller_ref, caller_assignment_revision, caller_assignment_generation)
            pointer_ref, assignment, pointer_revision = self._resolve_default(
                tx=tx,
                actor=actor_value,
                supplied_ref=target_ref,
                supplied_revision=None if assignment_revision is None else _revision(assignment_revision, "assignment_revision"),
                supplied_generation=None if assignment_generation is None else int(assignment_generation),
                expected_default_revision=None if expected_default_revision is None else _revision(expected_default_revision, "expected_default_revision"),
            )
            relation = self._relation(default_ref=pointer_ref, assignment=assignment, request_key=request_key)
            batch = self.batches.create_pending_project(
                title=title,
                outcome=outcome,
                metadata=metadata,
                sheet=sheet,
                logical_request_key=project_key,
                actor=actor_value,
                creator=actor_value,
                curator=actor_value,
                _owner_supervision=relation,
            )
            receipt = self._writer.mutate(
                envelope,
                identity_payload=batch.project.payload,
                event_type=PLACEMENT_EVENT,
                result_ref=ResourceRef(self.authority, "work.project", batch.project.id, "rev-" + str(batch.project.version + 1)),
                after_refs=(pointer_ref, assignment.ref, batch.project.ref),
                effects={"portfolio_ref": self.portfolio_ref.to_dict(), "default_ref": pointer_ref.to_dict(), "assignment_ref": assignment.ref.to_dict(), "assignment_revision": _current_revision(assignment), "generation": int(assignment.generation), "project_ref": batch.project.ref.to_dict(), "project_receipt": batch.receipt.to_dict()},
                stream="work:" + batch.project.id,
                transaction=tx,
            )
            project = self.batches.graph.get(batch.project.ref)
            return {"outcome": "created", "project_ref": project.ref.to_dict(), "project": project.payload, "receipt": receipt.to_dict(), "project_receipt": batch.receipt.to_dict(), "default_ref": ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, pointer_revision).to_dict(), "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id, _current_revision(assignment)).to_dict(), "supervision": relation, "replayed": False, "event_ids": list(receipt.event_ids), "executable": False}

    def set_default(
        self,
        *,
        actor: Any,
        request_id: str,
        portfolio_ref: Any,
        target_assignment_ref: Any,
        target_assignment_revision: str,
        target_assignment_generation: int,
        expected_default_revision: str,
    ) -> Mapping[str, Any]:
        actor_value = self._actor(actor, privileged=True)
        request_key = _opaque(request_id, "request_id")
        portfolio = _ref(portfolio_ref, authority=self.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        if not _same_identity(portfolio, self.portfolio_ref):
            raise WorkValidationError("portfolio_ref does not match the trusted owner binding")
        target = _ref(target_assignment_ref, authority=self.authority, kind="wrk.assignment", field="target_assignment_ref")
        pointer_ref = self._default_ref()
        payload = {"portfolio_ref": portfolio.to_dict(), "target_assignment_ref": target.to_dict(), "target_assignment_revision": target_assignment_revision, "target_assignment_generation": target_assignment_generation, "expected_default_revision": expected_default_revision}
        with self._writer.transaction() as tx:
            envelope = self._envelope("work.orchestrator-default.set", pointer_ref, payload, request_key, actor_value, expected_version=_revision_version(expected_default_revision), expected_revision=expected_default_revision)
            prior = self._lookup_replay(envelope)
            if prior is not None:
                receipt = self._writer.mutate(envelope, event_type=DEFAULT_CHANGED_EVENT, result_ref=prior.result_ref, stream="orchestrator-default:" + pointer_ref.id, transaction=tx)
                return {"outcome": "replayed", "default_ref": pointer_ref.to_dict(), "receipt": receipt.to_dict(), "replayed": True, "event_ids": list(receipt.event_ids)}
            identity = self._writer.get_identity(pointer_ref)
            if identity is None or _current_revision(identity) != expected_default_revision:
                raise WorkValidationError("default pointer revision is stale or absent")
            assignment = self._assignment(target, expected_revision=_revision(target_assignment_revision, "target_assignment_revision"), expected_generation=int(target_assignment_generation), field="target_assignment_ref")
            new_payload = self._pointer_payload(assignment)
            receipt = self._writer.mutate(envelope, identity_payload=new_payload, event_type=DEFAULT_CHANGED_EVENT, result_ref=ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, "rev-" + str(identity.version + 1)), before_refs=(pointer_ref,), after_refs=(target,), effects={"from": identity.payload, "to": new_payload}, stream="orchestrator-default:" + pointer_ref.id, transaction=tx)
            return {"outcome": "changed", "default_ref": ResourceRef(self.authority, DEFAULT_KIND, pointer_ref.id, "rev-" + str(identity.version + 1)).to_dict(), "assignment_ref": ResourceRef(self.authority, "wrk.assignment", assignment.id, _current_revision(assignment)).to_dict(), "receipt": receipt.to_dict(), "replayed": False, "event_ids": list(receipt.event_ids)}

    def transfer_supervision(
        self,
        *,
        actor: Any,
        request_id: str,
        portfolio_ref: Any,
        project_ref: Any,
        expected_project_revision: str,
        expected_project_version: int,
        current_assignment_ref: Any,
        current_assignment_revision: str,
        current_assignment_generation: int,
        target_assignment_ref: Any,
        target_assignment_revision: str,
        target_assignment_generation: int,
        overlap_acknowledged: bool = False,
    ) -> Mapping[str, Any]:
        actor_value = self._actor(actor, privileged=True)
        if overlap_acknowledged is not True:
            raise WorkValidationError("explicit supervision transfer requires overlap acknowledgement")
        portfolio = _ref(portfolio_ref, authority=self.authority, kind=PORTFOLIO_KIND, field="portfolio_ref")
        project = _ref(project_ref, authority=self.authority, kind="work.project", field="project_ref")
        current_ref = _ref(current_assignment_ref, authority=self.authority, kind="wrk.assignment", field="current_assignment_ref")
        target_ref = _ref(target_assignment_ref, authority=self.authority, kind="wrk.assignment", field="target_assignment_ref")
        request_key = _opaque(request_id, "request_id")
        if not _same_identity(portfolio, self.portfolio_ref) or expected_project_version < 1:
            raise WorkValidationError("transfer scope or project version is invalid")
        payload = {"portfolio_ref": portfolio.to_dict(), "project_ref": project.to_dict(), "expected_project_revision": expected_project_revision, "expected_project_version": expected_project_version, "current_assignment_ref": current_ref.to_dict(), "current_assignment_revision": current_assignment_revision, "current_assignment_generation": current_assignment_generation, "target_assignment_ref": target_ref.to_dict(), "target_assignment_revision": target_assignment_revision, "target_assignment_generation": target_assignment_generation, "overlap_acknowledged": True}
        with self._writer.transaction() as tx:
            envelope = self._envelope("work.project.supervision.transfer", project, payload, request_key, actor_value, expected_version=expected_project_version, expected_revision=expected_project_revision)
            prior = self._lookup_replay(envelope)
            if prior is not None:
                receipt = self._writer.mutate(envelope, event_type=TRANSFER_EVENT, result_ref=prior.result_ref, stream="work:" + project.id, transaction=tx)
                record = self.batches.graph.get(project)
                return {"outcome": "replayed", "project_ref": record.ref.to_dict(), "project": record.payload, "receipt": receipt.to_dict(), "replayed": True, "event_ids": list(receipt.event_ids)}
            record = self.batches.graph.get(project)
            if _current_revision(record) != expected_project_revision or record.version != expected_project_version:
                raise WorkValidationError("project revision or version is stale")
            current = self._assignment(current_ref, expected_revision=_revision(current_assignment_revision, "current_assignment_revision"), expected_generation=int(current_assignment_generation), field="current_assignment_ref")
            target = self._assignment(target_ref, expected_revision=_revision(target_assignment_revision, "target_assignment_revision"), expected_generation=int(target_assignment_generation), field="target_assignment_ref")
            metadata = dict(record.payload.get("metadata", {}))
            existing = metadata.get(SUPERVISION_KEY)
            if not isinstance(existing, Mapping) or not _same_identity(ResourceRef.from_dict(existing["assignment_ref"]), current.ref):
                raise WorkValidationError("current supervision does not match the transfer fence")
            pointer_ref = self._default_ref()
            pointer = self._writer.get_identity(pointer_ref)
            if pointer is None:
                raise WorkValidationError("default pointer is absent")
            relation = self._relation(default_ref=pointer_ref, assignment=target, request_key=existing.get("request_id", request_key))
            updated = dict(record.payload)
            updated["metadata"] = dict(metadata, **{SUPERVISION_KEY: relation})
            receipt = self._writer.mutate(envelope, identity_payload=updated, event_type=TRANSFER_EVENT, result_ref=ResourceRef(self.authority, "work.project", project.id, "rev-" + str(record.version + 1)), before_refs=(record.ref, current.ref), after_refs=(target.ref,), effects={"from_assignment": current.ref.to_dict(), "to_assignment": target.ref.to_dict()}, stream="work:" + project.id, transaction=tx)
            return {"outcome": "transferred", "project_ref": ResourceRef(self.authority, "work.project", project.id, "rev-" + str(record.version + 1)).to_dict(), "project": updated, "supervision": relation, "receipt": receipt.to_dict(), "replayed": False, "event_ids": list(receipt.event_ids)}


Orchestration = command_facade(_OrchestrationEngine, ORCHESTRATION_DOMAIN_ID)


__all__ = [
    "DEFAULT_KIND",
    "ORCHESTRATION_DOMAIN_ID",
    "ORCHESTRATION_SCHEMA_REVISION",
    "Orchestration",
    "contribution",
]
