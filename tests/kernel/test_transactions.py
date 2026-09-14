from __future__ import annotations

import hashlib
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
    ContractError,
    DomainContribution,
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
    DescriptorDigestMismatchError,
    DescriptorExpectationMismatchError,
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
        store.register_domain(self.domain(resource="record", event="record.updated", operation="record.update", schema="record.v1"))
        return store

    def domain(self, domain_id: str = "example.domain", *, resource: str = "example.resource", document: str = "example.document", event: str = "example.updated", namespace: str = "example.namespace", operation: str = "example.update", schema: str = "example.v1") -> DomainContribution:
        return DomainContribution(
            domain_id,
            "1",
            "neutral-owner",
            (resource,),
            (document,),
            (namespace,),
            (operation,),
            (event,),
            schema,
        )

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

    def test_concurrent_public_reads_serialize_with_store_transaction(self) -> None:
        store = self.admitted()
        receipt = store.mutate(self.envelope(), event_type="record.updated", effects={"changed": ["value"]})
        ref = ResourceRef("neutral-store", "record", "record-1")
        barrier = threading.Barrier(3)
        errors = []

        def reader() -> None:
            try:
                for _ in range(50):
                    barrier.wait(timeout=5)
                    identity = store.get_identity(ref)
                    observed_receipt = store.get_receipt("request-1")
                    events = store.list_events()
                    self.assertIsNotNone(identity)
                    self.assertEqual(identity.ref.authority, "neutral-store")
                    self.assertEqual(identity.ref.kind, "record")
                    self.assertEqual(observed_receipt, receipt)
                    self.assertEqual(len(events), 1)
                    barrier.wait(timeout=5)
            except BaseException as exc:
                errors.append(exc)

        def writer() -> None:
            try:
                for _ in range(50):
                    barrier.wait(timeout=5)
                    with store.transaction() as transaction:
                        transaction.execute(
                            "UPDATE identities SET updated_at = updated_at WHERE authority = ? AND kind = ? AND id = ?",
                            ("neutral-store", "record", "record-1"),
                        )
                    barrier.wait(timeout=5)
            except BaseException as exc:
                errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(2)]
        writer = threading.Thread(target=writer)
        for thread in readers + [writer]:
            thread.start()
        for thread in readers + [writer]:
            thread.join(10)
        self.assertTrue(all(not thread.is_alive() for thread in readers + [writer]))
        self.assertEqual(errors, [])
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
        reopened = Store.open(self.db, expected_domains=(self.domain(resource="record", event="record.updated", operation="record.update", schema="record.v1"),))
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

    def test_empty_domain_descriptor_set_is_initialized_and_reopened(self) -> None:
        store = Store.create(self.db)
        self.assertEqual(store.registered_domains(), ())
        self.assertEqual(store.domain_descriptor_digest, hashlib.sha256(b"[]").hexdigest())
        store.close()
        reopened = Store.open(self.db)
        self.assertEqual(reopened.registered_domains(), ())
        self.assertEqual(reopened.domain_descriptor_digest, hashlib.sha256(b"[]").hexdigest())
        reopened.close()

    def test_valid_domain_descriptor_is_typed_durable_json_across_reopen(self) -> None:
        store = Store.create(self.db)
        contribution = self.domain()
        self.assertEqual(store.register_domain(contribution), contribution)
        identity = store.get_identity(ResourceRef("neutral-store", "domain", contribution.domain_id, contribution.version))
        self.assertIsNotNone(identity)
        self.assertEqual(identity.payload, contribution.to_dict())
        digest = store.domain_descriptor_digest
        self.assertNotEqual(digest, hashlib.sha256(b"[]").hexdigest())
        store.close()
        reopened = Store.open(self.db, expected_domains=(contribution,), expected_domain_digest=digest)
        self.assertEqual(reopened.registered_domains(), (contribution,))
        self.assertEqual(reopened.domain_descriptor_digest, digest)
        reopened.close()

    def test_duplicate_domain_and_type_rejection_is_atomic(self) -> None:
        store = Store.create(self.db)
        first = self.domain()
        store.register_domain(first)
        original_digest = store.domain_descriptor_digest
        duplicate_domain = self.domain()
        with self.assertRaises(ContractError):
            store.register_domain(duplicate_domain)
        colliding_type = self.domain("other.domain", resource=first.resource_types[0])
        with self.assertRaises(ContractError):
            store.register_domain(colliding_type)
        self.assertEqual(store.registered_domains(), (first,))
        self.assertEqual(store.domain_descriptor_digest, original_digest)
        self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM identities WHERE kind = 'domain'").fetchone()[0], 1)
        self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM record_references WHERE kind = 'domain'").fetchone()[0], 1)
        store.close()

    def test_descriptor_digest_tamper_or_missing_descriptor_refuses_open(self) -> None:
        store = Store.create(self.db)
        store.register_domain(self.domain())
        store.connection.execute("UPDATE store_metadata SET value = 'tampered' WHERE key = 'domain_descriptor_digest'")
        store.close()
        with self.assertRaises(DescriptorDigestMismatchError):
            Store.open(self.db)

        missing_db = Path(self.tempdir.name) / "missing-descriptor.sqlite3"
        store = Store.create(missing_db)
        store.register_domain(self.domain("missing.domain"))
        store.close()
        connection = sqlite3.connect(missing_db)
        connection.execute("DELETE FROM record_references WHERE kind = 'domain'")
        connection.execute("DELETE FROM identities WHERE kind = 'domain'")
        connection.commit()
        connection.close()
        with self.assertRaises(DescriptorDigestMismatchError):
            Store.open(missing_db)

    def test_domain_registration_uses_supplied_transaction_and_commits_once(self) -> None:
        store = Store.create(self.db)
        contribution = self.domain("transaction.domain")
        with store.transaction() as transaction:
            store.register_domain(contribution, transaction=transaction)
            self.assertEqual(store.registered_domains(), ())
            self.assertEqual(transaction.execute("SELECT COUNT(*) FROM identities WHERE kind = 'domain'").fetchone()[0], 1)
        self.assertEqual(store.registered_domains(), (contribution,))
        self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM identities WHERE kind = 'domain'").fetchone()[0], 1)
        store.close()

    def test_open_defaults_to_empty_descriptor_set_and_requires_exact_expectation(self) -> None:
        store = Store.create(self.db)
        first = self.domain("first.domain", resource="first.resource", document="first.document", event="first.updated")
        second = self.domain("second.domain", resource="second.resource", document="second.document", event="second.updated", namespace="second.namespace", operation="second.update")
        store.register_domain(first)
        store.register_domain(second)
        digest = store.domain_descriptor_digest
        store.close()

        with self.assertRaises(DescriptorExpectationMismatchError):
            Store.open(self.db)
        with self.assertRaises(DescriptorExpectationMismatchError):
            Store.open(self.db, expected_domains=(first,))
        with self.assertRaises(DescriptorExpectationMismatchError):
            Store.open(self.db, expected_domains=(first, second), expected_domain_digest="0" * 64)
        with self.assertRaises(DescriptorExpectationMismatchError):
            Store.open(self.db, expected_domains=(second, first), expected_domain_digest=digest)
        with self.assertRaises(DescriptorExpectationMismatchError):
            Store.open(self.db, expected_domains=(first, second), expected_domain_digest=hashlib.sha256(b"[]").hexdigest())

        reopened = Store.open(self.db, expected_domains=(first, second), expected_domain_digest=digest)
        self.assertEqual(reopened.registered_domains(), (first, second))
        reopened.close()

    def test_kernel_import_boundary_has_no_optional_domain_modules(self) -> None:
        code = "import sys; import herzchen.kernel; assert not any(x.startswith(('otto', 'astrid', 'runtime_protocol')) for x in sys.modules); print('boundary-ok')"
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "boundary-ok")


if __name__ == "__main__":
    unittest.main()
