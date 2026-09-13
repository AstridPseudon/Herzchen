from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    ContractError,
    ResourceRef,
    TransactionContext,
)
from herzchen.kernel import Store, StoreError, TargetMismatchError, VersionConflictError


class _ZeroRowsCursor:
    rowcount = 0


class IdentityRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "neutral.sqlite3"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def ref(self, ident: str = "identity-1", revision: Optional[str] = "rev-1") -> ResourceRef:
        return ResourceRef("neutral-store", "record", ident, revision)

    def admitted(self, ref: Optional[ResourceRef] = None, *, payload: Optional[dict[str, Any]] = None, version: int = 1, edit_token: Optional[str] = "edit-1") -> Store:
        store = Store.create(self.db)
        current = ref or self.ref()
        store.put_identity(current, payload or {"value": "initial"}, version=version, edit_token=edit_token)
        store.put_reference(current)
        return store

    def revise(self, store: Store, ref: ResourceRef, *, revision: str = "rev-2", version: int = 1, token: Optional[str] = "edit-1", transaction: Any = None) -> Any:
        return store.revise_identity(
            ref,
            {"value": "revised"},
            revision=revision,
            expected_revision=ref.revision,
            expected_version=version,
            expected_edit_token=token,
            transaction=transaction,
        )

    def test_success_advances_identity_and_preserves_immutable_reference_history(self) -> None:
        store = self.admitted()
        old = self.ref()

        revised = self.revise(store, old)

        self.assertEqual(revised.ref, self.ref(revision="rev-2"))
        self.assertEqual(revised.version, 2)
        self.assertEqual(revised.payload, {"value": "revised"})
        self.assertEqual(store.get_reference(old), old)
        self.assertEqual(store.get_reference(revised.ref), revised.ref)
        self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM record_references WHERE kind = 'record'").fetchone()[0], 2)
        self.assertEqual(store.get_identity(old).ref, revised.ref)  # type: ignore[union-attr]
        store.close()

    def test_validation_and_cas_fail_without_partial_update(self) -> None:
        store = self.admitted()
        old = self.ref()

        cases = (
            (TargetMismatchError, {"expected_revision": "wrong"}),
            (VersionConflictError, {"expected_version": 0}),
            (VersionConflictError, {"expected_edit_token": "wrong"}),
            (ContractError, {"revision": ""}),
            (ContractError, {"payload": {"bad": object()}}),
        )
        for error, changes in cases:
            kwargs = {
                "revision": "rev-2",
                "expected_revision": old.revision,
                "expected_version": 1,
                "expected_edit_token": "edit-1",
            }
            kwargs.update(changes)
            with self.subTest(error=error.__name__, changes=changes), self.assertRaises(error):
                store.revise_identity(old, kwargs.pop("payload", {"value": "revised"}), **kwargs)
            current = store.get_identity(old)
            self.assertEqual(current.ref.revision, "rev-1")  # type: ignore[union-attr]
            self.assertEqual(current.version, 1)  # type: ignore[union-attr]
            self.assertIsNone(store.get_reference(self.ref(revision="rev-2")))

        with self.subTest("same revision"):
            with self.assertRaises(VersionConflictError):
                self.revise(store, old, revision="rev-1")
        with self.subTest("older revision"):
            with self.assertRaises(VersionConflictError):
                self.revise(store, old, revision="rev-0")
        with self.subTest("skipped revision"):
            with self.assertRaises(VersionConflictError):
                self.revise(store, old, revision="rev-3")

        with self.subTest("foreign authority"):
            with self.assertRaises(TargetMismatchError):
                store.revise_identity(ResourceRef("foreign-store", "record", "identity-1", "rev-1"), {}, revision="rev-2", expected_revision="rev-1", expected_version=1)
        with self.subTest("missing identity"):
            missing = self.ref("missing")
            with self.assertRaises(TargetMismatchError):
                store.revise_identity(missing, {}, revision="rev-1", expected_revision="rev-1", expected_version=1)
        store.close()

    def test_legacy_opaque_revision_has_only_bounded_transition_to_numeric(self) -> None:
        legacy = self.ref(revision="legacy-base")
        store = self.admitted(legacy, version=7)

        revised = self.revise(store, legacy, revision="rev-8", version=7)
        self.assertEqual(revised.ref.revision, "rev-8")
        with self.assertRaises(VersionConflictError):
            self.revise(store, revised.ref, revision="legacy-next", version=8)
        store.close()

    def test_wrong_and_inactive_transactions_are_rejected(self) -> None:
        store = self.admitted()
        other_db = Path(self.tempdir.name) / "other.sqlite3"
        other = Store.create(other_db)
        old = self.ref()
        with other.transaction() as wrong_transaction:
            with self.assertRaises(StoreError):
                self.revise(store, old, transaction=wrong_transaction)
        with store.transaction() as transaction:
            pass
        with self.assertRaises(StoreError):
            self.revise(store, old, transaction=transaction)
        other.close()
        store.close()

    def test_affected_row_failure_rolls_back_update_and_reference(self) -> None:
        store = self.admitted()
        old = self.ref()
        with store.transaction() as transaction:
            execute = transaction.execute

            def fail_update(sql: str, parameters: Any = ()) -> Any:
                cursor = execute(sql, parameters)
                if sql.startswith("UPDATE identities SET"):
                    return _ZeroRowsCursor()
                return cursor

            transaction.execute = fail_update  # type: ignore[method-assign]
            with self.assertRaises(StoreError):
                self.revise(store, old, transaction=transaction)
        current = store.get_identity(old)
        self.assertEqual(current.ref.revision, "rev-1")  # type: ignore[union-attr]
        self.assertEqual(current.version, 1)  # type: ignore[union-attr]
        self.assertIsNone(store.get_reference(self.ref(revision="rev-2")))
        store.close()

    def test_two_contenders_cannot_both_revise_one_expected_version(self) -> None:
        store = self.admitted()
        old = self.ref()
        self.revise(store, old, revision="rev-2")
        with self.assertRaises(TargetMismatchError):
            self.revise(store, old, revision="rev-2")
        current = store.get_identity(old)
        self.assertEqual(current.version, 2)  # type: ignore[union-attr]
        self.assertEqual(current.ref.revision, "rev-2")  # type: ignore[union-attr]
        store.close()

    def test_supplied_outer_transaction_rolls_back_multiple_revisions(self) -> None:
        store = self.admitted()
        second = self.ref("identity-2")
        store.put_identity(second, {"value": "second"}, version=1, edit_token="edit-1")
        store.put_reference(second)
        first = self.ref()
        with self.assertRaises(RuntimeError):
            with store.transaction() as transaction:
                self.revise(store, first, transaction=transaction)
                self.revise(store, second, transaction=transaction)
                raise RuntimeError("parent operation failed")

        self.assertEqual(store.get_identity(first).ref.revision, "rev-1")  # type: ignore[union-attr]
        self.assertEqual(store.get_identity(second).ref.revision, "rev-1")  # type: ignore[union-attr]
        self.assertIsNone(store.get_reference(self.ref(revision="rev-2")))
        self.assertIsNone(store.get_reference(self.ref("identity-2", "rev-2")))
        store.close()

    def test_revision_composes_with_one_mutation_receipt_and_event_boundary(self) -> None:
        store = self.admitted()
        child = self.ref("child")
        store.put_identity(child, {"value": "child"}, version=1, edit_token="edit-1")
        store.put_reference(child)
        parent = self.ref("parent", None)
        store.put_identity(parent, {"value": "parent"}, version=0)
        actor = AuthenticatedActor("neutral-auth", "actor-1", "credential-1")
        envelope = CommandEnvelope(
            "parent.update",
            "parent.v1",
            parent,
            TransactionContext(actor, "parent-request", "b" * 64, expected_version=0),
            {"value": "parent-updated"},
        )

        with store.transaction() as transaction:
            self.revise(store, child, transaction=transaction)
            receipt = store.mutate(envelope, event_type="parent.updated", transaction=transaction)

        self.assertEqual(len(store.list_events()), 1)
        self.assertEqual(store.get_receipt("parent-request"), receipt)
        self.assertEqual(len(receipt.event_ids), 1)
        self.assertEqual(store.get_identity(child).ref.revision, "rev-2")  # type: ignore[union-attr]
        self.assertEqual(store.get_identity(parent).ref.revision, "rev-1")  # type: ignore[union-attr]
        store.close()


if __name__ == "__main__":
    unittest.main()
