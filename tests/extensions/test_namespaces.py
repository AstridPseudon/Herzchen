"""DAT-03 proof against the supplied FND-03 Store."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from herzchen.contracts import (
    AuthenticatedActor,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.extensions import (
    DEFAULT_CATALOG,
    MANAGED_NAMESPACE,
    OPEN_NAMESPACE,
    PROTOCOL_NAMESPACE,
    ExtensionCommandService,
    ExtensionError,
    ManagedFieldError,
    OwnerRequiredError,
    SchemaValidationError,
    domain_contribution,
)
from herzchen.kernel import Store, VersionConflictError


def subject(revision: str = "seed-1") -> ResourceRef:
    return ResourceRef("dat-store", "work.task", "task-1", revision)


def actor() -> AuthenticatedActor:
    return AuthenticatedActor("test-auth", "tester", "credential")


def context(key: str, value: object, *, version: int, revision: str) -> TransactionContext:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return TransactionContext(actor(), key, digest, expected_version=version, expected_revision=revision)


@pytest.fixture()
def environment(tmp_path: Path):
    path = tmp_path / "dat.sqlite"
    store = Store.create(path, authority="dat-store")
    stored = subject()
    store.put_identity(
        stored,
        {
            "managed_payload": {"identity": "owned-by-fnd", "version": 7, "archive": False},
            "metadata": {
                "annotation.sibling": {"keep": "yes"},
                MANAGED_NAMESPACE: {"identity": "protected", "primary": "fnd-owned"},
            },
        },
        version=1,
    )
    service = ExtensionCommandService(store)
    yield path, store, service, stored
    store.close()


def test_typed_contribution_and_definition_discovery_source_boundary(environment):
    _path, store, service, _stored = environment
    contribution = domain_contribution()
    assert contribution.domain_id == "dat.extensions"
    assert set(contribution.namespace_types) == {OPEN_NAMESPACE, PROTOCOL_NAMESPACE, MANAGED_NAMESPACE}
    assert contribution.operation_types[-2:] == ("dat.extensions.metadata.set", "dat.extensions.metadata.remove")
    assert contribution.composition_bindings == ("fnd-03.six-table-composition", "dat.content.document-roles")
    assert store.registered_domains() == (contribution,)
    catalog = service.describe()
    assert {item["namespace"] for item in catalog["definitions"]} == {OPEN_NAMESPACE, PROTOCOL_NAMESPACE, MANAGED_NAMESPACE}
    assert {item["role_id"] for item in catalog["document_roles"]} == {"candidate-manifest", "decision-manifest"}
    assert service.describe(OPEN_NAMESPACE)["schema_ref"]["revision"] == "1"


def test_open_set_read_query_and_sibling_preservation(environment):
    _path, store, service, stored = environment
    before_events = len(store.list_events())
    request = {"namespace": OPEN_NAMESPACE, "fields": {"new": {"unknown": [1, True]}}}
    result = service.set(stored, OPEN_NAMESPACE, request["fields"], context("open-set", request, version=1, revision="seed-1"))
    assert result["receipt"].status.value == "committed"
    assert len(result["receipt"].event_ids) == 1
    assert result["metadata"][OPEN_NAMESPACE]["new"] == {"unknown": [1, True]}
    assert result["metadata"]["annotation.sibling"] == {"keep": "yes"}
    assert result["payload"]["managed_payload"] == {"identity": "owned-by-fnd", "version": 7, "archive": False}
    assert len(store.list_events()) == before_events + 1

    fresh = service.read(result["subject"], OPEN_NAMESPACE)
    assert fresh["value"]["new"] == {"unknown": [1, True]}
    queried = service.query(result["subject"], OPEN_NAMESPACE, "new")
    assert queried["matches"][0]["value"] == {"unknown": [1, True]}
    assert queried["receipt"] is None


def test_narrow_remove_preserves_unrelated_namespaces(environment):
    _path, store, service, stored = environment
    first = service.set(stored, OPEN_NAMESPACE, {"remove_me": 1, "keep_me": 2}, context("remove-seed", {"x": 1}, version=1, revision="seed-1"))
    removed = service.remove(
        stored,
        OPEN_NAMESPACE,
        ("remove_me",),
        context("remove-one", {"field": "remove_me"}, version=first["version"], revision=first["revision"]),
    )
    assert "remove_me" not in removed["metadata"][OPEN_NAMESPACE]
    assert removed["metadata"][OPEN_NAMESPACE]["keep_me"] == 2
    assert removed["metadata"]["annotation.sibling"] == {"keep": "yes"}
    assert MANAGED_NAMESPACE in removed["metadata"]
    assert removed["receipt"].status.value == "committed"


def test_strict_misspelling_schema_rejection_has_no_delta(environment):
    _path, store, service, stored = environment
    before = store.get_identity(stored)
    events = len(store.list_events())
    with pytest.raises(SchemaValidationError):
        service.set(
            stored,
            PROTOCOL_NAMESPACE,
            {"choic": "accept"},
            context("bad-schema", {"choic": "accept"}, version=1, revision="seed-1"),
            owner="dat.protocol-owner",
        )
    after = store.get_identity(stored)
    assert after == before
    assert len(store.list_events()) == events


def test_managed_namespace_and_protected_annotation_fields_rejected(environment):
    _path, store, service, stored = environment
    before = store.get_identity(stored)
    events = len(store.list_events())
    for namespace, fields in (
        (MANAGED_NAMESPACE, {"identity": "forged"}),
        (OPEN_NAMESPACE, {"version": 99}),
        (OPEN_NAMESPACE, {"primary": True}),
        (OPEN_NAMESPACE, {"provenance": {"accepted": True}}),
        (OPEN_NAMESPACE, {"acceptance": "accepted"}),
    ):
        with pytest.raises(ManagedFieldError):
            service.set(stored, namespace, fields, context("managed-" + str(events) + namespace, fields, version=1, revision="seed-1"))
    assert store.get_identity(stored) == before
    assert len(store.list_events()) == events


def test_protocol_requires_registered_owner_and_validates_choice(environment):
    _path, store, service, stored = environment
    with pytest.raises(OwnerRequiredError):
        service.set(stored, PROTOCOL_NAMESPACE, {"choice": "accept"}, context("wrong-owner", {"choice": "accept"}, version=1, revision="seed-1"), owner="caller")
    result = service.set(
        stored,
        PROTOCOL_NAMESPACE,
        {"choice": "hold", "reason": "awaiting evidence"},
        context("protocol-ok", {"choice": "hold", "reason": "awaiting evidence"}, version=1, revision="seed-1"),
        owner="dat.protocol-owner",
    )
    assert result["value"] == {"choice": "hold", "reason": "awaiting evidence"}
    assert result["definition"]["owner"] == "dat.protocol-owner"
    assert result["definition"]["classification"] == "protocol"
    assert result["receipt"].status.value == "committed"


def test_same_key_replay_changed_digest_and_stale_write_are_atomic(environment):
    _path, store, service, stored = environment
    request = {"note": "one"}
    first = service.set(stored, OPEN_NAMESPACE, request, context("same-key", request, version=1, revision="seed-1"))
    events_after_first = tuple(store.list_events())
    replay = service.set(first["subject"], OPEN_NAMESPACE, request, context("same-key", request, version=1, revision="seed-1"))
    assert replay["receipt"] == first["receipt"]
    assert tuple(store.list_events()) == events_after_first

    changed = {"note": "changed"}
    with pytest.raises(ReplayConflictError):
        service.set(first["subject"], OPEN_NAMESPACE, changed, context("same-key", changed, version=1, revision="seed-1"))
    assert tuple(store.list_events()) == events_after_first
    assert store.get_identity(stored).payload["metadata"][OPEN_NAMESPACE] == request

    stale = {"another": True}
    with pytest.raises(VersionConflictError):
        service.set(ResourceRef("dat-store", "work.task", "task-1"), OPEN_NAMESPACE, stale, context("stale", stale, version=1, revision="seed-1"))
    assert tuple(store.list_events()) == events_after_first
    assert store.get_identity(stored).payload["metadata"][OPEN_NAMESPACE] == request


def test_restart_fresh_read_and_pinned_reference_semantics(environment):
    path, store, service, stored = environment
    result = service.set(stored, OPEN_NAMESPACE, {"persisted": "yes"}, context("restart", {"persisted": "yes"}, version=1, revision="seed-1"))
    current_ref = result["subject"]
    store.close()
    reopened = Store.open(path, authority="dat-store", expected_domains=(domain_contribution(),))
    restarted = ExtensionCommandService(reopened)
    fresh = restarted.read(current_ref, OPEN_NAMESPACE)
    assert fresh["value"] == {"persisted": "yes"}
    assert fresh["schema_ref"] == result["schema_ref"]
    assert fresh["subject"] == current_ref
    with pytest.raises(ExtensionError):
        restarted.read(ResourceRef("dat-store", "work.task", "task-1", "not-current"), OPEN_NAMESPACE)
    reopened.close()
