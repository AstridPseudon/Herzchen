from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path
import tempfile
import unittest

from herzchen.authoring.sessions import BaseRevisionMismatchError, InvalidSessionError
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, DocumentAssociation
from herzchen.content.authoring import (
    DocumentAuthoringHandler,
    SchemaValidationError,
    ScopeAuthorizationError,
)
from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
from herzchen.kernel import Store
from herzchen.authoring.sessions import register_authoring
from herzchen.content.model import domain_contribution


AUTHORITY = "dat-store"


def ref(kind: str, ident: str, revision: str | None = None) -> ResourceRef:
    return ResourceRef(AUTHORITY, kind, ident, revision)


def actor(name: str = "author") -> AuthenticatedActor:
    return AuthenticatedActor("auth", name, "credential-" + name)


def document(ident: str, *, visibility: str = "private", scope: ResourceRef | None = None) -> ContentDocument:
    return ContentDocument(
        ref("project.specification", ident),
        "specification",
        visibility,
        "append",
        "curator",
        authoring_scope=scope,
    )


class DocumentAuthoringContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store.create(Path(self.tempdir.name) / "content.sqlite", authority=AUTHORITY)
        self.store.register_domain_handler((domain_contribution(),))
        register_authoring(self.store)
        self.handler = DocumentAuthoringHandler(self.store)
        self.content = ContentCommandHandler(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def seed(self, doc: ContentDocument, content: object = None) -> None:
        content = {"title": doc.ref.id} if content is None else content
        revision = ContentRevision(doc.ref, "rev-1", content, actor("seed"), initial=True)
        context = TransactionContext(actor("seed"), "seed-" + doc.ref.id, "a" * 64, expected_version=0)
        self.content.execute(self.content.build_create_document(context, doc, revision))

    def open(self, target: ResourceRef | ContentDocument, name: str = "author", request: str = "open"):
        return self.handler.materialise(target, actor(name), request_id=request, initial_content={"title": "initial"})

    def test_private_shared_and_standalone_scope_resolution_and_fresh_refs(self) -> None:
        project = ref("project", "project-1")
        private = document("private", scope=project)
        shared = document("shared", visibility="shared", scope=project)
        standalone = document("standalone")
        for item in (private, shared, standalone):
            self.seed(item)

        self.assertEqual(self.handler.resolve_scope(private), project)
        self.assertEqual(self.handler.resolve_scope(shared), ref("document", "shared"))
        self.assertEqual(self.handler.resolve_scope(standalone), ref("document", "standalone"))
        materialised = self.open(private, request="private-open")
        self.assertEqual(materialised.scope, project)
        self.assertEqual(self.handler.read(private.ref)["content"]["current_revision"]["revision"], "rev-1")
        self.assertEqual(self.handler.read(private.ref)["scope"], project)
        same_actor_other_scope = self.open(shared, request="same-actor-conflict")
        self.assertEqual(same_actor_other_scope.open_result.status, "actor_occupied")
        self.handler.authoring.release(materialised.handle, request_id="private-release")

        shared_open = self.open(shared, request="shared-open", name="shared-author")
        self.assertEqual(shared_open.scope, ref("document", "shared"))
        with self.assertRaises(ScopeAuthorizationError):
            self.handler.apply(ref("project", "project-1"), {"document": shared, "content": {"title": "wrong scope"}}, actor=actor("shared-author"), handle=shared_open.handle, request_id="wrong-shared", expected_base_revision=shared_open.handle.base_revision)
        self.handler.authoring.release(shared_open.handle, request_id="shared-release")
        standalone_open = self.open(standalone, request="standalone-open")
        self.assertEqual(standalone_open.scope, ref("document", "standalone"))

    def test_occupied_parent_denies_direct_bypass_but_read_continues(self) -> None:
        project = ref("project", "project-occupied")
        doc = document("child", scope=project)
        self.seed(doc)
        holder = self.open(doc, "holder", "holder-open")
        blocked = self.open(doc, "other", "other-open")
        self.assertEqual(blocked.open_result.status, "occupied")
        read = self.handler.read(doc.ref, actor("other"))
        self.assertEqual(read["authoring"].status, "occupied")
        self.assertEqual(read["content"]["revision"]["content"], {"title": "child"})
        with self.assertRaises(ScopeAuthorizationError):
            self.handler.materialise(doc, actor("other"), request_id="wrong-parent", parent_scope=ref("project", "other"))
        with self.assertRaises(InvalidSessionError):
            self.handler.apply(holder, {"content": {"title": "forged"}}, request_id="forged", token="copied-token")
        with self.assertRaises(InvalidSessionError):
            stale = replace(holder.handle, session_id="stale-session")
            self.handler.apply(holder.target, {"content": {"title": "stale"}}, actor=actor("holder"), handle=stale, request_id="stale-session")
        with self.assertRaises(ScopeAuthorizationError):
            self.handler.apply(holder, {"content": {"title": "wrong-actor"}}, actor=actor("other"), request_id="wrong-actor")

    def test_new_document_revision_and_multiple_links_are_one_atomic_batch_and_unlink_preserves_history(self) -> None:
        project = ref("project", "project-batch")
        doc = document("batch-doc", scope=project)
        materialised = self.open(project, request="batch-open")
        draft = {
            "document": doc,
            "content": {"title": "new", "body": "text"},
            "links": [
                {"subject": project, "namespace": "project.documents", "key": "spec"},
                {"subject": ref("task", "task-1"), "namespace": "work.documents", "key": "spec"},
            ],
        }
        applied = self.handler.apply_project_sheet(project, draft, actor=actor(), handle=materialised.handle, request_id="batch")
        self.assertEqual(applied.document.ref, doc.ref)
        self.assertEqual(applied.revision.revision, "rev-" + applied.revision.content_digest[:24])
        self.assertEqual(len(applied.links), 2)
        for link in applied.links:
            self.assertEqual(link.document.ref, doc.ref)
            self.assertTrue(self.handler.read(ref("document-association", link.identity))["association"]["association"]["document"])

        unlinked = self.handler.unlink(applied.links[0], actor(), request_id="unlink", handle=materialised.handle)
        self.assertEqual(unlinked.status.value, "committed")
        self.assertEqual(self.handler.read(doc.ref)["content"]["revision"]["content"], draft["content"])
        self.assertEqual(self.handler.read(applied.revision.ref)["content"]["content"], draft["content"])
        self.assertFalse(self.handler.content.read(ref("document-association", applied.links[0].identity))["payload"]["active"])
        self.assertTrue(self.handler.content.read(ref("document-association", applied.links[1].identity))["payload"]["active"])

    def test_injected_mid_batch_failure_rolls_back_document_revision_links_receipts_and_events(self) -> None:
        project = ref("project", "project-atomic")
        doc = document("atomic-doc", scope=project)
        materialised = self.open(project, request="atomic-open")
        original = self.store.mutate
        calls = {"links": 0}

        def fail_on_second_link(envelope, **kwargs):
            if envelope.operation == "dat.content.link":
                calls["links"] += 1
                if calls["links"] == 2:
                    raise RuntimeError("injected mid-batch failure")
            return original(envelope, **kwargs)

        self.store.mutate = fail_on_second_link  # type: ignore[method-assign]
        draft = {
            "document": doc,
            "content": {"title": "must rollback"},
            "links": [
                {"subject": project, "namespace": "project.documents", "key": "a"},
                {"subject": ref("task", "task-2"), "namespace": "work.documents", "key": "b"},
            ],
        }
        with self.assertRaises(RuntimeError):
            self.handler.apply_project_sheet(project, draft, actor=actor(), handle=materialised.handle, request_id="atomic")
        self.assertEqual(self.handler.content.read(doc.ref), {})
        self.assertEqual(len(self.store.list_events()), 2)  # only authoring open + actor.open
        self.assertIsNone(self.store.get_receipt("atomic:document"))
        self.assertIsNone(self.store.get_receipt("atomic:link:0"))

    def test_direct_and_disk_finish_share_schema_validation_and_valid_finish_persists_before_cleanup(self) -> None:
        doc = document("finish-doc")
        self.seed(doc)
        direct = self.open(doc, request="direct-open")
        with self.assertRaises(SchemaValidationError) as direct_error:
            self.handler.apply(direct, {"content": {"title": "bad"}, "unknown": True}, request_id="direct-bad")
        self.handler.authoring.release(direct.handle, request_id="direct-release")

        disk = self.open(doc, "disk", "disk-open")
        path = Path(self.tempdir.name) / "draft.json"
        path.write_text('{"content":{"title":"disk"}}', encoding="utf-8")
        cleaned: list[bytes] = []

        def cleanup(value, *, snapshot):
            cleaned.append(Path(value).read_bytes())
            Path(value).unlink()

        finished = self.handler.finish(disk, request_id="disk-finish", path=path, cleanup=cleanup)
        self.assertIsNotNone(finished.applied)
        self.assertEqual(cleaned, [b'{"content":{"title":"disk"}}'])
        self.assertFalse(path.exists())
        self.assertIsNotNone(finished.fresh_snapshot)
        self.assertEqual(self.handler.read(doc.ref)["content"]["revision"]["content"], {"title": "disk"})
        self.assertEqual(str(direct_error.exception), "schema error: unknown draft fields: unknown")

    def test_malformed_disk_draft_is_recoverable_and_does_not_mutate_content(self) -> None:
        doc = document("malformed")
        self.seed(doc)
        materialised = self.open(doc, request="malformed-open")
        path = Path(self.tempdir.name) / "malformed.json"
        raw = b'{"content": [not-json]}'
        path.write_bytes(raw)
        result = self.handler.finish(materialised, request_id="malformed-finish", path=path)
        self.assertTrue(result.temporary_preserved)
        self.assertTrue(path.exists())
        self.assertTrue(result.schema_errors)
        self.assertEqual(self.handler.read(doc.ref)["content"]["revision"]["content"], {"title": "malformed"})
        self.assertIsNotNone(result.finish.final_snapshot)
        self.assertEqual(self.handler.authoring.read_snapshot(result.finish.final_snapshot.ref), raw)  # type: ignore[union-attr]

    def test_replay_changed_key_stale_base_and_pinned_materialisation(self) -> None:
        doc = document("replay")
        self.seed(doc)
        materialised = self.open(doc, request="replay-open")
        first = self.handler.apply(materialised, {"content": {"title": "same"}}, request_id="same")
        replay = self.handler.apply(materialised, {"content": {"title": "same"}}, request_id="same")
        self.assertEqual(replay.receipts, first.receipts)
        with self.assertRaises(Exception) as conflict:
            self.handler.apply(materialised, {"content": {"title": "changed"}}, request_id="same")
        self.assertIn("changed request digest", str(conflict.exception))
        with self.assertRaises(BaseRevisionMismatchError):
            self.handler.apply(materialised, {"content": {"title": "stale"}}, request_id="stale", expected_base_revision="old")

        pinned = first.revision.ref
        self.assertEqual(self.handler.read(pinned)["content"]["content"], {"title": "same"})

    def test_no_private_writer_sql_ddl_or_product_import_and_no_prose_interpreter(self) -> None:
        source = Path(inspect.getsourcefile(DocumentAuthoringHandler)).read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("CREATE TABLE", source)
        self.assertNotIn("astrid", source.lower())
        self.assertNotIn("runtime", source.lower())
        self.assertNotIn("eval(", source)
        self.assertNotIn("exec(", source)


if __name__ == "__main__":
    unittest.main()
