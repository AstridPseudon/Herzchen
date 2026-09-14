from __future__ import annotations

import hashlib
import tempfile
import unittest
from typing import Optional, Tuple

from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, DocumentAssociation
from herzchen.content.model import domain_contribution, revision_identity
from herzchen.content.packets import (
    AccessDeniedError,
    ContextPacketService,
    PacketError,
    PacketInput,
    SchemaAdoptionRequiredError,
    VisibilityContext,
    domain_contribution as packet_contribution,
)
from herzchen.contracts import AuthenticatedActor, EventCursor, ReferenceBinding, ResourceRef, TransactionContext
from herzchen.kernel import Store


def actor(name: str) -> AuthenticatedActor:
    return AuthenticatedActor("auth", name, "credential-" + name)


def context(who: AuthenticatedActor, key: str, *, version: int = 0, revision: Optional[str] = None) -> TransactionContext:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return TransactionContext(who, key, digest, expected_version=version, expected_revision=revision)


class ContextVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store.create(self.tempdir.name + "/dat.sqlite", authority="dat-store")
        self.store.register_domain_handler((domain_contribution(), packet_contribution()))
        self.content = ContentCommandHandler(self.store)
        self.service = ContextPacketService(self.store)
        self.owner = actor("owner")
        self.other = actor("other")
        self.scope = ResourceRef("dat-store", "scope", "project-1")

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def add_document(self, ident: str, value: object, *, visibility: str = "private", maintainer: str = "owner", scope: Optional[ResourceRef] = None) -> Tuple[ContentDocument, ContentRevision]:
        doc = ContentDocument(ResourceRef("dat-store", "document", ident), "brief", visibility, "append", maintainer, scope)
        rev = ContentRevision(doc.ref, "rev-1", value, self.owner, initial=True)
        self.content.execute(self.content.build_create_document(context(self.owner, "create-" + ident), doc, rev))
        return doc, rev

    def test_current_binding_is_pinned_at_assignment_and_head_change_does_not_rewrite_packet(self) -> None:
        doc, initial = self.add_document("source", {"title": "before"}, visibility="shared", scope=self.scope)
        packet = self.service.create_packet(
            "assignment-1", context(self.owner, "packet-1"), [ReferenceBinding(doc.ref)],
            responsibility={"mandate": "inspect", "outcome": "report", "criteria_refs": [], "omissions": ["private notes"]},
            scopes=(self.scope,),
        )
        pinned_packet = packet["packet_ref"]
        changed = ContentRevision(doc.ref, "rev-2", {"title": "after"}, self.owner, parent_revision="rev-1")
        self.content.execute(self.content.build_append_revision(context(self.owner, "append-source", version=1, revision="rev-1"), doc, changed))
        read = self.service.read_packet(pinned_packet, VisibilityContext("owner", scopes=(self.scope,)))
        self.assertEqual(read["content"]["inputs"][0]["resolved_ref"]["revision"], "rev-1")
        self.assertEqual(self.service.resolve_reference(doc.ref, VisibilityContext("owner", scopes=(self.scope,)))["resolved"].revision, "rev-2")
        self.assertEqual(self.service.compare_supplied_inputs(pinned_packet, {"input-1": doc.ref}, VisibilityContext("owner", scopes=(self.scope,)))["invalidated"], True)

    def test_private_visibility_and_inherited_backlink_never_leak_hidden_ground_truth(self) -> None:
        hidden, _ = self.add_document("hidden", {"secret": "ground-truth"})
        link = self.content.build_link(
            context(self.owner, "link-hidden"),
            DocumentAssociation(
                ResourceRef("dat-store", "task", "task-1"), "task.documents", "brief", ReferenceBinding(hidden.ref)
            ),
        )
        self.content.execute(link)
        with self.assertRaises(AccessDeniedError):
            self.service.resolve_reference(hidden.ref, VisibilityContext("fresh-actor"))
        self.assertEqual(self.service.visible_backlinks(hidden.ref, VisibilityContext("fresh-actor")), ())
        self.assertEqual(self.service.visible_backlinks(hidden.ref, VisibilityContext("owner"))[0]["subject"]["id"], "task-1")

    def test_explicit_adoption_preserves_unknown_historical_fields_and_blocks_unadopted_use(self) -> None:
        schema = ResourceRef("herzchen", "dat.extensions.schema", "example", "7")
        origin = ResourceRef("dat-store", "document", "schema-source", "rev-2")
        historical = {"known": "old", "unknown_from_history": {"kept": True}}
        with self.assertRaises(SchemaAdoptionRequiredError):
            self.service.validate_historical(historical, {"type": "object", "additionalProperties": True}, None)
        adoption = self.service.adopt_schema(schema, origin=origin)
        self.assertEqual(self.service.validate_historical(historical, {"type": "object", "additionalProperties": True}, adoption), historical)
        self.assertEqual(adoption.schema_ref.revision, "7")
        self.assertEqual(adoption.origin, origin)

    def test_candidate_and_decision_are_typed_immutable_ordinary_documents(self) -> None:
        source, source_rev = self.add_document("source-manifest", {"source": 1}, visibility="public")
        pinned_source = source_rev.ref
        candidate = {
            "candidate_id": "candidate-1", "manifest_revision": "manifest-1", "owner": "owner",
            "author": self.owner, "resource": pinned_source, "role": "candidate",
            "output_refs": [pinned_source], "source_refs": [pinned_source], "input_refs": [pinned_source],
            "criteria_refs": [pinned_source], "provenance": {"producer": "test", "origin": "source"},
        }
        created = self.service.register_candidate(candidate, context(self.owner, "candidate-1"), visibility="public")
        self.assertEqual(created["role"], "candidate-manifest")
        stored = self.store.get_identity(created["document_ref"])
        self.assertEqual(stored.payload["document"]["role"], "candidate-manifest")
        decision = {
            "decision_id": "decision-1", "decision_revision": "1", "subject": pinned_source,
            "author": self.owner, "authority": pinned_source, "question": "Accept candidate-1?",
            "candidate_refs": [created["revision_ref"]], "criteria_refs": [pinned_source], "evidence_refs": [pinned_source],
            "disposition": "hold", "rationale": "Need one more observation.", "return_condition": "source changes",
        }
        result = self.service.register_decision(decision, context(self.owner, "decision-1"), visibility="public")
        self.assertEqual(result["role"], "decision-manifest")
        self.assertEqual(result["receipt"].status.value, "committed")
        with self.assertRaises(PacketError):
            self.service.register_candidate(dict(candidate, candidate_id="candidate-bad", input_refs=[source.ref]), context(self.owner, "bad-candidate"))
        self.assertIsNone(self.store.get_identity(ResourceRef("dat-store", "dat.content.document", "candidate-manifest:candidate-bad")))

    def test_consumed_input_comparison_ignores_unrelated_annotation(self) -> None:
        doc, _ = self.add_document("input", {"value": 1}, visibility="public")
        packet = self.service.create_packet("assignment-2", context(self.owner, "packet-2"), [PacketInput("source", doc.ref)], visibility="public")
        same = self.service.compare_supplied_inputs(packet["packet_ref"], {"source": doc.ref, "annotation": {"note": "changed"}}, VisibilityContext("other"))
        self.assertTrue(same["applicable"])
        self.assertEqual(same["irrelevant_annotations"], ["annotation"])

    def test_amendment_notifies_without_hot_rewrite_and_attention_survives_replay(self) -> None:
        doc, _ = self.add_document("shared", {"value": "one"}, visibility="public")
        packet = self.service.create_packet("assignment-3", context(self.owner, "packet-3"), [doc.ref], visibility="public")
        amended = ResourceRef("dat-store", "document", "shared", "rev-1")
        notices = self.service.notify_amendment(doc.ref, amended, ["owner"], context(self.owner, "notice-1"), packet_refs=[packet["packet_ref"]])
        self.assertEqual(len(notices), 1)
        self.assertEqual(len(self.service.list_attention("owner")), 1)
        self.assertEqual(self.service.read_packet(packet["packet_ref"], VisibilityContext("owner"))["content"]["inputs"][0]["resolved_ref"]["revision"], "rev-1")
        replay = self.service.notify_amendment(doc.ref, amended, ["owner"], context(self.owner, "notice-1"), packet_refs=[packet["packet_ref"]])
        self.assertEqual(replay[0]["receipt"], notices[0]["receipt"])
        self.assertEqual(len(self.service.list_attention("owner")), 1)

    def test_responsibility_view_is_bounded_and_cursor_delta_is_useful(self) -> None:
        doc, _ = self.add_document("responsibility", {"value": 1}, visibility="public")
        packet = self.service.create_packet(
            "assignment-4", context(self.owner, "packet-4"), [doc.ref], visibility="public",
            responsibility={"mandate": "make a finding", "outcome": "decision", "adopted_task": "task-1", "adopted_protocol": "protocol-1", "profile": "normal", "criteria_refs": [doc.ref], "missing_prerequisites": ["evidence"], "open_decisions": ["scope"], "evidence_links": [doc.ref], "supported_operations": ["inspect"], "scope_coverage": ["project-1"], "omissions": ["transcript", "private reasoning"]},
        )
        view = self.service.responsibility_view(packet["packet_ref"], VisibilityContext("other"))
        for key in ("mandate", "outcome", "adopted_task", "adopted_protocol", "profile", "criteria_refs", "cursor_delta", "missing_prerequisites", "open_decisions", "evidence_links", "supported_operations", "provenance", "scope_coverage", "omissions"):
            self.assertIn(key, view)
        self.assertNotIn("transcript", view)
        self.assertNotIn("private_reasoning", view)
        self.assertEqual(view["missing_prerequisites"], ["evidence"])
        cursor = EventCursor("dat-store", "document:responsibility", 0)
        self.assertIsInstance(self.service.responsibility_view(packet["packet_ref"], VisibilityContext("other"), cursor=cursor)["cursor_delta"], tuple)


if __name__ == "__main__":
    unittest.main()
