"""Canonical project lifecycle transitions over the existing FND writer.

The service deliberately keeps no process-local project map.  Project state,
close requests, transition receipts and reconciliation intent live on the
canonical ``work.project`` identity and its ordinary work report records.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping, Optional, Sequence

from herzchen.command_ports import command_facade
from herzchen.contracts import AuthenticatedActor, DomainContribution, ResourceRef

from .assignments import ASSIGNMENT_KIND, ASSIGNMENT_SCHEMA_REVISION, REPORT_KIND
from .model import Lifecycle, WorkValidationError
from .module import SCHEMA_REVISION, _contract_types, _json, _digest, work_handler


LIFECYCLE_DOMAIN_ID = "herzchen.work.lifecycle"
LIFECYCLE_SCHEMA_REVISION = "work.project-lifecycle.v1"
LIFECYCLE_OPERATION = "work.lifecycle.transition"
LIFECYCLE_EVENT = "work.lifecycle.transitioned"
_ACTIONS = frozenset({"activate", "resume", "manager-close-request", "orchestrator-close", "reconcile"})


class ProjectLifecycleError(WorkValidationError):
    """A canonical project lifecycle request failed its owner fences."""


def contribution() -> DomainContribution:
    return DomainContribution(
        LIFECYCLE_DOMAIN_ID,
        "1.0",
        "wrk",
        (),
        (),
        ("work.lifecycle",),
        (LIFECYCLE_OPERATION,),
        (LIFECYCLE_EVENT,),
        LIFECYCLE_SCHEMA_REVISION,
        (
            "fnd-03.identities",
            "fnd-03.record_references",
            "fnd-03.transaction",
            "handler-required",
            "mutation-resource:work.project",
            "mutation-port:{}|{}|work.project|{}".format(
                LIFECYCLE_SCHEMA_REVISION, LIFECYCLE_OPERATION, LIFECYCLE_EVENT
            ),
        ),
    )


def _safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    return value


def _copy(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectLifecycleError(field + " must be an object")
    try:
        result = json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ProjectLifecycleError(field + " must contain JSON values") from exc
    if not isinstance(result, dict):
        raise ProjectLifecycleError(field + " must be an object")
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProjectLifecycleError(field + " must be non-blank text")
    return value.strip()


def _ref(value: Any, field: str, *, kind: Optional[str] = None) -> ResourceRef:
    try:
        result = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
    except (TypeError, ValueError, KeyError) as exc:
        raise ProjectLifecycleError(field + " must be a resource reference") from exc
    if kind is not None and result.kind != kind:
        raise ProjectLifecycleError(field + " has the wrong resource kind")
    return result


def _uuid(value: Any, field: str) -> str:
    text = _text(value, field)
    try:
        return str(uuid.UUID(text))
    except ValueError as exc:
        raise ProjectLifecycleError(field + " must be a UUID") from exc


def _json_ref(value: Any) -> dict[str, Any]:
    return _safe(value)


def _identity_dict(identity: Any) -> Optional[dict[str, Any]]:
    if identity is None:
        return None
    return {
        "ref": _safe(identity.ref),
        "version": identity.version,
        "payload": _safe(identity.payload),
    }


class _ProjectLifecycleEngine:
    """Owner-only implementation backed by the registered FND writer."""

    def __init__(self, store: Any, *, actor: Any = None) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        self.__writer = work_handler(store)
        self.reader = self.__writer.consumer()
        self.default_actor = actor

    def _actor(self, actor: Any) -> AuthenticatedActor:
        selected = actor or self.default_actor
        if not isinstance(selected, AuthenticatedActor):
            raise TypeError("actor must be an FND AuthenticatedActor")
        return selected

    def _current(self, project: Any) -> Any:
        ref = _ref(project, "project", kind="work.project")
        identity = self.__writer.get_identity(ref)
        if identity is None:
            raise ProjectLifecycleError("project is not readable")
        if ref.revision is not None and identity.ref.revision != ref.revision:
            raise ProjectLifecycleError("stale project revision")
        return identity

    def _current_unpinned(self, project: Any) -> Any:
        ref = _ref(project, "project", kind="work.project")
        identity = self.__writer.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
        if identity is None:
            raise ProjectLifecycleError("project is not readable")
        return identity

    def _assignment(self, value: Any, *, role: str, project: ResourceRef, actor: AuthenticatedActor, generation: int, task: Any = None) -> Any:
        ref = _ref(value, "assignment", kind=ASSIGNMENT_KIND)
        identity = self.__writer.get_identity(ref)
        if identity is None:
            raise ProjectLifecycleError("assignment is not readable")
        payload = identity.payload
        if payload.get("role") != role:
            raise ProjectLifecycleError("assignment role does not authorize this action")
        principal = payload.get("principal")
        principal_name = principal.get("actor") if isinstance(principal, Mapping) else principal
        if principal_name != actor.actor:
            raise ProjectLifecycleError("actor is not the assigned principal")
        if int(payload.get("generation", 0)) != generation:
            raise ProjectLifecycleError("assignment generation is stale")
        scope = payload.get("scope")
        scope_ref = _ref(scope, "assignment.scope")
        in_project = (scope_ref.authority, scope_ref.kind, scope_ref.id) == (project.authority, project.kind, project.id)
        if not in_project and task is not None:
            task_ref = _ref(task, "task", kind="work.task")
            if (scope_ref.authority, scope_ref.kind, scope_ref.id) == (task_ref.authority, task_ref.kind, task_ref.id):
                task_identity = self.__writer.get_identity(task_ref)
                task_project = None if task_identity is None else (task_identity.payload.get("project_ref") or task_identity.payload.get("parent"))
                in_project = isinstance(task_project, Mapping) and (task_project.get("authority"), task_project.get("kind"), task_project.get("id")) == (project.authority, project.kind, project.id)
        if not in_project:
            raise ProjectLifecycleError("assignment is outside project scope")
        if ref.revision is not None and identity.ref.revision != ref.revision:
            raise ProjectLifecycleError("assignment revision is stale")
        return identity

    def _evidence(self, value: Any, project: ResourceRef) -> dict[str, Any]:
        evidence = _copy(value, "evidence")
        if evidence.get("project_ref") != project.to_dict():
            raise ProjectLifecycleError("evidence is pinned to a different project revision")
        required = ("acceptance", "publication", "remote", "runtime")
        for name in required:
            if not isinstance(evidence.get(name), Mapping) or not evidence[name]:
                raise ProjectLifecycleError("terminal close requires acceptance, publication, remote and runtime evidence")
        return evidence

    def _packet(self, value: Any) -> dict[str, Any]:
        packet = _copy(value or {}, "effect_packet")
        for role, item in packet.items():
            if not isinstance(item, Mapping):
                raise ProjectLifecycleError("effect_packet entries must be objects")
            for key in ("effect_id", "readback_id", "ack_id"):
                if key in item:
                    _uuid(item[key], "effect_packet." + str(role) + "." + key)
        return packet

    def _settlement(self, value: Any, packet: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a host projection settlement without reopening lifecycle."""
        settlement = _copy(value, "settlement")
        if settlement.get("status") not in {"reconciled", "settled"}:
            raise ProjectLifecycleError("settlement.status must be reconciled or settled")
        request_id = _text(settlement.get("request_id"), "settlement.request_id")
        _uuid(settlement.get("effect_id"), "settlement.effect_id")
        config = settlement.get("config")
        readback = settlement.get("readback")
        acknowledgement = settlement.get("acknowledgment", settlement.get("ack"))
        if not isinstance(config, Mapping) or not config:
            raise ProjectLifecycleError("settlement.config is required")
        if not isinstance(readback, Mapping) or not readback:
            raise ProjectLifecycleError("settlement.readback is required")
        if not isinstance(acknowledgement, Mapping) or acknowledgement.get("outcome") not in {"reconciled", "settled"}:
            raise ProjectLifecycleError("settlement acknowledgment must be reconciled")
        if readback.get("request_id") not in {None, request_id}:
            raise ProjectLifecycleError("settlement readback request is stale")
        if "config" in readback and readback.get("config") != config:
            raise ProjectLifecycleError("settlement readback config does not match effect config")
        packet_ids = {
            item.get("effect_id")
            for item in packet.values()
            if isinstance(item, Mapping) and item.get("effect_id")
        }
        if packet_ids and settlement["effect_id"] not in packet_ids:
            raise ProjectLifecycleError("settlement effect is not in the effect packet")
        return {
            "status": settlement["status"],
            "effect_id": settlement["effect_id"],
            "request_id": request_id,
            "config": _safe(config),
            "readback": _safe(readback),
            "acknowledgment": _safe(acknowledgement),
        }

    def read(self, project: Any) -> Mapping[str, Any]:
        identity = self._current(project)
        payload = dict(identity.payload)
        control = payload.get("lifecycle_control", {})
        return {
            "outcome": "read",
            "project_ref": _json_ref(identity.ref),
            "revision": identity.ref.revision,
            "version": identity.version,
            "lifecycle": payload.get("lifecycle"),
            "close_request": _safe(control.get("close_request")) if isinstance(control, Mapping) else None,
            "transition": _safe(control.get("transition")) if isinstance(control, Mapping) else None,
            "reconciliation": _safe(control.get("reconciliation")) if isinstance(control, Mapping) else None,
            "manager_assignment": _safe(control.get("manager_assignment")) if isinstance(control, Mapping) else None,
            "orchestrator_assignment": _safe(control.get("orchestrator_assignment")) if isinstance(control, Mapping) else None,
        }

    def read_current(self, project: Any) -> Mapping[str, Any]:
        """Alias used by owner composition when exposing the finite read port."""
        return self.read(project)

    def transition(
        self,
        project: Any,
        *,
        action: str,
        logical_request_key: str,
        expected_project_revision: str,
        generation: int,
        manager_assignment: Any = None,
        task: Any = None,
        orchestrator_assignment: Any = None,
        evidence: Optional[Mapping[str, Any]] = None,
        effect_packet: Optional[Mapping[str, Any]] = None,
        settlement: Optional[Mapping[str, Any]] = None,
        actor: Any = None,
    ) -> Mapping[str, Any]:
        selected_actor = self._actor(actor)
        project_ref = _ref(project, "project", kind="work.project")
        action_value = _text(action, "action")
        if action_value not in _ACTIONS:
            raise ProjectLifecycleError("unsupported lifecycle action")
        key = _text(logical_request_key, "logical_request_key")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ProjectLifecycleError("generation must be a positive integer")
        if expected_project_revision != project_ref.revision:
            raise ProjectLifecycleError("expected project revision does not match project ref")
        prior = self.__writer.get_receipt(key)
        current = self._current_unpinned(project_ref) if prior is not None else self._current(project_ref)
        if prior is None and current.ref.revision != expected_project_revision:
            raise ProjectLifecycleError("stale project revision")
        manager = None
        orchestrator = None
        if action_value in {"activate", "resume", "manager-close-request"}:
            if manager_assignment is None:
                raise ProjectLifecycleError("manager assignment is required")
            manager = self._assignment(manager_assignment, role="manager", project=project_ref, actor=selected_actor, generation=generation, task=task)
        if action_value == "orchestrator-close":
            if orchestrator_assignment is None:
                raise ProjectLifecycleError("orchestrator assignment is required")
            orchestrator = self._assignment(orchestrator_assignment, role="orchestrator", project=project_ref, actor=selected_actor, generation=generation)
        if action_value == "reconcile":
            if manager_assignment is None and orchestrator_assignment is None:
                raise ProjectLifecycleError("reconciliation assignment is required")
            if manager_assignment is not None:
                manager = self._assignment(manager_assignment, role="manager", project=project_ref, actor=selected_actor, generation=generation)
            if orchestrator_assignment is not None:
                orchestrator = self._assignment(orchestrator_assignment, role="orchestrator", project=project_ref, actor=selected_actor, generation=generation)
        payload = {
            "project_ref": project_ref.to_dict(),
            "action": action_value,
            "expected_project_revision": expected_project_revision,
            "generation": generation,
            "manager_assignment": None if manager is None else manager.ref.to_dict(),
            "orchestrator_assignment": None if orchestrator is None else orchestrator.ref.to_dict(),
            "evidence": _safe(evidence) if evidence is not None else None,
            "effect_packet": self._packet(effect_packet),
            "settlement": _safe(settlement) if settlement is not None else None,
            "actor": selected_actor.to_dict(),
        }
        target = prior.target if prior is not None else current.ref
        target_version = 0 if target.revision is None else int(target.revision.removeprefix("rev-"))
        envelope = self._envelope(payload, key, selected_actor, target, target_version, target.revision)
        with self.__writer.transaction() as tx:
            if prior is not None:
                receipt = self.__writer.mutate(envelope, event_type=LIFECYCLE_EVENT, result_ref=prior.result_ref, stream="work:" + project_ref.id, transaction=tx)
                return self._result(current.ref, action_value, receipt, replayed=True)
            control = dict(current.payload.get("lifecycle_control", {}))
            if action_value == "manager-close-request":
                if current.payload.get("lifecycle") != Lifecycle.ACTIVE.value:
                    raise ProjectLifecycleError("manager close requires an active project")
                if control.get("close_request"):
                    raise ProjectLifecycleError("project already has an unresolved close request")
                report_ref = ResourceRef(self.__writer.authority, REPORT_KIND, "report-" + hashlib.sha256((project_ref.id + ":" + key).encode()).hexdigest()[:28])
                report_payload = {"record_type":"work.observation","observation_kind":"project-close-request","project":project_ref,"assignment":manager.ref,"generation":generation,"value":{"logical_request_key":key,"project_ref":project_ref,"project_revision":expected_project_revision}}
                report_receipt = self.__writer.mutate(self._envelope_generic("work.report.append", ASSIGNMENT_SCHEMA_REVISION, report_payload, key + ":report", selected_actor, report_ref, 0, None), identity_payload=report_payload, event_type="work.report.appended", result_ref=ResourceRef(report_ref.authority, report_ref.kind, report_ref.id, "rev-1"), after_refs=(project_ref, manager.ref), effects={"project":project_ref,"assignment":manager.ref,"transition":action_value}, stream="report:" + project_ref.id, transaction=tx)
                control["close_request"] = {"report_ref": report_ref.to_dict(), "request_id": key, "project_ref": project_ref.to_dict(), "project_revision": expected_project_revision, "manager_assignment": manager.ref.to_dict(), "generation": generation, "receipt": report_receipt.to_dict()}
            elif action_value == "orchestrator-close":
                if current.payload.get("lifecycle") != Lifecycle.ACTIVE.value or not control.get("close_request"):
                    raise ProjectLifecycleError("terminal close requires an active project with a manager close request")
                control["terminal_evidence"] = self._evidence(evidence, project_ref)
            elif action_value == "reconcile":
                if current.payload.get("lifecycle") != Lifecycle.COMPLETED.value:
                    raise ProjectLifecycleError("reconciliation requires a completed project")
                packet = self._packet(effect_packet)
                if not packet:
                    raise ProjectLifecycleError("reconciliation effect packet is required")
                control["reconciliation"] = {
                    "effect_packet": packet,
                    "status": "reconciled",
                    "settlement": self._settlement(settlement, packet),
                }
            next_payload = dict(current.payload)
            next_payload["lifecycle"] = current.payload.get("lifecycle") if action_value == "reconcile" else (Lifecycle.COMPLETED.value if action_value == "orchestrator-close" else Lifecycle.ACTIVE.value)
            if action_value != "reconcile":
                control.update({"transition":{"action":action_value,"request_id":key,"actor":selected_actor.to_dict(),"generation":generation,"project_ref":project_ref.to_dict(),"project_revision":expected_project_revision,"evidence":_safe(evidence) if evidence is not None else {}},"reconciliation":{"effect_packet":self._packet(effect_packet),"status":"pending"}})
            else:
                control["transition"] = {"action": action_value, "request_id": key, "actor": selected_actor.to_dict(), "generation": generation, "project_ref": project_ref.to_dict(), "project_revision": expected_project_revision, "evidence": {}}
            if manager is not None: control["manager_assignment"] = manager.ref.to_dict()
            if orchestrator is not None: control["orchestrator_assignment"] = orchestrator.ref.to_dict()
            next_payload["lifecycle_control"] = control
            receipt = self.__writer.mutate(envelope, identity_payload=next_payload, event_type=LIFECYCLE_EVENT, result_ref=ResourceRef(project_ref.authority, project_ref.kind, project_ref.id, "rev-" + str(current.version + 1)), before_refs=(current.ref,), after_refs=tuple(x for x in (manager.ref if manager else None, orchestrator.ref if orchestrator else None) if x is not None), effects={"project":project_ref,"action":action_value,"reconciliation":control["reconciliation"],"close_request":control.get("close_request")}, stream="work:" + project_ref.id, transaction=tx)
        return self._result(project_ref, action_value, receipt, replayed=False)

    def _envelope(self, payload: Mapping[str, Any], key: str, actor: AuthenticatedActor, target: ResourceRef, version: int, revision: Optional[str]) -> Any:
        return self._envelope_generic(LIFECYCLE_OPERATION, LIFECYCLE_SCHEMA_REVISION, payload, key, actor, target, version, revision)

    def _envelope_generic(self, operation: str, schema_revision: str, payload: Mapping[str, Any], key: str, actor: AuthenticatedActor, target: ResourceRef, version: int, revision: Optional[str]) -> Any:
        _, CommandEnvelope, _, _, TransactionContext, canonical_json = _contract_types()
        operation_payload = dict(payload)
        digest = hashlib.sha256(canonical_json({"operation":operation,"target":target,"payload":operation_payload,"expected_revision":revision,"expected_version":version}).encode("utf-8")).hexdigest()
        return CommandEnvelope(operation=operation, schema_revision=schema_revision, target=target, context=TransactionContext(actor=actor, logical_request_key=key, request_digest=digest, expected_revision=revision, expected_version=version), payload=operation_payload)

    def _result(self, project: Any, action: str, receipt: Any, *, replayed: bool) -> Mapping[str, Any]:
        current = self.__writer.get_identity(_ref(project, "project", kind="work.project"))
        return {"outcome":"replayed" if replayed else "transitioned","replayed":replayed,"action":action,"project_ref":_safe(None if current is None else current.ref),"record":_identity_dict(current),"receipt":receipt.to_dict(),"read":self.read(None if current is None else current.ref)}


ProjectLifecycle = command_facade(_ProjectLifecycleEngine, LIFECYCLE_DOMAIN_ID)


__all__ = ["LIFECYCLE_DOMAIN_ID", "LIFECYCLE_EVENT", "LIFECYCLE_OPERATION", "LIFECYCLE_SCHEMA_REVISION", "ProjectLifecycle", "ProjectLifecycleError", "contribution"]
