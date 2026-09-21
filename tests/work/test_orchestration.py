from __future__ import annotations

from pathlib import Path
import threading

import pytest

from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef
from herzchen.domains.work import contributions, register_orchestration, register_work
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.orchestration import (
    ORCHESTRATION_SCHEMA_REVISION,
    PORTFOLIO_KIND,
    _OrchestrationEngine,
)
from herzchen.domains.work.model import WorkValidationError
from herzchen.kernel import Store


AUTHORITY = "mo02-atomic-test"
PORTFOLIO = ResourceRef(AUTHORITY, PORTFOLIO_KIND, "portfolio-main")


def _environment(tmp_path: Path):
    store = Store.create(tmp_path / "orchestration.sqlite", authority=AUTHORITY)
    register_work(store)
    register_orchestration(store)
    owner = AuthenticatedActor(AUTHORITY, "manager", "credential")
    assignments = ResponsibilityAssignments(store, actor=owner)
    main = assignments.assign(
        PORTFOLIO,
        role="orchestrator",
        principal="main-orchestrator",
        manager="main-orchestrator",
        logical_request_key="seed-main",
        actor=owner,
    )
    engine = _OrchestrationEngine(
        store,
        actor=owner,
        portfolio_ref=PORTFOLIO,
        main_assignment_ref=main.ref,
        allowed_creator_ids=("second-manager",),
        expected_main_principal="main-orchestrator",
    )
    return store, owner, assignments, main, engine


def _close(store):
    if not getattr(store, "_closed", False):
        store.close()


def test_core_descriptor_reopens_then_late_orchestration_registration_enables_owner(tmp_path):
    path = tmp_path / "old-descriptor.sqlite"
    store = Store.create(path, authority=AUTHORITY)
    register_work(store)
    owner = AuthenticatedActor(AUTHORITY, "manager", "credential")
    assignments = ResponsibilityAssignments(store, actor=owner)
    main = assignments.assign(
        PORTFOLIO,
        role="orchestrator",
        principal="main-orchestrator",
        manager="main-orchestrator",
        logical_request_key="compat-seed-main",
        actor=owner,
    )
    expected = tuple(sorted(contributions(), key=lambda item: item.domain_id))
    assert "herzchen.work.orchestration" not in {item.domain_id for item in expected}
    store.close()

    reopened = Store.open(path, authority=AUTHORITY, expected_domains=expected)
    try:
        assert "herzchen.work.orchestration" not in {item.domain_id for item in reopened.registered_domains()}
        before_digest = reopened.domain_descriptor_digest
        register_orchestration(reopened)
        assert before_digest != reopened.domain_descriptor_digest
        engine = _OrchestrationEngine(
            reopened,
            actor=owner,
            portfolio_ref=PORTFOLIO,
            main_assignment_ref=main.ref,
            expected_main_principal="main-orchestrator",
        )
        created = engine.create_pending_with_supervisor(
            actor=owner,
            request_id="compat-create",
            portfolio_ref=PORTFOLIO,
            title="Compatibility project",
            expected_project_version=0,
        )
        assert created["outcome"] == "created"
    finally:
        reopened.close()


def test_create_replay_rebind_reopen_and_changed_replay_conflict(tmp_path):
    store, owner, assignments, main, engine = _environment(tmp_path)
    try:
        created = engine.create_pending_with_supervisor(
            actor=owner,
            request_id="create-1",
            portfolio_ref=PORTFOLIO,
            title="Atomic project",
            outcome="proof",
            expected_project_version=0,
        )
        assert created["outcome"] == "created"
        assert created["supervision"]["assignment_ref"]["id"] == main.id
        assert created["project"]["metadata"]["otto_orchestrator"]["default_revision"] == "rev-1"
        assert store.get_receipt("create-1") is not None
        assert store.get_receipt("create-1:project") is not None

        reassigned = assignments.reassign(
            main,
            principal="rebound-orchestrator",
            expected_generation=1,
            logical_request_key="rebind-1",
            actor=owner,
        )
        assert reassigned.generation == 2
        replay = engine.create_pending_with_supervisor(
            actor=owner,
            request_id="create-1",
            portfolio_ref=PORTFOLIO,
            title="Atomic project",
            outcome="proof",
            expected_project_version=0,
        )
        assert replay["outcome"] == "replayed"
        assert replay["project_ref"] == created["project_ref"]
        assert replay["supervision"] == created["supervision"]

        with pytest.raises(ReplayConflictError):
            engine.create_pending_with_supervisor(
                actor=AuthenticatedActor(AUTHORITY, "second-manager", "credential"),
                request_id="create-1",
                portfolio_ref=PORTFOLIO,
                title="Changed actor",
                outcome="proof",
                expected_project_version=0,
            )

        domains = store.registered_domains()
        path = tmp_path / "orchestration.sqlite"
        store.close()
        reopened = Store.open(path, authority=AUTHORITY, expected_domains=domains)
        try:
            fresh = _OrchestrationEngine(
                reopened,
                actor=owner,
                portfolio_ref=PORTFOLIO,
                main_assignment_ref=main.ref,
                allowed_creator_ids=("second-manager",),
                expected_main_principal="main-orchestrator",
            )
            observed = fresh.create_pending_with_supervisor(
                actor=owner,
                request_id="create-1",
                portfolio_ref=PORTFOLIO,
                title="Atomic project",
                outcome="proof",
                expected_project_version=0,
            )
            assert observed["outcome"] == "replayed"
            assert observed["project"]["metadata"]["otto_orchestrator"] == created["project"]["metadata"]["otto_orchestrator"]
        finally:
            reopened.close()
    finally:
        _close(store)


def test_second_creator_foreign_scope_and_rollback_leave_one_default(tmp_path, monkeypatch):
    store, owner, _assignments, main, engine = _environment(tmp_path)
    try:
        second = AuthenticatedActor(AUTHORITY, "second-manager", "credential")
        first = engine.create_pending_with_supervisor(
            actor=owner,
            request_id="first",
            portfolio_ref=PORTFOLIO,
            title="First",
            expected_project_version=0,
        )
        other = engine.create_pending_with_supervisor(
            actor=second,
            request_id="second",
            portfolio_ref=PORTFOLIO,
            title="Second",
            expected_project_version=0,
        )
        assert first["assignment_ref"] == other["assignment_ref"]
        assert len([item for item in store.list_events(stream="orchestrator-default:" + first["default_ref"]["id"])]) == 1

        original = engine.batches.create_pending_project

        def fail_after_nested_project(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected placement failure")

        monkeypatch.setattr(engine.batches, "create_pending_project", fail_after_nested_project)
        with pytest.raises(RuntimeError, match="injected placement failure"):
            engine.create_pending_with_supervisor(
                actor=owner,
                request_id="rollback",
                portfolio_ref=PORTFOLIO,
                title="Rolled back",
                expected_project_version=0,
            )
        assert store.get_receipt("rollback") is None
        assert store.get_receipt("rollback:project") is None
        assert store.get_identity(engine._default_ref()) is not None
    finally:
        _close(store)


def test_first_use_default_and_project_roll_back_together(tmp_path, monkeypatch):
    store, owner, _assignments, _main, engine = _environment(tmp_path)
    try:
        original = engine.batches.create_pending_project

        def fail_after_first_use(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected first-use failure")

        monkeypatch.setattr(engine.batches, "create_pending_project", fail_after_first_use)
        with pytest.raises(RuntimeError, match="injected first-use failure"):
            engine.create_pending_with_supervisor(
                actor=owner,
                request_id="first-use-rollback",
                portfolio_ref=PORTFOLIO,
                title="Should roll back",
                expected_project_version=0,
            )
        assert store.get_identity(engine._default_ref()) is None
        assert store.get_receipt("first-use-rollback") is None
        assert store.get_receipt("first-use-rollback:project") is None
        assert not store.list_events(stream="orchestrator-default:" + engine._default_ref().id)

        monkeypatch.setattr(engine.batches, "create_pending_project", original)
        created = engine.create_pending_with_supervisor(
            actor=owner,
            request_id="first-use-after-rollback",
            portfolio_ref=PORTFOLIO,
            title="First committed project",
            expected_project_version=0,
        )
        assert created["outcome"] == "created"
        assert len(store.list_events(stream="orchestrator-default:" + engine._default_ref().id)) == 1
    finally:
        _close(store)


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_two_first_use_creators_serialize_to_one_default(tmp_path, order):
    case = tmp_path / ("race-" + "-".join(order))
    case.mkdir()
    store = Store.create(case / "orchestration.sqlite", authority=AUTHORITY)
    register_work(store)
    register_orchestration(store)
    owner = AuthenticatedActor(AUTHORITY, "manager", "credential")
    assignments = ResponsibilityAssignments(store, actor=owner)
    main = assignments.assign(
        PORTFOLIO,
        role="orchestrator",
        principal="main-orchestrator",
        manager="main-orchestrator",
        logical_request_key="race-seed-main-" + order[0],
        actor=owner,
    )
    engines = {
        label: _OrchestrationEngine(
            store,
            actor=owner,
            portfolio_ref=PORTFOLIO,
            main_assignment_ref=main.ref,
            expected_main_principal="main-orchestrator",
        )
        for label in order
    }
    barrier = threading.Barrier(2)
    results = {}
    errors = []

    for label, engine in engines.items():
        original_actor = engine._actor

        def gated_actor(value, *, _original=original_actor):
            barrier.wait(timeout=5)
            return _original(value)

        engine._actor = gated_actor

    def create(label):
        try:
            results[label] = engines[label].create_pending_with_supervisor(
                actor=owner,
                request_id="race-first-use-" + label,
                portfolio_ref=PORTFOLIO,
                title="Race " + label,
                expected_project_version=0,
            )
        except BaseException as exc:  # make thread failures visible to pytest
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(label,)) for label in order]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    try:
        assert not errors
        assert all(not thread.is_alive() for thread in threads)
        assert {item["outcome"] for item in results.values()} == {"created"}
        assert len({item["project_ref"]["id"] for item in results.values()}) == 2
        assert len({item["assignment_ref"]["id"] for item in results.values()}) == 1
        default_stream = "orchestrator-default:" + engines[order[0]]._default_ref().id
        assert len(store.list_events(stream=default_stream)) == 1
    finally:
        _close(store)


@pytest.mark.parametrize("status", ["retired", "stopped", "cancelled", "completed"])
def test_terminal_or_retired_default_assignment_is_rejected(tmp_path, status):
    store, owner, _assignments, main, engine = _environment(tmp_path)
    try:
        identity = store.get_identity(main.ref)
        payload = dict(identity.payload)
        payload["status"] = status
        store.revise_identity(
            main.ref,
            payload,
            revision="rev-2",
            expected_revision="rev-1",
            expected_version=1,
        )
        with pytest.raises((WorkValidationError, ValueError)):
            engine.create_pending_with_supervisor(
                actor=owner,
                request_id="reject-" + status,
                portfolio_ref=PORTFOLIO,
                title="Rejected",
                expected_project_version=0,
            )
        assert store.get_identity(engine._default_ref()) is None
        assert store.get_receipt("reject-" + status) is None
    finally:
        _close(store)


def test_default_cas_transfer_fences_and_preserves_project_fields(tmp_path):
    store, owner, assignments, main, engine = _environment(tmp_path)
    try:
        created = engine.create_pending_with_supervisor(
            actor=owner,
            request_id="transfer-project",
            portfolio_ref=PORTFOLIO,
            title="Transfer project",
            expected_project_version=0,
        )
        target = assignments.assign(
            PORTFOLIO,
            role="orchestrator",
            principal="peer-orchestrator",
            manager="peer-orchestrator",
            logical_request_key="seed-peer",
            actor=owner,
        )
        changed = engine.set_default(
            actor=owner,
            request_id="default-change",
            portfolio_ref=PORTFOLIO,
            target_assignment_ref=target.ref,
            target_assignment_revision="rev-1",
            target_assignment_generation=1,
            expected_default_revision="rev-1",
        )
        assert changed["outcome"] == "changed"
        with pytest.raises(Exception):
            engine.set_default(
                actor=owner,
                request_id="default-stale",
                portfolio_ref=PORTFOLIO,
                target_assignment_ref=main.ref,
                target_assignment_revision="rev-1",
                target_assignment_generation=1,
                expected_default_revision="rev-1",
            )

        transferred = engine.transfer_supervision(
                actor=owner,
                request_id="transfer-1",
                portfolio_ref=PORTFOLIO,
                project_ref=ResourceRef.from_dict(created["project_ref"]),
                expected_project_revision=created["project_ref"]["revision"],
                expected_project_version=2,
            current_assignment_ref=ResourceRef.from_dict(created["assignment_ref"]),
            current_assignment_revision="rev-1",
            current_assignment_generation=1,
            target_assignment_ref=target.ref,
            target_assignment_revision="rev-1",
            target_assignment_generation=1,
            overlap_acknowledged=True,
        )
        assert transferred["supervision"]["assignment_ref"]["id"] == target.id
        assert transferred["project"]["metadata"]["otto_orchestrator"]["assignment_ref"]["id"] == target.id
    finally:
        _close(store)


def test_race_serializes_create_before_rebind(tmp_path):
    store, owner, assignments, main, engine = _environment(tmp_path)
    barrier = threading.Barrier(2)
    original = engine.batches.create_pending_project
    result = {}

    def barrier_create(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    engine.batches.create_pending_project = barrier_create

    def create():
        result["create"] = engine.create_pending_with_supervisor(
            actor=owner,
            request_id="race-create",
            portfolio_ref=PORTFOLIO,
            title="Race",
            expected_project_version=0,
        )

    def rebind():
        barrier.wait(timeout=5)
        result["rebind"] = assignments.reassign(
            main,
            principal="race-rebound",
            expected_generation=1,
            logical_request_key="race-rebind",
            actor=owner,
        )

    first = threading.Thread(target=create)
    second = threading.Thread(target=rebind)
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive() and not second.is_alive()
    assert result["create"]["outcome"] == "created"
    assert result["create"]["supervision"]["generation"] == 1
    assert result["rebind"].generation == 2
    store.close()
