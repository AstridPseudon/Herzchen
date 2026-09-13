"""Whole-project semantic batches composed on the supplied FND transaction.

This module intentionally has no schema or writer of its own.  The project
mutation is the parent logical command; task, link, metadata and document
state are composed in that same FND transaction and are described by the
parent event effects.  Child rows never receive a hidden request key.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import uuid
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from herzchen.contracts import AuthenticatedActor, CommandEnvelope, ReferenceBinding, ResourceRef, TransactionContext, canonical_json, ReplayConflictError
from herzchen.kernel import VersionConflictError

from .model import Lifecycle, WorkKind, WorkNotFoundError, WorkRecord, WorkValidationError
from .module import KIND_PREFIX, SCHEMA_REVISION, WorkGraph


BATCH_SCHEMA_REVISION = "work.batch.v1"
RESERVATION_KIND = "wrk.authoring-reservation"
READINESS_KIND = "wrk.readiness"
AMENDMENT_KIND = "wrk.amendment"


class MaterialisationError(WorkValidationError):
    """The durable project exists but an external editing checkout did not open."""


@dataclass(frozen=True)
class BatchResult:
    project: WorkRecord
    receipt: Any
    mappings: Mapping[str, ResourceRef]
    status: str = "committed"
    project_id: Optional[str] = None
    materialisation: Optional[Mapping[str, Any]] = None

    @property
    def ref(self) -> ResourceRef:
        return self.project.ref

    def __getattr__(self, name: str) -> Any:
        # The result is convenient in first-use paths while still exposing the
        # actual parent receipt and mappings explicitly.
        return getattr(self.project, name)

    def __getitem__(self, key: str) -> Any:
        if key == "project":
            return self.project
        if key == "receipt":
            return self.receipt
        if key == "mappings":
            return self.mappings
        if key == "status":
            return self.status
        raise KeyError(key)


@dataclass(frozen=True)
class CrossScopeResult:
    status: str
    receipts: Tuple[Any, ...]
    results: Tuple[BatchResult, ...]
    links: Tuple[ResourceRef, ...]


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise WorkValidationError(f"{field} must be a non-blank opaque identifier")
    return value


def _safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    return value


class ProjectBatches:
    """Semantic batch and pending-project operations for one work scope."""

    def __init__(self, store: Any, *, actor: Optional[AuthenticatedActor] = None) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        self.store = store
        self.default_actor = actor
        self.graph = WorkGraph(store, actor=actor)

    def apply_project_sheet(
        self,
        project: Any,
        sheet: Mapping[str, Any],
        *,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        decision_ref: Optional[Any] = None,
        base_revision: Optional[str] = None,
        next_action: Optional[str] = None,
    ) -> BatchResult:
        if not isinstance(sheet, Mapping):
            raise WorkValidationError("project sheet must be a mapping")
        request_key = self._request_key(logical_request_key)
        record = self.graph.get(project)
        if record.kind is not WorkKind.PROJECT:
            raise WorkValidationError("project sheet target must be a project")
        if base_revision is not None and base_revision != record.revision:
            raise VersionConflictError("sheet base revision is stale")
        plan = self._prepare_sheet(record, sheet, decision_ref=decision_ref, next_action=next_action)
        # Validate every child and dependency before the owner transaction is
        # opened.  The same checks are repeated as state is written below.
        self._validate_plan(record, plan)
        parent_payload = plan["project_payload"]
        with self.store.transaction() as tx:
            prior = self.store.get_receipt(request_key)
            envelope = self._envelope(
                "work.project-sheet.apply", record.ref, parent_payload, request_key, actor,
                expected_version=record.version, expected_revision=record.revision,
                digest_payload={"sheet": _safe(sheet), "decision_ref": _safe(decision_ref), "next_action": next_action},
            )
            receipt = self.store.mutate(
                envelope,
                event_type="work.project-sheet.applied",
                result_ref=ResourceRef(record.ref.authority, record.ref.kind, record.ref.id, "rev-" + str(record.version + 1)),
                before_refs=(record.ref,),
                # New child identities are admitted immediately after the
                # parent mutation.  FND reference rows are foreign-keyed, so
                # they cannot be listed in the parent event before admission;
                # the child writer below retains them in the same transaction.
                after_refs=(),
                effects={
                    "parent": record.ref,
                    "child_refs": tuple(plan["mappings"].values()),
                    "mapping": plan["mappings"],
                    "document_refs": tuple(plan["document_refs"]),
                    "logical_batch": True,
                    "next_action": next_action,
                },
                stream="work:" + record.id,
                transaction=tx,
            )
            # FND replay is decided before any child write.  A replay returns
            # here with no duplicate rows; the original result is reconstructed
            # from the parent's durable batch history below.
            if prior is not None:
                return self._result_from_replay(receipt, record)
            self._write_child_rows(tx, plan)
        fresh = self.graph.get(record.ref)
        mappings = dict(plan["mappings"])
        return BatchResult(fresh, receipt, mappings, project_id=fresh.id)

    apply_sheet = apply_project_sheet
    apply_batch = apply_project_sheet

    # Existing single-record commands remain available through their original
    # WRK-02 semantic path; a caller need not manufacture a one-row sheet.
    def revise(self, target: Any, **kwargs: Any) -> WorkRecord:
        return self.graph.revise(target, **kwargs)

    def link_parent(self, child: Any, parent: Any, **kwargs: Any) -> WorkRecord:
        return self.graph.link_parent(child, parent, **kwargs)

    def link_dependency(self, record: Any, prerequisite: Any, **kwargs: Any) -> WorkRecord:
        return self.graph.link_dependency(record, prerequisite, **kwargs)

    def create_pending_project(
        self,
        *,
        title: Optional[str] = None,
        outcome: str = "",
        curator: Any = None,
        creator: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
        sheet: Optional[Mapping[str, Any]] = None,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        reserve_authoring: bool = False,
        materializer: Optional[Callable[[WorkRecord], Any]] = None,
    ) -> BatchResult:
        request_key = self._request_key(logical_request_key)
        selected_actor = actor or self.default_actor
        project_id = "project-" + hashlib.sha256((self.store.authority + ":" + request_key).encode()).hexdigest()[:28]
        project_ref = ResourceRef(self.store.authority, KIND_PREFIX[WorkKind.PROJECT], project_id)
        initial = self._new_project_payload(project_id, title, outcome, curator, creator, metadata)
        if sheet is not None:
            if not isinstance(sheet, Mapping):
                raise WorkValidationError("project sheet must be a mapping")
            initial.update(self._pending_projection(sheet))
        reservation_ref = None
        if reserve_authoring:
            # A same-key retry must resolve the saved request first; the
            # caller's own durable reservation is expected to be present.
            if self.store.get_receipt(request_key) is None:
                self._preflight_reservation(project_ref, selected_actor)
            reservation_ref = ResourceRef(self.store.authority, RESERVATION_KIND, "reservation-" + project_id)
            initial["authoring_reservation"] = reservation_ref
        initial["creation_request"] = request_key
        with self.store.transaction() as tx:
            existing_receipt = self.store.get_receipt(request_key)
            if existing_receipt is not None:
                # The normal mutate path below performs the authoritative
                # digest comparison.  It is still useful to avoid a duplicate
                # reservation preflight on a safe same-request retry.
                pass
            receipt = self.store.mutate(
                self._envelope("work.project.create", project_ref, initial, request_key, actor, expected_version=0),
                event_type="work.project.created",
                result_ref=ResourceRef(project_ref.authority, project_ref.kind, project_ref.id, "rev-1"),
                after_refs=(),
                effects={"pending": True, "tasks": (), "curator": curator, "authoring_reservation": reservation_ref},
                stream="work:" + project_id,
                transaction=tx,
            )
            if existing_receipt is not None:
                existing = self.graph.get(receipt.result_ref or project_ref)
                return BatchResult(existing, receipt, {}, project_id=existing.id, materialisation=existing.payload.get("materialisation"))
            if reservation_ref is not None:
                reservation_payload = {"record_type": "work.authoring-reservation", "project": project_ref, "actor": _safe(selected_actor), "status": "held", "request_key": request_key, "token": "token-" + uuid.uuid4().hex}
                self.store.put_identity(ResourceRef(reservation_ref.authority, reservation_ref.kind, reservation_ref.id, "rev-1"), reservation_payload, version=1, transaction=tx)
                self.store.put_reference(reservation_ref, transaction=tx)
        project = self.graph.get(project_ref)
        result = BatchResult(project, receipt, {}, project_id=project.id, materialisation=project.payload.get("materialisation"))
        if materializer is not None:
            result = self._materialize(result, materializer, request_key, reservation_ref)
        return result

    create_pending = create_pending_project
    create_project = create_pending_project

    def retry_materialisation(self, result_or_project: Any, materializer: Callable[[WorkRecord], Any], *, logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None) -> BatchResult:
        project = result_or_project.project if isinstance(result_or_project, BatchResult) else self.graph.get(result_or_project)
        request_key = logical_request_key or project.payload.get("creation_request")
        if not request_key:
            raise WorkValidationError("saved project has no creation request ID")
        reservation = self._as_ref(project.payload.get("authoring_reservation")) if project.payload.get("authoring_reservation") else None
        return self._materialize(BatchResult(project, self.store.get_receipt(request_key), {}, project_id=project.id), materializer, request_key, reservation)  # type: ignore[arg-type]

    def activate_project(
        self, project: Any, *, manager: Any, logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None, resources: Optional[Mapping[str, Any]] = None,
    ) -> WorkRecord:
        record = self.graph.get(project)
        if record.kind is not WorkKind.PROJECT:
            raise WorkValidationError("only a project can be activated")
        if not manager:
            raise WorkValidationError("explicit manager authorisation is required")
        payload = dict(record.payload)
        payload["lifecycle"] = Lifecycle.ACTIVE.value
        payload["manager"] = _safe(manager)
        payload["resources"] = dict(resources or payload.get("resources", {}))
        payload["admitted"] = True
        payload["readiness"] = dict(payload.get("readiness", {}), dispatch=False)
        key = self._request_key(logical_request_key)
        with self.store.transaction() as tx:
            self.store.mutate(self._envelope("work.project.activate", record.ref, payload, key, actor, expected_version=record.version, expected_revision=record.revision), event_type="work.project.activated", effects={"explicit": True, "dispatch": False, "manager": _safe(manager)}, stream="work:" + record.id, transaction=tx)
        return self.graph.get(record.ref)

    activate = activate_project

    def observe_readiness(self, project: Any, observation: Mapping[str, Any], *, logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None) -> ResourceRef:
        record = self.graph.get(project)
        if not isinstance(observation, Mapping):
            raise WorkValidationError("readiness observation must be a mapping")
        key = self._request_key(logical_request_key)
        ident = ResourceRef(self.store.authority, READINESS_KIND, "readiness-" + hashlib.sha256((record.id + ":" + key).encode()).hexdigest()[:28])
        payload = {"record_type": "work.readiness", "project": record.ref, "observation": dict(observation), "dispatch": False}
        with self.store.transaction() as tx:
            self.store.mutate(self._envelope("work.readiness.observe", ident, payload, key, actor, expected_version=0), event_type="work.readiness.observed", result_ref=ResourceRef(ident.authority, ident.kind, ident.id, "rev-1"), after_refs=(record.ref,), effects={"attention_only": True, "dispatch": False}, stream="readiness:" + record.id, transaction=tx)
        return ident

    set_readiness = observe_readiness

    def append_report(self, project: Any, value: Any, *, logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None) -> ResourceRef:
        record = self.graph.get(project)
        key = self._request_key(logical_request_key)
        ident = ResourceRef(self.store.authority, "wrk.report", "report-" + hashlib.sha256((record.id + ":" + key).encode()).hexdigest()[:28])
        payload = {"record_type": "work.report", "project": record.ref, "value": value, "append_only": True}
        with self.store.transaction() as tx:
            self.store.mutate(self._envelope("work.report.append", ident, payload, key, actor, expected_version=0), event_type="work.report.appended", result_ref=ResourceRef(ident.authority, ident.kind, ident.id, "rev-1"), after_refs=(record.ref,), effects={"append_only": True, "authoring_lock": False}, stream="report:" + record.id, transaction=tx)
        return ident

    report = append_report

    def cross_scope_amendment(
        self, first_scope: Any, second_scope: Any, sheet: Mapping[str, Any], *, second_sheet: Optional[Mapping[str, Any]] = None, logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> CrossScopeResult:
        first_key = self._request_key(logical_request_key)
        first = self.apply_project_sheet(first_scope, sheet, logical_request_key=first_key + "-first", actor=actor)
        receipts = [first.receipt]
        results = [first]
        links: List[ResourceRef] = []
        status = "partial"
        try:
            second = self.apply_project_sheet(second_scope, second_sheet if second_sheet is not None else sheet, logical_request_key=first_key + "-second", actor=actor)
            results.append(second)
            receipts.append(second.receipt)
            status = "committed"
        except Exception as exc:
            status = "partial"
            # The link is an explicit, separately receipted amendment record;
            # it never claims that two scopes committed atomically.
            link_id = "amendment-" + hashlib.sha256(first_key.encode()).hexdigest()[:28]
            link_ref = ResourceRef(self.store.authority, AMENDMENT_KIND, link_id)
            payload = {"record_type": "work.amendment", "status": status, "first_scope": first.project.ref, "second_scope": self._as_ref(second_scope), "linked_receipts": [first.receipt.logical_request_key], "error": type(exc).__name__}
            with self.store.transaction() as tx:
                linked = self.store.mutate(self._envelope("work.amendment.link", link_ref, payload, first_key + "-partial", actor, expected_version=0), event_type="work.amendment.partially-linked", result_ref=ResourceRef(link_ref.authority, link_ref.kind, link_ref.id, "rev-1"), after_refs=(first.project.ref,), effects={"status": status, "separate_scope": True}, stream="amendment:" + link_id, transaction=tx)
            receipts.append(linked)
            links.append(link_ref)
        return CrossScopeResult(status, tuple(receipts), tuple(results), tuple(links))

    def choose_next_action(self, project: Any, action: str, records: Sequence[Any], *, logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None) -> BatchResult:
        action = _opaque(action, "action")
        sheet = {"tasks": [{"id": self.graph.get(item).id} for item in records], "manager_action": action}
        return self.apply_project_sheet(project, sheet, logical_request_key=logical_request_key, actor=actor, next_action=action)

    def _prepare_sheet(self, project: WorkRecord, sheet: Mapping[str, Any], *, decision_ref: Any, next_action: Optional[str]) -> Dict[str, Any]:
        allowed = {"title", "name", "outcome", "scope", "approach", "acceptance", "protocol", "custom", "metadata", "metadata_namespace", "tasks", "documents", "document_links", "document_changes", "manager_action", "resources"}
        unknown = set(sheet).difference(allowed)
        if unknown:
            raise WorkValidationError("unknown project-sheet fields: " + ", ".join(sorted(unknown)))
        task_entries = sheet.get("tasks", ())
        if not isinstance(task_entries, (list, tuple)):
            raise WorkValidationError("tasks must be an array")
        existing_by_id = {record.id: record for record in self.graph.list(project=project)}
        existing_by_alias = {alias: record for record in existing_by_id.values() for alias in record.aliases}
        # A sheet-local key is a durable alias for the lifetime of the
        # project.  Keep resolving it from the parent's batch history even
        # when the generated task identity is not itself human-readable.
        for batch in project.payload.get("batch_history", ()):
            for local_key, raw_ref in dict(batch.get("mapping", {})).items():
                mapped = self._as_ref(raw_ref)
                mapped_record = existing_by_id.get(mapped.id)
                if mapped_record is not None:
                    existing_by_alias[str(local_key)] = mapped_record
        mappings: Dict[str, ResourceRef] = {}
        planned: List[Dict[str, Any]] = []
        for index, raw in enumerate(task_entries):
            if not isinstance(raw, Mapping):
                raise WorkValidationError(f"task[{index}] must be an object")
            if raw.get("kind", "task") not in ("task", WorkKind.TASK, "work.task"):
                raise WorkValidationError(f"task[{index}] has unsupported kind")
            local_id = raw.get("id") or raw.get("alias")
            if local_id is None:
                raise WorkValidationError(f"task[{index}] needs an id or alias")
            local_key = _opaque(str(local_id), f"task[{index}].id")
            current = existing_by_id.get(local_key) or existing_by_alias.get(local_key)
            if current is not None and current.kind is not WorkKind.TASK:
                raise WorkValidationError(f"{local_key!r} is not a task")
            if current is None:
                task_id = "task-" + hashlib.sha256((project.id + ":" + local_key).encode()).hexdigest()[:28]
                ref = ResourceRef(self.store.authority, KIND_PREFIX[WorkKind.TASK], task_id)
                payload = self._new_task_payload(project, task_id, raw, index)
                version = 0
            else:
                ref = current.ref
                payload = dict(current.payload)
                version = current.version
            for forbidden in ("results", "observations", "attempts", "decisions"):
                if forbidden in raw:
                    raise WorkValidationError(f"observed field {forbidden!r} cannot be authored by a sheet")
            self._apply_task_fields(payload, raw, project, index)
            mappings[local_key] = ref
            planned.append({"local_key": local_key, "raw": raw, "ref": ref, "payload": payload, "version": version, "existing": current is not None})
        # Resolve dependencies after all local identities exist, allowing a
        # single sheet to refer forward to a later task.
        local_refs = dict(mappings)
        for item in planned:
            raw = item["raw"]
            deps = raw.get("dependencies", raw.get("depends_on", item["payload"].get("dependencies", ())))
            if not isinstance(deps, (list, tuple)):
                raise WorkValidationError(f"task {item['local_key']!r} dependencies must be an array")
            resolved: List[ResourceRef] = []
            for dependency in deps:
                dep_ref = self._resolve_task_ref(dependency, local_refs, project)
                if dep_ref not in resolved:
                    resolved.append(dep_ref)
            item["payload"]["dependencies"] = [_safe(ref) for ref in resolved]
            item["payload"]["project_ref"] = _safe(project.ref)
            item["payload"]["parent"] = _safe(project.ref)
        project_payload = dict(project.payload)
        for field in ("title", "name", "outcome", "scope", "approach", "acceptance", "protocol", "resources"):
            if field in sheet:
                project_payload[field] = _safe(sheet[field])
        if "custom" in sheet:
            project_payload["custom"] = dict(project_payload.get("custom", {}), **dict(sheet["custom"]))
        if "metadata" in sheet:
            if not isinstance(sheet["metadata"], Mapping):
                raise WorkValidationError("metadata must be a mapping")
            project_payload["metadata"] = dict(project_payload.get("metadata", {}), **dict(sheet["metadata"]))
        if "metadata_namespace" in sheet:
            if not isinstance(sheet["metadata_namespace"], Mapping):
                raise WorkValidationError("metadata_namespace must be a mapping")
            namespaces = dict(project_payload.get("metadata_namespaces", {}))
            for namespace, values in sheet["metadata_namespace"].items():
                if not isinstance(values, Mapping):
                    raise WorkValidationError("metadata namespace values must be mappings")
                namespaces[str(namespace)] = dict(namespaces.get(str(namespace), {}), **dict(values))
            project_payload["metadata_namespaces"] = namespaces
        if "tasks" in sheet:
            ordered = sorted(planned, key=lambda item: (int(item["payload"].get("order", item["raw"].get("order", 0))), item["local_key"]))
            planned_ids = {item["ref"].id for item in planned}
            retained = []
            for value in project.payload.get("tasks", ()):
                old_ref = self._as_ref(value)
                if old_ref.id not in planned_ids:
                    retained.append(old_ref)
            project_payload["tasks"] = [_safe(item["ref"]) for item in ordered] + [_safe(value) for value in retained]
        history = list(project_payload.get("batch_history", ()))
        history.append({"task_keys": [item["local_key"] for item in planned], "mapping": mappings, "manager_action": next_action or sheet.get("manager_action"), "decision_ref": _safe(decision_ref)})
        project_payload["batch_history"] = history
        project_payload["last_batch"] = history[-1]
        documents = self._prepare_documents(project, sheet, planned)
        return {"project_payload": project_payload, "planned": planned, "mappings": mappings, "documents": documents, "document_refs": tuple(documents["refs"]), "after_refs": tuple(list(mappings.values()) + list(documents["refs"]))}

    def _validate_plan(self, project: WorkRecord, plan: Mapping[str, Any]) -> None:
        adjacency: Dict[str, List[str]] = {}
        for item in plan["planned"]:
            adjacency[item["ref"].id] = [ref.id for ref in (self._as_ref(value) for value in item["payload"].get("dependencies", ()))]
            if item["payload"].get("lifecycle") not in {value.value for value in Lifecycle}:
                raise WorkValidationError("task lifecycle is invalid")
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting:
                raise WorkValidationError("project-sheet dependency cycle rejected")
            if node in visited:
                return
            visiting.add(node)
            for dep in adjacency.get(node, ()):
                if dep in adjacency:
                    visit(dep)
            visiting.remove(node)
            visited.add(node)
        for node in tuple(adjacency):
            visit(node)
        for item in plan["documents"]["changes"]:
            if item.get("scope") not in (None, "", project.id, project.ref.to_dict()):
                raise WorkValidationError("document change crosses the project scope")

    def _write_child_rows(self, tx: Any, plan: Mapping[str, Any]) -> None:
        for item in plan["planned"]:
            ref = item["ref"]
            payload = item["payload"]
            if item["existing"]:
                current = self.store.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
                if current is None:
                    raise WorkNotFoundError(f"task identity disappeared: {ref!r}")
                revised = self.store.revise_identity(
                    current.ref,
                    payload,
                    revision=self._next_identity_revision(current),
                    expected_revision=current.ref.revision,
                    expected_version=current.version,
                    expected_edit_token=current.edit_token,
                    transaction=tx,
                )
                next_ref = revised.ref
            else:
                next_ref = ResourceRef(ref.authority, ref.kind, ref.id, "rev-1")
                self.store.put_identity(next_ref, payload, version=1, transaction=tx)
                self.store.put_reference(next_ref, transaction=tx)
            for value in payload.get("dependencies", ()):
                self.store.put_reference(self._as_ref(value), transaction=tx)
        for doc in plan["documents"]["changes"]:
            self._write_document_change(tx, doc)
        for link in plan["documents"]["links"]:
            link_ref = link["ref"]
            if self.store.get_identity(link_ref) is None:
                self.store.put_identity(ResourceRef(link_ref.authority, link_ref.kind, link_ref.id, "rev-1"), link["payload"], version=1, transaction=tx)
            else:
                current = self.store.get_identity(link_ref)
                assert current is not None
                revised = self.store.revise_identity(
                    current.ref,
                    link["payload"],
                    revision=self._next_identity_revision(current),
                    expected_revision=current.ref.revision,
                    expected_version=current.version,
                    expected_edit_token=current.edit_token,
                    transaction=tx,
                )
                link_ref = revised.ref
            self.store.put_reference(link_ref, transaction=tx)

    def _write_document_change(self, tx: Any, change: Mapping[str, Any]) -> None:
        document = change["document"]
        current = self.store.get_identity(document)
        revision = change["revision"]
        revision_ref = ResourceRef(document.authority, "dat.content.revision", "revision-" + hashlib.sha256((document.id + ":" + revision).encode()).hexdigest()[:28], revision)
        revision_payload = {"record_type": "dat.content.revision", "document": document, "revision": revision, "content": change["content"], "author": change.get("author"), "initial": current is None}
        self.store.put_identity(revision_ref, revision_payload, version=0, transaction=tx)
        head_payload = {"record_type": "dat.content.document", "document": document, "current_revision": revision_ref}
        if current is None:
            self.store.put_identity(ResourceRef(document.authority, document.kind, document.id, revision), head_payload, version=1, transaction=tx)
        else:
            next_ref = self.store.revise_identity(
                current.ref,
                head_payload,
                revision=self._next_identity_revision(current),
                expected_revision=current.ref.revision,
                expected_version=current.version,
                expected_edit_token=current.edit_token,
                transaction=tx,
            ).ref
        self.store.put_reference(revision_ref, transaction=tx)

    @staticmethod
    def _next_identity_revision(identity: Any) -> str:
        """Return the one-step FND identity revision for a current record."""

        current_revision = identity.ref.revision
        if isinstance(current_revision, str) and current_revision.startswith("rev-") and current_revision[4:].isdigit():
            return "rev-" + str(int(current_revision[4:]) + 1)
        return "rev-" + str(identity.version + 1)

    def _prepare_documents(self, project: WorkRecord, sheet: Mapping[str, Any], planned: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        links: List[Dict[str, Any]] = []
        refs: List[ResourceRef] = []
        raw_changes = sheet.get("document_changes", ())
        if not isinstance(raw_changes, (list, tuple)):
            raise WorkValidationError("document_changes must be an array")
        changed_document_ids = set()
        for raw_change in raw_changes:
            if isinstance(raw_change, Mapping):
                value = raw_change.get("document_ref", raw_change.get("document"))
                if isinstance(value, str):
                    changed_document_ids.add(value)
                elif isinstance(value, Mapping) and value.get("id"):
                    changed_document_ids.add(value["id"])
        sources = [(project.ref, sheet.get("documents", ())), (project.ref, sheet.get("document_links", ()))]
        for item in planned:
            sources.append((item["ref"], item["raw"].get("documents", ())))
            sources.append((item["ref"], item["raw"].get("document_links", ())))
        for owner, raw_links in sources:
            if not isinstance(raw_links, (list, tuple)):
                raise WorkValidationError("document links must be an array")
            for index, raw in enumerate(raw_links):
                if not isinstance(raw, Mapping):
                    raise WorkValidationError(f"document link[{index}] must be an object")
                document = self._document_ref(raw.get("document_ref", raw.get("document")))
                mode = raw.get("binding", "current")
                if mode not in ("current", "pinned"):
                    raise WorkValidationError("document binding must be current or pinned")
                if mode == "current":
                    current = self.store.get_identity(ResourceRef(document.authority, document.kind, document.id))
                    binding = ResourceRef(document.authority, document.kind, document.id, current.ref.revision if current else None)
                else:
                    revision_value = raw.get("revision_ref")
                    if revision_value is None and isinstance(raw.get("revision"), str):
                        revision_value = {"authority": document.authority, "kind": document.kind, "id": document.id, "revision": raw["revision"]}
                    binding = self._document_ref(revision_value)
                    if binding.revision is None:
                        raise WorkValidationError("pinned document links require a revision")
                    if self.store.get_reference(binding) is None and self.store.get_identity(ResourceRef(binding.authority, binding.kind, binding.id)) is None and binding.id not in changed_document_ids:
                        raise WorkValidationError("pinned document revision is not retained")
                namespace = _opaque(raw.get("namespace", "work"), "document namespace")
                key = _opaque(raw.get("key", "document"), "document link key")
                ident = ResourceRef(self.store.authority, "dat.content.association", "link-" + hashlib.sha256(canonical_json({"subject": owner, "namespace": namespace, "key": key}).encode()).hexdigest()[:28])
                payload = {"record_type": "dat.content.association", "subject": owner, "namespace": namespace, "key": key, "document": ReferenceBinding(ResourceRef(binding.authority, binding.kind, binding.id, binding.revision), "pinned" if binding.revision else "current"), "active": True}
                links.append({"ref": ident, "payload": payload})
                refs.extend((document, binding))
        changes: List[Dict[str, Any]] = []
        for index, raw in enumerate(raw_changes):
            if not isinstance(raw, Mapping):
                raise WorkValidationError(f"document change[{index}] must be an object")
            document = self._document_ref(raw.get("document_ref", raw.get("document")))
            content = raw.get("content")
            if content is None and "body" in raw:
                content = raw["body"]
            if content is None:
                raise WorkValidationError(f"document change[{index}] needs content")
            revision = _opaque(raw.get("revision", "rev-" + hashlib.sha256(canonical_json(content).encode()).hexdigest()[:20]), "document revision")
            canonical_json(content)
            changes.append({"document": ResourceRef(document.authority, document.kind, document.id), "content": content, "revision": revision, "author": _safe(raw.get("author")), "scope": raw.get("scope")})
            refs.append(document)
        return {"links": links, "changes": changes, "refs": tuple(refs)}

    def _apply_task_fields(self, payload: Dict[str, Any], raw: Mapping[str, Any], project: WorkRecord, index: int) -> None:
        allowed = {"id", "alias", "aliases", "kind", "title", "name", "body", "instructions", "outcome", "acceptance", "fields", "metadata", "metadata_namespace", "custom", "order", "lifecycle", "dependencies", "depends_on", "documents", "document_links", "parent", "project_ref", "withdraw"}
        unknown = set(raw).difference(allowed)
        if unknown:
            raise WorkValidationError(f"unknown task fields for task[{index}]: {', '.join(sorted(unknown))}")
        for field in ("title", "name", "body", "instructions", "outcome", "acceptance", "order"):
            if field in raw:
                payload[field] = _safe(raw[field])
        if "title" not in payload or not isinstance(payload["title"], str) or not payload["title"].strip():
            raise WorkValidationError(f"task[{index}] title must be non-blank")
        for field in ("fields", "metadata", "custom"):
            if field in raw:
                if not isinstance(raw[field], Mapping):
                    raise WorkValidationError(f"task[{index}].{field} must be a mapping")
                payload[field] = dict(payload.get(field, {}), **dict(raw[field]))
        if "metadata_namespace" in raw:
            if not isinstance(raw["metadata_namespace"], Mapping):
                raise WorkValidationError(f"task[{index}].metadata_namespace must be a mapping")
            namespaces = dict(payload.get("metadata_namespaces", {}))
            for namespace, values in raw["metadata_namespace"].items():
                if not isinstance(values, Mapping):
                    raise WorkValidationError("task metadata namespace values must be mappings")
                namespaces[str(namespace)] = dict(namespaces.get(str(namespace), {}), **dict(values))
            payload["metadata_namespaces"] = namespaces
        if "aliases" in raw or "alias" in raw:
            values = list(payload.get("aliases", ()))
            additions = raw.get("aliases", ())
            if isinstance(additions, str):
                additions = (additions,)
            values.extend(additions)
            if raw.get("alias"):
                values.append(raw["alias"])
            values = list(dict.fromkeys(_opaque(value, "task alias") for value in values))
            payload["aliases"] = values
            payload["alias"] = values[0] if values else payload.get("alias", payload["id"])
        if raw.get("withdraw"):
            payload["lifecycle"] = Lifecycle.WITHDRAWN.value
        elif "lifecycle" in raw:
            payload["lifecycle"] = Lifecycle(raw["lifecycle"]).value
        payload.setdefault("kind", WorkKind.TASK.value)
        payload.setdefault("schema_revision", SCHEMA_REVISION)
        payload.setdefault("readiness", {"status": "not-evaluated", "ready": False, "dispatch": False})
        payload.setdefault("dependencies", [])

    def _new_task_payload(self, project: WorkRecord, task_id: str, raw: Mapping[str, Any], index: int) -> Dict[str, Any]:
        title = raw.get("title", raw.get("name"))
        if not isinstance(title, str) or not title.strip():
            raise WorkValidationError(f"task[{index}] title must be non-blank")
        return {"schema_revision": SCHEMA_REVISION, "kind": "task", "id": task_id, "title": title, "name": raw.get("name", title), "alias": raw.get("alias", task_id), "aliases": [raw.get("alias", task_id)], "parent": project.ref, "project_ref": project.ref, "dependencies": [], "lifecycle": Lifecycle.PENDING.value, "readiness": {"status": "not-evaluated", "ready": False, "dispatch": False}, "fields": {}, "metadata": {}, "custom": {}, "documents": [], "results": [], "order": index, "body": ""}

    def _resolve_task_ref(self, value: Any, local_refs: Mapping[str, ResourceRef], project: WorkRecord) -> ResourceRef:
        if isinstance(value, str) and value in local_refs:
            return ResourceRef(local_refs[value].authority, local_refs[value].kind, local_refs[value].id)
        ref = self._as_ref(value)
        if ref.kind == "work.external":
            found = self.graph._resolve(ref.id)
            if found is None or found.project_ref is None or found.project_ref.id != project.id:
                raise WorkNotFoundError(f"task dependency not found in project: {value!r}")
            return ResourceRef(found.ref.authority, found.ref.kind, found.ref.id)
        if self.store.get_identity(ResourceRef(ref.authority, ref.kind, ref.id)) is None:
            raise WorkNotFoundError(f"task dependency not found: {value!r}")
        return ResourceRef(ref.authority, ref.kind, ref.id)

    def _pending_projection(self, sheet: Mapping[str, Any]) -> Dict[str, Any]:
        allowed = {"outcome", "scope", "approach", "acceptance", "protocol", "custom", "metadata", "metadata_namespace", "documents"}
        unknown = set(sheet).difference(allowed | {"tasks", "title", "name"})
        if unknown:
            raise WorkValidationError("unknown pending-project fields: " + ", ".join(sorted(unknown)))
        result = {key: _safe(sheet[key]) for key in allowed if key in sheet}
        if "tasks" in sheet and sheet["tasks"] not in ((), [], None):
            raise WorkValidationError("pending creation accepts a sparse zero-task project; apply a sheet after creation")
        return result

    def _new_project_payload(self, project_id: str, title: Optional[str], outcome: str, curator: Any, creator: Any, metadata: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        if not isinstance(outcome, str):
            raise WorkValidationError("outcome must be text")
        title_value = title or "Untitled project"
        if not isinstance(title_value, str) or not title_value.strip():
            raise WorkValidationError("title must be non-blank")
        return {"schema_revision": SCHEMA_REVISION, "kind": "project", "id": project_id, "title": title_value, "name": title_value, "alias": project_id, "aliases": [project_id], "parent": None, "project_ref": None, "dependencies": [], "lifecycle": Lifecycle.PENDING.value, "readiness": {"status": "not-evaluated", "ready": False, "dispatch": False}, "outcome": outcome, "scope": "", "approach": "", "acceptance": {}, "tasks": [], "documents": [], "custom": {}, "protocol": None, "manager": None, "gate": None, "budget": None, "worker": None, "execution": None, "external_action": None, "provenance": {"creator": _safe(creator or self.default_actor), "curator": _safe(curator or self.default_actor)}, "metadata": dict(metadata or {})}

    def _preflight_reservation(self, project: ResourceRef, actor: Any) -> None:
        if actor is None:
            return
        actor_json = canonical_json(_safe(actor))
        rows = self.store.connection.execute("SELECT * FROM identities WHERE authority = ? AND kind = ?", (self.store.authority, RESERVATION_KIND)).fetchall()
        for row in rows:
            identity = self.store.get_identity(ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]))
            if identity is not None and identity.payload.get("status") == "held" and canonical_json(identity.payload.get("actor")) == actor_json:
                raise AssignmentBusyError("actor already holds an authoring reservation")

    def _materialize(self, result: BatchResult, materializer: Callable[[WorkRecord], Any], request_key: str, reservation: Optional[ResourceRef]) -> BatchResult:
        try:
            materializer(result.project)
        except Exception as exc:
            status = {"status": "saved; editing not opened", "error": type(exc).__name__, "request_id": request_key, "project_id": result.project.id}
            if reservation is not None:
                self._reconcile_reservation(reservation, status, request_key + "-materialisation-reconcile")
            return BatchResult(self.graph.get(result.project.ref), result.receipt, result.mappings, "saved; editing not opened", result.project.id, status)
        status = {"status": "editable", "request_id": request_key, "project_id": result.project.id}
        if reservation is not None:
            self._reconcile_reservation(reservation, status, request_key + "-materialisation-opened")
        return BatchResult(self.graph.get(result.project.ref), result.receipt, result.mappings, "editable", result.project.id, status)

    def _reconcile_reservation(self, reservation: ResourceRef, status: Mapping[str, Any], key: str) -> None:
        identity = self.store.get_identity(reservation)
        if identity is None:
            return
        payload = dict(identity.payload)
        payload["status"] = status["status"]
        payload["materialisation"] = dict(status)
        with self.store.transaction() as tx:
            self.store.mutate(self._envelope("work.authoring.reconcile", identity.ref, payload, key, None, expected_version=identity.version, expected_revision=identity.ref.revision), event_type="work.authoring.reconciled", effects=dict(status), stream="authoring:" + reservation.id, transaction=tx)

    def _result_from_replay(self, receipt: Any, original: WorkRecord) -> BatchResult:
        project = self.graph.get(receipt.result_ref or original.ref)
        last = project.payload.get("last_batch", {})
        mappings = {str(k): self._as_ref(v) for k, v in dict(last.get("mapping", {})).items()}
        return BatchResult(project, receipt, mappings, project_id=project.id)

    def _document_ref(self, value: Any) -> ResourceRef:
        if isinstance(value, ResourceRef):
            return value
        if isinstance(value, Mapping):
            return ResourceRef.from_dict(value)
        if isinstance(value, str):
            return ResourceRef(self.store.authority, "dat.content.document", _opaque(value, "document_ref"))
        raise WorkValidationError("document reference is required")

    def _as_ref(self, value: Any) -> ResourceRef:
        if isinstance(value, ResourceRef):
            return value
        if hasattr(value, "ref"):
            value = value.ref
            if isinstance(value, ResourceRef):
                return value
        if isinstance(value, Mapping):
            if "ref" in value and not {"authority", "kind", "id"}.issubset(value):
                return self._as_ref(value["ref"])
            try:
                return ResourceRef.from_dict(value)
            except (TypeError, ValueError) as exc:
                raise WorkValidationError("reference is malformed") from exc
        if isinstance(value, str):
            return ResourceRef(self.store.authority, "work.external", _opaque(value, "reference"))
        raise WorkValidationError("reference is required")

    def _request_key(self, value: Optional[str]) -> str:
        return _opaque(value or "request-" + uuid.uuid4().hex, "logical_request_key")

    def _envelope(self, operation: str, target: ResourceRef, payload: Mapping[str, Any], key: str, actor: Optional[AuthenticatedActor], *, expected_version: Optional[int], expected_revision: Optional[str] = None, digest_payload: Any = None) -> CommandEnvelope:
        selected = actor or self.default_actor or AuthenticatedActor("herzchen.work", "work-batch", "herzchen.work")
        if not isinstance(selected, AuthenticatedActor):
            raise TypeError("actor must be an FND AuthenticatedActor")
        digest_value = payload if digest_payload is None else digest_payload
        digest_target = ResourceRef(target.authority, target.kind, target.id)
        return CommandEnvelope(operation, BATCH_SCHEMA_REVISION, target, TransactionContext(selected, key, _digest({"operation": operation, "target": digest_target, "payload": digest_value}), expected_revision=expected_revision, expected_version=expected_version), payload)

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


ProjectBatchService = ProjectBatches
Batches = ProjectBatches
BatchService = ProjectBatches

__all__ = ["BATCH_SCHEMA_REVISION", "BatchResult", "BatchService", "Batches", "CrossScopeResult", "MaterialisationError", "ProjectBatchService", "ProjectBatches", "RESERVATION_KIND"]
