from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from herzchen.contracts import AuthenticatedActor, CommandEnvelope, DomainContribution, ResourceRef, TransactionContext
from herzchen.kernel import (
    COMPOSITION,
    SCHEMA_FINGERPRINT,
    CursorExpiredError,
    CursorMalformedError,
    CursorScopeError,
    EventCursorReader,
    EventFilter,
    IntervalController,
    RecoveryManager,
    SnapshotError,
    SnapshotValidationError,
    StaleTokenError,
    Store,
    RestoreActivationError,
    create_snapshot,
    restore_snapshot,
    verify_restore_candidate,
)


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = self.root / "state.sqlite3"
        self.store = Store.create(self.db)
        self.fixture_domain = DomainContribution(
            "recovery-cursor-fixture", "1", "neutral-owner", ("item",), (), (),
            ("item.update",), ("item.updated",), "item.v1",
            ("handler:tests.kernel.recovery-cursor",),
        )
        self.store.register_domain(self.fixture_domain)
        self.actor = AuthenticatedActor("neutral-auth", "agent-1", "credential-1")
        self.source = ResourceRef("source-authority", "source", "checkout", "source-v1")
        self.realm = ResourceRef("neutral-store", "realm", "realm-1", "realm-v1")

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    @staticmethod
    def composition_digest() -> str:
        return hashlib.sha256(json.dumps(sorted(COMPOSITION), separators=(",", ":")).encode("utf-8")).hexdigest()

    def append(self, number: int, visibility: str = "public") -> None:
        target = ResourceRef("neutral-store", "item", "item-{}".format(number))
        digest = hashlib.sha256("request-{}".format(number).encode("utf-8")).hexdigest()
        envelope = CommandEnvelope(
            "item.update", "item.v1", target,
            TransactionContext(self.actor, "request-{}".format(number), digest, expected_version=0),
            {"number": number},
        )
        self.store.mutate(
            envelope,
            event_type="item.updated",
            effects={"visibility": visibility, "number": number},
            stream="items",
        )

    def snapshot_kwargs(self):
        return {
            "expected_source_identity": self.source,
            "expected_realm_identity": self.realm,
            "expected_authority": "neutral-store",
            "expected_composition": COMPOSITION,
            "expected_composition_digest": self.composition_digest(),
            "expected_schema_fingerprint": SCHEMA_FINGERPRINT,
        }

    def test_snapshot_has_consistent_db_external_bytes_and_event_watermark(self) -> None:
        self.append(1)
        payload = b"exact cas bytes\x00\xff"
        external = ResourceRef("external-authority", "object", "object-1", "digest-v1")
        snapshot = create_snapshot(
            self.store,
            self.root / "snapshot",
            source_identity=self.source,
            realm_identity=self.realm,
            external_refs=(external,),
            object_files={external: payload},
        )
        self.assertEqual(snapshot.event_watermarks, {"items": 1})
        self.assertEqual(snapshot.composition_digest, self.composition_digest())
        object_digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual((self.root / "snapshot" / "objects" / object_digest).read_bytes(), payload)
        loaded = json.loads((self.root / "snapshot" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(loaded["database_digest"], hashlib.sha256((self.root / "snapshot" / "database.sqlite3").read_bytes()).hexdigest())
        self.assertEqual(loaded["schema_fingerprint"], SCHEMA_FINGERPRINT)

    def test_interrupted_snapshot_leaves_partial_evidence_and_damaged_target_untouched(self) -> None:
        partial = self.root / "partial"
        with self.assertRaises(Exception):
            create_snapshot(
                self.store,
                partial,
                source_identity=self.source,
                realm_identity=self.realm,
                object_files={"missing": self.root / "does-not-exist"},
            )
        self.assertTrue((partial / "database.sqlite3").exists())
        damaged = self.root / "damaged-target"
        damaged.mkdir()
        marker = damaged / "preserve.bin"
        marker.write_bytes(b"do not overwrite")
        create_snapshot(self.store, self.root / "snapshot", source_identity=self.source, realm_identity=self.realm)
        with self.assertRaises(RestoreActivationError):
            restore_snapshot(
                self.root / "snapshot", damaged, candidate_root=self.root / "candidate-preserved", **self.snapshot_kwargs()
            )
        self.assertEqual(marker.read_bytes(), b"do not overwrite")
        self.assertTrue((self.root / "candidate-preserved" / "database.sqlite3").exists())

    def test_restore_verifies_unused_candidate_and_requires_caller_identities_digest(self) -> None:
        self.append(1)
        create_snapshot(self.store, self.root / "snapshot", source_identity=self.source, realm_identity=self.realm)
        candidate = verify_restore_candidate(self.root / "snapshot", self.root / "candidate", **self.snapshot_kwargs())
        self.assertEqual(candidate.database_path, self.root / "candidate" / "database.sqlite3")
        restored = Store.open(candidate.database_path, expected_domains=(self.fixture_domain,))
        try:
            self.assertEqual([event.event_id for event in restored.list_events(stream="items")], [event.event_id for event in self.store.list_events(stream="items")])
        finally:
            restored.close()
        with self.assertRaises(SnapshotValidationError):
            verify_restore_candidate(
                self.root / "snapshot", self.root / "wrong-source",
                **dict(self.snapshot_kwargs(), expected_source_identity=ResourceRef("other", "source", "x", "v")),
            )
        with self.assertRaises(SnapshotValidationError):
            verify_restore_candidate(
                self.root / "snapshot", self.root / "wrong-digest",
                **dict(self.snapshot_kwargs(), expected_composition_digest="0" * 64),
            )

    def test_snapshot_restores_fresh_public_reads_for_wal_mutation(self) -> None:
        self.assertEqual(str(self.store.connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower(), "wal")
        self.append(11)
        target = ResourceRef("neutral-store", "item", "item-11")
        source_identity = self.store.get_identity(target)
        source_receipt = self.store.get_receipt("request-11")
        source_events = self.store.list_events(stream="items")
        self.assertIsNotNone(source_identity)
        self.assertIsNotNone(source_receipt)
        self.assertEqual(len(source_events), 1)
        refs = {target.to_json(): target}
        for event in source_events:
            for ref in event.before_refs + event.after_refs:
                refs[ref.to_json()] = ref
        for ref in refs.values():
            self.assertIsNotNone(self.store.get_reference(ref))
        create_snapshot(self.store, self.root / "snapshot", source_identity=self.source, realm_identity=self.realm)
        candidate = verify_restore_candidate(self.root / "snapshot", self.root / "candidate", **self.snapshot_kwargs())
        restored = Store.open(candidate.database_path, authority="neutral-store", expected_domains=self.store.registered_domains())
        try:
            self.assertEqual(restored.get_identity(target), source_identity)
            self.assertEqual(restored.get_receipt("request-11"), source_receipt)
            self.assertEqual(restored.list_events(stream="items"), source_events)
            for ref in refs.values():
                self.assertEqual(restored.get_reference(ref), self.store.get_reference(ref))
        finally:
            restored.close()

    def test_snapshot_rejects_source_or_external_file_change_and_preserves_partial_evidence(self) -> None:
        external = self.root / "external.bin"
        external.write_bytes(b"before")
        original_copy = __import__("herzchen.kernel.recovery", fromlist=["_copy_exact"])._copy_exact

        def replace_source_after_copy(source, target, *args):
            result = original_copy(source, target, *args)
            if source == self.db:
                replacement = self.root / "replacement.sqlite3"
                replacement.write_bytes(b"replaced")
                replacement.replace(self.db)
            return result

        with patch("herzchen.kernel.recovery._copy_exact", side_effect=replace_source_after_copy):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.store, self.root / "source-replaced", source_identity=self.source, realm_identity=self.realm)
        self.assertTrue((self.root / "source-replaced" / "database.sqlite3").exists())

        def change_external_after_copy(source, target, *args):
            result = original_copy(source, target, *args)
            if source == external:
                external.write_bytes(b"after")
            return result

        with patch("herzchen.kernel.recovery._copy_exact", side_effect=change_external_after_copy):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.store, self.root / "external-changed", source_identity=self.source, realm_identity=self.realm, object_files={"external": external})
        self.assertTrue((self.root / "external-changed" / "database.sqlite3").exists())

        sidecar = Path(str(self.db) + "-wal")

        def create_raw_sidecar_after_copy(source, target, *args):
            result = original_copy(source, target, *args)
            if source == self.db:
                sidecar.write_bytes(b"raw writer evidence")
            return result

        with patch("herzchen.kernel.recovery._copy_exact", side_effect=create_raw_sidecar_after_copy):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.store, self.root / "raw-sidecar", source_identity=self.source, realm_identity=self.realm)
        self.assertTrue((self.root / "raw-sidecar" / "database.sqlite3").exists())

    def test_restore_rejects_dangling_symlink_non_directory_and_symlink_parent_roots(self) -> None:
        create_snapshot(self.store, self.root / "snapshot", source_identity=self.source, realm_identity=self.realm)
        dangling = self.root / "dangling-candidate"
        dangling.symlink_to(self.root / "missing")
        with self.assertRaises(RestoreActivationError):
            verify_restore_candidate(self.root / "snapshot", dangling, **self.snapshot_kwargs())
        non_directory = self.root / "file-candidate"
        non_directory.write_bytes(b"occupied")
        with self.assertRaises(RestoreActivationError):
            verify_restore_candidate(self.root / "snapshot", non_directory, **self.snapshot_kwargs())
        symlink_parent = self.root / "symlink-parent"
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        symlink_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(RestoreActivationError):
            verify_restore_candidate(self.root / "snapshot", symlink_parent / "candidate", **self.snapshot_kwargs())
        target = self.root / "dangling-target"
        target.symlink_to(self.root / "missing-target")
        with self.assertRaises(RestoreActivationError):
            restore_snapshot(self.root / "snapshot", target, candidate_root=self.root / "preserved-candidate", **self.snapshot_kwargs())
        self.assertTrue((self.root / "preserved-candidate" / "database.sqlite3").exists())
        occupied_target = self.root / "occupied-target"
        occupied_target.write_bytes(b"preserve")
        with self.assertRaises(RestoreActivationError):
            restore_snapshot(self.root / "snapshot", occupied_target, candidate_root=self.root / "preserved-file-target-candidate", **self.snapshot_kwargs())
        self.assertEqual(occupied_target.read_bytes(), b"preserve")
        self.assertTrue((self.root / "preserved-file-target-candidate" / "database.sqlite3").exists())

    def test_corrupt_snapshot_database_is_rejected_without_repair(self) -> None:
        create_snapshot(self.store, self.root / "snapshot", source_identity=self.source, realm_identity=self.realm)
        database = self.root / "snapshot" / "database.sqlite3"
        original = database.read_bytes()
        database.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaises(SnapshotValidationError):
            verify_restore_candidate(self.root / "snapshot", self.root / "candidate", **self.snapshot_kwargs())
        self.assertNotEqual(database.read_bytes(), original)

    def test_epoch_retires_stale_token_before_external_or_durable_result_mutation(self) -> None:
        manager = RecoveryManager(self.store, self.source, self.realm)
        manager.begin_epoch("boot-1")
        token = manager.issue_token(ResourceRef("neutral-store", "operation", "operation-1"))
        manager.begin_epoch("boot-2")
        called = []
        with self.assertRaises(StaleTokenError):
            manager.settle(token, logical_request_key="settle-stale", apply=lambda: called.append("mutated"))
        self.assertEqual(called, [])
        self.assertIsNone(self.store.get_receipt("settle-stale"))
        retained = manager.retain_unknown_operation(ResourceRef("neutral-store", "operation", "unknown-1"), {"observed": "timeout"})
        self.assertEqual(retained.payload["record_type"], "unknown-operation")
        self.assertEqual(manager.current().tokens[0].status, "retired")

        manager.begin_epoch("boot-3")
        active = manager.issue_token(ResourceRef("neutral-store", "operation", "known-1"))
        settled = manager.settle(
            active,
            logical_request_key="settle-known",
            result_ref=ResourceRef("neutral-store", "result", "result-1", "result-v1"),
            result={"state": "committed"},
        )
        self.assertEqual(settled.token.status, "settled")
        durable = manager.current().tokens[-1]
        self.assertEqual(durable.result_ref, settled.result_ref)
        self.assertEqual(durable.result, {"state": "committed"})

    def test_bounded_cursor_is_deterministic_scope_checked_and_filter_explicit(self) -> None:
        self.append(1, "public")
        self.append(2, "private")
        self.append(3, "public")
        reader = EventCursorReader(self.store)
        first = reader.page("items", limit=1)
        repeated = reader.page("items", limit=1)
        self.assertEqual([event.event_id for event in first.events], [event.event_id for event in repeated.events])
        second = reader.page("items", cursor=first.next_cursor, limit=1)
        self.assertEqual(second.events[0].sequence, 3)
        public = reader.page("items", event_filter=EventFilter(visibility=("public",)), limit=10)
        self.assertEqual([event.sequence for event in public.events], [1, 3])
        with self.assertRaises(CursorScopeError):
            reader.page("other-stream", cursor=first.next_cursor, limit=1)
        with self.assertRaises(CursorScopeError):
            reader.page("items", cursor=first.next_cursor, event_filter=EventFilter(visibility=("private",)), limit=1)
        with self.assertRaises(CursorMalformedError):
            reader.page("items", cursor="not-a-cursor", limit=1)

    def test_restart_catchup_and_gap_are_explicit_and_do_not_scan_full_transcript(self) -> None:
        for number in (1, 2, 3):
            self.append(number)
        reader = EventCursorReader(self.store)
        first = reader.page("items", limit=1)
        cursor = first.cursor
        self.store.close()
        self.store = Store.open(self.db, expected_domains=(self.fixture_domain,))
        restarted = EventCursorReader(self.store)
        after_restart = restarted.catch_up("items", cursor=cursor, limit=10)
        self.assertEqual([event.sequence for event in after_restart.events], [2, 3])
        duplicate = restarted.catch_up("items", cursor=cursor, limit=10)
        self.assertEqual([event.event_id for event in duplicate.events], [event.event_id for event in after_restart.events])
        self.store.connection.execute("DELETE FROM events WHERE stream = 'items' AND sequence = 2")
        gap = restarted.catch_up("items", cursor=cursor, limit=10)
        self.assertEqual(gap.status, "gap")
        self.assertEqual((gap.gap_from, gap.gap_to), (2, 2))
        self.assertEqual([event.sequence for event in gap.events], [3])

    def test_expired_cursor_is_rejected_and_committed_effect_is_visible_without_notification(self) -> None:
        self.append(1)
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        reader = EventCursorReader(self.store, cursor_ttl_seconds=10, clock=lambda: now[0])
        page = reader.page("items", limit=1)
        now[0] += timedelta(seconds=11)
        with self.assertRaises(CursorExpiredError):
            reader.page("items", cursor=page.cursor, limit=1)
        # There is no notification/subscription dependency: the committed
        # event is discoverable through a fresh authoritative read.
        self.assertEqual(len(EventCursorReader(self.store).page("items", limit=10).events), 1)

    def test_interval_anchor_persists_missed_slots_coalesces_and_allows_one_request(self) -> None:
        clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        ref = ResourceRef("neutral-store", "attention-interval", "optimisation")
        controller = IntervalController(self.store, ref, 3 * 60 * 60, clock=lambda: clock[0])
        started = controller.start()
        self.assertEqual(started.anchor, "2026-01-01T00:00:00.000000Z")
        due = controller.poll(now=clock[0] + timedelta(hours=3))
        self.assertTrue(due.due)
        again = controller.poll(now=clock[0] + timedelta(hours=12))
        self.assertEqual(again.request_id, due.request_id)
        self.assertGreaterEqual(again.missed_intervals, 2)
        restarted = IntervalController(self.store, ref, 3 * 60 * 60, clock=lambda: clock[0])
        self.assertEqual(restarted.state().anchor, started.anchor)
        self.assertEqual(restarted.complete("unknown-call").in_flight, due.request_id)
        completed = restarted.complete(due.request_id)
        self.assertIsNone(completed.in_flight)
        next_request = restarted.poll(now=clock[0] + timedelta(hours=12))
        self.assertTrue(next_request.due)
        self.assertNotEqual(next_request.request_id, due.request_id)
        self.assertEqual(restarted.complete(due.request_id).in_flight, next_request.request_id)

    def test_kernel_recovery_has_no_product_specific_imports_or_second_event_composition(self) -> None:
        source = (Path(__file__).parents[2] / "src" / "herzchen" / "kernel" / "recovery.py").read_text(encoding="utf-8")
        for forbidden in ("otto", "astrid", "runtime_protocol", "sqlite3.connect"):
            self.assertNotIn(forbidden, source.lower())
        tables = tuple(row[0] for row in self.store.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        self.assertEqual(tables, tuple(sorted(COMPOSITION)))


if __name__ == "__main__":
    unittest.main()
