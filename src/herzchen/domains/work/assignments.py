"""Generic responsibility and execution assignments for the work domain.

The records in this module are deliberately small projections over the FND
identity/event/receipt writer.  A responsibility is not an owner column on a
project or task: it is one independently addressable assignment whose role,
principal, reporter and physical launcher can be inspected and reassigned.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import uuid
from typing import Any, Mapping, Optional, Sequence, Tuple
from herzchen.command_ports import command_facade

from herzchen.contracts import AuthenticatedActor, CommandEnvelope, DomainContribution, ResourceRef, TransactionContext, canonical_json

from .model import Lifecycle, WorkNotFoundError, WorkValidationError


ASSIGNMENT_SCHEMA_REVISION = "work.assignment.v1"
DOMAIN_ID = "herzchen.work.assignments"
# Keep auxiliary identities outside WorkGraph's ``work.*`` structural scan;
# they are shared work-domain records but are not WorkKind graph vertices.
RESPONSIBILITY_KIND = "wrk.responsibility"
ASSIGNMENT_KIND = "wrk.assignment"
RESULT_KIND = "wrk.result"
REPORT_KIND = "wrk.report"
DISPATCH_KIND = "wrk.dispatch"


def contribution() -> DomainContribution:
    ports = (
        ("work.assignment.create", ASSIGNMENT_KIND, "work.assignment.created"),
        ("work.assignment.reassign", ASSIGNMENT_KIND, "work.assignment.reassigned"),
        ("work.assignment.dispatch", DISPATCH_KIND, "work.assignment.dispatched"),
        ("work.result.append", RESULT_KIND, "work.result.appended"),
        ("work.report.append", REPORT_KIND, "work.report.appended"),
    )
    return DomainContribution(
        DOMAIN_ID, "1.0", "wrk",
        (RESPONSIBILITY_KIND, ASSIGNMENT_KIND, RESULT_KIND, REPORT_KIND, DISPATCH_KIND),
        (), ("work.assignments",), tuple(port[0] for port in ports),
        tuple(port[2] for port in ports), ASSIGNMENT_SCHEMA_REVISION,
        ("fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction", "handler-required")
        + tuple("mutation-port:{}|{}|{}|{}".format(ASSIGNMENT_SCHEMA_REVISION, *port) for port in ports),
    )


class AssignmentStatus(str, Enum):
    QUEUED = "queued"
    IN_FLIGHT = "in-flight"
    REASSIGNED = "reassigned"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StaleAssignmentError(WorkValidationError):
    """A writer tried to use an assignment generation that is no longer live."""


class AssignmentBusyError(WorkValidationError):
    """An actor already has an authoring reservation in the requested scope."""


@dataclass(frozen=True)
class ResponsibilityAssignment:
    ref: ResourceRef
    scope: Any
    role: str
    principal: Any
    reporter: Any
    launcher: Any
    agent: Any
    session: Any
    generation: int
    status: AssignmentStatus
    pins: Tuple[ResourceRef, ...]
    history: Tuple[Mapping[str, Any], ...]
    version: int
    payload: Mapping[str, Any]

    @property
    def id(self) -> str:
        return self.ref.id

    @property
    def revision(self) -> Optional[str]:
        return self.ref.revision

    @property
    def assignment_ref(self) -> ResourceRef:
        return self.ref


@dataclass(frozen=True)
class DispatchRecord:
    ref: ResourceRef
    assignment: ResourceRef
    generation: int
    pinned_inputs: Tuple[ResourceRef, ...]
    status: str
    action: Optional[str] = None


@dataclass(frozen=True)
class ObservationRecord:
    ref: ResourceRef
    assignment: ResourceRef
    kind: str
    generation: int
    value: Any
    version: int


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise WorkValidationError(f"{field} must be a non-blank opaque identifier")
    return value


def _json_safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


class _ResponsibilityAssignmentsEngine:
    """The shared generic responsibility/assignment command surface."""

    def __init__(self, store: Any, *, actor: Optional[AuthenticatedActor] = None) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        from .module import work_handler
        self.__writer = work_handler(store)
        self.reader = self.__writer.consumer()
        self.default_actor = actor

    def assign(
        self,
        scope: Any,
        *,
        role: str,
        principal: Any,
        reporter: Any = None,
        launcher: Any = None,
        agent: Any = None,
        session: Any = None,
        manager: Any = None,
        pins: Sequence[Any] = (),
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> ResponsibilityAssignment:
        role = _opaque(role, "role")
        request_key = self._request_key(logical_request_key)
        scope_ref = self._as_ref(scope)
        normalized_pins = tuple(self._pin_reference(value) for value in pins)
        assignment_id = "assignment-" + hashlib.sha256((self.__writer.authority + ":" + request_key).encode()).hexdigest()[:28]
        ref = ResourceRef(self.__writer.authority, ASSIGNMENT_KIND, assignment_id)
        responsibility_ref = ResourceRef(self.__writer.authority, RESPONSIBILITY_KIND, assignment_id)
        payload = {
            "record_type": "work.responsibility-assignment",
            "schema_revision": ASSIGNMENT_SCHEMA_REVISION,
            "scope": _json_safe(scope_ref),
            "role": role,
            "principal": _json_safe(principal),
            "reporter": _json_safe(reporter),
            "launcher": _json_safe(launcher),
            "agent": _json_safe(agent),
            "session": _json_safe(session),
            "manager": _json_safe(manager),
            "generation": 1,
            "status": AssignmentStatus.QUEUED.value,
            "pins": [_json_safe(pin) for pin in normalized_pins],
            "history": [{"generation": 1, "principal": _json_safe(principal), "agent": _json_safe(agent), "session": _json_safe(session), "reason": "initial"}],
            "responsibility_ref": _json_safe(responsibility_ref),
        }
        with self.__writer.transaction() as tx:
            envelope = self._envelope("work.assignment.create", ref, payload, request_key, actor, expected_version=0)
            prior = self.__writer.get_receipt(request_key)
            receipt = self.__writer.mutate(envelope, event_type="work.assignment.created", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), effects={"responsibility": responsibility_ref, "generation": 1}, stream="assignment:" + assignment_id, transaction=tx)
            if prior is None:
                self.__writer.put_identity(responsibility_ref, {"record_type": "work.responsibility", "assignment": ref, "role": role, "principal": _json_safe(principal)}, version=0, transaction=tx)
                self.__writer.put_reference(responsibility_ref, transaction=tx)
        return self.get(ref)

    create = assign
    assign_responsibility = assign

    def get(self, target: Any) -> ResponsibilityAssignment:
        ref = self._resolve_ref(target)
        identity = self.__writer.get_identity(ref) if ref is not None else None
        if identity is None or identity.ref.kind != ASSIGNMENT_KIND:
            raise WorkNotFoundError(f"assignment not found: {target!r}")
        return self._from_payload(identity.ref, identity.version, identity.payload)

    def _from_payload(self, ref: ResourceRef, version: int, payload: Mapping[str, Any]) -> ResponsibilityAssignment:
        payload = dict(payload)
        pins = tuple(self._as_ref(value) for value in payload.get("pins", ()))
        return ResponsibilityAssignment(
            ref,
            self._as_ref(payload.get("scope")),
            payload.get("role", "responsibility"),
            payload.get("principal"), payload.get("reporter"), payload.get("launcher"),
            payload.get("agent"), payload.get("session"), int(payload.get("generation", 1)),
            AssignmentStatus(payload.get("status", AssignmentStatus.QUEUED.value)), pins,
            tuple(payload.get("history", ())), version, payload,
        )

    resolve = get

    def reassign(
        self,
        target: Any,
        *,
        principal: Any = None,
        reporter: Any = None,
        launcher: Any = None,
        agent: Any = None,
        session: Any = None,
        reason: str = "reassigned",
        expected_generation: Optional[int] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> ResponsibilityAssignment:
        key = self._request_key(logical_request_key)
        request_payload = {
            "target": self._request_locator(target),
            "principal": _json_safe(principal),
            "reporter": _json_safe(reporter),
            "launcher": _json_safe(launcher),
            "agent": _json_safe(agent),
            "session": _json_safe(session),
            "reason": _opaque(reason, "reason"),
            "expected_generation": expected_generation,
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
            envelope = self._envelope(
                "work.assignment.reassign", replay_target, request_payload, key, actor,
                expected_version=replay_version, expected_revision=replay_target.revision,
            )
            receipt = self.__writer.mutate(
                envelope, event_type="work.assignment.reassigned", result_ref=prior.result_ref,
                stream="assignment:" + replay_target.id,
            )
            event = next((item for item in self.__writer.list_events(stream="assignment:" + replay_target.id) if item.event_id in prior.event_ids), None)
            if event is not None and isinstance(event.effects.get("result_payload"), Mapping):
                return self._from_payload(prior.result_ref or replay_target, self._revision_version(prior.result_ref.revision if prior.result_ref else replay_target.revision), event.effects["result_payload"])
            return self.get(ResourceRef(replay_target.authority, replay_target.kind, replay_target.id))
        current = self.get(target)
        self._fence(current, expected_generation)
        payload = dict(current.payload)
        next_generation = current.generation + 1
        payload.update({
            "principal": _json_safe(current.principal if principal is None else principal),
            "reporter": _json_safe(current.reporter if reporter is None else reporter),
            "launcher": _json_safe(current.launcher if launcher is None else launcher),
            "agent": _json_safe(current.agent if agent is None else agent),
            "session": _json_safe(current.session if session is None else session),
            "generation": next_generation,
            "status": AssignmentStatus.REASSIGNED.value,
        })
        history = list(current.history)
        history.append({"generation": next_generation, "principal": payload["principal"], "agent": payload["agent"], "session": payload["session"], "reason": _opaque(reason, "reason")})
        payload["history"] = history
        with self.__writer.transaction() as tx:
            envelope = self._envelope("work.assignment.reassign", current.ref, request_payload, key, actor, expected_version=current.version, expected_revision=current.revision)
            self.__writer.mutate(envelope, identity_payload=payload, event_type="work.assignment.reassigned", effects={"from_generation": current.generation, "to_generation": next_generation, "history_length": len(history), "result_payload": payload}, stream="assignment:" + current.id, transaction=tx)
        return self.get(current.ref)

    def fence(self, target: Any, generation: int) -> ResponsibilityAssignment:
        current = self.get(target)
        self._fence(current, generation)
        return current

    def append_result(
        self, target: Any, value: Any, *, expected_generation: Optional[int] = None,
        logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None,
    ) -> ObservationRecord:
        return self._append_observation(target, value, kind="result", expected_generation=expected_generation, logical_request_key=logical_request_key, actor=actor)

    record_result = append_result

    def append_report(
        self, target: Any, value: Any, *, expected_generation: Optional[int] = None,
        logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None,
    ) -> ObservationRecord:
        return self._append_observation(target, value, kind="report", expected_generation=expected_generation, logical_request_key=logical_request_key, actor=actor)

    report = append_report

    def dispatch(
        self, target: Any, *, input_refs: Sequence[Any] = (), action: Optional[str] = None,
        expected_generation: Optional[int] = None, logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> DispatchRecord:
        assignment = self.get(target)
        self._fence(assignment, expected_generation)
        action_value = None if action is None else _opaque(action, "action")
        pins = tuple(self._pin_reference(value) for value in (input_refs or assignment.pins))
        key = self._request_key(logical_request_key)
        dispatch_id = "dispatch-" + hashlib.sha256((assignment.id + ":" + key).encode()).hexdigest()[:28]
        ref = ResourceRef(self.__writer.authority, DISPATCH_KIND, dispatch_id)
        payload = {"record_type": "work.dispatch", "assignment": assignment.ref, "generation": assignment.generation, "inputs": pins, "action": action_value, "status": "dispatched"}
        with self.__writer.transaction() as tx:
            envelope = self._envelope("work.assignment.dispatch", ref, payload, key, actor, expected_version=0)
            self.__writer.mutate(envelope, event_type="work.assignment.dispatched", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), after_refs=pins + (assignment.ref,), effects={"assignment": assignment.ref, "generation": assignment.generation, "pinned_inputs": pins, "action": action_value}, stream="dispatch:" + assignment.id, transaction=tx)
        return DispatchRecord(ref, assignment.ref, assignment.generation, pins, "dispatched", action_value)

    def list_observations(self, target: Any, *, kind: Optional[str] = None) -> Tuple[ObservationRecord, ...]:
        assignment = self.get(target)
        rows = self.__writer.connection.execute("SELECT * FROM identities WHERE authority = ? AND kind IN (?, ?) ORDER BY id", (self.__writer.authority, RESULT_KIND, REPORT_KIND)).fetchall()
        result = []
        for row in rows:
            identity = self.__writer.get_identity(ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]))
            if identity is None or identity.payload.get("assignment") != assignment.ref.to_dict():
                continue
            if kind is not None and identity.payload.get("observation_kind") != kind:
                continue
            result.append(ObservationRecord(identity.ref, assignment.ref, identity.payload.get("observation_kind", "result"), int(identity.payload.get("generation", 0)), identity.payload.get("value"), identity.version))
        return tuple(result)

    def _append_observation(self, target: Any, value: Any, *, kind: str, expected_generation: Optional[int], logical_request_key: Optional[str], actor: Optional[AuthenticatedActor]) -> ObservationRecord:
        assignment = self.get(target)
        self._fence(assignment, expected_generation)
        key = self._request_key(logical_request_key)
        identity_kind = RESULT_KIND if kind == "result" else REPORT_KIND
        ident = identity_kind.split(".")[-1] + "-" + hashlib.sha256((assignment.id + ":" + key).encode()).hexdigest()[:28]
        ref = ResourceRef(self.__writer.authority, identity_kind, ident)
        payload = {"record_type": "work.observation", "observation_kind": kind, "assignment": assignment.ref, "generation": assignment.generation, "value": value}
        with self.__writer.transaction() as tx:
            envelope = self._envelope("work." + kind + ".append", ref, payload, key, actor, expected_version=0)
            self.__writer.mutate(envelope, event_type="work." + kind + ".appended", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), after_refs=(assignment.ref,), effects={"assignment": assignment.ref, "generation": assignment.generation, "append_only": True}, stream=kind + ":" + assignment.id, transaction=tx)
        identity = self.__writer.get_identity(ref)
        assert identity is not None
        return ObservationRecord(identity.ref, assignment.ref, kind, assignment.generation, value, identity.version)

    def _pin_reference(self, value: Any) -> ResourceRef:
        ref = self._as_ref(value)
        if ref.revision is not None:
            retained = self.__writer.get_reference(ref)
            current = self.__writer.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
            if retained is None and (current is None or current.ref.revision != ref.revision):
                raise WorkValidationError("pinned input revision is not retained")
            return ref
        current = self.__writer.get_identity(ref)
        if current is None:
            raise WorkNotFoundError(f"input reference not found: {ref!r}")
        return current.ref

    def _fence(self, assignment: ResponsibilityAssignment, expected_generation: Optional[int]) -> None:
        if expected_generation is not None and expected_generation != assignment.generation:
            raise StaleAssignmentError("assignment generation is stale")

    def _resolve_ref(self, target: Any) -> Optional[ResourceRef]:
        if isinstance(target, ResponsibilityAssignment):
            return target.ref
        if hasattr(target, "ref") and hasattr(target, "kind"):
            return ResourceRef(self.__writer.authority, ASSIGNMENT_KIND, target.ref.id)
        if isinstance(target, ResourceRef):
            return ResourceRef(target.authority, ASSIGNMENT_KIND, target.id, target.revision)
        if isinstance(target, Mapping):
            if target.get("ref") is not None:
                return self._resolve_ref(target["ref"])
            if target.get("id") is not None:
                return ResourceRef(self.__writer.authority, ASSIGNMENT_KIND, str(target["id"]))
        if isinstance(target, str):
            return ResourceRef(self.__writer.authority, ASSIGNMENT_KIND, target)
        return None

    def _as_ref(self, value: Any) -> ResourceRef:
        if isinstance(value, ResourceRef):
            return value
        if hasattr(value, "ref"):
            value = value.ref
            if isinstance(value, ResourceRef):
                return value
        if isinstance(value, Mapping):
            try:
                return ResourceRef.from_dict(value)
            except (TypeError, ValueError) as exc:
                raise WorkValidationError("reference is malformed") from exc
        if isinstance(value, str):
            return ResourceRef(self.__writer.authority, "work.external", _opaque(value, "reference"))
        raise WorkValidationError("reference is required")

    def _request_key(self, value: Optional[str]) -> str:
        return _opaque(value or "request-" + uuid.uuid4().hex, "logical_request_key")

    def _request_locator(self, value: Any) -> Any:
        if isinstance(value, ResourceRef):
            return value.to_dict()
        if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
            return value.ref.to_dict()
        return value

    @staticmethod
    def _revision_version(revision: Optional[str]) -> int:
        if revision is None or not revision.startswith("rev-"):
            return 0
        try:
            return int(revision.removeprefix("rev-"))
        except ValueError:
            return 0

    def _envelope(self, operation: str, target: ResourceRef, payload: Mapping[str, Any], key: str, actor: Optional[AuthenticatedActor], *, expected_version: Optional[int] = None, expected_revision: Optional[str] = None) -> CommandEnvelope:
        selected = actor or self.default_actor or AuthenticatedActor("herzchen.work", "work-assignment", "herzchen.work")
        if not isinstance(selected, AuthenticatedActor):
            raise TypeError("actor must be an FND AuthenticatedActor")
        return CommandEnvelope(operation, ASSIGNMENT_SCHEMA_REVISION, target, TransactionContext(selected, key, _digest({"operation": operation, "target": target, "payload": payload}), expected_revision=expected_revision, expected_version=expected_version), payload)


ResponsibilityAssignments = command_facade(_ResponsibilityAssignmentsEngine, DOMAIN_ID)
Assignments = ResponsibilityAssignments
AssignmentService = ResponsibilityAssignments
ResponsibilityService = ResponsibilityAssignments

__all__ = [
    "ASSIGNMENT_KIND", "ASSIGNMENT_SCHEMA_REVISION", "AssignmentBusyError", "AssignmentService", "AssignmentStatus",
    "Assignments", "DispatchRecord", "ObservationRecord", "REPORT_KIND", "ResponsibilityAssignment",
    "ResponsibilityAssignments", "ResponsibilityService", "StaleAssignmentError",
]
