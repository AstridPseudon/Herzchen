from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import subprocess
import sys
import unittest

from herzchen.contracts import (
    Applicability,
    AttentionRecord,
    AuthenticatedActor,
    AuthoringCheckout,
    CandidateManifest,
    CleanupStatus,
    CommandEnvelope,
    CommandReceipt,
    CONTRACT_DIGEST,
    CONTRACT_REVISION,
    CursorState,
    DecisionRecord,
    DomainContribution,
    DomainRegistry,
    EventCursor,
    EventEnvelope,
    ExtensionDescriptor,
    ExtensionRegistry,
    FinishClaim,
    HostOperation,
    HostPort,
    HostReceipt,
    HostRequest,
    HostIdentity,
    HostOutcome,
    PackResourceDescriptor,
    ReadinessExplanation,
    ReceiptStatus,
    ReplayConflictError,
    ResourceRef,
    SCHEMA_DEFINITIONS,
    TransactionContext,
    UnsupportedOperationError,
    canonical_json,
    validate_expected_state,
    validate_replay,
)


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "contracts" / "shared-ports"


def ref(kind="document", ident="doc-1", revision=None):
    return ResourceRef("neutral-store", kind, ident, revision)


def actor():
    return AuthenticatedActor("neutral-auth", "agent-1", "credential-1")


def context(key="request-1", digest="a" * 64):
    return TransactionContext(actor(), key, digest, expected_revision="rev-1", expected_version=1, edit_token="edit-1", correlation_id="corr-1")


class ReferenceTests(unittest.TestCase):
    def test_current_and_pinned_document_round_trip(self):
        current = ResourceRef("neutral-store", "document", "doc-1")
        pinned = ResourceRef("neutral-store", "document", "doc-1", "rev-3")
        self.assertFalse(current.is_pinned)
        self.assertTrue(pinned.is_pinned)
        self.assertEqual(pinned, ResourceRef.from_dict(pinned.to_dict()))

    def test_blank_malformed_and_path_references_reject(self):
        for values in (("", "document", "id"), ("authority", "", "id"), ("authority", "document", ""), ("authority", "document", "/tmp/id"), ("authority", "document", "a/b"), ("authority", "document", "id", "")):
            with self.assertRaises(ValueError):
                ResourceRef(*values)

    def test_revision_and_document_refs_are_explicit(self):
        document = __import__("herzchen.contracts", fromlist=["DocumentRef"]).DocumentRef("neutral-store", "document", "doc-1", "rev-1", "candidate")
        self.assertEqual(document.as_resource().revision, "rev-1")


class ExtensionAndDomainTests(unittest.TestCase):
    def extension(self, namespace="example.ns", operation="example.update"):
        return ExtensionDescriptor(namespace, "v1", ("example.resource",), "Example extension", "example-owner", operation_bindings=(__import__("herzchen.contracts", fromlist=["OperationBinding"]).OperationBinding(operation, "v1"),))

    def domain(self, domain_id="example.domain", operation="example.update", namespace="example.ns", resources=("example.resource",), documents=("example.document",), events=("example.updated",)):
        return DomainContribution(domain_id, "1", "example-owner", resources, documents, (namespace,), (operation,), events, "v1")

    def test_duplicate_namespace_and_operation_reject(self):
        registry = ExtensionRegistry()
        registry.register(self.extension())
        with self.assertRaises(ValueError):
            registry.register(self.extension("other.ns", "example.update"))
        with self.assertRaises(ValueError):
            registry.register(self.extension("example.ns", "other.update"))

    def test_duplicate_domain_command_and_namespace_reject(self):
        registry = DomainRegistry()
        registry.register(self.domain())
        with self.assertRaises(ValueError):
            registry.register(self.domain("other.domain", "example.update", "other.ns"))
        with self.assertRaises(ValueError):
            registry.register(self.domain("example.domain", "other.update", "other.ns"))

    def test_duplicate_resource_document_and_event_types_reject(self):
        cases = (
            {"resources": ("example.resource",), "documents": (), "events": ("other.updated",)},
            {"resources": ("other.resource",), "documents": ("example.document",), "events": ("other.updated",)},
            {"resources": ("other.resource",), "documents": (), "events": ("example.updated",)},
        )
        for kwargs in cases:
            registry = DomainRegistry()
            registry.register(self.domain())
            with self.assertRaisesRegex(ValueError, "duplicate (resource|document|event) type identity"):
                registry.register(self.domain("other.domain", "other.update", "other.ns", **kwargs))

    def test_unknown_resource_kind_is_preserved(self):
        value = PackResourceDescriptor("resource-1", "future.unknown.kind", "v1", ref("source", "source-1", "rev-1"), annotations={"future": {"keep": True}})
        self.assertEqual(PackResourceDescriptor.from_dict(value.to_dict()).kind, "future.unknown.kind")
        self.assertEqual(value.to_dict()["annotations"]["future"]["keep"], True)


class CommandTests(unittest.TestCase):
    def envelope(self):
        return CommandEnvelope("document.update", "document.v1", ref(revision="rev-1"), context(), {"annotations": {"unknown": {"preserve": True}}})

    def receipt(self):
        return CommandReceipt("request-1", "a" * 64, "document.update", ref(revision="rev-1"), ReceiptStatus.COMMITTED, transaction_id="tx-1", event_ids=("event-1",))

    def test_envelope_round_trip_and_closed_reserved_shape(self):
        command = self.envelope()
        self.assertEqual(CommandEnvelope.from_dict(command.to_dict()), command)
        bad = command.to_dict()
        bad["future_reserved"] = True
        with self.assertRaises(ValueError):
            CommandEnvelope.from_dict(bad)

    def test_receipt_statuses_have_distinct_required_fields(self):
        committed = self.receipt()
        self.assertEqual(CommandReceipt.from_dict(committed.to_dict()).status, ReceiptStatus.COMMITTED)
        self.assertEqual(CommandReceipt("key-noop", "b" * 64, "op", ref(), ReceiptStatus.NOOP).status, ReceiptStatus.NOOP)
        self.assertEqual(CommandReceipt("key-fail", "c" * 64, "op", ref(), ReceiptStatus.FAILED, error_code="rejected").error_code, "rejected")
        self.assertEqual(CommandReceipt("key-unknown", "d" * 64, "op", ref(), ReceiptStatus.UNKNOWN, unknown_reason="lost").unknown_reason, "lost")
        with self.assertRaises(ValueError):
            CommandReceipt("key", "e" * 64, "op", ref(), ReceiptStatus.FAILED)

    def test_changed_replay_key_is_conflict_and_digest_is_not_permission(self):
        with self.assertRaises(ReplayConflictError):
            validate_replay(self.receipt(), dataclasses.replace(self.envelope(), context=context(digest="f" * 64)))
        with self.assertRaises(ValueError):
            AuthenticatedActor("authority", "actor", "credential", authenticated=False)

    def test_expected_version_revision_and_edit_token_are_checked(self):
        validate_expected_state(context(), current_revision="rev-1", current_version=1, supplied_edit_token="edit-1")
        for kwargs in ({"current_version": 2, "current_revision": "rev-1", "supplied_edit_token": "edit-1"}, {"current_version": 1, "current_revision": "rev-2", "supplied_edit_token": "edit-1"}, {"current_version": 1, "current_revision": "rev-1", "supplied_edit_token": "wrong"}):
            with self.assertRaises(ValueError):
                validate_expected_state(context(), **kwargs)


class EventTests(unittest.TestCase):
    def event(self, sequence=2, event_id="event-2"):
        return EventEnvelope(event_id, "neutral-store", "stream-1", ref(revision="rev-2"), "event.v1", "document.updated", sequence, actor(), "document.update", "corr-1", "event-1", "2026-09-13T20:00:00Z", before_refs=(ref(revision="rev-1"),), after_refs=(ref(revision="rev-2"),), effects={"changed": ["title"]})

    def test_cursor_duplicate_reorder_gap_and_expired_are_explicit(self):
        normal = EventCursor("neutral-store", "stream-1", 1, "event-1")
        self.assertEqual(normal.observe(self.event(2)).state, CursorState.NORMAL)
        self.assertEqual(normal.observe(self.event(1, "event-1")).state, CursorState.DUPLICATE)
        self.assertEqual(normal.observe(self.event(1, "event-old")).state, CursorState.REORDERED)
        self.assertEqual(normal.observe(self.event(4, "event-4")).state, CursorState.GAP)
        expired = EventCursor("neutral-store", "stream-1", 1, "event-1", CursorState.EXPIRED)
        self.assertEqual(expired.observe(self.event()).state, CursorState.EXPIRED)

    def test_cursor_never_implies_readiness_or_dispatch(self):
        observed = EventCursor("neutral-store", "stream-1", 1, "event-1").observe(self.event(4, "event-4"))
        self.assertEqual(observed.state, CursorState.GAP)
        self.assertFalse(hasattr(observed, "dispatch"))

    def test_event_round_trip(self):
        event = self.event()
        self.assertEqual(EventEnvelope.from_dict(event.to_dict()), event)


class AuthoringTests(unittest.TestCase):
    def checkout(self):
        return AuthoringCheckout(ref("scope", "scope-1", "rev-1"), "document", actor(), "session-1", "token-1", "fence-1", "rev-1", ref("snapshot", "draft-1", "digest-d1"), None, ("title", "body"))

    def test_finish_claim_identity_is_shared_by_manual_and_idle(self):
        checkout = self.checkout()
        finished = checkout.finish(FinishClaim("finish-1", "manual", "claim-1"), ref("snapshot", "final-1", "digest-f1"))
        self.assertEqual(finished.finish_claim.finalization_identity, "finish-1")
        with self.assertRaises(ValueError):
            finished.finish(FinishClaim("finish-2", "idle", "claim-2"), ref("snapshot", "final-2", "digest-f2"))

    def test_token_fence_base_and_exact_snapshots_are_retained(self):
        checkout = self.checkout()
        self.assertEqual(AuthoringCheckout.from_dict(checkout.to_dict()), checkout)
        self.assertEqual((checkout.token, checkout.fence, checkout.base_revision), ("token-1", "fence-1", "rev-1"))
        self.assertEqual(checkout.allowed_fields, ("title", "body"))

    def test_cleanup_is_separate_and_unmanaged_writer_is_unsafe(self):
        unsafe = dataclasses.replace(self.checkout(), unmanaged_writers=True)
        self.assertEqual(unsafe.mark_cleanup(CleanupStatus.PENDING).cleanup, CleanupStatus.PENDING)
        with self.assertRaises(ValueError):
            unsafe.mark_cleanup(CleanupStatus.COMPLETE)


class CandidateDecisionTests(unittest.TestCase):
    def candidate(self):
        return CandidateManifest("candidate-1", "manifest-1", "owner-1", ref("work", "work-1", "rev-1"), "deliverable", (ref("artifact", "artifact-1", "digest-a1"),), (ref("source", "source-1", "rev-1"),), (ref("input", "input-1", "rev-1"),), (ref("criteria", "criteria-1", "rev-1"),), {"origin": "fixture"})

    def decision(self):
        return DecisionRecord("decision-1", ref("work", "work-1", "rev-1"), "Accept candidate?", actor(), ref("authority", "authority-1", "rev-1"), (ref("candidate", "candidate-1", "manifest-1"),), (ref("criteria", "criteria-1", "rev-1"),), (ref("evidence", "evidence-1", "rev-1"),), "accepted", "Pinned evidence satisfies the criteria.", __import__("herzchen.contracts", fromlist=["Reconsideration"]).Reconsideration("A consumed input changes", "input.updated", (ref("input", "input-1", "rev-1"),)), applicability=Applicability.APPLICABLE)

    def test_candidate_is_immutable_and_pins_exact_refs(self):
        candidate = self.candidate()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            candidate.candidate_id = "changed"
        self.assertEqual(CandidateManifest.from_dict(candidate.to_dict()), candidate)
        self.assertEqual(candidate.output_refs[0].revision, "digest-a1")

    def test_decision_has_explicit_reconsideration_and_applicability(self):
        decision = self.decision()
        self.assertEqual(decision.applicability, Applicability.APPLICABLE)
        self.assertIsNotNone(decision.reconsideration)
        stale = dataclasses.replace(decision, applicability=Applicability.STALE)
        self.assertEqual(DecisionRecord.from_dict(stale.to_dict()).applicability, Applicability.STALE)


class ReadinessAttentionHostTests(unittest.TestCase):
    def test_readiness_and_attention_round_trip(self):
        readiness = ReadinessExplanation("Await source", "owner-1", ref("source", "source-1", "rev-1"), "rev-1", "source.updated", causes=("missing-source",))
        attention = AttentionRecord("owner-1", "source-updated", ref("work", "work-1", "rev-1"), "dedupe-1", EventCursor("neutral-store", "work:work-1", 1, "event-1"))
        self.assertEqual(ReadinessExplanation.from_dict(readiness.to_dict()), readiness)
        self.assertEqual(AttentionRecord.from_dict(attention.to_dict()), attention)

    def test_neutral_host_has_logical_identity_and_explicit_unsupported(self):
        request = HostRequest(HostOperation.INVOKE, HostIdentity("agent-1"), ref("attention", "attention-1", "rev-1"), "fixture-profile")
        self.assertEqual(HostRequest.from_dict(request.to_dict()), request)
        port = HostPort({HostOperation.INSPECT})
        port.require(HostOperation.INSPECT)
        with self.assertRaises(UnsupportedOperationError):
            port.require(HostOperation.RESUME)
        receipt = HostReceipt(HostOperation.RESUME, HostOutcome.UNSUPPORTED, HostIdentity("agent-1"), "request-1", unsupported_reason="adapter_has_no_resume")
        self.assertEqual(HostReceipt.from_dict(receipt.to_dict()), receipt)


class CompositionAndFixtureTests(unittest.TestCase):
    def test_contract_import_has_no_product_imports(self):
        code = "import herzchen.contracts, sys; assert not any(name.startswith(('otto', 'astrid', 'runtime_protocol')) for name in sys.modules)"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fixture_load_round_trip_and_digest(self):
        fixture_types = {
            "resource-ref.json": [("value", ResourceRef)],
            "command-receipt.json": [("command", CommandEnvelope), ("receipts", CommandReceipt)],
            "event-cursor.json": [("cursor", EventCursor), ("event", EventEnvelope)],
            "authoring.json": [("value", AuthoringCheckout)],
            "domain-contribution.json": [("value", DomainContribution)],
            "candidate-decision.json": [("candidate", CandidateManifest), ("decision", DecisionRecord)],
            "attention.json": [("readiness", ReadinessExplanation), ("attention", AttentionRecord)],
            "host.json": [("request", HostRequest), ("unsupported", HostReceipt)],
            "invocation.json": [("request", HostRequest), ("receipt", HostReceipt)],
        }
        for filename, entries in fixture_types.items():
            data = json.loads((FIXTURES / filename).read_text())
            self.assertEqual(data["contract_revision"], CONTRACT_REVISION)
            for key, cls in entries:
                values = data[key] if isinstance(data[key], list) else [data[key]]
                for value in values:
                    parsed = cls.from_dict(value)
                    self.assertEqual(cls.from_dict(parsed.to_dict()), parsed, filename)
        import herzchen.contracts as contracts
        self.assertEqual(contracts.CONTRACT_DIGEST, contracts.SCHEMA_DIGEST)
        self.assertEqual(CONTRACT_DIGEST, __import__("hashlib").sha256(canonical_json(SCHEMA_DEFINITIONS).encode()).hexdigest())

    def test_negative_fixture_examples_are_rejected(self):
        data = json.loads((FIXTURES / "negative-collision.json").read_text())
        with self.assertRaises(ValueError):
            ResourceRef.from_dict(data["path_ref"])
        with self.assertRaises(ValueError):
            CommandEnvelope.from_dict(data["unknown_reserved_envelope"])


if __name__ == "__main__":
    unittest.main()
