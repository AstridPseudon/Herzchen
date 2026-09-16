from __future__ import annotations

from contextlib import contextmanager

import pytest

from herzchen.contracts import AuthenticatedActor, DomainContribution, ReplayConflictError, ResourceRef
from herzchen.kernel import (
    OperationManager,
    OperationOwner,
    OperationOwnerCapability,
    OperationRequest,
    OperationState,
    RuntimeOperationOwner,
    RuntimeOperationReader,
    Store,
    StoreAdmissionError,
    issue_operation_owner,
)
from herzchen.kernel.operations import _OperationManagerEngine


def _request(key: str = "owner-capability") -> OperationRequest:
    return OperationRequest(
        "adapter.invoke",
        "adapter.v1",
        ResourceRef("neutral-adapter", "adapter", "adapter-1"),
        AuthenticatedActor("neutral-auth", "actor-1", "credential-1"),
        key,
        "0" * 64,
        {"input": "value"},
        ResourceRef("physical", "invocation", "invocation-1"),
        ResourceRef("external", "owner", "owner-1"),
    )


def test_store_issues_typed_operation_owner_and_engine_does_not_retain_store(tmp_path):
    store = Store.create(tmp_path / "owner.sqlite3")
    try:
        owner = store.issue_operation_owner()
        assert isinstance(owner, OperationOwnerCapability)
        assert isinstance(owner, OperationOwner)
        engine = _OperationManagerEngine(owner)
        retained = object.__getattribute__(engine, "_OperationManagerEngine__owner")
        assert retained is owner
        assert not isinstance(retained, Store)
        with pytest.raises(StoreAdmissionError):
            _OperationManagerEngine(object())
    finally:
        store.close()


def test_owner_capability_keeps_nested_operation_write_atomic(tmp_path):
    store = Store.create(tmp_path / "rollback.sqlite3")
    try:
        owner = store.issue_operation_owner()
        engine = _OperationManagerEngine(owner)
        request = _request("nested-rollback")
        with owner.transaction() as transaction:
            with pytest.raises(RuntimeError, match="abort nested"):
                with transaction.savepoint():
                    engine.prepare(request, transaction=transaction)
                    raise RuntimeError("abort nested")
            committed = engine.prepare(_request("outer-commit"), transaction=transaction)
        assert owner.get_identity(ResourceRef("neutral-store", "operation", "nested-rollback")) is None
        assert owner.get_receipt("nested-rollback") is None
        events = owner.list_events(stream="operations")
        assert len(events) == 1
        assert events[0].subject.id == "outer-commit"
        assert owner.get_receipt("outer-commit") == committed.receipt
    finally:
        store.close()


def test_operation_facade_accepts_only_issued_owner_and_preserves_exact_replay(tmp_path):
    store = Store.create(tmp_path / "facade.sqlite3")
    try:
        owner = store.issue_operation_owner()
        manager = OperationManager(owner)
        first = manager.prepare(_request("facade-replay"))
        replay = manager.prepare(_request("facade-replay"))
        assert replay.receipt == first.receipt
        with pytest.raises(ReplayConflictError):
            manager.prepare(
                OperationRequest(
                    "adapter.other",
                    "adapter.v1",
                    _request().adapter_ref,
                    _request().actor,
                    "facade-replay",
                    first.request.request_digest,
                    {"input": "changed"},
                )
            )
        assert owner.get_receipt("facade-replay") == first.receipt
        assert owner.list_events(stream="operations")
        with pytest.raises(StoreAdmissionError):
            OperationManager(object())
    finally:
        store.close()


class _RuntimeReader(RuntimeOperationReader):
    __slots__ = ("_reader",)

    def __init__(self, reader):
        self._reader = reader

    @property
    def authority(self):
        return self._reader.authority

    @property
    def domain_descriptor_digest(self):
        return self._reader.domain_descriptor_digest

    def get_identity(self, ref):
        return self._reader.get_identity(ref)

    def get_receipt(self, logical_request_key):
        return self._reader.get_receipt(logical_request_key)

    def list_events(self, *, stream=None):
        return self._reader.list_events(stream=stream)

    def registered_domains(self):
        return self._reader.registered_domains()


class _ForeignRuntimeOwner(RuntimeOperationOwner):
    __slots__ = ("_store", "reader", "seen_transactions")

    def __init__(self, store):
        self._store = store
        self.reader = _RuntimeReader(store.consumer())
        self.seen_transactions = []

    @property
    def authority(self):
        return self._store.authority

    @property
    def domain_descriptor_digest(self):
        return self._store.domain_descriptor_digest

    def registered_domains(self):
        return self._store.registered_domains()

    @contextmanager
    def transaction(self):
        with self._store.transaction() as transaction:
            self.seen_transactions.append(transaction)
            yield transaction

    def mutate(self, *args, **kwargs):
        return self._store.mutate(*args, **kwargs)

    def get_identity(self, ref):
        return self._store.get_identity(ref)

    def get_receipt(self, logical_request_key):
        return self._store.get_receipt(logical_request_key)

    def list_events(self, *, stream=None):
        return self._store.list_events(stream=stream)

    def lookup_replay(self, envelope):
        prior = self._store.get_receipt(envelope.context.logical_request_key)
        if prior is not None:
            from herzchen.contracts import validate_replay
            validate_replay(prior, envelope)
        return prior

    def event_lineage(self, receipt):
        wanted = set(receipt.event_ids)
        return tuple(event for event in self._store.list_events() if event.event_id in wanted)


class _BroadRuntimeReader(_RuntimeReader):
    @property
    def connection(self):
        return object()


def test_foreign_runtime_owner_uses_one_existing_owner_transaction_without_store_reopen(tmp_path):
    store = Store.create(tmp_path / "runtime-owner.sqlite3")
    try:
        store.register_domain(DomainContribution(
            "runtime.owner", "v1", "runtime", ("runtime-item",), (), (),
            ("runtime.describe",), ("runtime.described",), "runtime.v1",
        ))
        runtime_owner = _ForeignRuntimeOwner(store)
        capability = issue_operation_owner(runtime_owner)
        assert isinstance(capability, OperationOwnerCapability)
        assert capability.reader is runtime_owner.reader
        engine = _OperationManagerEngine(capability)
        with capability.transaction() as transaction:
            with pytest.raises(RuntimeError, match="foreign savepoint abort"):
                with transaction.savepoint():
                    engine.prepare(_request("foreign-savepoint"), transaction=transaction)
                    raise RuntimeError("foreign savepoint abort")
            engine.prepare(_request("foreign-runtime"), transaction=transaction)
        assert runtime_owner.seen_transactions[-1] is transaction
        assert capability.get_identity(ResourceRef("neutral-store", "operation", "foreign-savepoint")) is None
        assert capability.get_receipt("foreign-runtime") is not None
        # The public facade accepts the nominal Runtime owner directly and
        # issues the same finite operation port; it does not open a Store.
        runtime_manager = OperationManager(runtime_owner)
        runtime_manager.prepare(_request("foreign-facade"))
        assert capability.get_receipt("foreign-facade") is not None
    finally:
        store.close()


def test_foreign_runtime_owner_requires_nominal_finite_bridge_and_descriptor_digest(tmp_path):
    store = Store.create(tmp_path / "runtime-owner-admission.sqlite3")
    try:
        class StructuralSpoof:
            pass

        with pytest.raises(StoreAdmissionError):
            issue_operation_owner(StructuralSpoof())
        runtime_owner = _ForeignRuntimeOwner(store)
        runtime_owner.reader._reader = type("WrongReader", (), {"domain_descriptor_digest": "wrong"})()
        with pytest.raises(StoreAdmissionError):
            issue_operation_owner(runtime_owner)
        runtime_owner.reader = _BroadRuntimeReader(store.consumer())
        with pytest.raises(StoreAdmissionError):
            issue_operation_owner(runtime_owner)
    finally:
        store.close()
