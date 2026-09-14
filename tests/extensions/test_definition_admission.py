"""GF01 typed definition digest and authenticated protocol-owner proof."""

from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext, canonical_json
from herzchen.extensions import (
    DEFAULT_CATALOG,
    OPEN_NAMESPACE,
    PROTOCOL_NAMESPACE,
    DefinitionCatalog,
    ExtensionCommandService,
    ExtensionError,
    OwnerRequiredError,
)
from herzchen.kernel import Store


def _context(actor: AuthenticatedActor, key: str, value, *, version: int = 1, revision: str = "seed-1") -> TransactionContext:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return TransactionContext(actor, key, digest, expected_version=version, expected_revision=revision)


def _catalog_with_protocol(**changes) -> DefinitionCatalog:
    altered = replace(DEFAULT_CATALOG.get(PROTOCOL_NAMESPACE), **changes)
    definitions = tuple(altered if item.namespace == PROTOCOL_NAMESPACE else item for item in DEFAULT_CATALOG.definitions)
    return DefinitionCatalog(definitions, DEFAULT_CATALOG.roles)


@pytest.fixture()
def admitted(tmp_path):
    owner = Store.create(tmp_path / "extensions.sqlite", authority="dat-store")
    subject = ResourceRef("dat-store", "work.task", "task-1", "seed-1")
    owner.put_identity(subject, {"record_type": "work.task", "metadata": {"sibling": {"keep": True}}}, version=1)
    service = ExtensionCommandService(owner)
    try:
        yield owner, owner.consumer(), service, subject
    finally:
        owner.close()


def test_non_owner_actor_cannot_escalate_with_caller_supplied_owner(admitted):
    owner, consumer, service, subject = admitted
    actor = AuthenticatedActor("test-auth", "non-owner-actor", "credential")
    fields = {"choice": "hold", "reason": "attempted owner-string override"}
    before_record = consumer.get_identity(subject)
    before = dict(consumer.snapshot_counts())
    with pytest.raises(OwnerRequiredError):
        service.set(subject, PROTOCOL_NAMESPACE, fields, _context(actor, "owner-spoof", fields), owner="dat.protocol-owner")
    assert consumer.get_identity(subject) == before_record
    assert consumer.snapshot_counts() == before
    assert consumer.get_receipt("owner-spoof") is None
    assert consumer.list_events() == ()


@pytest.mark.parametrize(
    "catalog",
    (
        _catalog_with_protocol(schema={"type": "object", "additionalProperties": True}),
        _catalog_with_protocol(owner="attacker-owner"),
        _catalog_with_protocol(classification="open_annotation"),
        _catalog_with_protocol(writable=False),
    ),
    ids=("schema", "owner", "classification", "writability"),
)
def test_same_namespace_altered_complete_definition_is_rejected_before_use(admitted, catalog):
    owner, consumer, service, subject = admitted
    before_record = consumer.get_identity(subject)
    before = dict(consumer.snapshot_counts())
    with pytest.raises(ExtensionError):
        ExtensionCommandService(owner, catalog=catalog)
    # The rejected service is never constructed, so none of describe,
    # validation, query, or mutation can use its altered definition.
    assert service.describe(PROTOCOL_NAMESPACE)["owner"] == "dat.protocol-owner"
    assert service.query(subject, OPEN_NAMESPACE)["receipt"] is None
    assert consumer.get_identity(subject) == before_record
    assert consumer.snapshot_counts() == before


def test_catalog_changed_after_admission_is_rejected_before_describe_or_mutation(admitted):
    owner, consumer, _service, subject = admitted
    catalog = DefinitionCatalog(DEFAULT_CATALOG.definitions, DEFAULT_CATALOG.roles)
    service = ExtensionCommandService(owner, catalog=catalog)
    catalog._definitions[PROTOCOL_NAMESPACE] = replace(  # type: ignore[attr-defined]
        catalog.get(PROTOCOL_NAMESPACE),
        owner="attacker-owner",
    )
    before = dict(consumer.snapshot_counts())
    with pytest.raises(ExtensionError):
        service.describe(PROTOCOL_NAMESPACE)
    with pytest.raises(ExtensionError):
        service.set(
            subject,
            PROTOCOL_NAMESPACE,
            {"choice": "hold"},
            _context(
                AuthenticatedActor("dat-auth", "dat-handler", "credential"),
                "changed-after-admission",
                {"choice": "hold"},
            ),
            owner="dat.protocol-owner",
        )
    assert consumer.snapshot_counts() == before


def test_valid_bound_protocol_actor_and_open_extension_share_receipt_event_boundary(admitted):
    _owner, consumer, service, subject = admitted
    open_fields = {"note": "preserve sibling"}
    open_result = service.set(
        subject,
        OPEN_NAMESPACE,
        open_fields,
        _context(AuthenticatedActor("dat-auth", "writer", "credential"), "open", open_fields),
    )
    protocol_fields = {"choice": "hold", "reason": "authenticated DAT owner"}
    protocol_result = service.set(
        open_result["subject"],
        PROTOCOL_NAMESPACE,
        protocol_fields,
        _context(
            AuthenticatedActor("dat-auth", "dat-handler", "dat-credential"),
            "protocol",
            protocol_fields,
            version=open_result["version"],
            revision=open_result["revision"],
        ),
        owner="dat.protocol-owner",
    )
    assert protocol_result["payload"]["metadata"]["sibling"] == {"keep": True}
    assert protocol_result["value"] == protocol_fields
    for result in (open_result, protocol_result):
        receipt = result["receipt"]
        assert consumer.get_receipt(receipt.logical_request_key) == receipt
        assert len(receipt.event_ids) == 1
        assert any(event.event_id == receipt.event_ids[0] for event in consumer.list_events())
