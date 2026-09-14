from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from herzchen.authoring.sessions import AuthoringSessionService, InvalidSessionError, domain_contribution, register_authoring
from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef
from herzchen.domains.assessment import AssessmentModule, Verdict
from herzchen.domains.work import Lifecycle, WorkGraph, WorkKind
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.batches import ProjectBatches
from herzchen.kernel import LimitService, Store
from herzchen.packs.authoring import (
    ManagedPack,
    ManagedPackAuthoringHandler,
    ManagedResource,
    ManagedSourceIdentity,
)


def _counts(store: Store) -> tuple[int, int, int, int]:
    return (
        store.connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0],
        store.connection.execute("SELECT COUNT(*) FROM record_references").fetchone()[0],
        store.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0],
        len(store.list_events()),
    )


@pytest.fixture
def work_env(tmp_path: Path):
    store = Store.create(tmp_path / "work.sqlite", authority="gf02-test")
    actor = AuthenticatedActor("gf02-test", "worker", "credential")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(title="Replay project", logical_request_key="project")
    try:
        yield store, actor, graph, project
    finally:
        store.close()


def test_work_revise_exact_retry_after_advance_covers_all_six_kinds(work_env):
    store, _actor, graph, project = work_env
    records = [project]
    for kind in (WorkKind.EFFORT, WorkKind.TASK, WorkKind.CRITERION, WorkKind.SCENARIO, WorkKind.GATE):
        records.append(graph.create(kind, project=project, title=kind.value, logical_request_key="create-" + kind.value))

    for index, original in enumerate(records):
        key = "revise-" + original.kind.value
        first = graph.revise(original, title="first-" + str(index), logical_request_key=key)
        receipt = store.get_receipt(key)
        assert receipt is not None
        graph.revise(first, outcome="intervening", logical_request_key=key + "-advance")
        before = _counts(store)
        replay = graph.revise(original, title="first-" + str(index), logical_request_key=key)
        assert replay.title == first.title
        assert store.get_receipt(key) == receipt
        assert _counts(store) == before

        with pytest.raises(ReplayConflictError):
            graph.revise(graph.get(original.ref), title="first-" + str(index), logical_request_key=key)
        assert _counts(store) == before


@pytest.mark.parametrize("path", ["parent", "dependency", "state"])
def test_work_revision_mutation_paths_replay_without_delta_and_conflict_on_changed_request(work_env, path):
    store, _actor, graph, project = work_env
    child = graph.create_task(project, title="child", logical_request_key="child-" + path)
    other = graph.create_task(project, title="other", logical_request_key="other-" + path)
    if path == "parent":
        first = graph.link_parent(child, other, logical_request_key="path-first")
        retry = lambda: graph.link_parent(child, other, logical_request_key="path-first")
        changed = lambda: graph.link_parent(child, project, logical_request_key="path-first")
    elif path == "dependency":
        first = graph.link_dependency(child, other, logical_request_key="path-first")
        retry = lambda: graph.link_dependency(child, other, logical_request_key="path-first")
        changed = lambda: graph.link_dependency(child, project, logical_request_key="path-first")
    else:
        observation = {"ready": True, "cause": "accepted"}
        first = graph.set_readiness(child, observation, logical_request_key="path-first")
        retry = lambda: graph.set_readiness(child, observation, logical_request_key="path-first")
        changed = lambda: graph.set_readiness(child, {"ready": False}, logical_request_key="path-first")
    receipt = store.get_receipt("path-first")
    assert receipt is not None
    graph.revise(first, outcome="intervening", logical_request_key="path-advance")
    before = _counts(store)
    assert retry().id == first.id
    assert store.get_receipt("path-first") == receipt
    assert _counts(store) == before
    with pytest.raises(ReplayConflictError):
        changed()
    assert _counts(store) == before


def test_project_activation_replays_original_base_after_advance(work_env):
    store, _actor, graph, project = work_env
    batches = ProjectBatches(store, actor=graph.default_actor)
    base = project.ref.revision
    first = batches.activate_project(project, manager="manager", base_revision=base, logical_request_key="activate")
    receipt = store.get_receipt("activate")
    assert receipt is not None
    graph.revise(first, outcome="post-activation state", logical_request_key="activate-advance")
    before = _counts(store)
    replay = batches.activate_project(project, manager="manager", base_revision=base, logical_request_key="activate")
    assert replay.lifecycle is Lifecycle.ACTIVE
    assert store.get_receipt("activate") == receipt
    assert _counts(store) == before
    with pytest.raises(ReplayConflictError):
        batches.activate_project(project, manager="manager", base_revision=replay.ref.revision, logical_request_key="activate")
    assert _counts(store) == before


def _assessment_env(store: Store, graph: WorkGraph, actor: AuthenticatedActor, project):
    parent = graph.create_task(project, title="obligation", logical_request_key="assessment-parent")
    criterion = graph.create_criterion(parent, title="criterion", logical_request_key="assessment-criterion")

    def admit(kind: str, ident: str) -> ResourceRef:
        ref = ResourceRef(store.authority, kind, ident, "rev-1")
        store.put_identity(ref, {"record_type": kind, "value": ident}, version=1)
        store.put_reference(ref)
        return ref

    source, artifact, spec = (admit("fixture." + name, name) for name in ("source", "artifact", "spec"))
    candidate = admit("fixture.candidate", "candidate")
    assessment = AssessmentModule(store, actor=actor)
    assessment.register()
    scope = assessment.declare_scope(
        ResourceRef(store.authority, "assessment.scope", "scope"),
        parent_obligation=parent, protocol="test", criteria=(criterion,),
        logical_request_key="assessment-scope",
    )
    packet = assessment.freeze_input(scope, packet={"candidate": candidate}, consumed_refs=(source,), logical_request_key="assessment-packet")
    pool = LimitService(store).create_pool(ResourceRef(store.authority, "limit", "pool"), 1, 3, logical_request_key="assessment-pool", actor=actor)
    result = assessment.assess(
        scope, candidate=candidate, criterion=criterion, input_packet=packet,
        verdict=Verdict.PASS, findings=({"summary": "close me"},), limit_pool=pool.ref,
        logical_request_key="assessment-run",
    )
    return assessment, result, artifact


def test_assessment_finding_close_replays_and_changed_finding_precondition_conflicts(tmp_path: Path):
    store = Store.create(tmp_path / "assessment.sqlite", authority="assessment-gf02")
    actor = AuthenticatedActor("assessment-gf02", "approver", "credential")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    project = graph.create_project(logical_request_key="project")
    assessment, result, artifact = _assessment_env(store, graph, actor, project)
    finding = result.findings[0]
    first = assessment.close_finding(finding, evidence_refs=(artifact,), rationale="verified", logical_request_key="finding-close")
    receipt = store.get_receipt("finding-close")
    assert receipt is not None
    before = _counts(store)
    replay = assessment.close_finding(finding, evidence_refs=(artifact,), rationale="verified", logical_request_key="finding-close")
    assert replay.status == first.status == "closed"
    assert store.get_receipt("finding-close") == receipt
    assert _counts(store) == before
    derived = assessment.get_finding(finding)
    replay_after_projection_change = assessment.close_finding(derived, evidence_refs=(artifact,), rationale="verified", logical_request_key="finding-close")
    assert replay_after_projection_change.status == "closed"
    assert _counts(store) == before
    with pytest.raises(ReplayConflictError):
        assessment.close_finding(derived.ref, evidence_refs=(artifact,), rationale="verified", logical_request_key="finding-close")
    assert _counts(store) == before
    store.close()


def test_reassign_replays_original_generation_and_changed_generation_conflicts(work_env):
    store, actor, graph, project = work_env
    assignments = ResponsibilityAssignments(store, actor=actor)
    assigned = assignments.assign(project, role="review", principal="one", logical_request_key="assignment")
    first = assignments.reassign(assigned, principal="two", expected_generation=1, logical_request_key="reassign")
    receipt = store.get_receipt("reassign")
    assert receipt is not None
    second = assignments.reassign(first, principal="three", expected_generation=2, logical_request_key="reassign-advance")
    before = _counts(store)
    replay = assignments.reassign(assigned, principal="two", expected_generation=1, logical_request_key="reassign")
    assert replay.generation == first.generation
    assert store.get_receipt("reassign") == receipt
    assert _counts(store) == before
    with pytest.raises(ReplayConflictError):
        assignments.reassign(assigned, principal="two", expected_generation=2, logical_request_key="reassign")
    assert _counts(store) == before
    assert second.generation == 3


def _managed_pack(tmp_path: Path) -> ManagedPack:
    root = tmp_path / "managed-pack"
    root.mkdir()
    manifest = root / "pack.yaml"
    manifest.write_text("{}", encoding="utf-8")
    content = b"original"
    source = ManagedSourceIdentity(
        "replay-pack", "managed", "a" * 40, "b" * 64, "c" * 64, "d" * 64,
        str(root), str(manifest),
    )
    resource = ManagedResource("skill.md", "skill", content, hashlib.sha256(content).hexdigest(), ResourceRef("astrid-managed", "managed_pack", "replay-pack", "a" * 40))
    return ManagedPack("replay-pack", "1.0.0", source, {"id": "replay-pack"}, (resource,), (), ())


def test_managed_pack_author_replays_without_new_revision_or_effect(tmp_path: Path):
    pack = _managed_pack(tmp_path)
    store = Store.create(tmp_path / "pack.sqlite", authority="pack-gf02")
    store.register_domain_handler((__import__("herzchen.packs.authoring", fromlist=["domain_contribution"]).domain_contribution(),))
    handler = ManagedPackAuthoringHandler(store)
    actor = AuthenticatedActor("pack-gf02", "author", "credential")
    first = handler.author(pack, {"skill.md": b"first"}, logical_request_key="pack-author", actor=actor)
    receipt = store.get_receipt("pack-author")
    assert receipt is not None
    handler.author(pack, {"skill.md": b"advance"}, logical_request_key="pack-advance", actor=actor)
    before = _counts(store)
    replay = handler.author(pack, {"skill.md": b"first"}, logical_request_key="pack-author", actor=actor)
    assert replay.receipt == receipt
    assert replay.revision == first.revision
    assert _counts(store) == before
    with pytest.raises(ReplayConflictError):
        handler.author(pack, {"skill.md": b"changed"}, logical_request_key="pack-author", actor=actor)
    assert _counts(store) == before
    store.close()


def test_authoring_release_and_actor_release_exact_retry_keep_invalid_first_invalid(tmp_path: Path):
    db = tmp_path / "authoring.sqlite"
    store = Store.create(db, authority="edt-gf02")
    register_authoring(store)
    service = AuthoringSessionService(store)
    actor = AuthenticatedActor("edt-gf02", "author", "credential")
    scope = ResourceRef(store.authority, "project", "release-project", "base-1")
    opened = service.open(scope, actor, request_id="open", target_kind="project", base_revision="base-1", initial_content=b"draft")
    first = service.release(opened.handle, request_id="release")
    receipt = store.get_receipt("release")
    actor_receipt = store.get_receipt("release:actor")
    assert receipt is not None and actor_receipt is not None
    before = _counts(store)
    replay = service.release(opened.handle, request_id="release")
    assert replay.status == "released"
    assert replay.receipt == receipt
    assert store.get_receipt("release:actor") == actor_receipt
    assert _counts(store) == before
    with pytest.raises(InvalidSessionError):
        service.release(opened.handle, request_id="invalid-first")
    assert _counts(store) == before
    assert first.receipt == receipt
    store.close()

    reopened = Store.open(db, authority="edt-gf02", expected_domains=(domain_contribution(),))
    try:
        reopened_service = AuthoringSessionService(reopened)
        replay_after_reopen = reopened_service.release(opened.handle, request_id="release")
        assert replay_after_reopen.receipt == receipt
        assert _counts(reopened) == before
    finally:
        reopened.close()
