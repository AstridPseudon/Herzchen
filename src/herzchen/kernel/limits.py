"""Neutral integer capacity reservations and cumulative allowance accounting.

Limit and reservation records are ordinary FND-03 identities.  Their state is
advanced with ``Store.mutate`` and therefore shares the supplied transaction,
receipt, event, and rollback boundary.  No table, connection, migration, or
private writer is introduced here.
"""

from __future__ import annotations

import weakref

_COMMAND_PORTS = weakref.WeakKeyDictionary()

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Mapping, Optional, Sequence, Tuple

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    CommandReceipt,
    ResourceRef,
    TransactionContext,
    canonical_request_digest,
    validate_replay,
)

from .store import Store, StoreError, TargetMismatchError, Transaction


LIMIT_SCHEMA_REVISION = "fnd-04.limit.v1"
LIMIT_KIND = "limit"
RESERVATION_KIND = "reservation"
_UNSET = object()
LIMIT_STREAM = "limits"


class LimitError(StoreError):
    """Base error for neutral capacity and allowance admission."""


class CapacityExhaustedError(LimitError):
    """Reusable capacity is not available for the requested integer units."""


class AllowanceExhaustedError(LimitError):
    """The cumulative integer allowance would be exceeded."""


class ReservationStateError(LimitError):
    """A reservation transition is not valid for its current state."""


class ReservationExistsError(LimitError):
    """A reservation identity already has a different declaration."""


class ReservationStatus(str, Enum):
    HELD = "held"
    UNCERTAIN = "uncertain"
    CONSUMED = "consumed"
    RELEASED = "released"


def _actor(actor: Optional[AuthenticatedActor]) -> AuthenticatedActor:
    return actor or AuthenticatedActor("neutral-kernel", "limits", "limits")


def _positive_units(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LimitError("{} must be a positive integer".format(field))
    return value


def _units(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LimitError("{} must be a non-negative integer".format(field))
    return value


def _ref_dict(ref: ResourceRef) -> dict[str, Any]:
    return ref.to_dict()


def _stable(ref: ResourceRef, kind: str, authority: str) -> ResourceRef:
    if not isinstance(ref, ResourceRef):
        raise TypeError("reference must be a ResourceRef")
    if ref.authority != authority:
        raise TargetMismatchError("reference authority does not belong to this store")
    if ref.kind != kind:
        raise LimitError("reference kind must be {}".format(kind))
    if ref.revision is not None:
        raise LimitError("stable {} identity must not be pinned".format(kind))
    return ref


@dataclass(frozen=True)
class LimitPool:
    ref: ResourceRef
    capacity_units: int
    cumulative_allowance_units: int
    version: int = 0
    current_revision: Optional[str] = None
    held_units: int = 0
    cumulative_used_units: int = 0
    receipt: Optional[CommandReceipt] = None

    @property
    def available_capacity_units(self) -> int:
        return max(0, self.capacity_units - self.held_units)

    @property
    def remaining_allowance_units(self) -> int:
        return max(0, self.cumulative_allowance_units - self.cumulative_used_units)


@dataclass(frozen=True)
class ReservationRecord:
    ref: ResourceRef
    pool_ref: ResourceRef
    declared_units: int
    status: ReservationStatus
    actual_units: int
    charged_units: int
    version: int
    receipt: Optional[CommandReceipt] = None

    @property
    def overrun_units(self) -> int:
        return max(0, self.actual_units - self.declared_units)

    @property
    def held(self) -> bool:
        return self.status in (ReservationStatus.HELD, ReservationStatus.UNCERTAIN)


class LimitService:
    """One neutral reservation ledger over an admitted FND-03 store."""

    def __init__(self, store: Store) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be a Store")
        _COMMAND_PORTS[self] = store
        self.reader = store.consumer()

    def _envelope(
        self,
        operation: str,
        target: ResourceRef,
        actor: AuthenticatedActor,
        logical_request_key: str,
        request_digest: str,
        payload: Mapping[str, Any],
        *,
        expected_revision: Optional[str] = None,
        expected_version: Optional[int] = None,
        edit_token: Optional[str] = None,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
    ) -> CommandEnvelope:
        context = TransactionContext(
            actor,
            logical_request_key,
            request_digest,
            expected_revision=expected_revision,
            expected_version=expected_version,
            edit_token=edit_token,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        canonical = canonical_request_digest(
            logical_request_key=logical_request_key,
            operation=operation,
            schema_revision=LIMIT_SCHEMA_REVISION,
            target=target,
            actor=actor,
            payload=payload,
            context=context,
        )
        return CommandEnvelope(
            operation,
            LIMIT_SCHEMA_REVISION,
            target,
            TransactionContext(
                actor,
                logical_request_key,
                canonical,
                expected_revision=expected_revision,
                expected_version=expected_version,
                edit_token=edit_token,
                correlation_id=correlation_id,
                causation_id=causation_id,
            ),
            dict(payload),
        )

    def _digest(
        self,
        operation: str,
        target: ResourceRef,
        actor: AuthenticatedActor,
        key: str,
        value: Mapping[str, Any],
        supplied: Optional[str],
        *,
        expected_revision: Optional[str] = None,
        expected_version: Optional[int] = None,
        edit_token: Optional[str] = None,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
    ) -> str:
        # ``supplied`` remains accepted for API compatibility, but a caller
        # cannot select replay identity with an unrelated digest-shaped value.
        context = TransactionContext(
            actor,
            key,
            "0" * 64,
            expected_revision=expected_revision,
            expected_version=expected_version,
            edit_token=edit_token,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return canonical_request_digest(
            logical_request_key=key,
            operation=operation,
            schema_revision=LIMIT_SCHEMA_REVISION,
            target=target,
            actor=actor,
            payload=value,
            context=context,
        )

    def _event_effects(self, receipt: CommandReceipt) -> Mapping[str, Any]:
        if not receipt.event_ids:
            return {}
        wanted = set(receipt.event_ids)
        for event in _COMMAND_PORTS[self].list_events(stream=LIMIT_STREAM):
            if event.event_id in wanted:
                return event.effects
        raise LimitError("receipt event is not visible in the admitted store")

    def _pool_from_identity(self, identity: Any, receipt: Optional[CommandReceipt] = None) -> LimitPool:
        payload = identity.payload
        if payload.get("record_type") != LIMIT_KIND:
            raise LimitError("identity is not a neutral limit pool")
        pool_ref = ResourceRef(identity.ref.authority, LIMIT_KIND, identity.ref.id)
        held, used = self._pool_totals(_COMMAND_PORTS[self].connection, pool_ref)
        return LimitPool(pool_ref, int(payload["capacity_units"]), int(payload["cumulative_allowance_units"]), identity.version, identity.ref.revision, held, used, receipt)

    def _pool_totals(self, tx: Transaction, pool_ref: ResourceRef) -> Tuple[int, int]:
        held = 0
        used = 0
        rows = tx.execute("SELECT payload_json FROM identities WHERE authority = ? AND kind = ?", (_COMMAND_PORTS[self].authority, RESERVATION_KIND)).fetchall()
        for row in rows:
            payload = json.loads(row[0])
            if payload.get("record_type") != RESERVATION_KIND or payload.get("pool_ref") != pool_ref.to_dict():
                continue
            status = ReservationStatus(payload["status"])
            if status in (ReservationStatus.HELD, ReservationStatus.UNCERTAIN):
                held += int(payload["declared_units"])
            used += int(payload.get("charged_units", 0))
        return held, used

    def _reservation_from_payload(self, identity: Any, receipt: Optional[CommandReceipt] = None, effects: Optional[Mapping[str, Any]] = None) -> ReservationRecord:
        payload = effects or identity.payload
        ref = receipt.result_ref if receipt is not None and receipt.result_ref is not None else ResourceRef(identity.ref.authority, RESERVATION_KIND, identity.ref.id, identity.ref.revision)
        return ReservationRecord(
            ref,
            ResourceRef.from_dict(payload["pool_ref"]),
            int(payload["declared_units"]),
            ReservationStatus(payload["status"]),
            int(payload.get("actual_units", 0)),
            int(payload.get("charged_units", 0)),
            int(payload.get("version", identity.version)),
            receipt,
        )

    def _replayed(self, envelope: CommandEnvelope, kind: str, *, pool_ref: Optional[ResourceRef] = None) -> Optional[Any]:
        receipt = _COMMAND_PORTS[self].get_receipt(envelope.context.logical_request_key)
        if receipt is None:
            return None
        validate_replay(receipt, envelope)
        effects = self._event_effects(receipt)
        if kind == LIMIT_KIND:
            identity = _COMMAND_PORTS[self].get_identity(pool_ref or receipt.target)
            if identity is None:
                raise LimitError("replayed limit receipt has no current identity")
            return self._pool_from_identity(identity, receipt)
        identity = _COMMAND_PORTS[self].get_identity(receipt.target)
        if identity is None:
            raise LimitError("replayed reservation receipt has no current identity")
        return self._reservation_from_payload(identity, receipt, effects)

    def create_pool(self, pool_ref: ResourceRef, capacity_units: int, cumulative_allowance_units: int, *, logical_request_key: str, request_digest: Optional[str] = None, actor: Optional[AuthenticatedActor] = None, expected_revision: Optional[str] = None, expected_version: Optional[int] = 0, edit_token: Optional[str] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None, transaction: Optional[Transaction] = None) -> LimitPool:
        pool_ref = _stable(pool_ref, LIMIT_KIND, _COMMAND_PORTS[self].authority)
        capacity_units = _units(capacity_units, "capacity_units")
        cumulative_allowance_units = _units(cumulative_allowance_units, "cumulative_allowance_units")
        body = {"record_type": LIMIT_KIND, "capacity_units": capacity_units, "cumulative_allowance_units": cumulative_allowance_units}
        selected_actor = _actor(actor)
        digest = self._digest("limit.create", pool_ref, selected_actor, logical_request_key, body, request_digest, expected_revision=expected_revision, expected_version=expected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id)
        envelope = self._envelope("limit.create", pool_ref, selected_actor, logical_request_key, digest, body, expected_revision=expected_revision, expected_version=expected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id)
        replay = self._replayed(envelope, LIMIT_KIND, pool_ref=pool_ref)
        if replay is not None:
            return replay
        receipt = _COMMAND_PORTS[self].mutate(
            envelope,
            event_type="limit.created",
            result_ref=ResourceRef(_COMMAND_PORTS[self].authority, LIMIT_KIND, pool_ref.id, "rev-1"),
            effects={"record_type": LIMIT_KIND, **body, "version": 1},
            stream=LIMIT_STREAM,
            transaction=transaction,
        )
        identity = _COMMAND_PORTS[self].get_identity(pool_ref)
        if identity is None:
            raise LimitError("limit creation did not produce an identity")
        return self._pool_from_identity(identity, receipt)

    def get_pool(self, pool_ref: ResourceRef) -> Optional[LimitPool]:
        pool_ref = _stable(pool_ref, LIMIT_KIND, _COMMAND_PORTS[self].authority)
        identity = _COMMAND_PORTS[self].get_identity(pool_ref)
        return None if identity is None else self._pool_from_identity(identity)

    def _reservation_ref(self, value: Any) -> ResourceRef:
        if isinstance(value, ResourceRef):
            return _stable(value, RESERVATION_KIND, _COMMAND_PORTS[self].authority)
        if isinstance(value, str):
            return ResourceRef(_COMMAND_PORTS[self].authority, RESERVATION_KIND, value)
        raise TypeError("reservation_ref must be a ResourceRef or opaque id")

    def reserve(self, pool_ref: ResourceRef, reservation_ref: Any, declared_units: int, *, logical_request_key: str, request_digest: Optional[str] = None, actor: Optional[AuthenticatedActor] = None, expected_revision: Optional[str] = None, expected_version: Optional[int] = 0, edit_token: Optional[str] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None, transaction: Optional[Transaction] = None) -> ReservationRecord:
        pool_ref = _stable(pool_ref, LIMIT_KIND, _COMMAND_PORTS[self].authority)
        reservation_ref = self._reservation_ref(reservation_ref)
        declared_units = _positive_units(declared_units, "declared_units")
        body = {"record_type": RESERVATION_KIND, "pool_ref": _ref_dict(pool_ref), "declared_units": declared_units, "status": ReservationStatus.HELD.value, "actual_units": 0, "charged_units": 0}
        selected_actor = _actor(actor)
        digest = self._digest("limit.reserve", reservation_ref, selected_actor, logical_request_key, body, request_digest, expected_revision=expected_revision, expected_version=expected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id)
        envelope = self._envelope("limit.reserve", reservation_ref, selected_actor, logical_request_key, digest, body, expected_revision=expected_revision, expected_version=expected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id)
        if transaction is None:
            with _COMMAND_PORTS[self].transaction() as owned:
                return self._reserve_with_transaction(pool_ref, reservation_ref, declared_units, envelope, body, owned)
        return self._reserve_with_transaction(pool_ref, reservation_ref, declared_units, envelope, body, transaction)

    def _reserve_with_transaction(self, pool_ref: ResourceRef, reservation_ref: ResourceRef, declared_units: int, envelope: CommandEnvelope, body: Mapping[str, Any], tx: Transaction) -> ReservationRecord:
        replay = self._replayed(envelope, RESERVATION_KIND)
        if replay is not None:
            return replay
        pool_identity = _COMMAND_PORTS[self].get_identity(pool_ref)
        if pool_identity is None:
            raise TargetMismatchError("limit pool identity is not admitted")
        pool = self._pool_from_identity(pool_identity)
        return self._reserve_in_transaction(pool, reservation_ref, declared_units, envelope, body, tx)

    def _reserve_in_transaction(self, pool: LimitPool, reservation_ref: ResourceRef, declared_units: int, envelope: CommandEnvelope, body: Mapping[str, Any], tx: Transaction) -> ReservationRecord:
        existing = tx.execute("SELECT payload_json FROM identities WHERE authority = ? AND kind = ? AND id = ?", (reservation_ref.authority, RESERVATION_KIND, reservation_ref.id)).fetchone()
        if existing is not None:
            raise ReservationExistsError("reservation identity already exists")
        held, used = self._pool_totals(tx, pool.ref)
        open_projected = 0
        rows = tx.execute("SELECT payload_json FROM identities WHERE authority = ? AND kind = ?", (_COMMAND_PORTS[self].authority, RESERVATION_KIND)).fetchall()
        for row in rows:
            payload = json.loads(row[0])
            if payload.get("record_type") == RESERVATION_KIND and payload.get("pool_ref") == pool.ref.to_dict() and payload.get("status") in (ReservationStatus.HELD.value, ReservationStatus.UNCERTAIN.value):
                open_projected += max(int(payload["declared_units"]), int(payload.get("actual_units", 0)))
        if held + declared_units > pool.capacity_units:
            raise CapacityExhaustedError("reusable capacity is exhausted")
        if used + open_projected + declared_units > pool.cumulative_allowance_units:
            raise AllowanceExhaustedError("cumulative allowance is exhausted")
        receipt = _COMMAND_PORTS[self].mutate(
            envelope,
            event_type="reservation.held",
            result_ref=ResourceRef(_COMMAND_PORTS[self].authority, RESERVATION_KIND, reservation_ref.id, "rev-1"),
            effects={**body, "version": 1, "overrun_units": 0},
            stream=LIMIT_STREAM,
            transaction=tx,
        )
        identity = _COMMAND_PORTS[self].get_identity(reservation_ref)
        if identity is None:
            raise LimitError("reservation admission did not produce an identity")
        return self._reservation_from_payload(identity, receipt, self._event_effects(receipt))

    def get_reservation(self, reservation_ref: ResourceRef) -> Optional[ReservationRecord]:
        stable = self._reservation_ref(reservation_ref)
        identity = _COMMAND_PORTS[self].get_identity(stable)
        return None if identity is None else self._reservation_from_payload(identity)

    def _transition(self, reservation: ReservationRecord, target_state: ReservationStatus, actual_units: int, *, logical_request_key: str, request_digest: Optional[str], actor: Optional[AuthenticatedActor], expected_revision: Any = _UNSET, expected_version: Any = _UNSET, edit_token: Optional[str] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None, transaction: Optional[Transaction]) -> ReservationRecord:
        body = {"record_type": RESERVATION_KIND, "pool_ref": _ref_dict(reservation.pool_ref), "declared_units": reservation.declared_units, "status": target_state.value, "actual_units": actual_units, "charged_units": actual_units if target_state in (ReservationStatus.CONSUMED, ReservationStatus.RELEASED) else reservation.charged_units}
        selected_actor = _actor(actor)
        selected_revision = reservation.ref.revision if expected_revision is _UNSET else expected_revision
        selected_version = reservation.version if expected_version is _UNSET else expected_version
        digest = self._digest("limit." + target_state.value, reservation.ref, selected_actor, logical_request_key, body, request_digest, expected_revision=selected_revision, expected_version=selected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id)
        envelope = self._envelope("limit." + target_state.value, reservation.ref, selected_actor, logical_request_key, digest, body, expected_revision=selected_revision, expected_version=selected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id)
        replay = self._replayed(envelope, RESERVATION_KIND)
        if replay is not None:
            return replay
        if target_state == ReservationStatus.UNCERTAIN and reservation.status not in (ReservationStatus.HELD,):
            raise ReservationStateError("only a held reservation can become uncertain")
        if target_state == ReservationStatus.CONSUMED and reservation.status not in (ReservationStatus.HELD, ReservationStatus.UNCERTAIN):
            raise ReservationStateError("only held or uncertain reservations can be consumed")
        if target_state == ReservationStatus.RELEASED and reservation.status not in (ReservationStatus.HELD, ReservationStatus.UNCERTAIN):
            raise ReservationStateError("only held or uncertain reservations can be released")
        effect = {**body, "version": reservation.version + 1, "overrun_units": max(0, actual_units - reservation.declared_units)}
        receipt = _COMMAND_PORTS[self].mutate(
            envelope,
            event_type="reservation." + target_state.value,
            result_ref=ResourceRef(_COMMAND_PORTS[self].authority, RESERVATION_KIND, reservation.ref.id, "rev-{}".format(reservation.version + 1)),
            effects=effect,
            stream=LIMIT_STREAM,
            transaction=transaction,
        )
        identity = _COMMAND_PORTS[self].get_identity(reservation.ref)
        if identity is None:
            raise LimitError("reservation transition did not produce an identity")
        return self._reservation_from_payload(identity, receipt, self._event_effects(receipt))

    def mark_uncertain(self, reservation: ReservationRecord, actual_units: int = 0, *, logical_request_key: str, request_digest: Optional[str] = None, actor: Optional[AuthenticatedActor] = None, expected_revision: Any = _UNSET, expected_version: Any = _UNSET, edit_token: Optional[str] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None, transaction: Optional[Transaction] = None) -> ReservationRecord:
        return self._transition(reservation, ReservationStatus.UNCERTAIN, _units(actual_units, "actual_units"), logical_request_key=logical_request_key, request_digest=request_digest, actor=actor, expected_revision=expected_revision, expected_version=expected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id, transaction=transaction)

    def settle(self, reservation: ReservationRecord, actual_units: int, *, logical_request_key: str, request_digest: Optional[str] = None, actor: Optional[AuthenticatedActor] = None, expected_revision: Any = _UNSET, expected_version: Any = _UNSET, edit_token: Optional[str] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None, transaction: Optional[Transaction] = None) -> ReservationRecord:
        return self._transition(reservation, ReservationStatus.CONSUMED, _units(actual_units, "actual_units"), logical_request_key=logical_request_key, request_digest=request_digest, actor=actor, expected_revision=expected_revision, expected_version=expected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id, transaction=transaction)

    def release(self, reservation: ReservationRecord, *, actual_units: int = 0, logical_request_key: str, request_digest: Optional[str] = None, actor: Optional[AuthenticatedActor] = None, expected_revision: Any = _UNSET, expected_version: Any = _UNSET, edit_token: Optional[str] = None, correlation_id: Optional[str] = None, causation_id: Optional[str] = None, transaction: Optional[Transaction] = None) -> ReservationRecord:
        return self._transition(reservation, ReservationStatus.RELEASED, _units(actual_units, "actual_units"), logical_request_key=logical_request_key, request_digest=request_digest, actor=actor, expected_revision=expected_revision, expected_version=expected_version, edit_token=edit_token, correlation_id=correlation_id, causation_id=causation_id, transaction=transaction)


ReservationLedger = LimitService
Limits = LimitService


__all__ = [
    "LIMIT_KIND", "LIMIT_SCHEMA_REVISION", "LIMIT_STREAM", "RESERVATION_KIND",
    "LimitError", "CapacityExhaustedError", "AllowanceExhaustedError",
    "ReservationStateError", "ReservationExistsError", "ReservationStatus",
    "LimitPool", "ReservationRecord", "LimitService", "ReservationLedger", "Limits",
]
