from __future__ import annotations

import unittest
import tempfile
from typing import Optional

from herzchen.content import (
    ContentCommandHandler,
    ContentDocument,
    ContentError,
    ContentRevision,
    DocumentAssociation,
    PersistenceUnavailableError,
    domain_contribution,
    revision_identity,
    validate_document_binding,
    validate_revision_owner,
)
from herzchen.contracts import (
    AuthenticatedActor,
    ReferenceBinding,
    ResourceRef,
    TransactionContext,
)


def ref(kind: str, ident: str, revision: Optional[str] = None, authority: str = "dat-store") -> ResourceRef:
    return ResourceRef(authority, kind, ident, revision)


def actor() -> AuthenticatedActor:
    return AuthenticatedActor("auth", "author", "credential")


def context(key: str = "content-request", digest: str = "a" * 64, *, revision: Optional[str] = None, version: Optional[int] = 0) -> TransactionContext:
    return TransactionContext(actor(), key, digest, expected_revision=revision, expected_version=version)


def document(ident: str = "doc-1", **kwargs: object) -> ContentDocument:
    values = {
        "ref": ref("project.specification", ident),
        "role": "initial-specification",
        "visibility": "private",
        "access_mode": "append",
        "maintainer": "curator",
    }
    values.update(kwargs)
    return ContentDocument(**values)  # type: ignore[arg-type]


def revision(doc: ContentDocument, value: object = None, **kwargs: object) -> ContentRevision:
    if value is None:
        value = {"title": "Untitled project", "outcome": ""}
    values = {
        "document": doc.ref,
        "revision": "rev-1",
        "content": value,
        "author": actor(),
        "initial": True,
    }
    values.update(kwargs)
    return ContentRevision(**values)  # type: ignore[arg-type]


class DocumentSchemaTests(unittest.TestCase):
    def test_document_identity_and_independent_scope_access_maintenance(self):
        value = document(authoring_scope=ref("project", "project-1"), visibility="shared", access_mode="append")
        self.assertEqual(value.ref.revision, None)
        self.assertEqual(value.maintainer, "curator")
        self.assertEqual(value.document_ref.role, "initial-specification")

    def test_imported_source_is_reference_only_and_not_writable(self):
        imported = document(
            source_ref=ref("runtime.document", "runtime-1", "runtime-rev-4", "runtime"),
            import_mode="pinned",
            writable=False,
            access_mode="read",
        )
        self.assertEqual(imported.source_ref.authority, "runtime")
        with self.assertRaises(ContentError):
            document(source_ref=ref("runtime.document", "runtime-1"), import_mode="pinned", writable=True, access_mode="read")
        with self.assertRaises(ContentError):
            document(source_ref=ref("runtime.document", "runtime-1"), import_mode="pinned", writable=False, access_mode="read")

    def test_cross_authority_document_ref_is_not_a_local_foreign_key(self):
        link = DocumentAssociation(
            ref("task", "task-1", authority="work-store"),
            "work.documents",
            "spec",
            ReferenceBinding(ref("project.specification", "doc-1", authority="dat-store")),
        )
        self.assertEqual(link.document.ref.authority, "dat-store")
        self.assertNotEqual(link.subject.authority, link.document.ref.authority)

    def test_pinned_revision_must_match_document_authority_kind_and_id(self):
        doc = document()
        good = revision(doc)
        validate_revision_owner(doc, good)
        for bad_document in (ref(doc.ref.kind, doc.ref.id, authority="other-store"), ref("other.kind", doc.ref.id), ref(doc.ref.kind, "other-id")):
            with self.assertRaises(ContentError):
                validate_revision_owner(doc, ContentRevision(bad_document, "rev-1", {"x": 1}, actor(), initial=True))

    def test_binding_must_remain_on_same_document_identity(self):
        doc = document()
        validate_document_binding(doc, ReferenceBinding(ref(doc.ref.kind, doc.ref.id, "rev-1"), "pinned"))
        with self.assertRaises(ContentError):
            validate_document_binding(doc, ReferenceBinding(ref(doc.ref.kind, "other-id"), "current"))

    def test_current_and_pinned_bindings_are_distinct(self):
        current = ReferenceBinding(ref("project.specification", "doc-1"), "current")
        pinned = ReferenceBinding(ref("project.specification", "doc-1", "rev-1"), "pinned")
        self.assertFalse(current.ref.is_pinned)
        self.assertTrue(pinned.ref.is_pinned)
        with self.assertRaises(ValueError):
            ReferenceBinding(ref("project.specification", "doc-1", "rev-1"), "current")


class CommandBoundaryTests(unittest.TestCase):
    def test_create_and_append_are_envelopes_not_writes(self):
        handler = ContentCommandHandler()
        doc = document()
        create = handler.build_create_document(context(), doc, revision(doc))
        self.assertEqual(create.operation, "dat.content.document.create")
        self.assertEqual(create.target, doc.ref)
        appended = ContentRevision(doc.ref, "rev-2", {"title": "Edited"}, actor(), parent_revision="rev-1")
        command = handler.build_append_revision(context("append"), doc, appended)
        self.assertEqual(command.operation, "dat.content.revision.append")
        with self.assertRaises(PersistenceUnavailableError):
            handler.execute(create)
        with self.assertRaises(PersistenceUnavailableError):
            handler.read(doc.ref)

    def test_unlink_command_preserves_document_and_revisions(self):
        handler = ContentCommandHandler()
        link = DocumentAssociation(ref("project", "project-1"), "project.documents", "spec", ReferenceBinding(ref("project.specification", "doc-1")))
        command = handler.build_unlink(context("unlink"), link)
        self.assertTrue(command.payload["preserve_document"])
        self.assertTrue(command.payload["preserve_revisions"])
        self.assertNotEqual(command.target.kind, "project.specification")

    def test_initial_revision_is_only_revision_for_blank_starter(self):
        doc = document()
        initial = revision(doc)
        self.assertIsNone(initial.parent_revision)
        with self.assertRaises(ValueError):
            ContentCommandHandler().build_create_document(context(), doc, ContentRevision(doc.ref, "rev-2", {"x": 1}, actor()))
        with self.assertRaises(ContentError):
            ContentRevision(doc.ref, "rev-2", {"x": 1}, actor(), parent_revision="rev-1", initial=True)

    def test_domain_contribution_is_explicit_and_collision_ready(self):
        contribution = domain_contribution()
        self.assertEqual(contribution.domain_id, "dat.content")
        self.assertIn("dat.content.document.create", contribution.operation_types)
        self.assertIn("dat.content.document.created", contribution.event_types)

    def test_revision_identity_is_unique_per_document_and_revision(self):
        doc = document()
        first = revision_identity(doc.ref, "rev-1")
        second = revision_identity(doc.ref, "rev-2")
        other = revision_identity(document("doc-2").ref, "rev-1")
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.id, other.id)
        self.assertEqual(first.kind, "dat.content.revision")
        self.assertEqual(first.revision, "rev-1")


try:
    from herzchen.kernel import Store, StoreError
except ImportError:  # FND-03 is an integration dependency, not a test fallback.
    Store = None  # type: ignore[assignment,misc]
    StoreError = Exception  # type: ignore[assignment,misc]


@unittest.skipUnless(Store is not None, "FND-03 kernel package is unavailable")
class FND03ContentIntegrationTests(unittest.TestCase):
    """DAT proof against the actual FND-03 Store, never a private test store."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store.create(self.tempdir.name + "/content.sqlite", authority="dat-store")
        self.handler = ContentCommandHandler(self.store)
        self.doc = document()
        self.initial = revision(self.doc)
        self.create = self.handler.build_create_document(context("create"), self.doc, self.initial)

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_create_links_unlink_and_fresh_reads_share_one_document(self):
        created = self.handler.execute(self.create)
        self.assertEqual(created.status.value, "committed")
        self.assertEqual(len(created.event_ids), 1)
        self.assertEqual(self.handler.read(self.doc.ref)["current_revision"]["revision"], "rev-1")

        subjects = [ref("project", "project-1"), ref("project", "project-2")]
        subjects += [ref("task", "task-{}".format(index)) for index in range(1, 6)]
        links = []
        for index, subject in enumerate(subjects):
            association = DocumentAssociation(subject, "work.documents", "spec", ReferenceBinding(self.doc.ref))
            receipt = self.handler.execute(self.handler.build_link(context("link-{}".format(index)), association))
            self.assertEqual(receipt.status.value, "committed")
            self.assertEqual(len(receipt.event_ids), 1)
            links.append(association)
            stored = self.handler.read(ResourceRef(subject.authority, "document-association", association.identity))
            self.assertEqual(stored["payload"]["association"]["document"]["ref"], self.doc.ref.to_dict())

        unlink = self.handler.build_unlink(context("unlink", version=1), links[0])
        unlinked = self.handler.execute(unlink)
        self.assertEqual(len(unlinked.event_ids), 1)
        self.assertFalse(self.handler.read(unlink.target)["payload"]["active"])
        self.assertEqual(self.handler.read(self.doc.ref)["revision"]["content"], self.initial.content)
        self.assertTrue(self.handler.read(ResourceRef(links[1].subject.authority, "document-association", links[1].identity))["payload"]["active"])
        self.assertEqual(self.handler.read(self.initial.ref)["content"], self.initial.content)
        self.assertEqual(len(self.store.list_events()), 9)

    def test_current_head_moves_but_pinned_revision_stays_unchanged(self):
        self.handler.execute(self.create)
        updated = ContentRevision(self.doc.ref, "rev-2", {"title": "Edited"}, actor(), parent_revision="rev-1")
        append_context = context("append", revision="rev-1", version=1)
        receipt = self.handler.execute(self.handler.build_append_revision(append_context, self.doc, updated))
        self.assertEqual(receipt.observed_revision, "rev-2")
        self.assertEqual(len(receipt.event_ids), 1)
        self.assertEqual(self.handler.read(self.doc.ref)["revision"]["content"], {"title": "Edited"})
        self.assertEqual(self.handler.read(self.initial.ref)["content"], self.initial.content)
        self.assertEqual(self.handler.read(updated.ref)["content"], {"title": "Edited"})

    def test_replay_conflict_and_stale_append_leave_no_partial_delta(self):
        first = self.handler.execute(self.create)
        replay = self.handler.execute(self.create)
        self.assertEqual(replay, first)
        self.assertEqual(len(self.store.list_events()), 1)
        with self.assertRaises(Exception) as conflict:
            self.handler.execute(self.handler.build_create_document(context("create", digest="b" * 64), self.doc, self.initial))
        self.assertIn("changed request digest", str(conflict.exception))

        updated = ContentRevision(self.doc.ref, "rev-2", {"title": "Edited"}, actor(), parent_revision="rev-1")
        self.handler.execute(self.handler.build_append_revision(context("append", revision="rev-1", version=1), self.doc, updated))
        stale = ContentRevision(self.doc.ref, "rev-3", {"title": "Stale"}, actor(), parent_revision="rev-1")
        with self.assertRaises(Exception):
            self.handler.execute(self.handler.build_append_revision(context("stale", revision="rev-1", version=1), self.doc, stale))
        self.assertEqual(self.handler.read(self.doc.ref)["revision"]["content"], {"title": "Edited"})
        self.assertIsNone(self.store.get_receipt("stale"))

    def test_revision_row_failure_rolls_back_head_event_and_receipt(self):
        self.handler.execute(self.create)
        collision = revision_identity(self.doc.ref, "rev-2")
        self.store.put_identity(collision, {"record_type": "foreign", "value": True})
        attempted = ContentRevision(self.doc.ref, "rev-2", {"title": "Edited"}, actor(), parent_revision="rev-1")
        with self.assertRaises(StoreError):
            self.handler.execute(self.handler.build_append_revision(context("rollback", revision="rev-1", version=1), self.doc, attempted))
        self.assertEqual(self.handler.read(self.doc.ref)["current_revision"]["revision"], "rev-1")
        self.assertIsNone(self.store.get_receipt("rollback"))
        self.assertEqual(len(self.store.list_events()), 1)

    def test_imported_content_never_gets_a_local_revision_command(self):
        imported = document(
            source_ref=ref("runtime.document", "runtime-1", "runtime-rev-4", "runtime"),
            import_mode="pinned", writable=False, access_mode="read",
        )
        with self.assertRaises(ValueError):
            self.handler.build_create_document(context("import"), imported, revision(imported))


if __name__ == "__main__":
    unittest.main()
