"""Neutral durable operation identity and adapter-context mechanics.

This module deliberately does not invoke an adapter.  It records the request
and each explicit outcome through the FND-03 ``Store`` transaction port.  The
operation identity, physical invocation reference, and authoritative external
owner are separate values so an adapter cannot accidentally collapse them into
one product-specific authority.
"""

from __future__ import annotations

import weakref

_COMMAND_PORTS = weakref.WeakKeyDictionary()

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
from typing import Any, Mapping, Optional

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    CommandReceipt,
    ResourceRef,
    TransactionContext,
    canonical_request_digest,
    canonical_json,
    validate_replay,
)

from .store import Store, StoreError, TargetMismatchError, Transaction


OPERATION_SCHEMA_REVISION = "fnd-04.operation.v1"
OPERATION_KIND = "operation"
OPERATION_STREAM = "operations"
_UNSET = object()


class OperationError(StoreError):
    """Base error for neutral operation admission and state transitions."""


class OperationState(str, Enum):
    PREPARED = "prepared"
    COMMITTED = "committed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNCERTAIN = "uncertain"


class UnknownOutcomeError(OperationError):
    """An unknown operation requires an explicit resolution."""


@dataclass(frozen=True)
class OperationRequest:
    """Validated request and neutral adapter context.

    ``logical_request_key`` and ``request_digest`` identify the durable
    command.  The three references are intentionally independent: the
    operation identity is created by this module, while the adapter context,
    physical invocation, and external owner are supplied by a caller.
    """

    operation: str
    schema_revision: str
    adapter_ref: ResourceRef
    actor: AuthenticatedActor
    logical_request_key: str
    request_digest: str
    payload: Mapping[str, Any]
    physical_invocation_ref: Optional[ResourceRef] = None
    external_owner_ref: Optional[ResourceRef] = None
    expected_revision: Optional[str] = None
    expected_version: Optional[int] = None
    edit_token: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise OperationError("operation must be a non-blank string")
        if not isinstance(self.schema_revision, str) or not self.schema_revision.strip():
            raise OperationError("schema_revision must be a non-blank string")
        if not isinstance(self.adapter_ref, ResourceRef):
            raise OperationError("adapter_ref must be a ResourceRef")
        if not isinstance(self.actor, AuthenticatedActor):
            raise OperationError("actor must be an AuthenticatedActor")
        if not isinstance(self.payload, Mapping):
            raise OperationError("payload must be a mapping")
        if self.physical_invocation_ref is not None and not isinstance(self.physical_invocation_ref, ResourceRef):
            raise OperationError("physical_invocation_ref must be a ResourceRef")
        if self.external_owner_ref is not None and not isinstance(self.external_owner_ref, ResourceRef):
            raise OperationError("external_owner_ref must be a ResourceRef")
        # Constructing the neutral FND context performs the canonical key and
        # digest validation before a writer transaction is admitted.
        TransactionContext(
            self.actor,
            self.logical_request_key,
            self.request_digest,
            expected_revision=self.expected_revision,
            expected_version=self.expected_version,
            edit_token=self.edit_token,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
        )
        canonical_json(dict(self.payload))

    def semantic_payload(self) -> dict[str, Any]:
        """Return request arguments whose meaning is fixed by this request."""
        return {
            "adapter_ref": self.adapter_ref.to_dict(),
            "payload": dict(self.payload),
            "physical_invocation_ref": _ref_dict(self.physical_invocation_ref),
            "external_owner_ref": _ref_dict(self.external_owner_ref),
        }

    def _context(
        self,
        *,
        expected_revision: Any = _UNSET,
        expected_version: Any = _UNSET,
        edit_token: Any = _UNSET,
        correlation_id: Any = _UNSET,
        causation_id: Any = _UNSET,
    ) -> TransactionContext:
        return TransactionContext(
            self.actor,
            self.logical_request_key,
            self.request_digest,
            expected_revision=self.expected_revision if expected_revision is _UNSET else expected_revision,
            expected_version=self.expected_version if expected_version is _UNSET else expected_version,
            edit_token=self.edit_token if edit_token is _UNSET else edit_token,
            correlation_id=self.correlation_id if correlation_id is _UNSET else correlation_id,
            causation_id=self.causation_id if causation_id is _UNSET else causation_id,
        )

    def canonical_digest(
        self,
        target: ResourceRef,
        *,
        expected_revision: Any = _UNSET,
        expected_version: Any = _UNSET,
        edit_token: Any = _UNSET,
        correlation_id: Any = _UNSET,
        causation_id: Any = _UNSET,
    ) -> str:
        context = self._context(
            expected_revision=expected_revision,
            expected_version=expected_version,
            edit_token=edit_token,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return canonical_request_digest(
            logical_request_key=context.logical_request_key,
            operation=self.operation,
            schema_revision=self.schema_revision,
            target=target,
            actor=context.actor,
            payload=self.semantic_payload(),
            context=context,
        )

    def canonicalized(self, target: ResourceRef, **context_fields: Any) -> "OperationRequest":
        """Return the request with its digest bound to admitted semantics."""
        context = self._context(**context_fields)
        return replace(
            self,
            request_digest=self.canonical_digest(target, **context_fields),
            expected_revision=context.expected_revision,
            expected_version=context.expected_version,
            edit_token=context.edit_token,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )

    def envelope(
        self,
        target: ResourceRef,
        *,
        expected_revision: Any = _UNSET,
        expected_version: Any = _UNSET,
        edit_token: Any = _UNSET,
        correlation_id: Any = _UNSET,
        causation_id: Any = _UNSET,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> CommandEnvelope:
        envelope_payload = dict(self.payload if payload is None else payload)
        context = self._context(
            expected_revision=expected_revision,
            expected_version=expected_version,
            edit_token=edit_token,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return CommandEnvelope(
            self.operation,
            self.schema_revision,
            target,
            TransactionContext(
                context.actor,
                self.logical_request_key,
                canonical_request_digest(
                    logical_request_key=context.logical_request_key,
                    operation=self.operation,
                    schema_revision=self.schema_revision,
                    target=target,
                    actor=context.actor,
                    payload=envelope_payload,
                    context=context,
                ),
                expected_revision=context.expected_revision,
                expected_version=context.expected_version,
                edit_token=context.edit_token,
                correlation_id=context.correlation_id,
                causation_id=context.causation_id,
            ),
            envelope_payload,
        )


# The brief uses both “operation context” and “request”.  Keep one canonical
# type while offering the neutral context spelling to adapters.
OperationContext = OperationRequest


@dataclass(frozen=True)
class OperationRecord:
    operation_ref: ResourceRef
    request: OperationRequest
    state: OperationState
    result: Mapping[str, Any]
    receipt: Optional[CommandReceipt]
    version: int

    @property
    def logical_receipt(self) -> Optional[CommandReceipt]:
        return self.receipt

    @property
    def physical_invocation_ref(self) -> Optional[ResourceRef]:
        return self.request.physical_invocation_ref

    @property
    def external_owner_ref(self) -> Optional[ResourceRef]:
        return self.request.external_owner_ref


def request_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical digest helper for callers constructing requests."""
    return hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _ref_dict(ref: Optional[ResourceRef]) -> Optional[dict[str, Any]]:
    return None if ref is None else ref.to_dict()


def _ref(value: Optional[Mapping[str, Any]]) -> Optional[ResourceRef]:
    return None if value is None else ResourceRef.from_dict(value)


class OperationManager:
    """Record operation requests and explicit outcomes; never invoke them."""

    def __init__(self, store: Store) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be a Store")
        _COMMAND_PORTS[self] = store
        self.reader = store.consumer()

    def _target(self, logical_request_key: str) -> ResourceRef:
        return ResourceRef(_COMMAND_PORTS[self].authority, OPERATION_KIND, logical_request_key)

    def _payload(self, request: OperationRequest, state: OperationState, result: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "record_type": OPERATION_KIND,
            "operation": request.operation,
            "schema_revision": request.schema_revision,
            "adapter_ref": request.adapter_ref.to_dict(),
            "request_actor": request.actor.to_dict(),
            "logical_request_key": request.logical_request_key,
            "request_digest": request.request_digest,
            "request_payload": dict(request.payload),
            "physical_invocation_ref": _ref_dict(request.physical_invocation_ref),
            "external_owner_ref": _ref_dict(request.external_owner_ref),
            "expected_revision": request.expected_revision,
            "expected_version": request.expected_version,
            "edit_token": request.edit_token,
            "correlation_id": request.correlation_id,
            "causation_id": request.causation_id,
            "state": state.value,
            "result": dict(result),
        }

    def _record_from_event(self, receipt: CommandReceipt, event_effects: Mapping[str, Any], request: OperationRequest, operation_ref: ResourceRef, version: int) -> OperationRecord:
        state = OperationState(event_effects["state"])
        result = dict(event_effects.get("result", {}))
        recorded_request = OperationRequest(
            request.operation,
            request.schema_revision,
            ResourceRef.from_dict(event_effects.get("adapter_ref", request.adapter_ref.to_dict())),
            AuthenticatedActor.from_dict(event_effects.get("request_actor", request.actor.to_dict())),
            request.logical_request_key,
            request.request_digest,
            event_effects.get("request_payload", request.payload),
            _ref(event_effects.get("physical_invocation_ref")),
            _ref(event_effects.get("external_owner_ref")),
            event_effects.get("expected_revision", request.expected_revision),
            event_effects.get("expected_version", request.expected_version),
            event_effects.get("edit_token", request.edit_token),
            event_effects.get("correlation_id", request.correlation_id),
            event_effects.get("causation_id", request.causation_id),
        )
        return OperationRecord(operation_ref, recorded_request, state, result, receipt, version)

    def _event_for_receipt(self, receipt: CommandReceipt) -> Mapping[str, Any]:
        if not receipt.event_ids:
            return {"state": OperationState.PREPARED.value, "result": {}, "version": 1}
        wanted = set(receipt.event_ids)
        for event in _COMMAND_PORTS[self].list_events(stream=OPERATION_STREAM):
            if event.event_id in wanted:
                return event.effects
        raise OperationError("receipt event is not visible in the admitted store")

    def _request_from_identity(self, payload: Mapping[str, Any], actor: Optional[AuthenticatedActor] = None) -> OperationRequest:
        request_actor = actor
        if request_actor is None and payload.get("request_actor") is not None:
            request_actor = AuthenticatedActor.from_dict(payload["request_actor"])
        if request_actor is None:
            raise OperationError("operation actor is absent from identity and event lineage")
        return OperationRequest(
            payload["operation"],
            payload["schema_revision"],
            ResourceRef.from_dict(payload["adapter_ref"]),
            request_actor,
            payload["logical_request_key"],
            payload["request_digest"],
            payload.get("request_payload", {}),
            _ref(payload.get("physical_invocation_ref")),
            _ref(payload.get("external_owner_ref")),
            payload.get("expected_revision"),
            payload.get("expected_version"),
            payload.get("edit_token"),
            payload.get("correlation_id"),
            payload.get("causation_id"),
        )

    def prepare(self, request: OperationRequest, *, transaction: Optional[Transaction] = None) -> OperationRecord:
        if not isinstance(request, OperationRequest):
            raise TypeError("request must be an OperationRequest")
        target = self._target(request.logical_request_key)
        request = request.canonicalized(target, expected_version=0)
        payload = self._payload(request, OperationState.PREPARED, {})
        envelope = request.envelope(target, expected_version=0, payload=payload)
        effects = {
            "state": OperationState.PREPARED.value,
            "result": {},
            "adapter_ref": request.adapter_ref.to_dict(),
            "request_actor": request.actor.to_dict(),
            "physical_invocation_ref": _ref_dict(request.physical_invocation_ref),
            "external_owner_ref": _ref_dict(request.external_owner_ref),
            "request_payload": dict(request.payload),
            "version": 1,
        }
        receipt = _COMMAND_PORTS[self].mutate(
            envelope,
            event_type="operation.prepared",
            result_ref=ResourceRef(_COMMAND_PORTS[self].authority, OPERATION_KIND, request.logical_request_key, "rev-1"),
            effects=effects,
            stream=OPERATION_STREAM,
            transaction=transaction,
        )
        event_effects = self._event_for_receipt(receipt)
        identity = _COMMAND_PORTS[self].get_identity(target)
        version = int(event_effects.get("version", identity.version if identity else 1))
        operation_ref = receipt.result_ref or (identity.ref if identity else target)
        return self._record_from_event(receipt, event_effects, request, operation_ref, version)

    def _transition(
        self,
        record: OperationRecord,
        state: OperationState,
        result: Mapping[str, Any],
        *,
        transition_key: Optional[str],
        transition_digest: Optional[str],
        physical_invocation_ref: Optional[ResourceRef],
        external_owner_ref: Optional[ResourceRef],
        allow_unknown_resolution: bool,
        transition_actor: AuthenticatedActor,
        transaction: Optional[Transaction],
    ) -> OperationRecord:
        if not isinstance(result, Mapping):
            raise OperationError("result must be a mapping")
        next_request_key = transition_key or (record.request.logical_request_key + ":outcome")
        # The optional legacy digest is deliberately not trusted.  The
        # envelope derives the transition digest from its full semantics.
        next_request = OperationRequest(
            "operation.outcome",
            record.request.schema_revision,
            record.request.adapter_ref,
            transition_actor,
            next_request_key,
            request_digest({"operation": record.request.logical_request_key, "state": state.value, "result": dict(result)}),
            {
                "original_request_payload": dict(record.request.payload),
                "state": state.value,
                "result": dict(result),
            },
            physical_invocation_ref if physical_invocation_ref is not None else record.request.physical_invocation_ref,
            external_owner_ref if external_owner_ref is not None else record.request.external_owner_ref,
        )
        target = record.operation_ref
        if target.revision is None:
            raise OperationError("operation record must carry its current revision")
        identity_request = OperationRequest(
            record.request.operation,
            record.request.schema_revision,
            record.request.adapter_ref,
            record.request.actor,
            record.request.logical_request_key,
            record.request.request_digest,
            record.request.payload,
            next_request.physical_invocation_ref,
            next_request.external_owner_ref,
        )
        envelope = next_request.envelope(
            target,
            expected_revision=target.revision,
            expected_version=record.version,
            payload=self._payload(identity_request, state, result),
        )
        prior = _COMMAND_PORTS[self].get_receipt(next_request_key)
        if prior is not None:
            validate_replay(prior, envelope)
            event_effects = self._event_for_receipt(prior)
            return self._record_from_event(prior, event_effects, record.request, prior.result_ref or target, int(event_effects.get("version", record.version + 1)))
        if record.state in (OperationState.UNKNOWN, OperationState.UNCERTAIN) and not allow_unknown_resolution:
            raise UnknownOutcomeError("unknown operation outcome requires explicit resolution")
        if record.state not in (OperationState.PREPARED, OperationState.UNKNOWN, OperationState.UNCERTAIN):
            raise OperationError("operation already has a terminal outcome")
        effects = {
            "state": state.value,
            "result": dict(result),
            "adapter_ref": next_request.adapter_ref.to_dict(),
            "request_actor": record.request.actor.to_dict(),
            "physical_invocation_ref": _ref_dict(next_request.physical_invocation_ref),
            "external_owner_ref": _ref_dict(next_request.external_owner_ref),
            "request_payload": dict(record.request.payload),
            "version": record.version + 1,
        }
        receipt = _COMMAND_PORTS[self].mutate(
            envelope,
            event_type="operation.outcome",
            result_ref=ResourceRef(target.authority, target.kind, target.id, "rev-{}".format(record.version + 1)),
            effects=effects,
            stream=OPERATION_STREAM,
            transaction=transaction,
        )
        event_effects = self._event_for_receipt(receipt)
        new_ref = receipt.result_ref or target
        return self._record_from_event(receipt, event_effects, identity_request, new_ref, int(event_effects.get("version", record.version + 1)))

    def record_outcome(self, record: OperationRecord, state: OperationState, result: Optional[Mapping[str, Any]] = None, *, transition_key: Optional[str] = None, transition_digest: Optional[str] = None, physical_invocation_ref: Optional[ResourceRef] = None, external_owner_ref: Optional[ResourceRef] = None, transaction: Optional[Transaction] = None) -> OperationRecord:
        if not isinstance(state, OperationState):
            state = OperationState(state)
        if state not in (OperationState.COMMITTED, OperationState.FAILED, OperationState.UNKNOWN, OperationState.UNCERTAIN):
            raise OperationError("record_outcome requires a terminal or uncertain state")
        return self._transition(record, state, result or {}, transition_key=transition_key, transition_digest=transition_digest, physical_invocation_ref=physical_invocation_ref, external_owner_ref=external_owner_ref, allow_unknown_resolution=False, transition_actor=record.request.actor, transaction=transaction)

    def resolve_unknown(self, record: OperationRecord, state: OperationState, result: Optional[Mapping[str, Any]] = None, *, resolver: Optional[AuthenticatedActor] = None, transition_key: Optional[str] = None, transition_digest: Optional[str] = None, physical_invocation_ref: Optional[ResourceRef] = None, external_owner_ref: Optional[ResourceRef] = None, transaction: Optional[Transaction] = None) -> OperationRecord:
        if state not in (OperationState.COMMITTED, OperationState.FAILED):
            raise OperationError("unknown resolution must be committed or failed")
        if not isinstance(resolver, AuthenticatedActor):
            raise OperationError("unknown resolution requires an authenticated resolver")
        return self._transition(record, state, result or {}, transaction=transaction, transition_key=transition_key, transition_digest=transition_digest, physical_invocation_ref=physical_invocation_ref, external_owner_ref=external_owner_ref, allow_unknown_resolution=True, transition_actor=resolver)

    def get(self, logical_request_key: str) -> Optional[OperationRecord]:
        target = self._target(logical_request_key)
        identity = _COMMAND_PORTS[self].get_identity(target)
        if identity is None or identity.payload.get("record_type") != OPERATION_KIND:
            return None
        lineage_actor = next(
            (
                event.actor
                for event in _COMMAND_PORTS[self].list_events(stream=OPERATION_STREAM)
                if event.subject.authority == identity.ref.authority
                and event.subject.kind == identity.ref.kind
                and event.subject.id == identity.ref.id
                and event.event_type == "operation.prepared"
            ),
            None,
        )
        request = self._request_from_identity(identity.payload, actor=lineage_actor)
        receipt = _COMMAND_PORTS[self].get_receipt(request.logical_request_key)
        return OperationRecord(identity.ref, request, OperationState(identity.payload["state"]), dict(identity.payload.get("result", {})), receipt, identity.version)


OperationAdapter = OperationManager


__all__ = [
    "OPERATION_KIND", "OPERATION_SCHEMA_REVISION", "OperationError", "UnknownOutcomeError",
    "OperationState", "OperationRequest", "OperationContext", "OperationRecord",
    "OperationManager", "OperationAdapter", "request_digest",
]
