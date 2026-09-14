"""GF01 proof for the installed public Store capability/admission boundary."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.kernel import ConsumerStore, MutationAdmissionError, Store, StoreAdmissionError
from herzchen.packs.authoring import (
    ManagedPack,
    ManagedPackAuthoringHandler,
    ManagedResource,
    ManagedSourceIdentity,
)


def _envelope(operation: str, kind: str, key: str = "gf01", *, schema: str = "fixture.v1") -> CommandEnvelope:
    payload = {"value": key}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return CommandEnvelope(
        operation,
        schema,
        ResourceRef("gf01-store", kind, "record-1"),
        TransactionContext(
            AuthenticatedActor("fixture-auth", "fixture-handler", "credential"),
            key,
            digest,
            expected_version=0,
        ),
        payload,
    )


def _contribution() -> DomainContribution:
    return DomainContribution(
        "fixture.domain",
        "1",
        "fixture-owner",
        ("fixture.record",),
        (),
        (),
        ("fixture.create",),
        ("fixture.created",),
        "fixture.v1",
        ("handler:tests.fixture-handler", "actor-authority:fixture-auth"),
    )


def test_ordinary_consumer_has_no_writer_connection_sql_or_direct_mutators(tmp_path):
    owner = Store.create(tmp_path / "consumer.sqlite", authority="gf01-store")
    try:
        consumer = owner.consumer()
        assert isinstance(consumer, ConsumerStore)
        assert consumer.authority == "gf01-store"
        for name in (
            "path",
            "connection",
            "transaction",
            "put_identity",
            "revise_identity",
            "append_event",
            "mutate",
            "put_reference",
            "register_domain",
        ):
            assert not hasattr(consumer, name), name
            with pytest.raises(AttributeError):
                getattr(consumer, name)

        # The raw writer object cannot be forged from a SQLite connection.  It
        # is acquired only with the host create/open owner operation.
        raw = sqlite3.connect(":memory:")
        try:
            with pytest.raises(StoreAdmissionError):
                Store(raw, None, ":memory:", "gf01-store")
        finally:
            raw.close()

        # Owner-only bootstrap methods remain on the sealed capability, not on
        # the ordinary consumer surface.
        assert all(hasattr(owner, name) for name in ("transaction", "put_identity", "revise_identity", "append_event", "mutate"))
        assert consumer.snapshot_counts() == {
            "identities": 0,
            "record_references": 0,
            "events": 0,
            "command_receipts": 0,
            "event_sequences": 0,
        }
    finally:
        owner.close()


@pytest.mark.parametrize(
    ("operation", "kind", "event_type", "schema"),
    (
        ("missing.create", "fixture.record", "fixture.created", "fixture.v1"),
        ("fixture.create", "missing.record", "fixture.created", "fixture.v1"),
        ("fixture.create", "fixture.record", "missing.created", "fixture.v1"),
        ("fixture.create", "fixture.record", "fixture.created", "other.v1"),
    ),
)
def test_unregistered_operation_resource_event_or_schema_rejects_before_durable_delta(tmp_path, operation, kind, event_type, schema):
    owner = Store.create(tmp_path / (key := operation.replace(".", "-") + kind.replace(".", "-") + event_type.replace(".", "-") + schema.replace(".", "-") + ".sqlite"), authority="gf01-store")
    try:
        owner.register_domain(_contribution())
        consumer = owner.consumer()
        before = dict(consumer.snapshot_counts())
        with pytest.raises(MutationAdmissionError):
            owner.mutate(_envelope(operation, kind, key, schema=schema), event_type=event_type)
        assert consumer.snapshot_counts() == before
        assert consumer.get_identity(ResourceRef("gf01-store", kind, "record-1")) is None
        assert consumer.get_receipt(key) is None
    finally:
        owner.close()


def test_registered_combination_commits_identity_event_receipt_and_reference_together(tmp_path):
    owner = Store.create(tmp_path / "admitted.sqlite", authority="gf01-store")
    try:
        owner.register_domain(_contribution())
        consumer = owner.consumer()
        before = dict(consumer.snapshot_counts())
        receipt = owner.mutate(_envelope("fixture.create", "fixture.record", "admitted"), event_type="fixture.created")
        after = dict(consumer.snapshot_counts())
        assert receipt.status.value == "committed"
        assert consumer.get_receipt("admitted") == receipt
        assert consumer.get_identity(ResourceRef("gf01-store", "fixture.record", "record-1")) is not None
        assert tuple(event.event_id for event in consumer.list_events()) == receipt.event_ids
        assert after["identities"] == before["identities"] + 1
        assert after["events"] == before["events"] + 1
        assert after["command_receipts"] == before["command_receipts"] + 1
        assert after["event_sequences"] == before["event_sequences"] + 1
    finally:
        owner.close()


def test_non_owner_actor_cannot_use_an_admitted_combination(tmp_path):
    owner = Store.create(tmp_path / "actor-spoof.sqlite", authority="gf01-store")
    try:
        owner.register_domain(_contribution())
        consumer = owner.consumer()
        envelope = _envelope("fixture.create", "fixture.record", "actor-spoof")
        spoofed = CommandEnvelope(
            envelope.operation,
            envelope.schema_revision,
            envelope.target,
            TransactionContext(
                AuthenticatedActor("attacker-auth", "fixture-handler", "attacker-credential"),
                envelope.context.logical_request_key,
                envelope.context.request_digest,
                expected_version=0,
            ),
            envelope.payload,
        )
        before = dict(consumer.snapshot_counts())
        with pytest.raises(MutationAdmissionError):
            owner.mutate(spoofed, event_type="fixture.created")
        assert consumer.snapshot_counts() == before
        assert consumer.get_identity(envelope.target) is None
        assert consumer.get_receipt("actor-spoof") is None
    finally:
        owner.close()


def test_existing_pkg_handler_succeeds_through_explicit_admitted_port(tmp_path):
    pack_root = tmp_path / "pack"
    pack_root.mkdir()
    manifest = pack_root / "pack.yaml"
    manifest.write_text("{}", encoding="utf-8")
    source = ManagedSourceIdentity(
        "fixture-pack",
        "managed",
        "1" * 40,
        "2" * 64,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "3" * 64,
        str(pack_root),
        str(manifest),
    )
    content = b"bounded pack content\n"
    resource = ManagedResource(
        "skill.md",
        "skill",
        content,
        hashlib.sha256(content).hexdigest(),
        ResourceRef("astrid-managed", "managed_pack", "fixture-pack", "1" * 40),
    )
    pack = ManagedPack("fixture-pack", "1", source, {"schema_version": 2}, (resource,), (), ())
    declaration = DomainContribution(
        "pkg.managed-authoring",
        "1",
        "pkg",
        ("managed_pack",),
        (),
        (),
        ("pack.content.author",),
        ("managed_pack.content_authored",),
        "pkg-05.managed-pack.v1",
        (
            "handler:herzchen.packs.authoring.ManagedPackAuthoringHandler",
            "actor-authority:pkg-auth",
        ),
    )
    owner = Store.create(tmp_path / "pkg.sqlite", authority="gf01-store")
    try:
        owner.register_domain(declaration)
        result = ManagedPackAuthoringHandler(owner).author(
            pack,
            {"skill.md": "updated bounded content\n"},
            logical_request_key="pkg-author",
            actor=AuthenticatedActor("pkg-auth", "pack-owner", "credential"),
        )
        consumer = owner.consumer()
        assert result.receipt == consumer.get_receipt("pkg-author")
        assert result.receipt.event_ids == tuple(event.event_id for event in consumer.list_events())
        assert consumer.get_identity(result.snapshot_ref).payload["resources"]["skill.md"]
    finally:
        owner.close()
