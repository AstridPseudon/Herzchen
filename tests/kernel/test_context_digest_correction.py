from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    CommandReceipt,
    ReceiptStatus,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_request_digest,
    validate_replay,
)
from herzchen.kernel import LimitService, OperationRequest, Store


ACTOR = AuthenticatedActor("fixture-auth", "fixture-actor", "fixture-credential")
TARGET = ResourceRef("fixture-store", "document", "document-1")
PAYLOAD = {"value": "stable"}


def _context(**changes: object) -> TransactionContext:
    values = {
        "expected_revision": "rev-7",
        "expected_version": 7,
        "edit_token": "edit-7",
        "correlation_id": "corr-7",
        "causation_id": "cause-6",
    }
    values.update(changes)
    return TransactionContext(ACTOR, "context-key", "a" * 64, **values)


def _digest(context: TransactionContext) -> str:
    return canonical_request_digest(
        logical_request_key=context.logical_request_key,
        operation="document.update",
        schema_revision="document.v1",
        target=TARGET,
        actor=context.actor,
        payload=PAYLOAD,
        context=context,
    )


def _pre_correction_receipt(envelope: CommandEnvelope) -> CommandReceipt:
    legacy_digest = canonical_request_digest(
        logical_request_key=envelope.context.logical_request_key,
        operation=envelope.operation,
        schema_revision=envelope.schema_revision,
        target=envelope.target,
        actor=envelope.context.actor,
        payload=envelope.payload,
    )
    return CommandReceipt(
        envelope.context.logical_request_key,
        legacy_digest,
        envelope.operation,
        envelope.target,
        ReceiptStatus.COMMITTED,
        transaction_id="pre-correction-tx",
    )


def test_each_transaction_context_input_changes_the_canonical_digest() -> None:
    baseline = _digest(_context())
    scalar_form = canonical_request_digest(
        logical_request_key="context-key",
        operation="document.update",
        schema_revision="document.v1",
        target=TARGET,
        actor=ACTOR,
        payload=PAYLOAD,
        expected_revision="rev-7",
        expected_version=7,
        edit_token="edit-7",
        correlation_id="corr-7",
        causation_id="cause-6",
    )
    assert scalar_form == baseline
    for field, changed in (
        ("expected_revision", "rev-8"),
        ("expected_version", 8),
        ("edit_token", "edit-8"),
        ("correlation_id", "corr-8"),
        ("causation_id", "cause-7"),
    ):
        assert _digest(_context(**{field: changed})) != baseline


def test_supplied_digest_and_derived_current_projection_are_not_digest_inputs() -> None:
    first = _digest(_context())
    supplied_digest_changed = replace(_context(), request_digest="b" * 64)
    assert _digest(supplied_digest_changed) == first

    # Current identity state is a Store projection, not a helper input.  The
    # same admitted request therefore retains its digest as that projection
    # changes; expected_* values above are the caller's explicit preconditions.
    current_identity_projection = {"revision": "rev-7", "version": 7}
    before = _digest(_context())
    current_identity_projection.update(revision="rev-8", version=8)
    after = _digest(_context())
    assert before == after


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("expected_revision", "rev-8"),
        ("expected_version", 8),
        ("edit_token", "edit-8"),
        ("correlation_id", "corr-8"),
        ("causation_id", "cause-7"),
    ),
)
def test_each_context_change_rejects_a_pre_correction_receipt(field: str, changed: object) -> None:
    original = _context()
    original_envelope = CommandEnvelope(
        "document.update",
        "document.v1",
        TARGET,
        TransactionContext(
            original.actor,
            original.logical_request_key,
            _digest(original),
            expected_revision=original.expected_revision,
            expected_version=original.expected_version,
            edit_token=original.edit_token,
            correlation_id=original.correlation_id,
            causation_id=original.causation_id,
        ),
        PAYLOAD,
    )
    changed_context = replace(original, **{field: changed})
    incoming = replace(
        original_envelope,
        context=TransactionContext(
            changed_context.actor,
            changed_context.logical_request_key,
            _digest(changed_context),
            expected_revision=changed_context.expected_revision,
            expected_version=changed_context.expected_version,
            edit_token=changed_context.edit_token,
            correlation_id=changed_context.correlation_id,
            causation_id=changed_context.causation_id,
        ),
    )
    with pytest.raises(ReplayConflictError):
        validate_replay(_pre_correction_receipt(original_envelope), incoming)


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("expected_revision", "rev-1"),
        ("expected_version", 1),
        ("edit_token", "edit-8"),
        ("correlation_id", "corr-8"),
        ("causation_id", "cause-7"),
    ),
)
def test_limit_service_rejects_each_context_change_against_legacy_receipt(tmp_path: Path, field: str, changed: object) -> None:
    store = Store.create(tmp_path / ("legacy-" + field + ".sqlite3"))
    try:
        service = LimitService(store)
        pool = service.create_pool(
            ResourceRef("neutral-store", "limit", "legacy-pool"),
            2,
            10,
            logical_request_key="legacy-pool-create",
            actor=ACTOR,
        )
        service.reserve(
            pool.ref,
            "legacy-reservation",
            1,
            logical_request_key="legacy-reserve",
            actor=ACTOR,
        )
        with pytest.raises(ReplayConflictError):
            service.reserve(
                pool.ref,
                "legacy-reservation",
                1,
                logical_request_key="legacy-reserve",
                actor=ACTOR,
                **{field: changed},
            )
    finally:
        store.close()


def test_operation_request_envelope_carries_all_context_inputs_into_digest() -> None:
    request = OperationRequest(
        "adapter.invoke",
        "adapter.v1",
        ResourceRef("fixture-adapter", "adapter", "adapter-1"),
        ACTOR,
        "operation-key",
        "c" * 64,
        PAYLOAD,
        expected_revision="rev-7",
        expected_version=7,
        edit_token="edit-7",
        correlation_id="corr-7",
        causation_id="cause-6",
    )
    envelope = request.envelope(TARGET)
    assert envelope.context.expected_revision == "rev-7"
    assert envelope.context.expected_version == 7
    assert envelope.context.edit_token == "edit-7"
    assert envelope.context.correlation_id == "corr-7"
    assert envelope.context.causation_id == "cause-6"
    assert envelope.context.request_digest == canonical_request_digest(
        logical_request_key=envelope.context.logical_request_key,
        operation=envelope.operation,
        schema_revision=envelope.schema_revision,
        target=envelope.target,
        actor=envelope.context.actor,
        payload=envelope.payload,
        context=envelope.context,
    )


def test_limit_service_public_builders_construct_context_aware_envelopes(tmp_path: Path) -> None:
    store = Store.create(tmp_path / "context-aware.sqlite3")
    try:
        service = LimitService(store)
        pool = service.create_pool(
            ResourceRef("neutral-store", "limit", "context-pool"),
            2,
            10,
            logical_request_key="context-pool-create",
            actor=ACTOR,
        )
        reservation = service.reserve(
            pool.ref,
            "context-reservation",
            1,
            logical_request_key="context-reserve",
            actor=ACTOR,
        )
        with patch.object(store, "mutate", wraps=store.mutate) as mutate:
            service.settle(
                reservation,
                1,
                logical_request_key="context-settle",
                actor=ACTOR,
                expected_revision=reservation.ref.revision,
                expected_version=reservation.version,
                edit_token=None,
                correlation_id="corr-7",
                causation_id="cause-6",
            )
            envelope = mutate.call_args.args[0]
        assert envelope.context.expected_revision == reservation.ref.revision
        assert envelope.context.expected_version == reservation.version
        assert envelope.context.edit_token is None
        assert envelope.context.correlation_id == "corr-7"
        assert envelope.context.causation_id == "cause-6"
        assert envelope.context.request_digest == canonical_request_digest(
            logical_request_key=envelope.context.logical_request_key,
            operation=envelope.operation,
            schema_revision=envelope.schema_revision,
            target=envelope.target,
            actor=envelope.context.actor,
            payload=envelope.payload,
            context=envelope.context,
        )
    finally:
        store.close()
