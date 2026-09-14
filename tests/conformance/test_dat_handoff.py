"""DAT-06 vertical conformance through the shipped neutral public APIs.

The probe is deliberately executable evidence rather than a fixture-shape
check.  It uses WorkGraph, the supplied FND Store, DAT content/packet APIs,
and the namespaced extension service on task-shaped, shot-shaped, document,
and neutral assignment-shaped records.  The shot and assignment records are
contract fixtures; they do not represent an Astrid adapter or product state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional

import pytest

from herzchen.content import (
    ContentCommandHandler,
    ContentDocument,
    ContentRevision,
    DocumentAssociation,
)
from herzchen.content.model import revision_identity
from herzchen.content.packets import (
    AccessDeniedError,
    ContextPacketService,
    PacketInput,
    VisibilityContext,
    domain_contribution as packet_contribution,
)
from herzchen.contracts import (
    AuthenticatedActor,
    ReferenceBinding,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.domains.work import WorkGraph
from herzchen.extensions import (
    MANAGED_NAMESPACE,
    OPEN_NAMESPACE,
    PROTOCOL_NAMESPACE,
    ExtensionCommandService,
    ManagedFieldError,
    OwnerRequiredError,
    SchemaValidationError,
    domain_contribution as extension_contribution,
)
from herzchen.kernel import (
    SCHEMA_FINGERPRINT,
    SCHEMA_REVISION,
    Store,
    VersionConflictError,
)
from herzchen.content import domain_contribution as content_contribution
from herzchen.domains.work import register_work

try:  # The package harness exposes these as the planned elegance inputs.
    from fixtures.definition_catalog import build_definition_catalog
    from fixtures.operating_context import build_operating_context_cases
except ModuleNotFoundError:  # pragma: no cover - useful for direct package use.
    from conformance.fixtures.definition_catalog import build_definition_catalog
    from conformance.fixtures.operating_context import build_operating_context_cases


AUTHORITY = "dat-store"
ACTOR = AuthenticatedActor("dat-auth", "dat-worker", "dat-credential")
SCOPE = ResourceRef(AUTHORITY, "work.project", "dat06-scope")
CONTENT_SCHEMA_REVISION = "dat-content.v1"
EXTENSION_SCHEMA_REVISION = "dat.extensions.v1"
WORK_SCHEMA_REVISION = "work.v1"


def _plain(value: Any) -> Any:
    """Use the contract serializer for all exported evidence values."""

    return json.loads(canonical_json(value))


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _context(key: str, value: Any, *, version: int, revision: Optional[str]) -> TransactionContext:
    return TransactionContext(
        ACTOR,
        key,
        _digest(value),
        expected_version=version,
        expected_revision=revision,
    )


def _identity_snapshot(store: Store, reference: ResourceRef) -> Any:
    return _plain(store.get_identity(ResourceRef(reference.authority, reference.kind, reference.id)))


def _receipt(value: Any) -> Any:
    return None if value is None else _plain(value)


def _event_evidence(store: Store, receipts: Mapping[str, Any]) -> dict[str, Any]:
    events = {event.event_id: _plain(event) for event in store.list_events()}
    return {
        label: {
            "receipt": _receipt(receipt),
            "events": [events[event_id] for event_id in receipt.event_ids],
        }
        for label, receipt in receipts.items()
    }


def _register_domains(store: Store) -> tuple[Any, ...]:
    # Registration is performed through the common FND domain registry.  The
    # sorted order is also the order required by Store.open admission.
    register_work(store)
    for descriptor in (content_contribution(), packet_contribution(), extension_contribution()):
        store.register_domain(descriptor)
    return store.registered_domains()


def _run_probe(db_path: Path) -> dict[str, Any]:
    store = Store.create(db_path, authority=AUTHORITY)
    contributions = _register_domains(store)
    graph = WorkGraph(store, actor=ACTOR)
    metadata = ExtensionCommandService(store)
    content = ContentCommandHandler(store)
    packets = ContextPacketService(store)
    receipts: dict[str, Any] = {}

    try:
        # WorkGraph supplies the real task-shaped graph read/modify/fresh-read.
        project = graph.create_project(
            title="DAT-06 conformance project",
            outcome="exercise shared data extension rails",
            logical_request_key="dat06-project-create",
        )
        receipts["project_create"] = store.get_receipt("dat06-project-create")
        task = graph.create_task(
            project,
            title="DAT-06 task-shaped fixture",
            fields={"assignment": "assignment-dat06", "unrelated": {"keep": True}},
            logical_request_key="dat06-task-create",
        )
        receipts["task_create"] = store.get_receipt("dat06-task-create")
        task_before = graph.get(task.ref)
        task_after = graph.revise(
            task.ref,
            fields={
                "assignment": "assignment-dat06",
                "unrelated": {"keep": True},
                "changed_by": "public-work-graph",
            },
            logical_request_key="dat06-task-revise",
        )
        receipts["task_revise"] = store.get_receipt("dat06-task-revise")
        task_fresh = graph.get(task_after.ref)
        assert task_fresh.ref == task_after.ref
        assert task_fresh.payload["fields"]["unrelated"] == {"keep": True}

        # These are neutral contract identities, not product adapters.  The
        # assignment shape is admitted by the public FND identity surface;
        # WorkGraph intentionally exposes no WorkKind.ASSIGNMENT.
        shot = ResourceRef(AUTHORITY, "work.task", "shot-dat06", "seed-1")
        assignment = ResourceRef(AUTHORITY, "wrk.assignment", "assignment-dat06", "seed-1")
        seed_payload = {
            "record_type": "work.task",
            "managed_payload": {
                "owner": "fnd",
                "primary_state": "fnd-owned",
                "provenance": {"source": "neutral-fixture"},
                "acceptance": {"status": "pending"},
            },
            "metadata": {
                "annotation.sibling": {"keep": "seed"},
                MANAGED_NAMESPACE: {
                    "identity": "fnd-owned",
                    "primary": "fnd-owned",
                    "provenance": "fnd-owned",
                    "acceptance": "fnd-owned",
                },
            },
        }
        store.put_identity(shot, dict(seed_payload, fixture_shape="shot"), version=1)
        store.put_identity(
            assignment,
            dict(seed_payload, fixture_shape="assignment", task=task_after.ref),
            version=1,
        )
        shot_before = _identity_snapshot(store, shot)
        assignment_before = _identity_snapshot(store, assignment)

        definitions = {
            "all": _plain(metadata.describe()),
            "task": _plain(metadata.describe(resource_kind=task_after.ref.kind)),
            "shot": _plain(metadata.describe(resource_kind=shot.kind)),
            "assignment": _plain(metadata.describe(resource_kind=assignment.kind)),
            "candidate_role": _plain(metadata.describe_role("candidate-manifest")),
            "decision_role": _plain(metadata.describe_role("decision-manifest")),
        }
        # Execute, rather than merely validate, the two package elegance data
        # inputs through actual DAT APIs below.
        elegance_inputs = {
            "context_fixture": _plain(build_operating_context_cases()),
            "definition_fixture": _plain(build_definition_catalog()),
            "actual_context_surface": "ContextPacketService",
            "actual_definition_surface": "ExtensionCommandService",
        }

        # Invalid owner/schema/protected writes must leave both state and the
        # common event stream unchanged.
        invalid_before_state = _identity_snapshot(store, shot)
        invalid_before_events = len(store.list_events())
        invalid_cases = (
            (
                "wrong_owner",
                OwnerRequiredError,
                task_after.ref,
                PROTOCOL_NAMESPACE,
                {"choice": "accept"},
                "wrong-owner",
                None,
            ),
            (
                "schema_typo",
                SchemaValidationError,
                task_after.ref,
                PROTOCOL_NAMESPACE,
                {"choic": "accept"},
                "schema-typo",
                "dat.protocol-owner",
            ),
            (
                "managed_namespace",
                ManagedFieldError,
                shot,
                MANAGED_NAMESPACE,
                {"identity": "forged"},
                "managed-namespace",
                None,
            ),
            (
                "protected_primary",
                ManagedFieldError,
                shot,
                OPEN_NAMESPACE,
                {"primary": "promoted"},
                "protected-primary",
                None,
            ),
            (
                "protected_provenance",
                ManagedFieldError,
                shot,
                OPEN_NAMESPACE,
                {"provenance": {"source": "forged"}},
                "protected-provenance",
                None,
            ),
            (
                "protected_acceptance",
                ManagedFieldError,
                shot,
                OPEN_NAMESPACE,
                {"acceptance": "accepted"},
                "protected-acceptance",
                None,
            ),
        )
        rejection_evidence: dict[str, Any] = {}
        for label, error_type, subject, namespace, fields, key, owner in invalid_cases:
            before_state = _identity_snapshot(store, subject)
            before_events = len(store.list_events())
            if subject == task_after.ref:
                subject_version, subject_revision = task_after.version, task_after.revision
            else:
                subject_version, subject_revision = 1, "seed-1"
            try:
                metadata.set(
                    subject,
                    namespace,
                    fields,
                    _context(key, fields, version=subject_version, revision=subject_revision),
                    owner=owner,
                )
            except error_type as exc:
                rejection_evidence[label] = {"error": type(exc).__name__, "message": str(exc)}
            else:  # pragma: no cover - the assertion is the conformance proof.
                raise AssertionError(f"invalid case unexpectedly committed: {label}")
            assert _identity_snapshot(store, subject) == before_state
            assert len(store.list_events()) == before_events

        shot_fields = {"color": "blue", "future_annotation": {"retain": [1, True]}}
        shot_metadata = metadata.set(
            shot,
            OPEN_NAMESPACE,
            shot_fields,
            _context("dat06-shot-metadata", shot_fields, version=1, revision="seed-1"),
        )
        receipts["shot_metadata"] = shot_metadata["receipt"]
        shot_fresh = metadata.read(shot_metadata["subject"], OPEN_NAMESPACE)
        shot_query = metadata.query(shot_metadata["subject"], OPEN_NAMESPACE, "color", equals="blue")
        assert shot_fresh["value"] == shot_fields
        assert shot_fresh["metadata"]["annotation.sibling"] == {"keep": "seed"}
        assert shot_query["matches"][0]["value"] == "blue"

        task_fields = {"note": "task annotation", "unknown": {"survives": True}}
        task_metadata = metadata.set(
            task_after.ref,
            OPEN_NAMESPACE,
            task_fields,
            _context("dat06-task-metadata", task_fields, version=task_after.version, revision=task_after.revision),
        )
        receipts["task_metadata"] = task_metadata["receipt"]
        task_protocol = {"choice": "hold", "reason": "fixture proof", "profile": "worker_normal"}
        protocol_result = metadata.set(
            task_metadata["subject"],
            PROTOCOL_NAMESPACE,
            task_protocol,
            _context("dat06-task-protocol", task_protocol, version=task_metadata["version"], revision=task_metadata["revision"]),
            owner="dat.protocol-owner",
        )
        receipts["task_protocol"] = protocol_result["receipt"]
        assert metadata.query(protocol_result["subject"], OPEN_NAMESPACE, "unknown")["matches"][0]["value"] == {"survives": True}

        assignment_fields = {"owner_hint": "worker_normal", "assignment_note": "neutral fixture"}
        assignment_metadata = metadata.set(
            assignment,
            OPEN_NAMESPACE,
            assignment_fields,
            _context("dat06-assignment-metadata", assignment_fields, version=1, revision="seed-1"),
        )
        receipts["assignment_metadata"] = assignment_metadata["receipt"]
        assignment_after = _identity_snapshot(store, assignment)
        assert assignment_after["payload"]["metadata"]["annotation.sibling"] == {"keep": "seed"}
        assert assignment_after["payload"]["metadata"][OPEN_NAMESPACE] == assignment_fields

        # Exact replay returns the original receipt and does not append an
        # event.  A changed input on the same key and a stale write are both
        # rejected before any state/event delta.
        events_after_assignment = tuple(store.list_events())
        replay = metadata.set(
            assignment_metadata["subject"],
            OPEN_NAMESPACE,
            assignment_fields,
            _context("dat06-assignment-metadata", assignment_fields, version=1, revision="seed-1"),
        )
        assert replay["receipt"] == assignment_metadata["receipt"]
        assert tuple(store.list_events()) == events_after_assignment
        changed_replay = {"owner_hint": "changed"}
        with pytest.raises(Exception) as changed_error:
            metadata.set(
                assignment_metadata["subject"],
                OPEN_NAMESPACE,
                changed_replay,
                _context("dat06-assignment-metadata", changed_replay, version=1, revision="seed-1"),
            )
        assert "changed request digest" in str(changed_error.value)
        assert tuple(store.list_events()) == events_after_assignment
        with pytest.raises(VersionConflictError):
            metadata.set(
                assignment_metadata["subject"],
                OPEN_NAMESPACE,
                {"stale": True},
                _context("dat06-assignment-stale", {"stale": True}, version=1, revision="seed-1"),
            )
        assert _identity_snapshot(store, assignment) == assignment_after
        assert tuple(store.list_events()) == events_after_assignment

        # One shared document identity has immutable revisions and three named
        # links.  Current and pinned bindings intentionally coexist.
        shared_ref = ResourceRef(AUTHORITY, "dat.content.document", "dat06-shared-doc")
        shared_doc = ContentDocument(shared_ref, "dat06-brief", "shared", "append", ACTOR.actor, SCOPE)
        shared_initial = ContentRevision(shared_ref, "rev-1", {"title": "before", "unknown": {"keep": True}}, ACTOR, initial=True)
        create_doc = content.build_create_document(
            _context("dat06-document-create", shared_initial.content, version=0, revision=None),
            shared_doc,
            shared_initial,
        )
        receipts["document_create"] = content.execute(create_doc)
        task_subject = ResourceRef(AUTHORITY, "work.task", task.id)
        shot_subject = ResourceRef(AUTHORITY, "work.task", shot.id)
        assignment_subject = ResourceRef(AUTHORITY, "wrk.assignment", assignment.id)
        task_link = DocumentAssociation(task_subject, "work.documents", "brief", ReferenceBinding(shared_ref))
        assignment_link = DocumentAssociation(assignment_subject, "work.documents", "brief", ReferenceBinding(shared_ref))
        receipts["link_task"] = content.execute(content.build_link(_context("dat06-link-task", {}, version=0, revision=None), task_link))
        receipts["link_assignment"] = content.execute(content.build_link(_context("dat06-link-assignment", {}, version=0, revision=None), assignment_link))

        shared_revision_2 = ContentRevision(
            shared_ref,
            "rev-2",
            {"title": "after", "unknown": {"keep": True}},
            ACTOR,
            parent_revision="rev-1",
        )
        receipts["document_append_2"] = content.execute(
            content.build_append_revision(
                _context("dat06-document-append-2", shared_revision_2.content, version=1, revision="rev-1"),
                shared_doc,
                shared_revision_2,
            )
        )
        pinned_shot_link = DocumentAssociation(
            shot_subject,
            "work.documents",
            "historical-brief",
            ReferenceBinding(shared_initial.ref, "pinned"),
        )
        receipts["link_shot_pinned"] = content.execute(
            content.build_link(_context("dat06-link-shot-pinned", {}, version=0, revision=None), pinned_shot_link)
        )

        packet = packets.create_packet(
            "dat06-assignment-packet",
            _context("dat06-packet-create", {}, version=0, revision=None),
            [PacketInput("shared_document", ReferenceBinding(shared_ref), purpose="assignment-input")],
            responsibility={
                "mandate": "inspect shared data extension",
                "outcome": "report conformance",
                "adopted_task": task.id,
                "adopted_protocol": "dat.extensions.protocol.choice.v1",
                "profile": "worker_normal",
                "criteria_refs": ["C05", "C06", "C33", "C35"],
                "scope_coverage": [SCOPE],
                "omissions": ["Astrid binding", "third specialist"],
                "supported_operations": ["read", "modify", "fresh-read"],
            },
            visibility="shared",
            maintainer=ACTOR.actor,
            authoring_scope=SCOPE,
            scopes=(SCOPE,),
            provenance={"source": "DAT-06", "assignment": assignment.id},
        )
        receipts["packet_create"] = packet["receipt"]
        packet_before = packets.read_packet(packet["packet_ref"], VisibilityContext.from_actor(ACTOR, scopes=(SCOPE,)))
        packet_revision = packet_before["content"]["inputs"][0]["resolved_ref"]

        shared_revision_3 = ContentRevision(
            shared_ref,
            "rev-3",
            {"title": "after-again", "unknown": {"keep": True}},
            ACTOR,
            parent_revision="rev-2",
        )
        receipts["document_append_3"] = content.execute(
            content.build_append_revision(
                _context("dat06-document-append-3", shared_revision_3.content, version=2, revision="rev-2"),
                shared_doc,
                shared_revision_3,
            )
        )
        packet_after = packets.read_packet(packet["packet_ref"], VisibilityContext.from_actor(ACTOR, scopes=(SCOPE,)))
        assert packet_after["content"]["inputs"][0]["resolved_ref"] == packet_revision
        assert content.read(shared_ref)["revision"]["content"]["title"] == "after-again"
        assert content.read(shared_initial.ref)["content"]["title"] == "before"
        assert content.read(shared_revision_2.ref)["content"]["title"] == "after"

        task_unlink = content.build_unlink(
            _context("dat06-unlink-task", {}, version=1, revision="rev-1"),
            task_link,
        )
        receipts["unlink_task"] = content.execute(task_unlink)
        task_link_after = content.read(task_link and ResourceRef(AUTHORITY, "document-association", task_link.identity))
        shot_link_after = content.read(ResourceRef(AUTHORITY, "document-association", pinned_shot_link.identity))
        assert task_link_after["payload"]["active"] is False
        assert shot_link_after["payload"]["active"] is True
        assert content.read(shared_ref)["revision"]["content"]["unknown"] == {"keep": True}

        # Scope/access separation is evaluated by the packet surface, not by
        # an association's existence.  A matching scope is sufficient for a
        # shared document; an unscoped actor cannot inherit it via a link.
        outsider = VisibilityContext("outsider")
        with pytest.raises(AccessDeniedError):
            packets.resolve_reference(shared_ref, outsider)
        scoped_outsider = packets.resolve_reference(shared_ref, VisibilityContext("outsider", scopes=(SCOPE,)))
        assert scoped_outsider["resolved"].revision == "rev-3"
        backlinks = {
            "owner": _plain(packets.visible_backlinks(shared_ref, VisibilityContext.from_actor(ACTOR, scopes=(SCOPE,)))),
            "outsider_without_scope": _plain(packets.visible_backlinks(shared_ref, outsider)),
            "outsider_with_scope": _plain(packets.visible_backlinks(shared_ref, VisibilityContext("outsider", scopes=(SCOPE,)))),
        }
        assert backlinks["outsider_without_scope"] == []
        responsibility = _plain(packets.responsibility_view(packet["packet_ref"], VisibilityContext.from_actor(ACTOR, scopes=(SCOPE,))))
        assert responsibility["mandate"] == "inspect shared data extension"
        assert "Astrid binding" in responsibility["omissions"]

        # Reopen the same admitted composition and prove fresh reads and
        # replay against durable receipts/events, not the old Python objects.
        store.close()
        reopened = Store.open(db_path, authority=AUTHORITY, expected_domains=contributions)
        try:
            restarted_metadata = ExtensionCommandService(reopened)
            restarted_content = ContentCommandHandler(reopened)
            restarted_graph = WorkGraph(reopened, actor=ACTOR)
            replay_after_restart = restarted_metadata.set(
                assignment_metadata["subject"],
                OPEN_NAMESPACE,
                assignment_fields,
                _context("dat06-assignment-metadata", assignment_fields, version=1, revision="seed-1"),
            )
            assert replay_after_restart["receipt"] == assignment_metadata["receipt"]
            assert restarted_metadata.read(assignment_metadata["subject"], OPEN_NAMESPACE)["value"] == assignment_fields
            assert restarted_graph.get(task_after.ref).payload["fields"]["unrelated"] == {"keep": True}
            assert restarted_content.read(shared_ref)["revision"]["content"]["title"] == "after-again"
            assert reopened.get_receipt("dat06-assignment-metadata") == assignment_metadata["receipt"]
        finally:
            reopened.close()

        # The original handle is closed above. Reopen through the same public
        # Store admission contract for the exported event and state evidence.
        evidence_store = Store.open(db_path, authority=AUTHORITY, expected_domains=contributions)
        try:
            events = _event_evidence(evidence_store, receipts)
            event_count = len(evidence_store.list_events())
            persisted_receipt = _receipt(evidence_store.get_receipt("dat06-assignment-metadata"))
            after_rejection_state = _identity_snapshot(evidence_store, shot)
            evidence_content = ContentCommandHandler(evidence_store)
            final_snapshots = {
                "task": _identity_snapshot(evidence_store, task_after.ref),
                "shot": _identity_snapshot(evidence_store, shot),
                "assignment": _identity_snapshot(evidence_store, assignment),
                "document": _plain(evidence_content.read(shared_ref)),
                "document_historical_initial": _plain(evidence_content.read(shared_initial.ref)),
                "document_historical_revision_2": _plain(evidence_content.read(shared_revision_2.ref)),
                "task_link": _plain(evidence_content.read(ResourceRef(AUTHORITY, "document-association", task_link.identity))),
                "shot_pinned_link": _plain(evidence_content.read(ResourceRef(AUTHORITY, "document-association", pinned_shot_link.identity))),
            }
        finally:
            evidence_store.close()

        return {
            "handoff_schema": "dat-06-handoff/v1",
            "task": {
                "id": "DAT-06",
                "title": "Hand off data-extension conformance",
                "criteria": ["C05", "C06", "C33", "C35"],
                "status": "worker_evidence_only",
                "source_reuse_entries": ["EX-CONTENT", "EX-METADATA"],
            },
            "resources": {
                "project": _plain(project.ref),
                "task": {"identity": _plain(task_after.ref), "before": _plain(task_before), "after": _plain(task_after), "fresh_after": _plain(task_fresh)},
                "shot_fixture": {"identity": _plain(shot), "before": shot_before, "after": _plain(shot_metadata), "fresh_after": _plain(shot_fresh), "query": _plain(shot_query)},
                "assignment_fixture": {"identity": _plain(assignment), "before": assignment_before, "after": _plain(assignment_metadata), "fresh_after": assignment_after},
                "document": {"identity": _plain(shared_ref), "initial_revision": _plain(shared_initial.ref), "revision_2": _plain(shared_revision_2.ref), "revision_3": _plain(shared_revision_3.ref), "current": final_snapshots["document"], "historical_initial": final_snapshots["document_historical_initial"], "historical_revision_2": final_snapshots["document_historical_revision_2"]},
                "assignment_packet": {"identity": _plain(packet["packet_ref"]), "before": _plain(packet_before), "after": _plain(packet_after), "responsibility_view": responsibility},
                "relationships": {"task_current_link": _plain(task_link), "assignment_current_link": _plain(assignment_link), "shot_pinned_link": _plain(pinned_shot_link), "task_detached": _plain(task_link_after), "shot_pinned_after": _plain(shot_link_after)},
            },
            "definitions": definitions,
            "elegance_inputs_executed": elegance_inputs,
            "rejections": {"before_state": invalid_before_state, "after_state": after_rejection_state, "event_count_before": invalid_before_events, "cases": rejection_evidence},
            "replay_and_restart": {"same_key_original_receipt": _receipt(assignment_metadata["receipt"]), "same_key_replay_equal": True, "changed_input_replay": "rejected: ReplayConflictError", "stale_write": "rejected: VersionConflictError", "restart_fresh_read": True, "restart_replay_equal": True, "persisted_receipt": persisted_receipt},
            "receipts_and_events": {"event_count": event_count, "by_operation": events},
            "backlinks_and_scope": backlinks,
            "final_snapshots": final_snapshots,
            "pins": {
                "fnd_schema_revision": SCHEMA_REVISION,
                "fnd_schema_fingerprint": SCHEMA_FINGERPRINT,
                "content_schema_revision": CONTENT_SCHEMA_REVISION,
                "extension_schema_revision": EXTENSION_SCHEMA_REVISION,
                "work_schema_revision": WORK_SCHEMA_REVISION,
                "extension_definition_refs": [definitions["task"]["definitions"][0]["schema_ref"], definitions["task"]["definitions"][1]["schema_ref"]],
            },
            "source_pins": {
                "accepted_base_commit": "e9f91f196d5130965069c6110e3f2d60098c3952",
                "accepted_base_tree": "a735253153056ae80b755005b64ee78d4322f275",
                "dat05_source_commit": "3597187aaaebb627ed818f5dd3ab1f165eb15097",
                "dat05_source_tree": "b405bdd3c229ee5d8fed04b8be5c45a86b71a64d",
                "fnd_typed_identity_source_commit": "59043551e6fb4a19d7130d5aa47cf75a732e0a45",
                "fnd_typed_identity_source_tree": "39bb3ac322855f3e6552813b3ce87c6834d40917",
                "refreshed_source_manifest_sha256": "742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a",
                "source_origin": "worker checkout via PYTHONPATH=src",
                "installed_origin": "not represented by this source-generated handoff; see worker result",
            },
            "migration": {
                "aliases": [],
                "instructions": "Use ResourceRef authority/kind/id as the neutral identity boundary; keep the declared work.task fixture synthetic until an approved Astrid adapter exists.",
            },
            "unresolved": {
                "astrid": "actual Astrid binding deferred behind G-OTTO",
                "installed": "candidate-wheel import proof only; pytest unavailable in disposable installed environment",
                "publication": "not performed by this worker",
                "license": "not evaluated by this worker",
            },
            "boundaries": {
                "astrid_integration_proven": False,
                "astrid_status": "deferred behind G-OTTO; shot fixture is synthetic contract proof only",
                "assignment_status": "declared wrk.assignment identity through the public FND store",
                "third_specialist_status": "deferred",
                "domain_specific_document_tables": False,
                "copied_content_or_private_writer": False,
                "ddl_or_event_engine_added": False,
            },
        }
    finally:
        # The reopen branch closes its own handle; this is a no-op when the
        # normal path already closed the original store.
        store.close()

def test_dat06_public_api_conformance(tmp_path: Path) -> None:
    evidence = _run_probe(tmp_path / "dat06.sqlite")
    assert evidence["boundaries"]["astrid_integration_proven"] is False
    assert evidence["resources"]["document"]["current"]["revision"]["content"]["title"] == "after-again"
    assert evidence["resources"]["document"]["historical_initial"]["content"]["title"] == "before"
    assert evidence["replay_and_restart"]["same_key_replay_equal"] is True
    assert evidence["replay_and_restart"]["changed_input_replay"].startswith("rejected")
    assert evidence["backlinks_and_scope"]["outsider_without_scope"] == []


def _write_handoff(path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="dat06-handoff-") as temporary:
        evidence = _run_probe(Path(temporary) / "dat06.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-handoff", action="store_true")
    parser.add_argument("--path", type=Path, default=Path("handoffs/DAT.json"))
    args = parser.parse_args()
    if not args.write_handoff:
        raise SystemExit("use --write-handoff to create the DAT-06 evidence handoff")
    _write_handoff(args.path)
