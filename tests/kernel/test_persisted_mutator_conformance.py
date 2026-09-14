"""Focused effect/replay/rejection/restart proof for every GF01 port."""

from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.kernel import MutationAdmissionError, Store

from .gf01_mutator_inventory import MUTATOR_INVENTORY, descriptors, mutation_ports


DESCRIPTORS = {descriptor.domain_id: descriptor for descriptor in descriptors()}


def _envelope(row, key: str, *, target_id: str = "record", payload=None, context=None):
    schema, operation, resource, _ = row.mutation_port.split("|")
    descriptor = DESCRIPTORS[row.domain_id]
    kind = descriptor.resource_types[0] if resource == "*" else resource
    target = ResourceRef("inventory", kind, target_id)
    body = {"mutation_port": row.mutation_port, "value": "original"} if payload is None else payload
    actor = AuthenticatedActor("inventory-auth", row.domain_id, "credential")
    base = TransactionContext(actor, key, hashlib.sha256(canonical_json(body).encode()).hexdigest(), expected_version=0)
    return CommandEnvelope(operation, schema, target, base if context is None else context, body)


def _counts(reader):
    return dict(reader.snapshot_counts())


def _assert_unchanged(reader, expected):
    assert _counts(reader) == expected


def test_inventory_is_bijective_complete_and_declares_aggregate_children():
    descriptor_ports = {
        port for descriptor in descriptors() for port in mutation_ports(descriptor)
    }
    rows = {row.mutation_port: row for row in MUTATOR_INVENTORY}
    assert len(MUTATOR_INVENTORY) == len(rows) == len(descriptor_ports) == 77
    assert set(rows) == descriptor_ports
    assert all(row.supported_entry_point.startswith("herzchen.") for row in rows.values())
    assert all(row.persisted_delta == {
        "identities": 1, "record_references": 2, "events": 1,
        "command_receipts": 1, "event_sequences": 1,
    } for row in rows.values())
    aggregate_operations = {
        "actor.open", "open", "finish", "work.project-sheet.apply",
        "work.project.create", "assessment.run", "assessment.correction.create",
        "dat.content.document.create", "dat.content.revision.append",
    }
    assert aggregate_operations == {
        row.mutation_port.split("|")[1] for row in rows.values() if row.aggregate_child_effects
    }


@pytest.mark.parametrize("row", MUTATOR_INVENTORY, ids=lambda row: row.mutation_port)
def test_each_persisted_mutation_port_effect_replay_rejection_rollback_and_restart(tmp_path, row):
    descriptor = DESCRIPTORS[row.domain_id]
    path = tmp_path / (hashlib.sha256(row.mutation_port.encode()).hexdigest() + ".sqlite")
    owner = Store.create(path, authority="inventory")
    handler = owner.register_domain_handler((descriptor,))
    reader = owner.consumer()
    envelope = _envelope(row, "request")
    event_type = row.mutation_port.rsplit("|", 1)[1]

    before = _counts(reader)
    receipt = handler.mutate(envelope, event_type=event_type, effects={"mutation_port": row.mutation_port})
    after = _counts(reader)
    assert {name: after[name] - before[name] for name in after} == row.persisted_delta
    identity = reader.get_identity(envelope.target)
    assert identity is not None and identity.payload == envelope.payload and identity.version == 1
    events = reader.list_events()
    assert receipt.event_ids == tuple(event.event_id for event in events)
    assert len(events) == 1 and receipt.transaction_id
    assert reader.get_receipt("request") == receipt
    assert reader.get_reference(envelope.target) == envelope.target
    assert reader.get_reference(receipt.result_ref) == receipt.result_ref

    advanced = owner.revise_identity(
        identity.ref, {"mutation_port": row.mutation_port, "value": "advanced"},
        revision="rev-2", expected_revision="rev-1", expected_version=1,
    )
    advanced_counts = _counts(reader)
    assert handler.mutate(envelope, event_type=event_type) == receipt
    _assert_unchanged(reader, advanced_counts)
    assert reader.get_identity(envelope.target) == advanced

    original_context = envelope.context
    variants = (
        replace(envelope, target=ResourceRef("inventory", envelope.target.kind, "changed-target")),
        replace(envelope, payload={"mutation_port": row.mutation_port, "value": "changed"}),
        replace(envelope, context=replace(original_context, actor=AuthenticatedActor("other-auth", "other-actor", "other-credential"))),
        replace(envelope, context=replace(original_context, expected_version=1)),
        replace(envelope, context=replace(original_context, expected_revision="rev-2")),
        replace(envelope, context=replace(original_context, edit_token="changed-token")),
        replace(envelope, context=replace(original_context, correlation_id="changed-correlation")),
        replace(envelope, context=replace(original_context, causation_id="changed-causation")),
    )
    for changed in variants:
        with pytest.raises(ReplayConflictError):
            handler.mutate(changed, event_type=event_type)
        _assert_unchanged(reader, advanced_counts)
        assert reader.get_identity(envelope.target) == advanced

    wrongs = (
        (replace(envelope, operation="unregistered.operation"), event_type),
        (replace(envelope, schema_revision="unregistered.v1"), event_type),
        (replace(envelope, target=ResourceRef("inventory", "unregistered.resource", "record")), event_type),
        (envelope, "unregistered.event"),
    )
    for changed, changed_event in wrongs:
        with pytest.raises(MutationAdmissionError):
            handler.mutate(changed, event_type=changed_event)
        _assert_unchanged(reader, advanced_counts)

    rollback_envelope = _envelope(row, "rollback", target_id="rollback")
    with pytest.raises(RuntimeError, match="forced rollback"):
        with owner.transaction() as tx:
            handler.mutate(rollback_envelope, event_type=event_type, transaction=tx)
            raise RuntimeError("forced rollback")
    _assert_unchanged(reader, advanced_counts)
    assert reader.get_identity(rollback_envelope.target) is None
    assert reader.get_receipt("rollback") is None

    owner.close()
    reopened = Store.open(path, authority="inventory", expected_domains=(descriptor,))
    try:
        restarted = reopened.consumer()
        assert restarted.get_identity(envelope.target) == advanced
        assert restarted.get_receipt("request") == receipt
        assert tuple(event.event_id for event in restarted.list_events()) == receipt.event_ids
        assert restarted.get_reference(receipt.result_ref) == receipt.result_ref
        replay_handler = reopened.domain_handler((descriptor,))
        restart_counts = _counts(restarted)
        assert replay_handler.mutate(envelope, event_type=event_type) == receipt
        _assert_unchanged(restarted, restart_counts)
    finally:
        reopened.close()
