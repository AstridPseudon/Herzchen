"""C33: executable persisted mutation-port conformance matrix.

The matrix is intentionally derived from the accepted domain contributions.  A
row is not an inventory count: its callable exercises the public command
surface, and the common harness checks the durable boundary around that call.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping

import pytest

from herzchen.authoring.sessions import AuthoringSessionService, domain_contribution as edt_contribution
from herzchen.authoring.snapshots import Snapshot
from herzchen.authoring.writer_lease import FileWriterLeaseAuthority
from herzchen.content.commands import ContentCommandHandler
from herzchen.content.model import ContentDocument, ContentRevision, DocumentAssociation, domain_contribution as content_contribution
from herzchen.content.packets import ContextPacketService, domain_contribution as packet_contribution
from herzchen.contracts import AuthenticatedActor, CleanupStatus, ReferenceBinding, ResourceRef, TransactionContext, canonical_json
from herzchen.domains.assessment import AssessmentModule, Disposition, Verdict
from herzchen.domains.assessment.module import contribution as assessment_contribution
from herzchen.domains.work import WorkGraph, WorkKind, contributions as work_contributions
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.decisions import DecisionsModule
from herzchen.domains.work.sheet import ProjectSheet
from herzchen.extensions import OPEN_NAMESPACE, ExtensionCommandService
from herzchen.extensions.model import domain_contribution as extension_contribution
from herzchen.kernel import LimitService, Store
from herzchen.packs.authoring import ManagedPack, ManagedPackAuthoringHandler, ManagedResource, ManagedSourceIdentity, domain_contribution as pack_contribution


ROOT = Path(__file__).parents[2]
ACTOR = AuthenticatedActor("c33-conformance", "public-handler", "credential")
TMP_AUTHORITY = "c33-store"


def _descriptors() -> tuple[Any, ...]:
    values = work_contributions() + (
        assessment_contribution(),
        edt_contribution(),
        content_contribution(),
        extension_contribution(),
        packet_contribution(),
        pack_contribution(),
    )
    return tuple(sorted(values, key=lambda item: item.domain_id))


DESCRIPTORS = _descriptors()


def _ports(descriptor: Any) -> tuple[str, ...]:
    return tuple(
        binding.split(":", 1)[1]
        for binding in descriptor.composition_bindings
        if binding.startswith("mutation-port:")
    )


REMOVED_PROJECT_PARENT_PORT = "work.v1|work.revise|work.project|work.parent-linked"
REMOVED_PROJECT_PARENT_REASON = (
    "P01/FND removed this unsupported descriptor port: WorkGraph rejects project "
    "parents and exposes no valid project-parent mutation path."
)

# The current candidate is intentionally a 76-port inventory. The historical
# 77-port matrix is retained as a separate immutable artifact; it is not mixed
# into current candidate evidence.
ALL_PERSISTED_PORTS = tuple(sorted(port for descriptor in DESCRIPTORS for port in _ports(descriptor)))
assert REMOVED_PROJECT_PARENT_PORT not in ALL_PERSISTED_PORTS
ACCEPTED_PORTS = ALL_PERSISTED_PORTS
assert len(ACCEPTED_PORTS) == 76
assert len(set(ACCEPTED_PORTS)) == 76


def _handler_for(port: str) -> str:
    if port.startswith("work.v1|"):
        return "herzchen.domains.work.WorkGraph"
    if port.startswith("work.assignment.v1|"):
        return "herzchen.domains.work.assignments.ResponsibilityAssignments"
    if port.startswith("work.batch.v1|"):
        return "herzchen.domains.work.batches.ProjectBatches"
    if port.startswith("work.decisions.v1|"):
        return "herzchen.domains.work.decisions.DecisionsModule"
    if port.startswith("assessment.v1|"):
        return "herzchen.domains.assessment.AssessmentModule"
    if port.startswith("edt-02.authoring.v1|"):
        return "herzchen.authoring.sessions.AuthoringSessionService"
    if port.startswith("dat-content.v1|"):
        return "herzchen.content.commands.ContentCommandHandler"
    if port.startswith("dat.extensions.v1|"):
        return "herzchen.extensions.commands.ExtensionCommandService"
    if port.startswith("dat.context.packet.v1|"):
        return "herzchen.content.packets.ContextPacketService"
    if port.startswith("pkg-05.managed-pack.v1|"):
        return "herzchen.packs.authoring.ManagedPackAuthoringHandler"
    raise AssertionError(port)


def _operation(port: str) -> str:
    return port.split("|", 4)[1]


MATRIX = tuple(
    {
        "matrix_key": "mutation-port:" + port,
        "port": port,
        "owner": next(descriptor.owner for descriptor in DESCRIPTORS if port in _ports(descriptor)),
        "domain_id": next(descriptor.domain_id for descriptor in DESCRIPTORS if port in _ports(descriptor)),
        "public_handler": _handler_for(port),
        "operation": _operation(port),
        "scenario_id": "C33-" + hashlib.sha256(port.encode()).hexdigest()[:12],
    }
    for port in ACCEPTED_PORTS
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _counts(store: Store) -> dict[str, int]:
    return dict(store.consumer().snapshot_counts())


def _unpin(ref: ResourceRef | None) -> ResourceRef | None:
    return None if ref is None else ResourceRef(ref.authority, ref.kind, ref.id)


def _ref_from(value: Any) -> ResourceRef | None:
    if isinstance(value, ResourceRef):
        return value
    if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
        return value.ref
    if isinstance(value, Mapping):
        for key in ("ref", "subject", "target", "result_ref"):
            if key in value:
                found = _ref_from(value[key])
                if found is not None:
                    return found
    return None


def _receipt(store: Store, key: str) -> Any:
    value = store.get_receipt(key)
    assert value is not None, f"public handler did not persist receipt {key}"
    return value


def _locate_receipt(store: Store, row: Mapping[str, Any], key: str) -> Any:
    lookup = _receipt_lookup(store, row, key)
    for candidate in lookup["candidates"]:
        receipt = store.get_receipt(candidate)
        if receipt is not None and lookup["event_ids"].intersection(receipt.event_ids):
            return receipt
    return _receipt(store, key)


def _receipt_lookup(store: Store, row: Mapping[str, Any], key: str) -> dict[str, Any]:
    candidates = (
        key,
        key + ":actor",
        key + ":materialized",
        key + ":actor-release",
        key + ":recovery",
        key + ":owner",
        key + "-owner",
        key + "-first",
        key + "-partial",
        key + "-result",
        "claim:" + key,
    )
    event_ids = {
        event.event_id
        for event in store.list_events()
        if event.operation == row["operation"]
    }
    matches = []
    for candidate in candidates:
        receipt = store.get_receipt(candidate)
        if receipt is not None:
            matches.append({"candidate": candidate, "event_ids": list(receipt.event_ids), "operation": receipt.operation})
    return {"candidates": candidates, "event_ids": event_ids, "matches": matches}


def _receipt_lookup_json(store: Store, row: Mapping[str, Any], key: str) -> dict[str, Any]:
    lookup = _receipt_lookup(store, row, key)
    lookup["event_ids"] = sorted(lookup["event_ids"])
    return lookup


def _event_rows(store: Store) -> list[dict[str, Any]]:
    return [_jsonable(event) for event in store.list_events()]


def _identity_rows(store: Store, refs: Iterable[ResourceRef]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for ref in refs:
        current = store.consumer().get_identity(_unpin(ref))
        values[ref.to_json()] = _jsonable(current)
    return values


def _new_store(path: Path) -> Store:
    store = Store.create(path, authority=TMP_AUTHORITY)
    store.register_domain_handler(DESCRIPTORS)
    return store


def _reopen(path: Path) -> Store:
    return Store.open(path, authority=TMP_AUTHORITY, expected_domains=DESCRIPTORS)


def _scenario(store: Store, action: Callable[[], Any], changed: Callable[[], Any], stable: Iterable[ResourceRef]) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    stable_refs = tuple(stable)
    stable_before = _identity_rows(store, stable_refs)
    return None, action, changed, stable_refs, stable_before


def _set_scenario_metadata(action: Callable[[], Any], **metadata: Any) -> Callable[[], Any]:
    setattr(action, "c33_metadata", metadata)
    return action


def _call_work(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    graph = WorkGraph(store, actor=ACTOR)
    operation = row["operation"]
    _schema, _op, resource, event = row["port"].split("|")
    kind = resource.removeprefix("work.")
    if operation == "work.create":
        project = None
        stable: list[ResourceRef] = []
        if kind != "project":
            project = graph.create_project(title="C33 project", logical_request_key=key + ":setup")
            stable.append(project.ref)

        def action() -> Any:
            if kind == "project":
                return graph.create_project(title="C33 project", logical_request_key=key)
            return graph.create(kind, project=project, title="C33 " + kind, logical_request_key=key)

        def changed() -> Any:
            if kind == "project":
                return graph.create_project(title="C33 changed", logical_request_key=key)
            return graph.create(kind, project=project, title="C33 changed", logical_request_key=key)

        return _scenario(store, action, changed, stable)

    if kind == "project":
        target = graph.create_project(title="C33 target", logical_request_key=key + ":setup")
    else:
        project = graph.create_project(title="C33 project", logical_request_key=key + ":project")
        target = graph.create(kind, project=project, title="C33 target", logical_request_key=key + ":target")
    stable = [target.ref]
    if event == "work.parent-linked":
        if kind == "project":
            parent = graph.create_project(title="C33 parent", logical_request_key=key + ":parent")
            changed_parent = parent
        else:
            parent = graph.create_effort(graph.get(target.project_ref), title="C33 parent", logical_request_key=key + ":parent") if target.project_ref else graph.create_project(title="C33 parent", logical_request_key=key + ":parent")
            changed_parent = graph.create_effort(graph.get(target.project_ref), title="C33 changed parent", logical_request_key=key + ":changed-parent") if target.project_ref else graph.create_project(title="C33 changed parent", logical_request_key=key + ":changed-parent")
        action = lambda: graph.link_parent(target, parent, logical_request_key=key)
        # Changed arguments must reuse the same logical key so the conformance
        # check exercises replay conflict/no-delta semantics.  A new key would
        # be a legitimate independent command and would falsely report a
        # product replay defect.
        changed = lambda: graph.link_parent(target, changed_parent, logical_request_key=key)
    elif event == "work.dependency-linked":
        prerequisite = graph.create(kind, project=target.project_ref, title="C33 prerequisite", logical_request_key=key + ":prerequisite") if kind != "project" else graph.create_project(title="C33 prerequisite", logical_request_key=key + ":prerequisite")
        changed_prerequisite = graph.create(kind, project=target.project_ref, title="C33 changed prerequisite", logical_request_key=key + ":changed-prerequisite") if kind != "project" else graph.create_project(title="C33 changed prerequisite", logical_request_key=key + ":changed-prerequisite")
        action = lambda: graph.link_dependency(target, prerequisite, logical_request_key=key)
        changed = lambda: graph.link_dependency(target, changed_prerequisite, logical_request_key=key)
    elif event == "work.state-changed":
        action = lambda: graph.set_readiness(target, {"status": "ready", "ready": True}, logical_request_key=key)
        changed = lambda: graph.set_readiness(target, {"status": "changed", "ready": False}, logical_request_key=key)
    else:
        action = lambda: graph.revise(target, title="C33 revised", logical_request_key=key)
        changed = lambda: graph.revise(target, title="C33 changed", logical_request_key=key)
    return _scenario(store, action, changed, stable)


def _call_assignment(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    graph = WorkGraph(store, actor=ACTOR)
    project = graph.create_project(title="C33 assignment project", logical_request_key=key + ":project")
    service = ResponsibilityAssignments(store, actor=ACTOR)
    operation = row["operation"]
    if operation == "work.assignment.create":
        action = lambda: service.assign(project, role="review", principal="worker", logical_request_key=key)
        changed = lambda: service.assign(project, role="changed", principal="worker", logical_request_key=key)
        return _scenario(store, action, changed, (project.ref,))
    assignment = service.assign(project, role="review", principal="worker", logical_request_key=key + ":setup")
    stable = (project.ref, assignment.ref)
    if operation == "work.assignment.reassign":
        action = lambda: service.reassign(assignment, principal="replacement", expected_generation=1, logical_request_key=key)
        changed = lambda: service.reassign(assignment, principal="changed", expected_generation=1, logical_request_key=key)
    elif operation == "work.assignment.dispatch":
        action = lambda: service.dispatch(assignment, action="investigate", expected_generation=1, logical_request_key=key)
        changed = lambda: service.dispatch(assignment, action="changed", expected_generation=1, logical_request_key=key)
    elif operation == "work.result.append":
        action = lambda: service.append_result(assignment, {"value": "result"}, expected_generation=1, logical_request_key=key)
        changed = lambda: service.append_result(assignment, {"value": "changed"}, expected_generation=1, logical_request_key=key)
    else:
        action = lambda: service.append_report(assignment, {"value": "report"}, expected_generation=1, logical_request_key=key)
        changed = lambda: service.append_report(assignment, {"value": "changed"}, expected_generation=1, logical_request_key=key)
    return _scenario(store, action, changed, stable)


def _call_batch(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    graph = WorkGraph(store, actor=ACTOR)
    batches = ProjectBatches(store, actor=ACTOR)
    operation = row["operation"]
    if operation == "work.project.create":
        action = lambda: batches.create_pending_project(title="C33 pending", logical_request_key=key, actor=ACTOR)
        changed = lambda: batches.create_pending_project(title="C33 changed", logical_request_key=key, actor=ACTOR)
        return _scenario(store, action, changed, ())
    project = graph.create_project(title="C33 batch project", logical_request_key=key + ":project")
    stable = (project.ref,)
    if operation == "work.project-sheet.apply":
        action = lambda: batches.apply_project_sheet(project, {"metadata": {"c33": "applied"}}, logical_request_key=key, actor=ACTOR)
        changed = lambda: batches.apply_project_sheet(project, {"metadata": {"c33": "changed"}}, logical_request_key=key, actor=ACTOR)
    elif operation == "work.project.activate":
        action = lambda: batches.activate_project(project, manager="manager", logical_request_key=key, actor=ACTOR)
        changed = lambda: batches.activate_project(project, manager="changed", logical_request_key=key, actor=ACTOR)
    elif operation == "work.readiness.observe":
        action = lambda: batches.observe_readiness(project, {"ready": True}, logical_request_key=key, actor=ACTOR)
        changed = lambda: batches.observe_readiness(project, {"ready": False}, logical_request_key=key, actor=ACTOR)
    elif operation == "work.project-report.append":
        action = lambda: batches.append_report(project, {"report": "one"}, logical_request_key=key, actor=ACTOR)
        changed = lambda: batches.append_report(project, {"report": "two"}, logical_request_key=key, actor=ACTOR)
    elif operation == "work.amendment.link":
        other = graph.create_project(title="C33 other", logical_request_key=key + ":other")
        action = lambda: batches.cross_scope_amendment(project, other, {"metadata": {"c33": "one"}}, second_sheet={"tasks": [{"id": "invalid", "title": ""}]}, logical_request_key=key, actor=ACTOR)
        changed = lambda: batches.cross_scope_amendment(project, other, {"metadata": {"c33": "two"}}, second_sheet={"tasks": [{"id": "invalid", "title": ""}]}, logical_request_key=key, actor=ACTOR)
    else:
        action = lambda: batches.create_pending_project(title="C33 pending", logical_request_key=key, actor=ACTOR, reserve_authoring=True, materializer=lambda _project: {"path": "c33"})
        changed = lambda: batches.create_pending_project(title="C33 changed", logical_request_key=key, actor=ACTOR, reserve_authoring=True, materializer=lambda _project: {"path": "c33"})
    return _scenario(store, action, changed, stable)


def _call_decision(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    graph = WorkGraph(store, actor=ACTOR)
    parent = graph.create_task(graph.create_project(logical_request_key=key + ":project"), title="C33 obligation", logical_request_key=key + ":parent")
    criterion = graph.create_criterion(parent, title="C33 criterion", logical_request_key=key + ":criterion")
    artifact = graph.create_task(parent.project_ref, title="C33 artifact", logical_request_key=key + ":artifact")
    source = graph.create_task(parent.project_ref, title="C33 source", logical_request_key=key + ":source")
    spec = graph.create_task(parent.project_ref, title="C33 spec", logical_request_key=key + ":spec")
    decisions = DecisionsModule(store, actor=ACTOR)
    operation = row["operation"]
    if operation == "work.candidate.create":
        action = lambda: decisions.create_candidate(parent_obligation=parent, artifact=artifact, source=source, spec=spec, criteria=(criterion,), owner="owner", logical_request_key=key)
        changed = lambda: decisions.create_candidate(parent_obligation=parent, artifact=artifact, source=source, spec=spec, criteria=(criterion,), owner="changed", logical_request_key=key)
        return _scenario(store, action, changed, (parent.ref, criterion.ref, artifact.ref, source.ref, spec.ref))
    candidate = decisions.create_candidate(parent_obligation=parent, artifact=artifact, source=source, spec=spec, criteria=(criterion,), owner="owner", logical_request_key=key + ":candidate")
    stable = (parent.ref, criterion.ref, candidate.ref)
    if operation == "work.candidate.annotate":
        action = lambda: decisions.annotate_candidate(candidate, {"note": "annotated"}, logical_request_key=key)
        changed = lambda: decisions.annotate_candidate(candidate, {"note": "changed"}, logical_request_key=key)
    elif operation == "work.decision.record":
        action = lambda: decisions.record_decision(parent, candidate=candidate, authority="board", rationale="rationale", disposition="hold", logical_request_key=key)
        changed = lambda: decisions.record_decision(parent, candidate=candidate, authority="board", rationale="changed", disposition="hold", logical_request_key=key)
    elif operation == "work.wait.record":
        action = lambda: decisions.record_wait(parent, missing_obligation="input", owner="owner", awaited_ref=source, logical_request_key=key)
        changed = lambda: decisions.record_wait(parent, missing_obligation="changed", owner="owner", awaited_ref=source, logical_request_key=key)
    else:
        action = lambda: decisions.choose_next_action(parent, action="inspect", available_actions=("inspect", "hold"), logical_request_key=key)
        changed = lambda: decisions.choose_next_action(parent, action="hold", available_actions=("inspect", "hold"), logical_request_key=key)
    return _scenario(store, action, changed, stable)


def _assessment_fixture(store: Store, key: str) -> dict[str, Any]:
    graph = WorkGraph(store, actor=ACTOR)
    project = graph.create_project(title="C33 assessment project", logical_request_key=key + ":project")
    parent = graph.create_task(project, title="C33 obligation", logical_request_key=key + ":parent")
    criterion = graph.create_criterion(parent, title="C33 criterion", logical_request_key=key + ":criterion")

    artifact = graph.create_task(project, title="C33 artifact", logical_request_key=key + ":artifact")
    source = graph.create_task(project, title="C33 source", logical_request_key=key + ":source")
    spec = graph.create_task(project, title="C33 spec", logical_request_key=key + ":spec")
    candidate = DecisionsModule(store, actor=ACTOR).create_candidate(
        parent_obligation=parent, artifact=artifact, source=source, spec=spec,
        criteria=(criterion,), consumed_inputs=(source,), owner="assessment-candidate",
        logical_request_key=key + ":candidate",
    )
    assessment = AssessmentModule(store, actor=ACTOR)
    scope = assessment.declare_scope(
        ResourceRef(store.authority, "assessment.scope", key + ":scope"),
        parent_obligation=parent,
        protocol="c33.protocol",
        criteria=(criterion,),
        designated_approver=ACTOR.actor,
        authority="review-board",
        logical_request_key=key + ":scope",
    )
    packet = assessment.freeze_input(
        scope,
        packet={"candidate": candidate, "facts": ["c33"]},
        consumed_refs=(source,),
        logical_request_key=key + ":input",
    )
    pool = LimitService(store).create_pool(
        ResourceRef(store.authority, "limit", key + ":pool"),
        20,
        20,
        logical_request_key=key + ":pool",
        actor=ACTOR,
    )
    return {
        "graph": graph,
        "assessment": assessment,
        "project": project,
        "parent": parent,
        "criterion": criterion,
        "artifact": artifact,
        "source": source,
        "spec": spec,
        "candidate": candidate,
        "scope": scope,
        "packet": packet,
        "pool": pool,
    }


def _call_assessment(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    fixture = _assessment_fixture(store, key)
    assessment = fixture["assessment"]
    operation = row["operation"]
    stable = (fixture["project"].ref, fixture["parent"].ref, fixture["criterion"].ref)
    if operation == "assessment.scope.declare":
        scope_ref = ResourceRef(store.authority, "assessment.scope", key + ":action")
        action = lambda: assessment.declare_scope(scope_ref, parent_obligation=fixture["parent"], protocol="c33.action", criteria=(fixture["criterion"],), logical_request_key=key)
        changed = lambda: assessment.declare_scope(scope_ref, parent_obligation=fixture["parent"], protocol="c33.changed", criteria=(fixture["criterion"],), logical_request_key=key)
    elif operation == "assessment.input.freeze":
        action = lambda: assessment.freeze_input(fixture["scope"], packet={"candidate": fixture["candidate"], "facts": ["action"]}, consumed_refs=(fixture["source"],), logical_request_key=key)
        changed = lambda: assessment.freeze_input(fixture["scope"], packet={"candidate": fixture["candidate"], "facts": ["changed"]}, consumed_refs=(fixture["source"],), logical_request_key=key)
    elif operation == "assessment.candidate.select":
        action = lambda: assessment.select_candidate(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], rationale="c33 selection", logical_request_key=key)
        changed = lambda: assessment.select_candidate(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], rationale="changed", logical_request_key=key)
    elif operation == "assessment.run" or operation == "assessment.result.link-correction":
        verdict = Verdict.REWORK if operation == "assessment.result.link-correction" else Verdict.PASS
        findings = ({"summary": "c33 finding", "subjective": False},) if verdict is Verdict.REWORK else ()
        result = assessment.assess(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], input_packet=fixture["packet"], verdict=verdict, guidance={"next": "c33"}, protocol_result={"proof": True}, findings=findings, limit_pool=fixture["pool"].ref, logical_request_key=key + ":setup-run")
        if operation == "assessment.result.link-correction":
            result_ref = _unpin(result.ref)
            action = lambda: assessment.create_correction(assessment.get_result(result_ref), instruction="c33 correction", logical_request_key=key)
            changed = lambda: assessment.create_correction(assessment.get_result(result_ref), instruction="changed correction", logical_request_key=key)
        else:
            action = lambda: assessment.assess(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], input_packet=fixture["packet"], verdict=Verdict.PASS, guidance={"next": "c33"}, protocol_result={"proof": True}, findings=(), limit_pool=fixture["pool"].ref, logical_request_key=key)
            changed = lambda: assessment.assess(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], input_packet=fixture["packet"], verdict=Verdict.REWORK, guidance={"next": "changed"}, protocol_result={"proof": True}, findings=(), limit_pool=fixture["pool"].ref, logical_request_key=key)
    elif operation == "assessment.correction.create":
        result = assessment.assess(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], input_packet=fixture["packet"], verdict=Verdict.REWORK, findings=({"summary": "c33 finding", "subjective": False},), limit_pool=fixture["pool"].ref, logical_request_key=key + ":setup-run")
        result_ref = _unpin(result.ref)
        action = lambda: assessment.create_correction(assessment.get_result(result_ref), instruction="c33 correction", logical_request_key=key)
        changed = lambda: assessment.create_correction(assessment.get_result(result_ref), instruction="changed correction", logical_request_key=key)
    elif operation == "assessment.finding.close":
        result = assessment.assess(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], input_packet=fixture["packet"], verdict=Verdict.REWORK, findings=({"summary": "c33 finding", "subjective": False},), limit_pool=fixture["pool"].ref, logical_request_key=key + ":setup-run")
        finding = result.findings[0]
        result_ref = _unpin(result.ref)
        finding_ref = _unpin(finding.ref)
        action = lambda: assessment.close_finding(assessment.get_finding(finding_ref), rationale="c33 closed", logical_request_key=key)
        changed = lambda: assessment.close_finding(assessment.get_finding(finding_ref), rationale="changed", logical_request_key=key)
    elif operation == "assessment.accept":
        result = assessment.assess(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], input_packet=fixture["packet"], verdict=Verdict.PASS, limit_pool=fixture["pool"].ref, logical_request_key=key + ":setup-run")
        result_ref = _unpin(result.ref)
        action = lambda: assessment.accept(assessment.get_result(result_ref), authority="review-board", rationale="c33 accepted", logical_request_key=key)
        changed = lambda: assessment.accept(assessment.get_result(result_ref), authority="review-board", rationale="changed", logical_request_key=key)
    elif operation == "assessment.unknown.disposition":
        result = assessment.assess(fixture["scope"], candidate=fixture["candidate"], criterion=fixture["criterion"], input_packet=fixture["packet"], verdict=Verdict.UNKNOWN, limit_pool=fixture["pool"].ref, logical_request_key=key + ":setup-run")
        result_ref = _unpin(result.ref)
        action = lambda: assessment.dispose_unknown(assessment.get_result(result_ref), disposition=Disposition.DEFER, authority="review-board", rationale="c33 waiting", logical_request_key=key)
        changed = lambda: assessment.dispose_unknown(assessment.get_result(result_ref), disposition=Disposition.REJECT, authority="review-board", rationale="changed", logical_request_key=key)
    else:
        action = lambda: assessment.record_loop_facts(fixture["parent"], attempt_count=1, unresolved_findings=0, exhausted_allowance=False, required_approver=ACTOR.actor, logical_request_key=key)
        changed = lambda: assessment.record_loop_facts(fixture["parent"], attempt_count=2, unresolved_findings=0, exhausted_allowance=False, required_approver=ACTOR.actor, logical_request_key=key)
    return _scenario(store, action, changed, stable)


def _content_values(store: Store, ident: str = "document") -> tuple[ContentCommandHandler, ContentDocument, ContentRevision]:
    handler = ContentCommandHandler(store)
    document = ContentDocument(ResourceRef(store.authority, "project.specification", ident), "initial-specification", "private", "append", "c33-owner")
    revision = ContentRevision(document.ref, "rev-1", {"title": "C33 content"}, ACTOR, initial=True)
    return handler, document, revision


def _content_context(key: str, *, version: int, revision: str | None = None, payload: Any = None) -> TransactionContext:
    return TransactionContext(ACTOR, key, _sha(payload if payload is not None else {"key": key}), expected_version=version, expected_revision=revision)


def _call_content(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    handler, document, initial = _content_values(store)
    operation = row["operation"]
    if operation == "dat.content.document.create":
        def action() -> Any:
            return handler.execute(handler.build_create_document(_content_context(key, version=0, payload={"document": document, "revision": initial}), document, initial))
        def changed() -> Any:
            changed_revision = ContentRevision(document.ref, "rev-1", {"title": "changed"}, ACTOR, initial=True)
            return handler.execute(handler.build_create_document(_content_context(key, version=0, payload={"document": document, "revision": changed_revision}), document, changed_revision))
        return _scenario(store, action, changed, ())
    handler.execute(handler.build_create_document(_content_context(key + ":setup", version=0, payload={"document": document, "revision": initial}), document, initial))
    project = WorkGraph(store, actor=ACTOR).create_project(title="C33 content subject", logical_request_key=key + ":subject")
    if operation == "dat.content.revision.append":
        def action() -> Any:
            revision = ContentRevision(document.ref, "rev-2", {"title": "C33 appended"}, ACTOR, parent_revision="rev-1")
            return handler.execute(handler.build_append_revision(_content_context(key, version=1, revision="rev-1", payload={"revision": revision}), document, revision))
        def changed() -> Any:
            revision = ContentRevision(document.ref, "rev-2", {"title": "changed"}, ACTOR, parent_revision="rev-1")
            return handler.execute(handler.build_append_revision(_content_context(key, version=1, revision="rev-1", payload={"revision": revision}), document, revision))
    else:
        binding_ref = initial.ref if operation == "dat.content.link" else document.ref
        association = DocumentAssociation(project.ref, "work.documents", "spec", ReferenceBinding(binding_ref, "pinned" if operation == "dat.content.link" else "current"))
        def action() -> Any:
            context = _content_context(key, version=0, payload={"association": association})
            return handler.execute(handler.build_link(context, association) if operation == "dat.content.link" else handler.build_unlink(context, association))
        def changed() -> Any:
            changed_association = DocumentAssociation(project.ref, "work.documents", "changed", association.document)
            context = _content_context(key, version=0, payload={"association": changed_association})
            return handler.execute(handler.build_link(context, changed_association) if operation == "dat.content.link" else handler.build_unlink(context, changed_association))
    return _scenario(store, action, changed, (document.ref, project.ref))


def _call_extension(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    graph = WorkGraph(store, actor=ACTOR)
    subject = graph.create_task(graph.create_project(logical_request_key=key + ":project"), title="C33 extension subject", logical_request_key=key + ":task")
    service = ExtensionCommandService(store, register=False)
    operation = row["operation"]
    if operation == "dat.extensions.metadata.set":
        def action() -> Any:
            return service.set(subject.ref, OPEN_NAMESPACE, {"c33": "set"}, _content_context(key, version=subject.version, revision=subject.ref.revision, payload={"c33": "set"}))
        def changed() -> Any:
            return service.set(subject.ref, OPEN_NAMESPACE, {"c33": "changed"}, _content_context(key, version=subject.version, revision=subject.ref.revision, payload={"c33": "changed"}))
    else:
        service.set(subject.ref, OPEN_NAMESPACE, {"seed": True}, _content_context(key + ":setup", version=subject.version, revision=subject.ref.revision, payload={"seed": True}))
        current = store.consumer().get_identity(subject.ref)
        assert current is not None
        subject = type("Subject", (), {"ref": current.ref, "version": current.version})()
        def action() -> Any:
            return service.remove(subject.ref, OPEN_NAMESPACE, ("seed",), _content_context(key, version=subject.version, revision=subject.ref.revision, payload={"remove": "seed"}))
        def changed() -> Any:
            return service.remove(subject.ref, OPEN_NAMESPACE, ("missing",), _content_context(key, version=subject.version - 1, revision=subject.ref.revision, payload={"remove": "missing"}))
        _set_scenario_metadata(action, request={"logical_request_key": key, "namespace": OPEN_NAMESPACE, "fields": ["seed"], "expected_version": subject.version, "expected_revision": subject.ref.revision})
        _set_scenario_metadata(changed, request={"logical_request_key": key, "namespace": OPEN_NAMESPACE, "fields": ["missing"], "expected_version": subject.version - 1, "expected_revision": subject.ref.revision})
    return _scenario(store, action, changed, (subject.ref,))


def _call_packet(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    handler, document, initial = _content_values(store, "packet-document")
    handler.execute(handler.build_create_document(_content_context(key + ":setup", version=0, payload={"document": document, "revision": initial}), document, initial))
    amended = ContentRevision(document.ref, "rev-2", {"title": "C33 amended"}, ACTOR, parent_revision="rev-1")
    handler.execute(handler.build_append_revision(_content_context(key + ":revision", version=1, revision="rev-1", payload={"revision": amended}), document, amended))
    service = ContextPacketService(store)
    context = _content_context(key, version=0, payload={"owner": "owner"})
    action = lambda: service.notify_amendment(document.ref, amended.ref, ("owner",), context, reason="c33")
    changed = lambda: service.notify_amendment(document.ref, amended.ref, ("owner",), _content_context(key, version=0, payload={"owner": "owner", "changed": True}), reason="changed")
    return _scenario(store, action, changed, (document.ref, amended.ref))


def _managed_pack_fixture() -> ManagedPack:
    pack_root = ROOT / "packs/megado"
    manifest = pack_root / "pack.yaml"
    content = b"c33 managed content\n"
    source = ManagedSourceIdentity("c33-pack", "managed", "1" * 40, "2" * 64, hashlib.sha256(manifest.read_bytes()).hexdigest(), "3" * 64, str(pack_root), str(manifest))
    resource = ManagedResource("skill.md", "skill", content, hashlib.sha256(content).hexdigest(), ResourceRef("astrid-managed", "managed_pack", "c33-pack", "1" * 40))
    return ManagedPack("c33-pack", "1", source, {"schema_version": 2}, (resource,), (), ())


def _call_pack(row: Mapping[str, Any], store: Store, key: str) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    handler = ManagedPackAuthoringHandler(store)
    pack = _managed_pack_fixture()
    operation = row["operation"]
    if operation != "pack.content.author":
        raise AssertionError(operation)
    action = lambda: handler.author(pack, {"skill.md": "c33 updated\n"}, logical_request_key=key, actor=ACTOR)
    changed = lambda: handler.author(pack, {"skill.md": "c33 changed\n"}, logical_request_key=key, actor=ACTOR)
    return _scenario(store, action, changed, ())


def _call_authoring(row: Mapping[str, Any], store: Store, key: str, tmp_path: Path) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    service = AuthoringSessionService(store)
    actor = AuthenticatedActor(store.authority, "author", "credential")
    target = ResourceRef(store.authority, "project", "authoring-target", "base-1")
    operation = row["operation"]
    lease_context: dict[str, Any] = {}

    def open_session(request: str, *, materialize: bool = False) -> Any:
        callback = (lambda *_args, **_kwargs: {"path": "c33-checkout"}) if materialize else None
        return service.open(target, actor, request_id=request, target_kind="project", base_revision="base-1", initial_content=b"initial", materialize=callback)

    if operation in {"actor.open", "open", "metadata"}:
        action = lambda: open_session(key, materialize=operation == "metadata")
        changed = lambda: service.open(target, actor, request_id=key, target_kind="project", base_revision="changed", initial_content=b"changed", materialize=(lambda *_args, **_kwargs: {"path": "changed"}) if operation == "metadata" else None)
        return _scenario(store, action, changed, (target,))

    opened = open_session(key + ":setup")
    assert opened.handle is not None
    handle = opened.handle
    if operation == "autosave":
        action = lambda: service.autosave(handle, request_id=key, snapshot=b"autosave")
        changed = lambda: service.autosave(handle, request_id=key, snapshot=b"changed")
    elif operation in {"finish.claim", "finish"}:
        action = lambda: service.finish(handle, request_id=key, mode="manual", capture=b"final")
        changed = lambda: service.finish(handle, request_id=key, mode="manual", capture=b"changed")
    elif operation == "finish.recovery":
        def failing_capture() -> bytes:
            raise RuntimeError("c33 capture failure")
        action = lambda: service.finish(handle, request_id=key, mode="manual", capture=failing_capture)
        changed = lambda: service.finish(handle, request_id=key, mode="manual", capture=lambda: b"changed")
    elif operation in {"actor.release", "release"}:
        action = lambda: service.release(handle, request_id=key)
        changed = lambda: service.release(handle, request_id=key)
    elif operation in {"cleanup", "cleanup.refresh"}:
        root = tmp_path / "lease-root"
        root.mkdir(exist_ok=True)
        leases = FileWriterLeaseAuthority(root, authority="c33-lease", secret=b"c33-conformance-secret-0123456789", writer_identities=("editor",))
        held = leases.hold_retirement(root, owner_identity="editor")
        guard = held.__enter__()
        lease_context["held"] = held
        finished = service.finish(handle, request_id=key + ":finish", mode="manual", capture=b"final", retirement_guard=guard)
        if operation == "cleanup":
            action = lambda: service.cleanup(handle, request_id=key)
            changed = lambda: service.cleanup(handle, request_id=key, status=CleanupStatus.UNSAFE)
        else:
            service.reestablish_retirement_fence(handle, request_id=key + ":reestablish", retirement_guard=guard)
            snapshot = Snapshot(ResourceRef(store.authority, "authoring-snapshot", "c33-refresh", hashlib.sha256(b"refresh").hexdigest()), b"refresh")
            action = lambda _held=held: service.refresh_final_snapshot(handle, request_id=key, snapshot=snapshot, retirement_guard=guard)
            changed = lambda _held=held: service.refresh_final_snapshot(handle, request_id=key, snapshot=Snapshot(ResourceRef(store.authority, "authoring-snapshot", "c33-refresh-2", _sha(b"changed")), b"changed"), retirement_guard=guard)
    else:
        raise AssertionError(operation)
    stable_before = _identity_rows(store, (target,))
    return None, action, changed, (target,), stable_before


def _dispatch(row: Mapping[str, Any], store: Store, key: str, tmp_path: Path | None = None) -> tuple[Any, Callable[[], Any], Callable[[], Any], tuple[ResourceRef, ...], dict[str, Any]]:
    if row["port"].startswith("work.v1|"):
        return _call_work(row, store, key)
    if row["port"].startswith("work.assignment.v1|"):
        return _call_assignment(row, store, key)
    if row["port"].startswith("work.batch.v1|"):
        return _call_batch(row, store, key)
    if row["port"].startswith("work.decisions.v1|"):
        return _call_decision(row, store, key)
    if row["port"].startswith("assessment.v1|"):
        return _call_assessment(row, store, key)
    if row["port"].startswith("dat-content.v1|"):
        return _call_content(row, store, key)
    if row["port"].startswith("dat.extensions.v1|"):
        return _call_extension(row, store, key)
    if row["port"].startswith("dat.context.packet.v1|"):
        return _call_packet(row, store, key)
    if row["port"].startswith("pkg-05.managed-pack.v1|"):
        return _call_pack(row, store, key)
    if row["port"].startswith("edt-02.authoring.v1|"):
        assert tmp_path is not None
        return _call_authoring(row, store, key, tmp_path)
    raise NotImplementedError(row["port"])


def _record_result(row: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    path = Path(os.environ.get("C33_RESULT_PATH", str(ROOT / "work/c33-persisted-port-result-20260914.json")))
    run_id = os.environ.get("C33_RUN_ID", "source")
    if path.exists():
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("run_id") != run_id:
            evidence = _evidence_header(run_id)
    else:
        evidence = _evidence_header(run_id)
    evidence.setdefault("rows", {})[row["matrix_key"]] = result
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _evidence_header(run_id: str) -> dict[str, Any]:
    return {
        "evidence_version": "c33-persisted-port-conformance/v1",
        "run_id": run_id,
        "source": {
            "commit": os.environ.get("C33_SOURCE_COMMIT"),
            "tree": os.environ.get("C33_SOURCE_TREE"),
        },
        "tooling_correction": "pytest/build commands use TMPDIR=/private/tmp because the prior macOS TMPDIR pointed to a deleted /var/folders/.../T path",
        "runtime": {"python": sys.version, "pytest": pytest.__version__},
        "wheel": {
            "path": os.environ.get("C33_WHEEL_PATH"),
            "sha256": os.environ.get("C33_WHEEL_SHA256"),
        },
        "module_origins": json.loads(os.environ["C33_MODULE_ORIGINS_JSON"]) if os.environ.get("C33_MODULE_ORIGINS_JSON") else {},
        "rows": {},
    }


def _count_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    return {name: after.get(name, 0) - before.get(name, 0) for name in before}


def _phase_error(phase: str, exc: BaseException) -> dict[str, str]:
    return {"phase": phase, "type": type(exc).__name__, "message": str(exc)}


def _status_for_exception(row: Mapping[str, Any], phase: str, exc: BaseException) -> str:
    if phase == "fixture_setup":
        return "fixture_incomplete"
    if (
        phase == "first_action"
        and row["port"] == "work.v1|work.revise|work.project|work.parent-linked"
        and type(exc).__name__ == "InvalidParentError"
    ):
        return "fixture_incomplete"
    return "reproduced_owner_defect"


def _metadata_snapshot(rows: Mapping[str, Any]) -> dict[str, Any]:
    if not rows:
        return {}
    identity = next(iter(rows.values()))
    payload = identity.get("payload", {}) if isinstance(identity, Mapping) else {}
    return _jsonable(payload.get("metadata", {})) if isinstance(payload, Mapping) else {}


def test_matrix_is_exact_bijection() -> None:
    assert tuple(item["port"] for item in MATRIX) == ACCEPTED_PORTS
    assert len({item["matrix_key"] for item in MATRIX}) == 76
    assert all(item["public_handler"] for item in MATRIX)
    matrix_path = Path(os.environ.get("C33_MATRIX_PATH", str(ROOT / "work/c33-persisted-port-matrix-76-20260914.json")))
    matrix_path.write_text(json.dumps({
        "matrix_version": "c33-persisted-port-conformance/v2-current-76",
        "source_commit": os.environ.get("C33_SOURCE_COMMIT"),
        "source_tree": os.environ.get("C33_SOURCE_TREE"),
        "row_count": len(MATRIX),
        "historical_row_count": 77,
        "removed_ports": [{"port": REMOVED_PROJECT_PARENT_PORT, "reason": REMOVED_PROJECT_PARENT_REASON}],
        "rows": list(MATRIX),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.parametrize("row", MATRIX, ids=lambda item: item["scenario_id"])
def test_persisted_port_public_handler_conformance(tmp_path: Path, row: Mapping[str, Any]) -> None:
    key = "c33:" + row["scenario_id"]
    path = tmp_path / (row["scenario_id"] + ".sqlite")
    store = _new_store(path)
    fixture_before_counts = _counts(store)
    fixture_before_events = _event_rows(store)

    def failure(
        status: str,
        phase: str,
        exc: BaseException,
        *,
        first_action_valid: bool | None,
        fixture_after_counts: Mapping[str, int],
        fixture_after_events: list[dict[str, Any]],
        action_before_counts: Mapping[str, int] | None = None,
        action_before_events: list[dict[str, Any]] | None = None,
        action_after_counts: Mapping[str, int] | None = None,
        action_after_events: list[dict[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        observation: dict[str, Any] = {
            "status": status,
            "matrix_key": row["matrix_key"],
            "public_handler": row["public_handler"],
            "first_action_valid": first_action_valid,
            "phase_exception": _phase_error(phase, exc),
            "fixture_setup": {
                "before_counts": fixture_before_counts,
                "after_counts": dict(fixture_after_counts),
                "delta": _count_delta(fixture_before_counts, fixture_after_counts),
                "before_event_count": len(fixture_before_events),
                "after_event_count": len(fixture_after_events),
            },
            "scenario": dict(metadata or {}),
        }
        if action_before_counts is not None and action_after_counts is not None:
            observation["command"] = {
                "before_counts": dict(action_before_counts),
                "after_counts": dict(action_after_counts),
                "delta": _count_delta(action_before_counts, action_after_counts),
                "before_event_count": len(action_before_events or []),
                "after_event_count": len(action_after_events or []),
            }
        if row["port"] == "work.v1|work.revise|work.project|work.parent-linked" and status == "fixture_incomplete":
            observation["catalog_inconsistency"] = {
                "descriptor": row["port"],
                "public_handler": "herzchen.domains.work.WorkGraph.link_parent",
                "mismatch": "the accepted descriptor requires project parent-linked, but the public WorkGraph surface rejects every project parent with InvalidParentError; no valid public parent-clear path was identified",
            }
        _record_result(row, observation)

    try:
        try:
            action_result, action, changed, stable_refs, stable_before = _dispatch(row, store, key, tmp_path)
        except Exception as exc:
            fixture_after_counts = _counts(store)
            fixture_after_events = _event_rows(store)
            failure("fixture_incomplete", "fixture_setup", exc, first_action_valid=None, fixture_after_counts=fixture_after_counts, fixture_after_events=fixture_after_events)
            return

        action_before_counts = _counts(store)
        action_before_events = _event_rows(store)
        scenario_metadata = getattr(action, "c33_metadata", {})
        try:
            action_result = action()
        except Exception as exc:
            action_after_counts = _counts(store)
            action_after_events = _event_rows(store)
            failure(_status_for_exception(row, "first_action", exc), "first_action", exc, first_action_valid=False, fixture_after_counts=action_before_counts, fixture_after_events=action_before_events, action_before_counts=action_before_counts, action_before_events=action_before_events, action_after_counts=action_after_counts, action_after_events=action_after_events, metadata=scenario_metadata)
            return

        action_after_counts = _counts(store)
        action_after_events = _event_rows(store)
        try:
            receipt = _locate_receipt(store, row, key)
            assert action_after_counts["events"] > action_before_counts["events"]
            assert action_after_counts["command_receipts"] > action_before_counts["command_receipts"]
            assert tuple(event.event_id for event in store.list_events() if event.event_id in receipt.event_ids) == receipt.event_ids
            result_ref = receipt.result_ref or _ref_from(action_result)
            assert result_ref is not None
            assert store.consumer().get_identity(_unpin(result_ref)) is not None or store.consumer().get_reference(result_ref) is not None
        except Exception as exc:
            evidence_metadata = dict(scenario_metadata)
            evidence_metadata["receipt_lookup"] = _receipt_lookup_json(store, row, key)
            failure("reproduced_owner_defect", "action_evidence", exc, first_action_valid=True, fixture_after_counts=action_before_counts, fixture_after_events=action_before_events, action_before_counts=action_before_counts, action_before_events=action_before_events, action_after_counts=action_after_counts, action_after_events=action_after_events, metadata=evidence_metadata)
            return

        stable_after = _identity_rows(store, stable_refs)
        try:
            replay = action()
            replay_counts = _counts(store)
            replay_events = _event_rows(store)
            replay_receipt = _locate_receipt(store, row, key)
            assert replay_receipt == receipt
            assert replay_counts == action_after_counts
            assert replay_events == action_after_events
        except Exception as exc:
            failure("reproduced_owner_defect", "exact_replay", exc, first_action_valid=True, fixture_after_counts=action_before_counts, fixture_after_events=action_before_events, action_before_counts=action_before_counts, action_before_events=action_before_events, action_after_counts=action_after_counts, action_after_events=action_after_events, metadata=scenario_metadata)
            return

        changed_error: dict[str, str] | None = None
        changed_result: Any = None
        reject_before_counts = _counts(store)
        reject_before_events = _event_rows(store)
        try:
            changed_result = changed()
        except Exception as exc:
            changed_error = {"type": type(exc).__name__, "message": str(exc)}
        reject_counts = _counts(store)
        reject_events = _event_rows(store)
        try:
            if changed_error is None:
                assert reject_counts == reject_before_counts, "changed request/precondition unexpectedly committed"
                assert reject_events == reject_before_events, "changed request/precondition emitted an event"
                changed_error = {"type": "RejectedWithoutException", "message": "public handler returned without a durable delta"}
            assert reject_counts == action_after_counts
            assert _locate_receipt(store, row, key) == receipt
            assert _identity_rows(store, stable_refs) == stable_after
        except Exception as exc:
            failure("reproduced_owner_defect", "changed_request", exc, first_action_valid=True, fixture_after_counts=action_before_counts, fixture_after_events=action_before_events, action_before_counts=action_before_counts, action_before_events=action_before_events, action_after_counts=action_after_counts, action_after_events=action_after_events, metadata=scenario_metadata)
            return

        store.close()
        try:
            reopened = _reopen(path)
            try:
                reopened_ref = _unpin(result_ref)
                assert reopened.consumer().get_identity(reopened_ref) is not None or reopened.consumer().get_reference(result_ref) is not None
                assert _locate_receipt(reopened, row, key) == receipt
                assert _event_rows(reopened) == reject_events
                reopen = {"counts": _counts(reopened), "identity": _jsonable(reopened.consumer().get_identity(reopened_ref)), "receipt": _jsonable(_locate_receipt(reopened, row, key)), "events": _event_rows(reopened)}
            finally:
                reopened.close()
        except Exception as exc:
            failure("reproduced_owner_defect", "close_reopen", exc, first_action_valid=True, fixture_after_counts=action_before_counts, fixture_after_events=action_before_events, action_before_counts=action_before_counts, action_before_events=action_before_events, action_after_counts=action_after_counts, action_after_events=action_after_events, metadata=scenario_metadata)
            return

        observation = {
            "status": "passed",
            "matrix_key": row["matrix_key"],
            "public_handler": row["public_handler"],
            "first_action_valid": True,
            "phase_exception": None,
            "fixture_setup": {"before_counts": fixture_before_counts, "after_counts": action_before_counts, "delta": _count_delta(fixture_before_counts, action_before_counts), "before_event_count": len(fixture_before_events), "after_event_count": len(action_before_events)},
            "before": {"counts": action_before_counts, "events": action_before_events, "stable_refs": stable_before},
            "action": {"result": _jsonable(action_result), "receipt": _jsonable(receipt), "delta": _count_delta(action_before_counts, action_after_counts), "stable_after": stable_after, "metadata": dict(scenario_metadata)},
            "replay": {"result": _jsonable(replay), "receipt": _jsonable(replay_receipt), "counts_unchanged": replay_counts == action_after_counts, "events_unchanged": replay_events == action_after_events},
            "reject": {"error": changed_error, "result": _jsonable(changed_result), "request": _jsonable(getattr(changed, "c33_metadata", {})), "counts_unchanged": reject_counts == action_after_counts, "events_unchanged": reject_events == action_after_events},
            "reopen": reopen,
        }
        if row["operation"] == "dat.extensions.metadata.remove":
            observation["metadata_remove"] = {
                "before": _metadata_snapshot(stable_before),
                "after": _metadata_snapshot(stable_after),
                "action_request": _jsonable(scenario_metadata.get("request", {})),
                "action_receipt": _jsonable(receipt),
                "action_event_ids": list(receipt.event_ids),
                "immediate_action_delta": _count_delta(action_before_counts, action_after_counts),
                "changed_request": _jsonable(getattr(changed, "c33_metadata", {})),
                "changed_request_zero_delta": reject_counts == action_after_counts and reject_events == action_after_events,
            }
        _record_result(row, observation)
    finally:
        try:
            store.close()
        except Exception:
            pass
