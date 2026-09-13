from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Optional

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    ResourceRef,
    TransactionContext,
    ReplayConflictError,
    ReceiptStatus,
)
from herzchen.kernel import (
    COMPOSITION,
    SCHEMA_FINGERPRINT,
    SCHEMA_REVISION,
    ClosedStoreError,
    CompositionMismatchError,
    SchemaMismatchError,
    Store,
    TargetMismatchError,
    WriterBusyError,
)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "neutral.sqlite3"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def actor(self) -> AuthenticatedActor:
        return AuthenticatedActor("neutral-auth", "actor-1", "credential-1")

    def envelope(self, key: str = "request-1", digest: str = "a" * 64, *, target: Optional[ResourceRef] = None, version: Optional[int] = 0, revision: Optional[str] = None) -> CommandEnvelope:
        target = target or ResourceRef("neutral-store", "record", "record-1", revision)
        context = TransactionContext(self.actor(), key, digest, expected_revision=revision, expected_version=version, edit_token="edit-1", correlation_id="corr-1")
        return CommandEnvelope("record.update", "record.v1", target, context, {"value": key})

    def admitted(self) -> Store:
        store = Store.create(self.db)
        store.put_identity(ResourceRef("neutral-store", "record", "record-1"), {"value": "initial"}, version=0, edit_token="edit-1")
        return store

    def test_create_open_fingerprint_composition_and_foreign_keys(self) -> None:
        store = Store.create(self.db)
        self.assertTrue(store.foreign_keys_enabled())
        tables = tuple(row[0] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        self.assertEqual(tables, tuple(sorted(COMPOSITION)))
        metadata = dict(store.connection.execute("SELECT key, value FROM store_metadata"))
        self.assertEqual(metadata["schema_revision"], SCHEMA_REVISION)
        self.assertEqual(metadata["schema_fingerprint"], SCHEMA_FINGERPRINT)
        store.close()
        reopened = Store.open(self.db)
        self.assertTrue(reopened.foreign_keys_enabled())
        reopened.close()

    def test_open_refuses_unknown_or_missing_composition_without_repair(self) -> None:
        store = Store.create(self.db)
        store.close()
        connection = sqlite3.connect(self.db)
        connection.execute("CREATE TABLE unexpected (value TEXT)")
        connection.commit()
        connection.close()
        with self.assertRaises(CompositionMismatchError):
            Store.open(self.db)
        connection = sqlite3.connect(self.db)
        self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='unexpected'").fetchone())
        connection.close()

    def test_open_refuses_fingerprint_mismatch(self) -> None:
        store = Store.create(self.db)
        store.connection.execute("UPDATE store_metadata SET value='wrong' WHERE key='schema_fingerprint'")
        store.close()
        with self.assertRaises(SchemaMismatchError):
            Store.open(self.db)

    def test_durable_writer_race_is_rejected(self) -> None:
        first = Store.create(self.db)
        outcome = []
        ready = threading.Event()

        def contender() -> None:
            ready.set()
            try:
                Store.open(self.db)
            except WriterBusyError:
                outcome.append("busy")

        thread = threading.Thread(target=contender)
        thread.start()
        ready.wait(2)
        thread.join(2)
        first.close()
        self.assertEqual(outcome, ["busy"])

    def test_nested_savepoint_rolls_back_only_failed_unit(self) -> None:
        store = Store.create(self.db)
        first = ResourceRef("neutral-store", "record", "first")
        second = ResourceRef("neutral-store", "record", "second")
        with store.transaction() as tx:
            store.put_identity(first, {"kept": True}, transaction=tx)
            try:
                with tx.savepoint():
                    store.put_identity(second, {"discard": True}, transaction=tx)
                    raise ValueError("failed unit")
            except ValueError:
                pass
            store.put_identity(ResourceRef("neutral-store", "record", "third"), {"outer": True}, transaction=tx)
        self.assertIsNotNone(store.get_identity(first))
        self.assertIsNone(store.get_identity(second))
        self.assertIsNotNone(store.get_identity(ResourceRef("neutral-store", "record", "third")))
        store.close()

    def test_mutation_is_atomic_and_replay_is_exact(self) -> None:
        store = self.admitted()
        first = store.mutate(self.envelope(), event_type="record.updated", effects={"changed": ["value"]})
        self.assertEqual(first.status, ReceiptStatus.COMMITTED)
        self.assertEqual(first, store.get_receipt("request-1"))
        self.assertEqual(len(store.list_events()), 1)
        event = store.list_events()[0]
        self.assertEqual(event.sequence, 1)
        self.assertEqual(event.before_refs, ())
        replay = store.mutate(self.envelope(), event_type="record.updated", effects={"different": True})
        self.assertEqual(replay, first)
        with self.assertRaises(ReplayConflictError):
            store.mutate(self.envelope(digest="b" * 64), event_type="record.updated")
        self.assertEqual(len(store.list_events()), 1)
        store.close()
        reopened = Store.open(self.db)
        self.assertEqual(reopened.get_receipt("request-1"), first)
        self.assertEqual(reopened.list_events()[0].event_id, first.event_ids[0])
        reopened.close()

    def test_expected_target_mismatch_leaves_no_receipt_or_event(self) -> None:
        store = self.admitted()
        bad = self.envelope(target=ResourceRef("neutral-store", "record", "record-1", "wrong"), revision="wrong")
        with self.assertRaises(TargetMismatchError):
            store.mutate(bad, event_type="record.updated")
        self.assertIsNone(store.get_receipt("request-1"))
        self.assertEqual(store.list_events(), ())
        store.close()

    def test_noop_is_explicit_and_has_no_event(self) -> None:
        store = self.admitted()
        receipt = store.mutate(self.envelope(key="noop", digest="c" * 64), event_type="record.updated", no_op=True)
        self.assertEqual(receipt.status, ReceiptStatus.NOOP)
        self.assertEqual(receipt.event_ids, ())
        self.assertEqual(store.list_events(), ())
        store.close()

    def test_foreign_keys_are_enforced_on_every_connection(self) -> None:
        store = Store.create(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            store.connection.execute(
                "INSERT INTO record_references(reference_key, authority, kind, id, revision, reference_json) VALUES (?, ?, ?, ?, ?, ?)",
                ("bad", "neutral-store", "missing", "missing", None, "{}"),
            )
        self.assertEqual(store.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        store.close()

    def test_closed_store_rejects_admission(self) -> None:
        store = Store.create(self.db)
        store.close()
        with self.assertRaises(ClosedStoreError):
            store.foreign_keys_enabled()
        with self.assertRaises(ClosedStoreError):
            store.get_receipt("missing")

    def test_kernel_import_boundary_has_no_optional_domain_modules(self) -> None:
        source_root = str(Path(__file__).resolve().parents[2] / "src")
        code = "import sys; import herzchen.kernel; assert not any(x.startswith(('otto', 'astrid', 'runtime_protocol')) for x in sys.modules); print('boundary-ok')"
        result = subprocess.run([sys.executable, "-B", "-c", code], env={"PYTHONPATH": source_root}, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "boundary-ok")


if __name__ == "__main__":
    unittest.main()
