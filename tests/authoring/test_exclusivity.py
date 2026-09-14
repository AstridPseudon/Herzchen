from __future__ import annotations

import base64
import inspect
from pathlib import Path
import tempfile
import threading
import unittest

from herzchen.authoring.sessions import (
    AuthoringSessionService,
    BaseRevisionMismatchError,
    CleanupStatus,
    InvalidSessionError,
    Snapshot,
    register_authoring,
)
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel import Store


class ExclusivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store.create(Path(self.tempdir.name) / "neutral.sqlite3")
        register_authoring(self.store)
        self.service = AuthoringSessionService(self.store)
        self.scope = ResourceRef("neutral-store", "project", "project-1", "base-1")
        self.other_scope = ResourceRef("neutral-store", "project", "project-2", "base-1")
        self.actor = AuthenticatedActor("neutral-auth", "actor-1", "credential-1")
        self.other_actor = AuthenticatedActor("neutral-auth", "actor-2", "credential-2")

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def open(self, scope=None, actor=None, request_id="open"):
        return self.service.open(
            scope or self.scope,
            actor or self.actor,
            request_id=request_id,
            target_kind="project",
            base_revision="base-1",
            initial_content=b"initial project bytes",
            pending=True,
            allowed_fields=("title", "body"),
        )

    def open_with(self, service, scope, actor, request_id):
        return service.open(
            scope,
            actor,
            request_id=request_id,
            target_kind="project",
            base_revision="base-1",
            initial_content=b"initial project bytes",
            pending=True,
            allowed_fields=("title", "body"),
        )

    def durable_reservation_counts(self):
        identity_counts = dict(
            self.store.connection.execute(
                "SELECT kind, COUNT(*) FROM identities "
                "WHERE kind IN ('authoring-scope', 'authoring-actor', 'authoring-snapshot') "
                "GROUP BY kind"
            ).fetchall()
        )
        receipt_rows = [
            tuple(row)
            for row in self.store.connection.execute(
            "SELECT operation, status, COUNT(*) FROM command_receipts "
            "WHERE operation IN ('open', 'actor.open') GROUP BY operation, status ORDER BY operation, status"
            ).fetchall()
        ]
        event_rows = [
            tuple(row)
            for row in self.store.connection.execute(
            "SELECT event_type, COUNT(*) FROM events "
            "WHERE event_type IN ('authoring.open', 'authoring.actor.open') GROUP BY event_type ORDER BY event_type"
            ).fetchall()
        ]
        return identity_counts, receipt_rows, event_rows

    def test_racing_opens_have_one_holder_and_occupied_read_is_masked(self) -> None:
        results = []
        barrier = threading.Barrier(2)

        def contender(request_id: str) -> None:
            barrier.wait()
            results.append(self.open(request_id=request_id))

        first = threading.Thread(target=contender, args=("open-a",))
        second = threading.Thread(target=contender, args=("open-b",))
        first.start()
        second.start()
        first.join(2)
        second.join(2)
        self.assertEqual(sorted(result.status for result in results), ["occupied", "opened"])
        occupied = next(result for result in results if result.status == "occupied")
        self.assertIsNone(occupied.handle)
        self.assertIsNone(occupied.checkout)
        self.assertEqual(self.service.read(self.scope).status, "occupied")

    def test_two_services_race_same_scope_has_one_durable_reservation(self) -> None:
        service_a = AuthoringSessionService(self.store)
        service_b = AuthoringSessionService(self.store)
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def contender(service, request_id):
            try:
                barrier.wait()
                results.append(self.open_with(service, self.scope, self.actor, request_id))
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=contender, args=(service_a, "shared-scope-a"))
        second = threading.Thread(target=contender, args=(service_b, "shared-scope-b"))
        first.start()
        second.start()
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(result.status for result in results), ["occupied", "opened"])

        identity_counts, receipt_rows, event_rows = self.durable_reservation_counts()
        self.assertEqual(identity_counts, {"authoring-actor": 1, "authoring-scope": 1, "authoring-snapshot": 1})
        self.assertEqual(receipt_rows, [("actor.open", "committed", 1), ("open", "committed", 1)])
        self.assertEqual(event_rows, [("authoring.actor.open", 1), ("authoring.open", 1)])
        self.assertEqual(
            sum(self.store.get_receipt(key) is not None for key in ("shared-scope-a", "shared-scope-b")),
            1,
        )
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM command_receipts WHERE logical_request_key LIKE 'shared-scope-%:actor'").fetchone()[0], 1)

    def test_two_services_race_same_actor_across_scopes_has_no_partial_loser(self) -> None:
        service_a = AuthoringSessionService(self.store)
        service_b = AuthoringSessionService(self.store)
        scope_a = ResourceRef("neutral-store", "project", "race-project-a", "base-1")
        scope_b = ResourceRef("neutral-store", "project", "race-project-b", "base-1")
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def contender(service, scope, request_id):
            try:
                barrier.wait()
                results.append(self.open_with(service, scope, self.actor, request_id))
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=contender, args=(service_a, scope_a, "shared-actor-a"))
        second = threading.Thread(target=contender, args=(service_b, scope_b, "shared-actor-b"))
        first.start()
        second.start()
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(result.status for result in results), ["actor_occupied", "opened"])

        identity_counts, receipt_rows, event_rows = self.durable_reservation_counts()
        self.assertEqual(identity_counts, {"authoring-actor": 1, "authoring-scope": 1, "authoring-snapshot": 1})
        self.assertEqual(receipt_rows, [("actor.open", "committed", 1), ("open", "committed", 1)])
        self.assertEqual(event_rows, [("authoring.actor.open", 1), ("authoring.open", 1)])
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM identities WHERE kind = 'authoring-scope' AND id IN ('race-project-a', 'race-project-b')").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM command_receipts WHERE logical_request_key LIKE 'shared-actor-%'").fetchone()[0], 2)

    def test_cross_scope_progress_and_same_actor_occupancy(self) -> None:
        first = self.open()
        self.assertEqual(self.open(self.other_scope, self.other_actor, "other-open").status, "opened")
        third_scope = ResourceRef("neutral-store", "project", "project-3", "base-1")
        occupied = self.open(third_scope, self.actor, "actor-open")
        self.assertEqual(occupied.status, "actor_occupied")

        self.service.release(first.handle, request_id="release-1")
        self.assertEqual(self.open(self.other_scope, self.actor, "actor-open-retry").status, "occupied")

    def test_nested_target_resolves_to_parent_and_direct_bypass_is_rejected(self) -> None:
        result = self.service.open(
            ResourceRef("neutral-store", "document", "doc-1", "doc-rev"),
            self.actor,
            request_id="nested-open",
            parent_scope=self.scope,
            target_kind="document",
            base_revision="doc-rev",
        )
        self.assertEqual(result.status, "opened")
        self.assertEqual(result.handle.scope, ResourceRef("neutral-store", "authoring-scope", "project-1"))
        with self.assertRaises(InvalidSessionError):
            self.service.authorize_mutation(result.handle, self.scope, token="wrong", fence=result.handle.fence, expected_base_revision="doc-rev")

    def test_create_and_open_does_not_create_when_actor_is_occupied(self) -> None:
        self.open()
        called = []

        def create_project(*args, **kwargs):
            called.append(True)
            return {"id": "must-not-exist"}

        result = self.service.create_and_open(
            self.other_scope,
            self.actor,
            request_id="create-while-occupied",
            target_kind="project",
            create_project=create_project,
        )
        self.assertEqual(result.status, "actor_occupied")
        self.assertEqual(called, [])

    def test_materialization_failure_saves_project_and_releases(self) -> None:
        project = {"ref": ResourceRef("neutral-store", "project", "saved-1", "rev-1")}

        def create_project(*args, **kwargs):
            return project

        def materialize(*args, **kwargs):
            raise OSError("checkout parent vanished")

        result = self.service.create_and_open(
            self.other_scope,
            self.other_actor,
            request_id="create-fails",
            target_kind="project",
            create_project=create_project,
            materialize=materialize,
        )
        self.assertEqual(result.status, "saved_project_edit_not_opened")
        self.assertEqual(result.project_ref, project["ref"])
        self.assertEqual(self.service.read(self.other_scope).status, "available")
        saved = self.store.get_identity(ResourceRef("neutral-store", "authoring-scope", self.other_scope.id))
        self.assertEqual(saved.payload["project"]["ref"]["id"], project["ref"].id)

    def test_exact_snapshots_finish_claim_replay_and_reopen_new_turn(self) -> None:
        opened = self.open()
        draft = Snapshot(ResourceRef("neutral-store", "authoring-snapshot", "draft-exact", "digest-draft"), b"exact draft")
        self.service.autosave(opened.handle, request_id="autosave-exact", snapshot=draft)
        final = Snapshot(ResourceRef("neutral-store", "authoring-snapshot", "final-exact", "digest-final"), b"exact final")
        applied = []

        def apply(snapshot, checkout, **kwargs):
            applied.append((snapshot.ref, snapshot.data, checkout.finish_claim.finalization_identity))

        finished = self.service.finish(opened.handle, request_id="finish-exact", mode="manual", capture=final, apply=apply)
        self.assertEqual(finished.status, "finished")
        self.assertEqual(applied, [(final.ref, final.data, "finish-" + opened.handle.session_id)])
        replay = self.service.finish(opened.handle, request_id="finish-exact", mode="manual", capture=final, apply=apply)
        self.assertEqual(replay.status, "replayed")
        self.assertEqual(len(applied), 1)
        alternate = self.service.finish(opened.handle, request_id="finish-idle-loser", mode="idle", capture=b"must-not-be-read", apply=apply)
        self.assertEqual(alternate.status, "already_finished")
        self.assertEqual(len(applied), 1)
        # A caller-supplied boolean/status is not writer ownership proof.  A
        # direct unfenced session finish therefore cannot record cleanup
        # complete; the lifecycle path supplies the authenticated held lease.
        self.assertEqual(self.service.cleanup(opened.handle, request_id="cleanup", status=CleanupStatus.COMPLETE).cleanup, CleanupStatus.UNSAFE)

        reopened = self.open(request_id="reopen")
        self.assertEqual(reopened.status, "opened")
        self.assertNotEqual(reopened.handle.session_id, opened.handle.session_id)
        self.assertNotEqual(reopened.handle.token, opened.handle.token)
        self.assertNotEqual(reopened.handle.fence, opened.handle.fence)

        record = self.store.get_identity(reopened.handle.scope)
        self.assertIsNotNone(record)
        self.assertEqual(base64.b64decode(record.payload["draft_bytes_b64"]), b"initial project bytes")
        self.assertEqual(self.store.get_identity(final.ref).payload["bytes_b64"], base64.b64encode(final.data).decode("ascii"))

    def test_idle_manual_share_claim_identity_and_stale_base_rejects(self) -> None:
        opened = self.open()
        result = self.service.finish(opened.handle, request_id="bad-base", mode="idle", capture=b"changed", expected_base_revision="wrong")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(self.service.read(self.scope).status, "available")
        with self.assertRaises(InvalidSessionError):
            self.service.autosave(opened.handle, request_id="late-write", snapshot=b"late")

    def test_import_boundary_has_no_sqlite_or_private_schema_writer(self) -> None:
        source = Path(inspect.getsourcefile(AuthoringSessionService)).read_text()
        self.assertNotIn("import sqlite3", source)
        self.assertNotIn("CREATE TABLE", source)
        self.assertNotIn("append_event", source)


if __name__ == "__main__":
    unittest.main()
