from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Optional

from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef
from herzchen.kernel import (
    COMPOSITION,
    AllowanceExhaustedError,
    CapacityExhaustedError,
    LimitService,
    OperationManager,
    OperationRequest,
    OperationState,
    ReservationStatus,
    Store,
    TargetMismatchError,
    UnknownOutcomeError,
)


class ReceiptAndLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "neutral.sqlite3"
        self.store = Store.create(self.path)
        self.actor = AuthenticatedActor("neutral-auth", "actor-1", "credential-1")

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def operation_request(self, *, key: str = "logical-1", digest: str = "a" * 64, payload: Optional[dict] = None) -> OperationRequest:
        return OperationRequest(
            "adapter.invoke",
            "adapter.v1",
            ResourceRef("neutral-adapter", "adapter", "adapter-1"),
            self.actor,
            key,
            digest,
            payload or {"input": "value"},
            ResourceRef("physical", "invocation", "invocation-1"),
            ResourceRef("external", "owner", "owner-1"),
        )

    def pool(self, *, capacity: int = 2, allowance: int = 10):
        return LimitService(self.store).create_pool(
            ResourceRef("neutral-store", "limit", "pool-1"),
            capacity,
            allowance,
            logical_request_key="pool-create",
            actor=self.actor,
        )

    def test_operation_identity_replay_conflict_and_explicit_unknown_resolution(self) -> None:
        manager = OperationManager(self.store)
        first = manager.prepare(self.operation_request())
        self.assertEqual(first.state, OperationState.PREPARED)
        replay = manager.prepare(self.operation_request(payload={"changed": True}))
        self.assertEqual(replay.receipt, first.receipt)
        self.assertEqual(replay.result, first.result)
        self.assertEqual(replay.state, first.state)
        with self.assertRaises(ReplayConflictError):
            manager.prepare(self.operation_request(digest="b" * 64))

        uncertain = manager.record_outcome(first, OperationState.UNKNOWN, {"reason": "no response"})
        self.assertEqual(uncertain.state, OperationState.UNKNOWN)
        uncertain_replay = manager.record_outcome(first, OperationState.UNKNOWN, {"reason": "no response"})
        self.assertEqual(uncertain_replay.receipt, uncertain.receipt)
        with self.assertRaises(UnknownOutcomeError):
            manager.record_outcome(uncertain, OperationState.COMMITTED, {"value": 1}, transition_key="logical-1:retry")
        resolved = manager.resolve_unknown(uncertain, OperationState.COMMITTED, {"value": 1}, transition_key="logical-1:resolve")
        self.assertEqual(resolved.state, OperationState.COMMITTED)
        self.assertEqual(resolved.physical_invocation_ref, first.physical_invocation_ref)
        self.assertEqual(resolved.external_owner_ref, first.external_owner_ref)

    def test_limit_reusable_capacity_is_separate_from_cumulative_usage_and_overrun_is_truthful(self) -> None:
        service = LimitService(self.store)
        pool = self.pool(capacity=2, allowance=5)
        first = service.reserve(pool.ref, "reservation-1", 2, logical_request_key="reserve-1", actor=self.actor)
        with self.assertRaises(CapacityExhaustedError):
            service.reserve(pool.ref, "reservation-2", 1, logical_request_key="reserve-2", actor=self.actor)
        released = service.release(first, logical_request_key="release-1", actor=self.actor)
        self.assertEqual(released.status, ReservationStatus.RELEASED)
        second = service.reserve(pool.ref, "reservation-2", 2, logical_request_key="reserve-2", actor=self.actor)
        consumed = service.settle(second, 6, logical_request_key="settle-2", actor=self.actor)
        self.assertEqual(consumed.status, ReservationStatus.CONSUMED)
        self.assertEqual(consumed.actual_units, 6)
        self.assertEqual(consumed.overrun_units, 4)
        current_pool = service.get_pool(pool.ref)
        self.assertIsNotNone(current_pool)
        self.assertEqual(current_pool.cumulative_used_units, 6)
        self.assertEqual(current_pool.held_units, 0)
        with self.assertRaises(AllowanceExhaustedError):
            service.reserve(pool.ref, "reservation-3", 1, logical_request_key="reserve-3", actor=self.actor)

    def test_uncertain_keeps_capacity_held_until_explicit_release_or_settlement(self) -> None:
        service = LimitService(self.store)
        pool = self.pool(capacity=1, allowance=10)
        first = service.reserve(pool.ref, "reservation-1", 1, logical_request_key="reserve-1", actor=self.actor)
        uncertain = service.mark_uncertain(first, 3, logical_request_key="uncertain-1", actor=self.actor)
        self.assertEqual(uncertain.status, ReservationStatus.UNCERTAIN)
        self.assertEqual(uncertain.overrun_units, 2)
        with self.assertRaises(CapacityExhaustedError):
            service.reserve(pool.ref, "reservation-2", 1, logical_request_key="reserve-2", actor=self.actor)
        released = service.release(uncertain, actual_units=3, logical_request_key="release-uncertain", actor=self.actor)
        self.assertEqual(released.status, ReservationStatus.RELEASED)
        self.assertEqual(released.charged_units, 3)
        second = service.reserve(pool.ref, "reservation-2", 1, logical_request_key="reserve-2", actor=self.actor)
        self.assertEqual(second.status, ReservationStatus.HELD)

    def test_same_key_reservation_replay_precedes_new_admission_and_digest_conflicts(self) -> None:
        service = LimitService(self.store)
        pool = self.pool(capacity=1, allowance=10)
        first = service.reserve(pool.ref, "reservation-1", 1, logical_request_key="reserve-1", actor=self.actor)
        service.mark_uncertain(first, logical_request_key="uncertain-1", actor=self.actor)
        replay = service.reserve(pool.ref, "reservation-1", 1, logical_request_key="reserve-1", actor=self.actor)
        self.assertEqual(replay.receipt, first.receipt)
        self.assertEqual(replay.status, ReservationStatus.HELD)
        with self.assertRaises(ReplayConflictError):
            service.reserve(pool.ref, "reservation-1", 1, logical_request_key="reserve-1", request_digest="c" * 64, actor=self.actor)

    def test_last_unit_race_allows_only_one_contender(self) -> None:
        service = LimitService(self.store)
        pool = self.pool(capacity=1, allowance=10)
        barrier = threading.Barrier(3)
        results = []

        def contender(number: int) -> None:
            barrier.wait()
            try:
                service.reserve(pool.ref, "race-{}".format(number), 1, logical_request_key="race-key-{}".format(number), actor=self.actor)
                results.append("ok")
            except CapacityExhaustedError:
                results.append("capacity")

        threads = [threading.Thread(target=contender, args=(number,)) for number in (1, 2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(5)
        self.assertEqual(sorted(results), ["capacity", "ok"])

    def test_stale_transition_and_transaction_rollback_leave_no_partial_receipt(self) -> None:
        service = LimitService(self.store)
        pool = self.pool()
        first = service.reserve(pool.ref, "reservation-1", 1, logical_request_key="reserve-1", actor=self.actor)
        service.mark_uncertain(first, logical_request_key="uncertain-1", actor=self.actor)
        with self.assertRaises(TargetMismatchError):
            service.release(first, logical_request_key="stale-release", actor=self.actor)
        with self.assertRaises(RuntimeError):
            with self.store.transaction() as tx:
                service.reserve(pool.ref, "reservation-rollback", 1, logical_request_key="reserve-rollback", actor=self.actor, transaction=tx)
                raise RuntimeError("rollback")
        self.assertIsNone(self.store.get_receipt("reserve-rollback"))
        self.assertIsNone(service.get_reservation(ResourceRef("neutral-store", "reservation", "reservation-rollback")))

    def test_reopen_preserves_receipts_reservations_stable_pool_and_cumulative_usage(self) -> None:
        service = LimitService(self.store)
        pool = self.pool(capacity=2, allowance=10)
        first = service.reserve(pool.ref, "reservation-1", 1, logical_request_key="reserve-1", actor=self.actor)
        service.settle(first, 3, logical_request_key="settle-1", actor=self.actor)
        receipt = self.store.get_receipt("settle-1")
        self.assertIsNotNone(receipt)
        self.store.close()
        self.store = Store.open(self.path)
        reopened = LimitService(self.store)
        reopened_pool = reopened.get_pool(pool.ref)
        self.assertIsNotNone(reopened_pool)
        self.assertEqual(reopened_pool.ref, pool.ref)
        self.assertEqual(reopened_pool.cumulative_used_units, 3)
        current = reopened.get_reservation(ResourceRef("neutral-store", "reservation", "reservation-1"))
        self.assertIsNotNone(current)
        self.assertEqual(current.status, ReservationStatus.CONSUMED)
        self.assertEqual(self.store.get_receipt("settle-1"), receipt)

    def test_schema_is_exactly_the_accepted_six_table_composition(self) -> None:
        tables = tuple(row[0] for row in self.store.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        self.assertEqual(tables, tuple(sorted(COMPOSITION)))
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE '%reservation%'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
