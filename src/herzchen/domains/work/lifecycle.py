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
from herzchen.contracts import AuthenticatedActor, DomainContribution, ResourceRef, canonical_json

from .assignments import ASSIGNMENT_KIND, ASSIGNMENT_SCHEMA_REVISION, REPORT_KIND, _ResponsibilityAssignmentsEngine
from .model import Lifecycle, WorkValidationError
from .module import SCHEMA_REVISION, _contract_types, _json, _digest, work_handler


LIFECYCLE_DOMAIN_ID = "herzchen.work.lifecycle"
LIFECYCLE_SCHEMA_REVISION = "work.project-lifecycle.v1"
LIFECYCLE_OPERATION = "work.lifecycle.transition"
LIFECYCLE_EVENT = "work.lifecycle.transitioned"
_ACTIONS = frozenset({"activate", "resume", "manager-close-request", "orchestrator-close", "reconcile"})
_PM_ACTIONS = frozenset({
    "pm-bind-existing",
    "pm-manager-close-request",
    "pm-orchestrator-close",
    "pm-reconcile-no-owned-schedule",
})


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

    def __init__(self, store: Any, *, actor: Any = None, delegation_issuer: Optional[AuthenticatedActor] = None) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        self.__writer = work_handler(store)
        self.reader = self.__writer.consumer()
        self.default_actor = actor
        self.delegation_issuer = delegation_issuer

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

    def _pm_owner(self, actor: AuthenticatedActor) -> None:
        issuer = self.delegation_issuer
        if not isinstance(issuer, AuthenticatedActor) or issuer.to_dict() != actor.to_dict():
            raise ProjectLifecycleError("PM lifecycle actions require the injected owner delegation")

    def _pm_ref(self, value: Any, field: str, *, kind: Optional[str] = None) -> ResourceRef:
        result = _ref(value, field, kind=kind)
        if result.authority != self.__writer.authority:
            raise ProjectLifecycleError(field + " must belong to the store authority")
        return result

    def _pm_tasks(self, values: Sequence[Any], project: ResourceRef) -> tuple[ResourceRef, ...]:
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
            raise ProjectLifecycleError("task_refs must be a non-empty sequence")
        result: list[ResourceRef] = []
        seen: set[tuple[str, str, str]] = set()
        for index, value in enumerate(values):
            ref = self._pm_ref(value, "task_refs[{}]".format(index), kind="work.task")
            identity = self.__writer.get_identity(ref)
            if identity is None or identity.ref.revision != ref.revision:
                raise ProjectLifecycleError("task reference is stale or not readable")
            locator = identity.payload.get("project_ref") or identity.payload.get("parent")
            if not isinstance(locator, Mapping) or (locator.get("authority"), locator.get("kind"), locator.get("id")) != (project.authority, project.kind, project.id):
                raise ProjectLifecycleError("task is outside the requested project")
            if identity.payload.get("lifecycle") != Lifecycle.COMPLETED.value:
                raise ProjectLifecycleError("all PM task references must be completed")
            if not isinstance(identity.payload.get("completion"), Mapping):
                raise ProjectLifecycleError("completed PM tasks require committed completion evidence")
            key = (ref.authority, ref.kind, ref.id)
            if key in seen:
                raise ProjectLifecycleError("duplicate task reference")
            seen.add(key)
            result.append(ref)
        return tuple(result)

    def _pm_assignment(self, value: Any, *, role: str, project: ResourceRef, generation: int) -> Any:
        ref = self._pm_ref(value, "assignment", kind=ASSIGNMENT_KIND)
        identity = self.__writer.get_identity(ref)
        if identity is None or identity.ref.revision != ref.revision:
            raise ProjectLifecycleError("assignment reference is stale or not readable")
        payload = identity.payload
        if payload.get("role") != role:
            raise ProjectLifecycleError("assignment role does not authorize this PM action")
        if int(payload.get("generation", 0)) != generation:
            raise ProjectLifecycleError("assignment generation is stale")
        scope = self._pm_ref(payload.get("scope"), "assignment.scope")
        if (scope.authority, scope.kind, scope.id) != (project.authority, project.kind, project.id):
            raise ProjectLifecycleError("assignment is outside project scope")
        return identity

    def _pm_attribution(
        self,
        *,
        project: ResourceRef,
        manager: Any,
        orchestrator: Any,
        generation: int,
        key: str,
        actor: AuthenticatedActor,
        draft: Optional[Mapping[str, Any]],
        action: str,
    ) -> dict[str, Any]:
        if action == "pm-bind-existing":
            value = _copy(draft or {}, "owner_attribution")
            issuer = value.get("issuer")
            root = value.get("orchestrator") if isinstance(value.get("orchestrator"), Mapping) else {}
            principal = root.get("principal") or value.get("orchestrator_principal")
            if not isinstance(principal, str) or not principal.strip():
                raise ProjectLifecycleError("owner_attribution.orchestrator.principal is required")
            manager_value = value.get("manager") if isinstance(value.get("manager"), Mapping) else {}
            value = {
                "schema": "work.owner-attribution.v1",
                "purpose": "existing-pm-closeout",
                "issuer": actor.to_dict() if issuer is None else _copy(issuer, "owner_attribution.issuer"),
                "project_ref": project.to_dict(),
                "manager": {
                    "assignment_ref": manager.ref.to_dict(),
                    "principal": manager_value.get("principal", manager.payload.get("principal")),
                    "generation": generation,
                },
                "orchestrator": {
                    "assignment_ref": orchestrator.ref.to_dict(),
                    "principal": principal,
                    "generation": generation,
                },
                "allowed_actions": sorted(_PM_ACTIONS),
                "issued_request_key": key,
            }
            if value["issuer"] != actor.to_dict():
                raise ProjectLifecycleError("owner attribution issuer does not match the authenticated owner")
            digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
            value["digest"] = digest
            return value
        current = self._current_unpinned(project)
        control = current.payload.get("lifecycle_control", {})
        value = control.get("owner_attribution") if isinstance(control, Mapping) else None
        if not isinstance(value, Mapping):
            raise ProjectLifecycleError("PM owner attribution is missing")
        value = _copy(value, "owner_attribution")
        if attribution_digest := value.get("digest"):
            without_digest = dict(value)
            without_digest.pop("digest", None)
            if hashlib.sha256(canonical_json(without_digest).encode("utf-8")).hexdigest() != attribution_digest:
                raise ProjectLifecycleError("owner attribution digest is invalid")
        else:
            raise ProjectLifecycleError("owner attribution digest is missing")
        if attribution_digest != getattr(self, "_pm_requested_digest", attribution_digest):
            raise ProjectLifecycleError("owner attribution digest does not match the request")
        bound_project = value.get("project_ref")
        if not isinstance(bound_project, Mapping) or (bound_project.get("authority"), bound_project.get("kind"), bound_project.get("id")) != (project.authority, project.kind, project.id) or value.get("issuer") != actor.to_dict():
            raise ProjectLifecycleError("owner attribution is not bound to this owner and project")
        manager_value = value.get("manager")
        if not isinstance(manager_value, Mapping) or manager_value.get("assignment_ref") != manager.ref.to_dict() or int(manager_value.get("generation", 0)) != generation:
            raise ProjectLifecycleError("owner attribution manager fence does not match")
        if manager_value.get("principal") != manager.payload.get("principal"):
            raise ProjectLifecycleError("owner attribution manager principal does not match")
        orchestrator_value = value.get("orchestrator")
        if orchestrator is not None and (not isinstance(orchestrator_value, Mapping) or orchestrator_value.get("assignment_ref") != orchestrator.ref.to_dict() or int(orchestrator_value.get("generation", 0)) != generation):
            raise ProjectLifecycleError("owner attribution orchestrator fence does not match")
        if orchestrator is not None and orchestrator_value.get("principal") != orchestrator.payload.get("principal"):
            raise ProjectLifecycleError("owner attribution orchestrator principal does not match")
        allowed = value.get("allowed_actions")
        if not isinstance(allowed, list) or action not in allowed:
            raise ProjectLifecycleError("owner attribution does not allow this action")
        return value

    def _pm_result(self, project: ResourceRef, action: str, receipt: Any, *, replayed: bool, assignment: Any = None, assignment_receipt: Any = None, attribution: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        current = self.__writer.get_identity(ResourceRef(project.authority, project.kind, project.id))
        result = {
            "outcome": "replayed" if replayed else "transitioned",
            "replayed": replayed,
            "action": action,
            "project_ref": _safe(None if current is None else current.ref),
            "record": _identity_dict(current),
            "receipt": receipt.to_dict(),
            "lifecycle_receipt": receipt.to_dict(),
            "read": self.read(None if current is None else current.ref),
        }
        if assignment is not None:
            result["orchestrator_assignment_ref"] = _safe(assignment.ref)
        if assignment_receipt is not None:
            result["assignment_receipt"] = assignment_receipt.to_dict()
        if attribution is not None:
            result["attribution_digest"] = attribution.get("digest")
        return result

    def _transition_pm(
        self,
        project_ref: ResourceRef,
        *,
        action: str,
        key: str,
        expected_project_revision: str,
        expected_project_version: Optional[int],
        generation: int,
        manager_assignment: Any,
        orchestrator_assignment: Any,
        orchestrator_principal: Optional[str],
        task_refs: Sequence[Any],
        attribution_digest: Optional[str],
        owner_attribution: Optional[Mapping[str, Any]],
        evidence: Optional[Mapping[str, Any]],
        schedule_observation: Optional[Mapping[str, Any]],
        actor: AuthenticatedActor,
    ) -> Mapping[str, Any]:
        self._pm_owner(actor)
        if expected_project_version is None or isinstance(expected_project_version, bool) or expected_project_version < 0:
            raise ProjectLifecycleError("expected_project_version is required for PM lifecycle actions")
        if expected_project_revision != project_ref.revision or expected_project_revision != "rev-" + str(expected_project_version):
            raise ProjectLifecycleError("expected project revision/version do not agree")
        prior = self.__writer.get_receipt(key)
        if prior is not None:
            current = self._current_unpinned(project_ref)
            manager = self._pm_assignment(manager_assignment, role="manager", project=project_ref, generation=generation)
            tasks = self._pm_tasks(task_refs, project_ref)
            orchestrator = None
            assignment_receipt = None
            if action == "pm-bind-existing":
                assignment_engine = _ResponsibilityAssignmentsEngine(self.__writer, actor=actor)
                draft = owner_attribution or {"orchestrator": {"principal": orchestrator_principal}}
                draft_orchestrator = draft.get("orchestrator") if isinstance(draft, Mapping) else None
                replay_principal = orchestrator_principal or (draft_orchestrator.get("principal") if isinstance(draft_orchestrator, Mapping) else None) or ""
                with self.__writer.transaction() as tx:
                    assignment, assignment_receipt = assignment_engine._create_in_transaction(
                        tx=tx,
                        scope=project_ref,
                        role="orchestrator",
                        principal=replay_principal,
                        pins=(project_ref, manager.ref, *tasks),
                        logical_request_key=key + ":assignment",
                        actor=actor,
                    )
                    attribution = self._pm_attribution(project=project_ref, manager=manager, orchestrator=assignment, generation=generation, key=key, actor=actor, draft=draft, action=action)
                    payload = {"project_ref": project_ref.to_dict(), "action": action, "expected_project_revision": expected_project_revision, "expected_project_version": expected_project_version, "generation": generation, "manager_assignment": manager.ref.to_dict(), "orchestrator_assignment": assignment.ref.to_dict(), "task_refs": [item.to_dict() for item in tasks], "owner_attribution": attribution, "actor": actor.to_dict()}
                    envelope = self._envelope(payload, key, actor, prior.target, expected_project_version, expected_project_revision)
                    receipt = self.__writer.mutate(envelope, event_type=LIFECYCLE_EVENT, result_ref=prior.result_ref, stream="work:" + project_ref.id, transaction=tx)
                return self._pm_result(project_ref, action, receipt, replayed=True, assignment=assignment, assignment_receipt=assignment_receipt, attribution=attribution)
            if action in {"pm-orchestrator-close", "pm-reconcile-no-owned-schedule"}:
                orchestrator = self._pm_assignment(orchestrator_assignment, role="orchestrator", project=project_ref, generation=generation)
            self._pm_requested_digest = attribution_digest
            attribution = self._pm_attribution(project=project_ref, manager=manager, orchestrator=orchestrator, generation=generation, key=key, actor=actor, draft=None, action=action)
            payload = {"project_ref": project_ref.to_dict(), "action": action, "expected_project_revision": expected_project_revision, "expected_project_version": expected_project_version, "generation": generation, "manager_assignment": manager.ref.to_dict(), "orchestrator_assignment": None if orchestrator is None else orchestrator.ref.to_dict(), "task_refs": [item.to_dict() for item in tasks], "attribution_digest": attribution_digest, "evidence": _safe(evidence) if evidence is not None else None, "schedule_observation": _safe(schedule_observation) if schedule_observation is not None else None, "actor": actor.to_dict()}
            envelope = self._envelope(payload, key, actor, prior.target, expected_project_version, expected_project_revision)
            with self.__writer.transaction() as tx:
                receipt = self.__writer.mutate(envelope, event_type=LIFECYCLE_EVENT, result_ref=prior.result_ref, stream="work:" + project_ref.id, transaction=tx)
            return self._pm_result(project_ref, action, receipt, replayed=True, assignment=orchestrator, attribution=attribution)
        current = self._current(project_ref)
        if current.ref.revision != expected_project_revision or current.version != expected_project_version:
            raise ProjectLifecycleError("stale project revision or version")
        manager = self._pm_assignment(manager_assignment, role="manager", project=project_ref, generation=generation)
        tasks = self._pm_tasks(task_refs, project_ref)
        if action == "pm-bind-existing":
            if current.payload.get("lifecycle") != Lifecycle.PENDING.value:
                raise ProjectLifecycleError("PM bind requires a pending project")
            if orchestrator_assignment is not None:
                raise ProjectLifecycleError("pm-bind-existing must derive the orchestrator assignment")
            if not isinstance(orchestrator_principal, str) or not orchestrator_principal.strip():
                raise ProjectLifecycleError("orchestrator_principal is required")
            assignment_key = key + ":assignment"
            assignment_engine = _ResponsibilityAssignmentsEngine(self.__writer, actor=actor)
            project_pin = project_ref
            with self.__writer.transaction() as tx:
                assignment, assignment_receipt = assignment_engine._create_in_transaction(
                    tx=tx,
                    scope=project_ref,
                    role="orchestrator",
                    principal=orchestrator_principal,
                    pins=(project_pin, manager.ref, *tasks),
                    logical_request_key=assignment_key,
                    actor=actor,
                )
                attribution = self._pm_attribution(project=project_ref, manager=manager, orchestrator=assignment, generation=generation, key=key, actor=actor, draft=owner_attribution, action=action)
                payload = {"project_ref": project_ref.to_dict(), "action": action, "expected_project_revision": expected_project_revision, "expected_project_version": expected_project_version, "generation": generation, "manager_assignment": manager.ref.to_dict(), "orchestrator_assignment": assignment.ref.to_dict(), "task_refs": [item.to_dict() for item in tasks], "owner_attribution": attribution, "actor": actor.to_dict()}
                envelope = self._envelope(payload, key, actor, current.ref, current.version, current.ref.revision)
                control = dict(current.payload.get("lifecycle_control", {}))
                control.update({"owner_attribution": attribution, "manager_assignment": manager.ref.to_dict(), "orchestrator_assignment": assignment.ref.to_dict(), "transition": {"action": action, "request_id": key, "actor": actor.to_dict(), "generation": generation, "project_ref": project_ref.to_dict(), "project_revision": expected_project_revision, "task_refs": [item.to_dict() for item in tasks], "attribution_digest": attribution["digest"]}})
                next_payload = dict(current.payload)
                next_payload["lifecycle_control"] = control
                receipt = self.__writer.mutate(envelope, identity_payload=next_payload, event_type=LIFECYCLE_EVENT, result_ref=ResourceRef(project_ref.authority, project_ref.kind, project_ref.id, "rev-" + str(current.version + 1)), before_refs=(current.ref,), after_refs=(manager.ref, assignment.ref, *tasks), effects={"project": project_ref, "action": action, "assignment": assignment.ref, "assignment_receipt": assignment_receipt.to_dict(), "attribution_digest": attribution["digest"]}, stream="work:" + project_ref.id, transaction=tx)
            return self._pm_result(project_ref, action, receipt, replayed=False, assignment=assignment, assignment_receipt=assignment_receipt, attribution=attribution)

        if not isinstance(attribution_digest, str) or not attribution_digest.strip():
            raise ProjectLifecycleError("attribution_digest is required")
        self._pm_requested_digest = attribution_digest
        orchestrator = None
        if action in {"pm-orchestrator-close", "pm-reconcile-no-owned-schedule"}:
            orchestrator = self._pm_assignment(orchestrator_assignment, role="orchestrator", project=project_ref, generation=generation)
        attribution = self._pm_attribution(project=project_ref, manager=manager, orchestrator=orchestrator, generation=generation, key=key, actor=actor, draft=None, action=action)
        control = dict(current.payload.get("lifecycle_control", {}))
        if action == "pm-manager-close-request":
            if current.payload.get("lifecycle") != Lifecycle.PENDING.value:
                raise ProjectLifecycleError("PM manager close requires a pending project")
            if control.get("close_request"):
                raise ProjectLifecycleError("project already has a PM close request")
        elif action == "pm-orchestrator-close":
            if current.payload.get("lifecycle") != Lifecycle.PENDING.value or not control.get("close_request"):
                raise ProjectLifecycleError("PM terminal close requires a pending project with a close request")
            terminal = self._evidence(evidence, project_ref)
            for name in ("acceptance", "publication", "remote", "runtime"):
                if terminal[name].get("status") not in {"passed", "verified", "qualified"}:
                    raise ProjectLifecycleError("terminal evidence status is not qualified")
        else:
            if current.payload.get("lifecycle") != Lifecycle.COMPLETED.value:
                raise ProjectLifecycleError("PM reconciliation requires a completed project")
            observation = _copy(schedule_observation, "schedule_observation")
            unknown = observation.get("unknown_ownership") or observation.get("ownership") == "unknown" or any(
                isinstance(item, Mapping) and item.get("status") == "unknown" for item in observation.get("shared_records", ())
            )
            if unknown:
                return {"outcome": "held", "replayed": False, "action": action, "project_ref": current.ref.to_dict(), "reason": "schedule ownership is unknown", "mutated": False}
            if observation.get("mode") != "no-owned-schedule" or observation.get("pm_owned_schedule_ids") != []:
                raise ProjectLifecycleError("PM reconciliation requires an empty owned schedule set")
            if not isinstance(observation.get("coverage"), Mapping) or not isinstance(observation.get("shared_records"), list):
                raise ProjectLifecycleError("schedule observation coverage is incomplete")
            for item in observation["shared_records"]:
                if not isinstance(item, Mapping) or item.get("status") != "preserved":
                    raise ProjectLifecycleError("shared schedule records must be preserved")
            control = dict(current.payload.get("lifecycle_control", {}))
        payload = {"project_ref": project_ref.to_dict(), "action": action, "expected_project_revision": expected_project_revision, "expected_project_version": expected_project_version, "generation": generation, "manager_assignment": manager.ref.to_dict(), "orchestrator_assignment": None if orchestrator is None else orchestrator.ref.to_dict(), "task_refs": [item.to_dict() for item in tasks], "attribution_digest": attribution_digest, "evidence": _safe(evidence) if evidence is not None else None, "schedule_observation": _safe(schedule_observation) if schedule_observation is not None else None, "actor": actor.to_dict()}
        envelope = self._envelope(payload, key, actor, current.ref, current.version, current.ref.revision)
        with self.__writer.transaction() as tx:
            control = dict(current.payload.get("lifecycle_control", {}))
            if action == "pm-manager-close-request":
                report_ref = ResourceRef(self.__writer.authority, REPORT_KIND, "report-" + hashlib.sha256((project_ref.id + ":" + key).encode()).hexdigest()[:28])
                report_payload = {"record_type": "work.observation", "observation_kind": "project-close-request", "project": project_ref, "assignment": manager.ref, "generation": generation, "value": {"logical_request_key": key, "project_ref": project_ref, "project_revision": expected_project_revision, "task_refs": tasks, "attribution_digest": attribution_digest}}
                report_receipt = self.__writer.mutate(self._envelope_generic("work.report.append", ASSIGNMENT_SCHEMA_REVISION, report_payload, key + ":report", actor, report_ref, 0, None), identity_payload=report_payload, event_type="work.report.appended", result_ref=ResourceRef(report_ref.authority, report_ref.kind, report_ref.id, "rev-1"), after_refs=(project_ref, manager.ref, *tasks), effects={"project": project_ref, "assignment": manager.ref, "transition": action}, stream="report:" + project_ref.id, transaction=tx)
                control["close_request"] = {"report_ref": report_ref.to_dict(), "request_id": key, "project_ref": project_ref.to_dict(), "project_revision": expected_project_revision, "manager_assignment": manager.ref.to_dict(), "generation": generation, "task_refs": [item.to_dict() for item in tasks], "attribution_digest": attribution_digest, "receipt": report_receipt.to_dict()}
            elif action == "pm-orchestrator-close":
                control["terminal_evidence"] = self._evidence(evidence, project_ref)
            else:
                observation = _copy(schedule_observation, "schedule_observation")
                control["reconciliation"] = {"status": "reconciled", "mode": "no-owned-schedule", "observation": observation, "host_effects": []}
            control["transition"] = {"action": action, "request_id": key, "actor": actor.to_dict(), "generation": generation, "project_ref": project_ref.to_dict(), "project_revision": expected_project_revision, "task_refs": [item.to_dict() for item in tasks], "attribution_digest": attribution_digest}
            next_payload = dict(current.payload)
            next_payload["lifecycle_control"] = control
            if action == "pm-orchestrator-close":
                next_payload["lifecycle"] = Lifecycle.COMPLETED.value
            receipt = self.__writer.mutate(envelope, identity_payload=next_payload, event_type=LIFECYCLE_EVENT, result_ref=ResourceRef(project_ref.authority, project_ref.kind, project_ref.id, "rev-" + str(current.version + 1)), before_refs=(current.ref,), after_refs=tuple(item for item in (manager.ref, orchestrator.ref if orchestrator is not None else None, *tasks) if item is not None), effects={"project": project_ref, "action": action, "attribution_digest": attribution_digest, "close_request": control.get("close_request"), "reconciliation": control.get("reconciliation")}, stream="work:" + project_ref.id, transaction=tx)
        return self._pm_result(project_ref, action, receipt, replayed=False, assignment=orchestrator, attribution=attribution)

    def transition(
        self,
        project: Any,
        *,
        action: str,
        logical_request_key: str,
        expected_project_revision: str,
        generation: int,
        expected_project_version: Optional[int] = None,
        manager_assignment: Any = None,
        task: Any = None,
        orchestrator_assignment: Any = None,
        orchestrator_principal: Optional[str] = None,
        task_refs: Sequence[Any] = (),
        attribution_digest: Optional[str] = None,
        owner_attribution: Optional[Mapping[str, Any]] = None,
        evidence: Optional[Mapping[str, Any]] = None,
        schedule_observation: Optional[Mapping[str, Any]] = None,
        effect_packet: Optional[Mapping[str, Any]] = None,
        settlement: Optional[Mapping[str, Any]] = None,
        actor: Any = None,
    ) -> Mapping[str, Any]:
        selected_actor = self._actor(actor)
        project_ref = _ref(project, "project", kind="work.project")
        action_value = _text(action, "action")
        if action_value not in _ACTIONS | _PM_ACTIONS:
            raise ProjectLifecycleError("unsupported lifecycle action")
        key = _text(logical_request_key, "logical_request_key")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ProjectLifecycleError("generation must be a positive integer")
        if expected_project_revision != project_ref.revision:
            raise ProjectLifecycleError("expected project revision does not match project ref")
        if action_value in _PM_ACTIONS:
            return self._transition_pm(
                project_ref,
                action=action_value,
                key=key,
                expected_project_revision=expected_project_revision,
                expected_project_version=expected_project_version,
                generation=generation,
                manager_assignment=manager_assignment,
                orchestrator_assignment=orchestrator_assignment,
                orchestrator_principal=orchestrator_principal,
                task_refs=task_refs,
                attribution_digest=attribution_digest,
                owner_attribution=owner_attribution,
                evidence=evidence,
                schedule_observation=schedule_observation,
                actor=selected_actor,
            )
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
