"""Bounded INT-03 installed public-API probes.

This is deliberately a small discriminating harness.  It uses only public
Herzchen APIs and writes its observations as candidate evidence; it does not
stand in for the existing domain suites or for later Otto/AST consumer work.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    ReferenceBinding,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, DocumentAssociation
from herzchen.content.model import domain_contribution as content_contribution
from herzchen.content.packets import AccessDeniedError, ContextPacketService
from herzchen.domains.work import WorkGraph, WorkKind, contribution as work_contribution
from herzchen.domains.work.assignments import ResponsibilityAssignments, StaleAssignmentError
from herzchen.domains.work.batches import ProjectBatches
from herzchen.extensions import (
    MANAGED_NAMESPACE,
    OPEN_NAMESPACE,
    PROTOCOL_NAMESPACE,
    ExtensionCommandService,
    ManagedFieldError,
    OwnerRequiredError,
    SchemaValidationError,
)
from herzchen.kernel import (
    CapacityExhaustedError,
    EventCursorReader,
    LimitService,
    Store,
    TargetMismatchError,
    VersionConflictError,
    WriterBusyError,
)
from herzchen.packs.authoring import (
    ManagedPackAuthoringHandler,
    PackContentError,
    read_managed_pack,
)
from herzchen.packs.composition import CompositionMetadata, TrustedDomain, compose
from herzchen.packs.templates import TemplateEngine, WorkProtocol, work_template


ROOT = Path(__file__).parents[2]
EVIDENCE_PATH = ROOT / "work/int-03-api-probe-evidence.json"
REPORT_PATH = ROOT / "work/int-03-api-probe-result.md"
AUTHORITY = "int03-probe"
ACTOR = AuthenticatedActor(AUTHORITY, "probe-worker", "credential")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _context(key: str, value: Any, *, version: int | None = None, revision: str | None = None) -> TransactionContext:
    return TransactionContext(
        ACTOR,
        key,
        _digest(value),
        expected_version=version,
        expected_revision=revision,
    )


def _receipt(value: Any) -> Any:
    return None if value is None else _jsonable(value)


def _error(call: Any) -> dict[str, str]:
    try:
        call()
    except Exception as exc:  # the harness records public rejection, then asserts it at the call site
        return {"type": type(exc).__name__, "message": str(exc)}
    raise AssertionError("expected public API rejection")


def _observation(
    test_id: str,
    api: str,
    before: Any,
    action: Any,
    receipt: Any,
    fresh_after: Any,
    *,
    replay: Any = None,
    reject: Any = None,
    reopen: Any = None,
    evidence_class: str = "candidate_installed_api",
) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "api": api,
        "evidence_class": evidence_class,
        "before": _jsonable(before),
        "action": _jsonable(action),
        "receipt": _receipt(receipt),
        "fresh_after": _jsonable(fresh_after),
        "replay": _jsonable(replay),
        "reject": _jsonable(reject),
        "reopen": _jsonable(reopen),
    }


def _contest_reservation(path: str, reservation_id: str, key: str, output: Any) -> None:
    """Two real processes contend for the one remaining public capacity unit."""
    for _attempt in range(80):
        try:
            store = Store.open(path, authority=AUTHORITY)
        except WriterBusyError:
            time.sleep(0.003)
            continue
        try:
            service = LimitService(store)
            pool_ref = ResourceRef(AUTHORITY, "limit", "pool-final-unit")
            reservation = service.reserve(
                pool_ref,
                ResourceRef(AUTHORITY, "reservation", reservation_id),
                1,
                logical_request_key=key,
                actor=ACTOR,
            )
            output.put({"contender": reservation_id, "outcome": "winner", "reservation": _jsonable(reservation)})
            return
        except CapacityExhaustedError as exc:
            output.put({"contender": reservation_id, "outcome": "loser", "error": {"type": type(exc).__name__, "message": str(exc)}})
            return
        except Exception as exc:
            output.put({"contender": reservation_id, "outcome": "error", "error": {"type": type(exc).__name__, "message": str(exc)}})
            return
        finally:
            store.close()
    output.put({"contender": reservation_id, "outcome": "error", "error": {"type": "WriterBusyError", "message": "writer lock did not become available"}})


def _managed_pack_fixture() -> tuple[Any, Any, Any, Any]:
    """Create the same neutral public-loader fixture shape used by PKG tests."""
    pack_root = ROOT / "packs/megado"
    manifest_path = pack_root / "pack.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    resources = ("skill/SKILL.md", "skill/references/improvement-loop.md")
    handles = tuple(
        SimpleNamespace(
            path=path,
            resolved=pack_root / path,
            sha256=hashlib.sha256((pack_root / path).read_bytes()).hexdigest(),
            kind="resource:skill",
        )
        for path in resources
    )
    entry = SimpleNamespace(
        id="megado",
        manifest=SimpleNamespace(sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest()),
        definition=SimpleNamespace(id="megado", version=manifest["version"], to_dict=lambda: manifest),
        resource_handles=handles,
    )
    discovered = SimpleNamespace(
        id="megado",
        entry=entry,
        source_kind="managed",
        source_revision="c" * 40,
        source_tree_sha256="a" * 64,
        source_manifest_sha256=entry.manifest.sha256,
        source_inventory_identity="b" * 64,
        pack_dir=pack_root,
    )

    def discoverer(*, project_root: str | Path) -> tuple[Any, ...]:
        assert Path(project_root) == ROOT
        return (discovered,)

    def loader(path: str | Path, *, expected_pack_id: str | None = None) -> Any:
        assert Path(path) == manifest_path and expected_pack_id == "megado"
        return SimpleNamespace(id="megado", schema_version="2")

    return pack_root, manifest_path, handles, discoverer, loader


def _write_evidence(observations: list[dict[str, Any]], *, package_seed: dict[str, Any]) -> None:
    candidate = {
        "commit": os.environ.get("INT03_CANDIDATE_COMMIT", "unknown"),
        "tree": os.environ.get("INT03_CANDIDATE_TREE", "unknown"),
        "WRK04_source_pin": "bb25ec35d3fd17fe1c63ec623e75d68e9f410a78",
        "WRK04_local_integration": "42a80d1abab6a77afcc5aae8eb186b64bf13999a",
        "accepted_dependency_checkpoint": "5617d8b7aae1e5dd6ac2b270489b4ad1cbd324fa",
        "accepted_edt04_correction": "4769c1153fd3177271b4d849cb7a3fceb450273b",
        "accepted_edt04_final_evidence": "aaa3faeb8e9f14c58480f94786ce78360f391b96",
    }
    evidence = {
        "evidence_version": "int-03-bounded-public-api-probes/v1",
        "gate_state": "pending",
        "scope": "candidate-installed public API probes only; no acceptance, review/oracle, consumer qualification, or publication",
        "candidate": candidate,
        "worker": {
            "route": "normal",
            "requested_model": "gpt-5.6-luna",
            "reasoning": "high",
            "launcher": "/Users/hannahomalley/.local/bin/codex",
        },
        "wheel": {
            "sha256": os.environ.get("INT03_WHEEL_SHA256", "unknown"),
            "path": os.environ.get("INT03_WHEEL_PATH", "unknown"),
            "python": os.environ.get("INT03_PYTHON_VERSION", "unknown"),
            "pytest": os.environ.get("INT03_PYTEST_VERSION", "unknown"),
            "environment_unset": ["PYTHONPATH", "PYTHONHOME"],
            "installed_module_origins": json.loads(os.environ.get("INT03_MODULE_ORIGINS", "{}")),
        },
        "commands": json.loads(os.environ.get("INT03_COMMANDS_JSON", "[]")),
        "seed": package_seed,
        "observations": observations,
        "source_only_and_harness_boundaries": {
            "source_only": [
                "WRK04 source pin bb25ec35d3fd17fe1c63ec623e75d68e9f410a78; no WRK04 installed assessment claim is made by this focused probe",
                "EDT04 accepted receipt is reused from work/edt-04-receipt.json; its 27-test installed evidence and two-service finish race are not duplicated here",
                "Astrid/Runtime and Otto/AST consumer paths are source/future obligations, not installed Herzchen evidence",
            ],
            "harness_fixture": [
                "neutral managed-pack discovery/loader adapter and checkout pack bytes",
                "seed identities used to exercise public DAT extension/context APIs",
            ],
            "unsupported_or_remaining": [
                "real Otto/AST consumer journeys and G-OTTO/G-FINAL obligations",
                "EDT05/EDT06 unless supplied by an accepted dependency",
                "review/oracle call, manager judgment, product qualification, and publication",
            ],
        },
        "installed_assertions_supporting_criteria": {
            "C02": ["tests/kernel/test_transactions.py::StoreTests::test_create_open_fingerprint_composition_and_foreign_keys", "tests/kernel/test_reduced_composition.py::ReducedCompositionTests::test_fresh_kernel_and_adapter_import_excludes_optional_domains", "INT03-FND-001"],
            "C03": ["tests/kernel/test_transactions.py::StoreTests::test_mutation_is_atomic_and_replay_is_exact", "tests/kernel/test_recovery.py", "INT03-FND-002", "INT03-CURSOR-001"],
            "C04": ["tests/kernel/test_receipts_limits.py", "INT03-LIMIT-001"],
            "C05": ["tests/content/test_documents.py::FND03ContentIntegrationTests::test_create_links_unlink_and_fresh_reads_share_one_document", "INT03-DAT-001"],
            "C06": ["tests/extensions/test_namespaces.py::test_open_set_read_query_and_sibling_preservation", "INT03-DAT-003"],
            "C10": ["tests/content/test_context_visibility.py::ContextVisibilityTests::test_private_visibility_and_inherited_backlink_never_leak_hidden_ground_truth", "INT03-DAT-002"],
            "C11": ["tests/packs/test_composition.py::test_allowed_composition_delegates_to_one_fnd_writer", "tests/packs/test_protocol_resources.py", "INT03-PKG-001"],
            "C12": ["tests/packs/test_task_templates.py::test_bundle_is_literal_idempotent_and_retains_origin_namespaces_and_review", "INT03-PKG-002"],
            "C13": ["tests/work/test_assignments.py::test_one_generic_assignment_separates_reporter_launcher_and_fences_stale_writer", "tests/assessment/test_accounting.py", "INT03-WRK-002"],
            "C14": ["tests/work/test_batches.py::test_parent_sheet_is_atomic_replay_safe_and_retains_observations", "tests/packs/test_task_templates.py", "INT03-WRK-001"],
            "C15": ["tests/assessment/test_accounting.py", "INT03-WRK-002"],
            "C16": ["tests/work/test_identity_graph.py::test_aliases_and_revisions_preserve_identity_and_omission_does_not_delete", "INT03-WRK-001"],
            "C17": ["tests/conformance/test_dat_handoff.py", "INT03-PKG-003"],
            "C31": ["tests/assessment/test_accounting.py", "INT03-WRK-002"],
            "C33": ["tests/kernel/test_transactions.py", "tests/content/test_documents.py", "INT03-FND-002", "INT03-DAT-001"],
            "C34": ["tests/packs/test_protocol_resources.py", "tests/kernel/test_reduced_composition.py", "INT03-PKG-001"],
            "C35": ["INT03-FND-001", "INT03-DAT-001", "INT03-PKG-001", "INT03-WRK-001"],
        },
        "pending_criteria": ["C02", "C03", "C04", "C05", "C06", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C31", "C33", "C34", "C35"],
        "foundation_c35_statement": "C35 foundation evidence in this file is public Herzchen API evidence. Future Otto/AST consumer journeys are later INT-04/INT-05/INT-07/G-OTTO/G-FINAL obligations and are not prerequisites silently pulled into this foundation run.",
    }
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# INT-03 bounded foundation public API probes",
        "",
        "Status: `gate_state: pending`. This is candidate-installed public Herzchen API evidence only; it is not INT-03 acceptance, G-FOUNDATION, G-OTTO, product qualification, review/oracle, or publication.",
        "",
        f"Candidate commit/tree: `{candidate['commit']}` / `{candidate['tree']}`.",
        f"Wheel SHA-256: `{evidence['wheel']['sha256']}`. Python/pytest: `{evidence['wheel']['python']}` / `{evidence['wheel']['pytest']}`.",
        "Environment proof: `PYTHONPATH` and `PYTHONHOME` were unset; module origins are recorded in the JSON evidence.",
        "",
        "## Probe inventory",
        "",
    ]
    for item in observations:
        lines.append(f"- `{item['test_id']}` — `{item['api']}`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.")
    lines += [
        "",
        "## Criteria status",
        "",
        "The installed assertions and focused probe IDs supporting C02/C03/C04/C05/C06/C10/C11/C12/C13/C14/C15/C16/C17/C31/C33/C34/C35 are listed in the JSON. All remain `pending`: this lane records bounded evidence and does not convert installed assertions into a gate verdict.",
        "",
        "C35 foundation evidence is public Herzchen API evidence. Future Otto/AST consumer journeys are later INT-04/INT-05/INT-07/G-OTTO/G-FINAL obligations, not prerequisites silently pulled into this foundation run.",
        "",
        "WRK04 source identity is recorded without an installed WRK04 assessment claim. The accepted EDT04 receipt is reused without duplicating its real two-service finish race. EDT05/EDT06 remain pending unless supplied by an accepted dependency.",
        "",
        "No package seed, `validation/scenarios.json`, `validation/area-contracts.json`, control DB, source manifest, extraction map, upstream, `src/`, or another owner's product path was edited.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_int03_installed_public_api_probes(tmp_path: Path) -> None:
    observations: list[dict[str, Any]] = []
    db_path = tmp_path / "int03.sqlite"

    # FND: one public mutation boundary, receipt/event identity, replay, and reopen.
    store = Store.create(db_path, authority=AUTHORITY)
    target = ResourceRef(AUTHORITY, "probe.record", "record-1")
    payload = {"record_type": "probe.record", "value": "one", "unchanged": {"keep": True}}
    envelope = CommandEnvelope("probe.record.create", "int03.probe.v1", target, _context("fnd-create", payload, version=0), payload)
    before = {"get_record": store.get_record(target), "get_identity": store.get_identity(target), "get_receipt": store.get_receipt("fnd-create"), "events": store.list_events(stream="probe:record-1")}
    with store.transaction() as tx:
        receipt = store.mutate(envelope, event_type="probe.record.created", effects={"changed": ["value"], "unchanged": ["unchanged"]}, stream="probe:record-1", transaction=tx)
    fresh = {"get_record": store.get_record(target), "get_identity": store.get_identity(target), "get_receipt": store.get_receipt("fnd-create"), "events": store.list_events(stream="probe:record-1")}
    replay = store.mutate(envelope, event_type="probe.record.created", effects={"changed": ["value"]}, stream="probe:record-1")
    reject = _error(lambda: store.mutate(CommandEnvelope("probe.record.create", "int03.probe.v1", target, _context("fnd-create", {"value": "changed"}, version=0), {"value": "changed"})))
    domains = store.registered_domains()
    store.close()
    reopened = Store.open(db_path, authority=AUTHORITY, expected_domains=domains)
    reopen = {"get_record": reopened.get_record(target), "get_identity": reopened.get_identity(target), "get_receipt": reopened.get_receipt("fnd-create"), "events": reopened.list_events(stream="probe:record-1")}
    observations.append(_observation("INT03-FND-001", "Store.create/open + Store.transaction/mutate/get_record/get_identity/get_receipt/list_events", before, {"operation": envelope.operation, "target": target, "payload": payload}, receipt, fresh, replay=replay, reject=reject, reopen=reopen))

    # FND cursor: a fresh reader catches up from a prior cursor after restart.
    reader = EventCursorReader(reopened)
    page = reader.page("probe:record-1", limit=1)
    cursor = page.cursor
    cursor_before = {"page": page, "cursor": cursor}
    cursor_payload = {"record_type": "probe.record", "value": "two", "unchanged": {"keep": True}}
    cursor_target = ResourceRef(AUTHORITY, "probe.record", "record-1", "rev-1")
    cursor_env = CommandEnvelope("probe.record.update", "int03.probe.v1", cursor_target, _context("fnd-update", cursor_payload, version=1, revision="rev-1"), cursor_payload)
    cursor_receipt = reopened.mutate(cursor_env, event_type="probe.record.updated", effects={"changed": ["value"]}, stream="probe:record-1")
    reopened.close()
    reopened = Store.open(db_path, authority=AUTHORITY, expected_domains=domains)
    cursor_after = EventCursorReader(reopened).catch_up("probe:record-1", cursor=cursor, limit=10)
    observations.append(_observation("INT03-CURSOR-001", "EventCursorReader.page/catch_up", cursor_before, {"operation": cursor_env.operation, "receipt": cursor_receipt}, cursor_after, cursor_after, replay={"unsupported": "cursor reader is read-only; business same-key replay is captured on the public mutator"}, reject={"unsupported": "cursor reader has no write rejection path"}, reopen={"fresh_process": True, "events": reopened.list_events(stream="probe:record-1")}))

    # C04: close the parent writer, then start two real processes for one last unit.
    limits = LimitService(reopened)
    pool_ref = ResourceRef(AUTHORITY, "limit", "pool-final-unit")
    pool = limits.create_pool(pool_ref, 1, 3, logical_request_key="pool-create", actor=ACTOR)
    reopened.close()
    context = mp.get_context("fork")
    queue = context.Queue()
    contenders = [
        context.Process(target=_contest_reservation, args=(str(db_path), "reservation-a", "reserve-a", queue)),
        context.Process(target=_contest_reservation, args=(str(db_path), "reservation-b", "reserve-b", queue)),
    ]
    for process in contenders:
        process.start()
    results = [queue.get(timeout=30) for _ in contenders]
    for process in contenders:
        process.join(timeout=30)
        assert process.exitcode == 0
    winners = [item for item in results if item["outcome"] == "winner"]
    losers = [item for item in results if item["outcome"] == "loser"]
    assert len(winners) == 1 and len(losers) == 1
    reopened = Store.open(db_path, authority=AUTHORITY)
    limits = LimitService(reopened)
    winner_id = winners[0]["contender"]
    winner_ref = ResourceRef(AUTHORITY, "reservation", winner_id)
    winner = limits.get_reservation(winner_ref)
    assert winner is not None
    replay_limit = limits.reserve(pool_ref, winner_ref, 1, logical_request_key="reserve-a" if winner_id == "reservation-a" else "reserve-b", actor=ACTOR)
    changed_limit_reject = _error(lambda: limits.reserve(pool_ref, winner_ref, 2, logical_request_key="reserve-a" if winner_id == "reservation-a" else "reserve-b", actor=ACTOR))
    uncertain = limits.mark_uncertain(winner, actual_units=1, logical_request_key="uncertain-" + winner_id, actor=ACTOR)
    settled = limits.settle(uncertain, actual_units=2, logical_request_key="settle-" + winner_id, actor=ACTOR)
    reused = limits.reserve(pool_ref, ResourceRef(AUTHORITY, "reservation", "reservation-reuse"), 1, logical_request_key="reserve-reuse", actor=ACTOR)
    released = limits.release(reused, actual_units=1, logical_request_key="release-reuse", actor=ACTOR)
    final_pool = limits.get_pool(pool_ref)
    assert final_pool is not None and final_pool.available_capacity_units == 1 and final_pool.cumulative_used_units == 3 and settled.overrun_units == 1
    limit_reject = {"changed_same_key": changed_limit_reject, "wrong_owner": _error(lambda: limits.get_pool(ResourceRef("wrong-owner", "limit", pool_ref.id))), "malformed_units": _error(lambda: limits.reserve(pool_ref, "bad-units", 0, logical_request_key="bad-units"))}
    observations.append(_observation("INT03-LIMIT-001", "LimitService.reserve/mark_uncertain/settle/release", {"pool": pool, "contenders": 2, "winner": winner_id, "loser": losers[0]}, {"winner": winner_id, "uncertainty": uncertain, "settlement": settled, "capacity_reuse": reused, "release": released, "cumulative_charge": final_pool.cumulative_used_units, "overrun": settled.overrun_units}, {"winner": settled.receipt, "uncertainty": uncertain.receipt, "reuse": released.receipt}, {"pool": final_pool, "winner": limits.get_reservation(winner_ref), "reused": limits.get_reservation(ResourceRef(AUTHORITY, "reservation", "reservation-reuse"))}, replay=replay_limit, reject=limit_reject, reopen={"fresh_process": True, "pool": limits.get_pool(pool_ref)}))

    # Compose the accepted content/work contributions through the public PKG seam.
    work_registration = WorkGraph(reopened, actor=ACTOR).register()
    composition = compose(
        reopened,
        [
            TrustedDomain(content_contribution(), CompositionMetadata(edit_scope_resolver="dat.scope", conformance_adapters=("dat.adapter",))),
        ],
    )
    assert composition.ready
    observations.append(_observation("INT03-PKG-001", "packs.composition.compose + WorkGraph.register", {"registered_domains": ()}, {"domains": [item.contribution.domain_id for item in composition.domains], "work_registration": work_registration}, {"receipt": "domain registration has no command receipt; registration identity is the public domain descriptor", "events": reopened.list_events(stream="domain")}, {"ready": composition.ready, "domains": reopened.registered_domains()}, replay={"same_domain_registration": reopened.registered_domains()}, reject={"unsupported": "composition registration is declaration-level, not a receipt-bearing mutation"}, reopen={"fresh_domains": reopened.registered_domains()}, evidence_class="candidate_installed_api"))

    # DAT content and context packet public paths.
    content = ContentCommandHandler(reopened)
    document = ContentDocument(ResourceRef(AUTHORITY, "dat.content.document", "doc-1"), "brief", "private", "write", ACTOR.actor)
    initial = ContentRevision(document.ref, "rev-1", {"title": "Initial", "keep": True}, ACTOR, initial=True)
    create_env = content.build_create_document(_context("content-create", {"document": document, "revision": initial}), document, initial)
    content_before = content.read(document.ref)
    create_receipt = content.execute(create_env)
    content_after = content.read(document.ref)
    content_replay = content.execute(create_env)
    content_changed_reject = _error(lambda: content.execute(content.build_create_document(_context("content-create", {"changed": True}), document, initial)))
    second = ContentRevision(document.ref, "rev-2", {"title": "Updated", "keep": True}, ACTOR, parent_revision="rev-1")
    append_env = content.build_append_revision(_context("content-append", {"revision": second}, version=1, revision="rev-1"), document, second)
    append_receipt = content.execute(append_env)
    stale = ContentRevision(document.ref, "rev-3", {"title": "Stale"}, ACTOR, parent_revision="rev-1")
    stale_reject = _error(lambda: content.execute(content.build_append_revision(_context("content-stale", {"revision": stale}, version=1, revision="rev-1"), document, stale)))
    association = DocumentAssociation(ResourceRef(AUTHORITY, "work.task", "task-for-link"), "work", "brief", ReferenceBinding(second.ref, "pinned"))
    link_receipt = content.execute(content.build_link(_context("content-link", {"association": association}), association))
    packet_service = ContextPacketService(reopened)
    packet = packet_service.create_packet("packet-1", _context("packet-create", {"packet": "packet-1"}), [ReferenceBinding(document.ref, "current")], visibility="private", maintainer=ACTOR.actor)
    packet_read = packet_service.read_packet(packet["packet_ref"], actor=ACTOR)
    packet_compare = packet_service.compare_supplied_inputs(packet["packet_ref"], {"input-1": ReferenceBinding(document.ref, "current"), "annotation": "ignored"}, actor=ACTOR)
    packet_reject = _error(lambda: packet_service.read_packet(packet["packet_ref"], actor=AuthenticatedActor(AUTHORITY, "other", "credential")))
    observations.append(_observation("INT03-DAT-001", "ContentCommandHandler builders/execute/read + ContextPacketService.create_packet/read_packet/compare_supplied_inputs", {"document": content_before, "events": reopened.list_events(stream="dat:doc-1")}, {"create": create_env, "append": append_env, "link": association, "packet": packet["packet_ref"]}, {"create": create_receipt, "append": append_receipt, "link": link_receipt}, {"document": content_after, "packet": packet_read, "compare": packet_compare}, replay=content_replay, reject={"same_key_changed": content_changed_reject, "stale_append": stale_reject, "wrong_owner": packet_reject}, reopen={"fresh_document": content.read(document.ref), "fresh_packet": packet_service.read_packet(packet["packet_ref"], actor=ACTOR)}))

    # DAT extension metadata: definition/help, namespace merge, protected and stale rejection.
    subject = ResourceRef(AUTHORITY, "work.task", "metadata-subject", "seed-1")
    reopened.put_identity(subject, {"record_type": "work.task", "metadata": {"sibling": {"keep": True}, MANAGED_NAMESPACE: {"identity": "fnd"}}}, version=1)
    extension = ExtensionCommandService(reopened)
    extension_before = extension.read(subject)
    extension_context = _context("extension-set", {"note": "hello"}, version=1, revision="seed-1")
    extension_result = extension.set(subject, OPEN_NAMESPACE, {"note": "hello"}, extension_context)
    extension_fresh = extension.read(extension_result["subject"], OPEN_NAMESPACE)
    extension_replay = extension.set(extension_result["subject"], OPEN_NAMESPACE, {"note": "hello"}, extension_context)
    extension_reject = {
        "same_key_changed": _error(lambda: extension.set(extension_result["subject"], OPEN_NAMESPACE, {"note": "changed"}, _context("extension-set", {"note": "changed"}, version=1, revision="seed-1"))),
        "managed_field": _error(lambda: extension.set(extension_result["subject"], OPEN_NAMESPACE, {"primary": True}, _context("extension-managed", {"primary": True}, version=2, revision=extension_result["revision"]))),
        "wrong_protocol_owner": _error(lambda: extension.set(extension_result["subject"], PROTOCOL_NAMESPACE, {"choice": "hold"}, _context("extension-owner", {"choice": "hold"}, version=2, revision=extension_result["revision"]), owner="caller")),
        "malformed_schema": _error(lambda: extension.set(extension_result["subject"], PROTOCOL_NAMESPACE, {"choic": "hold"}, _context("extension-schema", {"choic": "hold"}, version=2, revision=extension_result["revision"]), owner="dat.protocol-owner")),
    }
    observations.append(_observation("INT03-DAT-003", "ExtensionCommandService.describe/read/query/set", extension_before, {"namespace": OPEN_NAMESPACE, "fields": {"note": "hello"}}, extension_result["receipt"], extension_fresh, replay=extension_replay, reject=extension_reject, reopen={"fresh": extension.read(extension_result["subject"], OPEN_NAMESPACE)}))

    # PKG templates/protocol choice and public managed pack loader/authoring.
    graph = WorkGraph(reopened, actor=ACTOR)
    engine = TemplateEngine(reopened, graph=graph, actor=ACTOR)
    project_before = graph.list(kind=WorkKind.PROJECT)
    blank = engine.instantiate("work.blank_project", logical_request_key="template-blank", actor=ACTOR)
    blank_replay = engine.instantiate("work.blank_project", logical_request_key="template-blank", actor=ACTOR)
    template = work_template("probe.template", revision="probe-1", parameters={"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}}, seed={"tasks": [{"local_id": "task", "title": {"$param": "title"}}]})
    engine.register(template)
    bundle = engine.instantiate(template, {"title": "Literal task"}, project=blank.project, logical_request_key="template-bundle", actor=ACTOR)
    protocol = WorkProtocol("probe.protocol", "probe-1", {"choices": {"normal": {"profile": "normal"}, "xhard": {"profile": "xhard"}}})
    engine.register(protocol)
    adopted = engine.adopt_protocol(blank.project, protocol, logical_request_key="protocol-adopt", actor=ACTOR)
    template_reject = {"unknown": _error(lambda: engine.instantiate("does-not-exist", project=blank.project, logical_request_key="template-bad", actor=ACTOR))}
    observations.append(_observation("INT03-PKG-002", "TemplateEngine.instantiate/adopt_protocol", project_before, {"blank": "work.blank_project", "bundle": template, "protocol": protocol}, {"blank": blank.receipts, "bundle": bundle.receipts, "adopted": reopened.get_receipt("protocol-adopt")}, {"project": adopted, "records": graph.list(project=blank.project)}, replay=blank_replay, reject=template_reject, reopen={"project": graph.get(blank.project.ref), "records": graph.list(project=blank.project)}))

    pack_root, manifest_path, handles, discoverer, loader = _managed_pack_fixture()
    managed_pack = read_managed_pack("megado", project_root=ROOT, discoverer=discoverer, loader=loader)
    pack_handler = ManagedPackAuthoringHandler(reopened)
    pack_result = pack_handler.author(managed_pack, {"skill/SKILL.md": b"# INT03 fixture adoption\n"}, logical_request_key="pack-author", actor=ACTOR)
    pack_fresh = pack_handler.read("megado")
    pack_replay_reject = _error(lambda: pack_handler.author(managed_pack, {"skill/SKILL.md": b"# INT03 fixture adoption\n"}, logical_request_key="pack-author", actor=ACTOR))
    bad_handles = tuple(SimpleNamespace(path=item.path, resolved=item.resolved, sha256=("0" * 64 if item.path.endswith("improvement-loop.md") else item.sha256), kind=item.kind) for item in handles)
    bad_discovered = SimpleNamespace(
        id="megado", entry=SimpleNamespace(id="megado", manifest=SimpleNamespace(sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest()), definition=SimpleNamespace(id="megado", version="1.0", to_dict=lambda: json.loads(manifest_path.read_text())), resource_handles=bad_handles), source_kind=managed_pack.source.source_kind, source_revision=managed_pack.source.source_revision, source_tree_sha256=managed_pack.source.source_tree_sha256, source_manifest_sha256=managed_pack.source.source_manifest_sha256, source_inventory_identity=managed_pack.source.source_inventory_identity, pack_dir=pack_root,
    )
    bad_reject = _error(lambda: read_managed_pack("megado", project_root=ROOT, discoverer=lambda **_: (bad_discovered,), loader=loader))
    observations.append(_observation("INT03-PKG-003", "public pack loader/read_managed_pack + ManagedPackAuthoringHandler.author/read", {"manifest": manifest_path, "resource_digests": managed_pack.resource_digests}, {"pack": managed_pack.pack_id, "changed": ["skill/SKILL.md"]}, pack_result.receipt if hasattr(pack_result, "receipt") else pack_result, pack_fresh, replay={"unsupported": "authoring recomputes a new snapshot revision on repeated same-key input; exact replay is rejected rather than treated as idempotent"}, reject={"same_key_replay": pack_replay_reject, "digest": bad_reject}, reopen={"fresh": pack_handler.read("megado")}, evidence_class="candidate_installed_api_with_harness_fixture"))

    # WRK graph, batch, pending project, assignment, readiness and stale fencing.
    wrk_before = graph.list()
    project = graph.create_project(title="Pending probe", metadata={"reason": "foundation"}, logical_request_key="wrk-project", actor=ACTOR)
    task = graph.create_task(project, title="Task", fields={"keep": True}, logical_request_key="wrk-task", actor=ACTOR)
    assignments = ResponsibilityAssignments(reopened, actor=ACTOR)
    assignment = assignments.assign(task, role="execution", principal="worker", reporter="reporter", launcher="launcher", logical_request_key="wrk-assignment", actor=ACTOR)
    result = assignments.append_result(assignment, {"ok": True}, logical_request_key="wrk-result", actor=ACTOR)
    batches = ProjectBatches(reopened, actor=ACTOR)
    sheet = {"metadata": {"foundation": "retained"}, "tasks": [{"id": task.id, "title": "Task revised", "fields": {"new": "value"}}]}
    batch = batches.apply_project_sheet(project, sheet, logical_request_key="wrk-sheet", actor=ACTOR)
    batch_replay = batches.apply_project_sheet(project, sheet, logical_request_key="wrk-sheet", actor=ACTOR)
    pending = batches.create_pending_project(title="Saved pending", outcome="await manager", curator="curator", logical_request_key="wrk-pending", actor=ACTOR)
    readiness = batches.observe_readiness(project, {"ready": False, "attention": "manager-choice"}, logical_request_key="wrk-readiness", actor=ACTOR)
    wrk_reject = {
        "stale_sheet": _error(lambda: batches.apply_project_sheet(project, sheet, logical_request_key="wrk-stale", base_revision="rev-1", actor=ACTOR)),
        "malformed_sheet": _error(lambda: batches.apply_project_sheet(project, {"unknown": True}, logical_request_key="wrk-malformed", actor=ACTOR)),
        "stale_assignment": _error(lambda: assignments.append_result(assignment, {"stale": True}, expected_generation=0, logical_request_key="wrk-stale-result", actor=ACTOR)),
    }
    observations.append(_observation("INT03-WRK-001", "WorkGraph.register/create_project/create_task/get/list + ProjectBatches.apply_project_sheet/create_pending_project + assignment/readiness public records", wrk_before, {"project": project, "task": task, "sheet": sheet, "pending": pending}, {"project": reopened.get_receipt("wrk-project"), "task": reopened.get_receipt("wrk-task"), "assignment": reopened.get_receipt("wrk-assignment"), "batch": batch.receipt, "pending": pending.receipt, "readiness": reopened.get_receipt("wrk-readiness")}, {"project": graph.get(project.ref), "task": graph.get(task.ref), "assignment": assignments.get(assignment.ref), "result": assignments.list_observations(assignment), "batch": batch, "readiness": readiness}, replay=batch_replay, reject=wrk_reject, reopen={"project": graph.get(project.ref), "tasks": graph.list(project=project), "assignment": assignments.get(assignment.ref), "readiness": graph.state_view(project)}))

    # Final fresh process read after every surface has been admitted.
    final_domains = reopened.registered_domains()
    final_refs = {"document": document.ref, "project": project.ref, "subject": extension_result["subject"], "packet": packet["packet_ref"]}
    reopened.close()
    final_store = Store.open(db_path, authority=AUTHORITY, expected_domains=final_domains)
    final_graph = WorkGraph(final_store, actor=ACTOR)
    final_extension = ExtensionCommandService(final_store)
    final_packet = ContextPacketService(final_store)
    final_read = {"document": ContentCommandHandler(final_store).read(document.ref), "project": final_graph.get(project.ref), "subject": final_extension.read(extension_result["subject"], OPEN_NAMESPACE), "packet": final_packet.read_packet(packet["packet_ref"], actor=ACTOR), "refs": final_refs}
    observations.append(_observation("INT03-REOPEN-001", "Store.close/open fresh-process aggregate read", {"refs": final_refs}, {"restart": True}, {"unsupported": "aggregate restart read has no new mutation receipt"}, final_read, replay={"unsupported": "read-only aggregate"}, reject={"unsupported": "read-only aggregate"}, reopen={"registered_domains": final_store.registered_domains(), "events": len(final_store.list_events())}))
    final_store.close()

    checkout_scenarios = json.loads((ROOT / "validation/scenarios.json").read_text(encoding="utf-8"))
    immutable_seed_path = Path("/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/validation/scenarios.json")
    immutable_seed_bytes = immutable_seed_path.read_bytes()
    assert hashlib.sha256(immutable_seed_bytes).hexdigest() == "99ece17752f2b67cc5658ae344067dc7bcb4089608e27b1e426b291b177624f9"
    scenarios = json.loads(immutable_seed_bytes)
    wanted = {"S-PENDING-LOOP-CORE", "S-ELEGANCE-DEFINITION", "S-ELEGANCE-CONTEXT", "S-MANAGER-CHOICE", "S-REVIEW-CHOICE", "S-LOOP-02"}
    package_seed = {"sha256": "99ece17752f2b67cc5658ae344067dc7bcb4089608e27b1e426b291b177624f9", "rows": [{key: row[key] for key in ("id", "produced_by", "criteria", "name", "required_proof", "state")} for row in scenarios["scenarios"] if row["id"] in wanted]}
    area_links = json.loads((ROOT / "validation/int03-area-links.json").read_text(encoding="utf-8"))
    seed_by_id = {row["id"]: row for row in scenarios["scenarios"]}
    checkout_by_id = {row["id"]: row for row in checkout_scenarios["scenarios"]}
    expected_ids = ["S-PENDING-LOOP-CORE", "S-ELEGANCE-DEFINITION", "S-ELEGANCE-CONTEXT", "S-MANAGER-CHOICE", "S-REVIEW-CHOICE", "S-LOOP-02"]
    assert [row["scenario_id"] for row in area_links["links"]] == expected_ids
    for link in area_links["links"]:
        seed = seed_by_id[link["scenario_id"]]
        assert link["produced_by"] == seed["produced_by"]
        assert link["criteria"] == seed["criteria"]
    projection = {row["id"]: row for row in area_links["seed_row_projection"]}
    for scenario_id in expected_ids:
        seed = seed_by_id[scenario_id]
        assert projection[scenario_id] == {field: seed[field] for field in ("id", "produced_by", "criteria", "name", "required_proof", "state")}
        assert {field: checkout_by_id[scenario_id][field] for field in ("id", "produced_by", "criteria", "name", "required_proof", "state")} == projection[scenario_id]
    observations.append(_observation("INT03-LINK-001", "additive int03-area-links seed-field mechanical comparison", {"seed_sha256": area_links["seed_sha256"], "seed_rows": package_seed["rows"]}, {"ids": expected_ids, "compared_fields": area_links["mechanical_assertion"]["compared_fields"]}, {"result": "PASS", "rows_compared": 6}, {"seed_rows_match": True}, replay={"unsupported": "declarative mapping assertion has no request key"}, reject={"unsupported": "declarative mapping assertion has no mutation path"}, reopen={"seed_unchanged": True}, evidence_class="harness_fixture"))
    _write_evidence(observations, package_seed=package_seed)
