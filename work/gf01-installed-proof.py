"""Fresh installed-wheel probe for GF01_PUBLIC_MUTATION_AND_ADMISSION."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import tempfile

from herzchen.contracts import AuthenticatedActor, CommandEnvelope, ResourceRef, TransactionContext, canonical_json
from herzchen.extensions import DEFAULT_CATALOG, PROTOCOL_NAMESPACE, DefinitionCatalog, ExtensionCommandService
from herzchen.extensions import commands as extension_commands
from herzchen.extensions import model as extension_model
from herzchen.kernel import MutationAdmissionError, Store
from herzchen.kernel import store as kernel_store


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def altered_catalog(**changes):
    altered = replace(DEFAULT_CATALOG.get(PROTOCOL_NAMESPACE), **changes)
    definitions = tuple(altered if item.namespace == PROTOCOL_NAMESPACE else item for item in DEFAULT_CATALOG.definitions)
    return DefinitionCatalog(definitions, DEFAULT_CATALOG.roles)


evidence = {
    "python": __import__("sys").version.split()[0],
    "environment": {
        "PYTHONPATH": __import__("os").environ.get("PYTHONPATH"),
        "PYTHONHOME": __import__("os").environ.get("PYTHONHOME"),
    },
    "origins": {
        "kernel_store": inspect.getfile(kernel_store),
        "extension_commands": inspect.getfile(extension_commands),
        "extension_model": inspect.getfile(extension_model),
    },
}

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "gf01.sqlite"
    owner = Store.create(path, authority="dat-store")
    subject = ResourceRef("dat-store", "work.task", "task-1", "seed-1")
    owner.put_identity(subject, {"record_type": "work.task", "metadata": {"sibling": {"keep": True}}}, version=1)
    service = ExtensionCommandService(owner)
    consumer = owner.consumer()

    forbidden = ("path", "connection", "transaction", "put_identity", "revise_identity", "append_event", "mutate", "register_domain")
    evidence["ordinary_consumer"] = {name: hasattr(consumer, name) for name in forbidden}

    spoof_fields = {"choice": "hold", "reason": "spoof"}
    spoof_context = TransactionContext(
        AuthenticatedActor("test-auth", "non-owner-actor", "credential"),
        "owner-spoof",
        digest(spoof_fields),
        expected_revision="seed-1",
        expected_version=1,
    )
    before_spoof = dict(consumer.snapshot_counts())
    try:
        service.set(subject, PROTOCOL_NAMESPACE, spoof_fields, spoof_context, owner="dat.protocol-owner")
    except Exception as exc:
        spoof_error = type(exc).__name__
    else:
        raise AssertionError("non-owner actor unexpectedly committed")
    after_spoof = dict(consumer.snapshot_counts())
    evidence["non_owner"] = {"error": spoof_error, "before": before_spoof, "after": after_spoof, "unchanged": before_spoof == after_spoof}

    variants = {
        "schema": altered_catalog(schema={"type": "object", "additionalProperties": True}),
        "owner": altered_catalog(owner="attacker-owner"),
        "classification": altered_catalog(classification="open_annotation"),
        "writability": altered_catalog(writable=False),
    }
    rejected = {}
    for name, catalog in variants.items():
        try:
            ExtensionCommandService(owner, catalog=catalog)
        except Exception as exc:
            rejected[name] = type(exc).__name__
        else:
            raise AssertionError("altered catalog unexpectedly admitted: " + name)
    evidence["altered_catalogs"] = rejected

    invalid_payload = {"record_type": "unregistered"}
    invalid = CommandEnvelope(
        "unregistered.operation",
        "unregistered.v1",
        ResourceRef("dat-store", "unregistered.resource", "record-1"),
        TransactionContext(
            AuthenticatedActor("test-auth", "actor", "credential"),
            "unregistered",
            digest(invalid_payload),
            expected_version=0,
        ),
        invalid_payload,
    )
    before_invalid = dict(consumer.snapshot_counts())
    try:
        owner.mutate(invalid, event_type="unregistered.event")
    except MutationAdmissionError as exc:
        invalid_error = type(exc).__name__
    else:
        raise AssertionError("unregistered combination unexpectedly committed")
    after_invalid = dict(consumer.snapshot_counts())
    evidence["unregistered_combination"] = {"error": invalid_error, "before": before_invalid, "after": after_invalid, "unchanged": before_invalid == after_invalid}

    valid_fields = {"choice": "hold", "reason": "installed proof"}
    valid = service.set(
        subject,
        PROTOCOL_NAMESPACE,
        valid_fields,
        TransactionContext(
            AuthenticatedActor("dat-auth", "dat-handler", "dat-credential"),
            "valid-protocol",
            digest(valid_fields),
            expected_revision="seed-1",
            expected_version=1,
        ),
        owner="dat.protocol-owner",
    )
    receipt = valid["receipt"]
    evidence["valid"] = {
        "status": receipt.status.value,
        "event_ids": receipt.event_ids,
        "receipt_linked": consumer.get_receipt("valid-protocol") == receipt,
        "event_linked": tuple(event.event_id for event in consumer.list_events()) == receipt.event_ids,
        "sibling_preserved": valid["payload"]["metadata"]["sibling"] == {"keep": True},
    }
    domains = owner.registered_domains()
    owner.close()
    reopened = Store.open(path, authority="dat-store", expected_domains=domains)
    evidence["fresh_after"] = {
        "value": ExtensionCommandService(reopened).read(ResourceRef("dat-store", "work.task", "task-1"), PROTOCOL_NAMESPACE)["value"],
        "counts": dict(reopened.consumer().snapshot_counts()),
    }
    reopened.close()

print(json.dumps(evidence, sort_keys=True))
