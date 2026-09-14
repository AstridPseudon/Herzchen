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
    canonical_request_digest,
    ContractError,
    ReplayConflictError,
)
from herzchen.kernel import ConsumerStore, MutationAdmissionError, Store, StoreAdmissionError
from herzchen.domains.work import contributions as work_contributions, register_work
from herzchen.packs.authoring import (
    ManagedPack,
    ManagedPackAuthoringHandler,
    ManagedResource,
    ManagedSourceIdentity,
    domain_contribution as pack_authoring_contribution,
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
        ("fixture.create", "fixture.revise"),
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


def test_store_replaces_caller_digest_and_rejects_changed_replay_semantics_without_delta(tmp_path):
    owner = Store.create(tmp_path / "canonical-replay.sqlite", authority="gf01-store")
    try:
        owner.register_domain(_contribution())
        consumer = owner.consumer()
        original = _envelope("fixture.create", "fixture.record", "canonical-replay")
        receipt = owner.mutate(original, event_type="fixture.created")
        assert receipt.request_digest == canonical_request_digest(
            logical_request_key=original.context.logical_request_key,
            operation=original.operation,
            schema_revision=original.schema_revision,
            target=original.target,
            actor=original.context.actor,
            payload=original.payload,
        )
        assert receipt.request_digest != original.context.request_digest

        actor = original.context.actor
        variants = (
            CommandEnvelope(
                original.operation,
                original.schema_revision,
                original.target,
                TransactionContext(actor, "canonical-replay", original.context.request_digest, expected_version=0),
                {"value": "changed"},
            ),
            CommandEnvelope(
                original.operation,
                original.schema_revision,
                ResourceRef("gf01-store", "fixture.record", "record-2"),
                TransactionContext(actor, "canonical-replay", original.context.request_digest, expected_version=0),
                original.payload,
            ),
            CommandEnvelope(
                "fixture.revise",
                original.schema_revision,
                original.target,
                TransactionContext(actor, "canonical-replay", original.context.request_digest, expected_version=0),
                original.payload,
            ),
            CommandEnvelope(
                original.operation,
                original.schema_revision,
                original.target,
                TransactionContext(
                    AuthenticatedActor("fixture-auth", "other-fixture-handler", "other-credential"),
                    "canonical-replay",
                    original.context.request_digest,
                    expected_version=0,
                ),
                original.payload,
            ),
        )
        before = dict(consumer.snapshot_counts())
        before_record = consumer.get_identity(original.target)
        for changed in variants:
            with pytest.raises(ReplayConflictError):
                owner.mutate(changed, event_type="fixture.created")
            assert consumer.snapshot_counts() == before
            assert consumer.get_identity(original.target) == before_record
            assert consumer.get_receipt("canonical-replay") == receipt
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


def test_wrk_handler_is_required_store_bound_and_preserves_foreign_actor(tmp_path):
    owner = Store.create(tmp_path / "wrk-handler.sqlite", authority="gf01-store")
    foreign_owner = Store.create(tmp_path / "foreign-handler.sqlite", authority="foreign-store")
    try:
        handler = register_work(owner)
        foreign_handler = register_work(foreign_owner)
        actor = AuthenticatedActor("dat-auth", "dat-worker", "dat-credential")
        payload = {"record_type": "work.project", "title": "handler proof"}
        target = ResourceRef("gf01-store", "work.project", "handler-proof")
        envelope = CommandEnvelope(
            "work.create", "work.v1", target,
            TransactionContext(actor, "wrk-handler", "a" * 64, expected_version=0),
            payload,
        )
        before = dict(owner.consumer().snapshot_counts())
        for fake in (None, "wrk", foreign_handler):
            with pytest.raises(MutationAdmissionError):
                owner.mutate(envelope, event_type="work.created", _handler=fake)
            assert owner.consumer().snapshot_counts() == before
        with pytest.raises(MutationAdmissionError):
            handler.mutate(envelope, event_type="work.revised")
        assert owner.consumer().snapshot_counts() == before

        receipt = handler.mutate(envelope, event_type="work.created")
        event = owner.consumer().list_events()[0]
        assert receipt.event_ids == (event.event_id,)
        assert event.actor == actor
        assert owner.consumer().get_identity(target) is not None
        with pytest.raises(Exception):
            owner.register_domain(work_contributions()[0])
    finally:
        owner.close()
        foreign_owner.close()


def test_wrk_shared_event_identity_is_deliberate_and_foreign_duplicate_is_rejected(tmp_path):
    owner = Store.create(tmp_path / "wrk-event-identity.sqlite", authority="gf01-store")
    try:
        register_work(owner)
        # Assignment reports own work.report.appended. Batch reports use the
        # distinct work.project-report.appended identity.
        declared = {event for item in work_contributions() for event in item.event_types}
        assert "work.report.appended" in declared
        assert "work.project-report.appended" in declared
        duplicate = DomainContribution(
            "fixture.duplicate-work-event", "1", "fixture-owner",
            ("fixture.report",), (), (), ("fixture.report.append",),
            ("work.report.appended",), "fixture.report.v1", (),
        )
        before = owner.consumer().snapshot_counts()
        with pytest.raises(ContractError, match="duplicate event type identity"):
            owner.register_domain(duplicate)
        assert owner.consumer().snapshot_counts() == before
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
    declaration = pack_authoring_contribution()
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
