"""Typed project-sheet views and bindings over the accepted WRK ports.

``ProjectSheet`` is deliberately an adapter, not another work writer.  Plan
changes are checked here for sheet-specific policy and then delegated to
``ProjectBatches.apply_project_sheet``.  That keeps a sheet edit and a direct
batch command on the same FND transaction, receipt, event, replay, and
rollback path.

The read side joins fresh FND identities from work, assignments, decisions,
waiting, and DAT associations.  Observed values are returned separately from
the editable authored projection and are never accepted as sheet input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional, Sequence, Tuple
from herzchen.command_ports import command_facade

from herzchen.contracts import AuthenticatedActor, DomainContribution, ReferenceBinding, ResourceRef, canonical_json
from herzchen.kernel import VersionConflictError

from .assignments import ASSIGNMENT_KIND, DISPATCH_KIND, RESULT_KIND, REPORT_KIND, ResponsibilityAssignments
from .batches import BatchResult, ProjectBatches, _ProjectBatchesEngine
from .decisions import DECISION_KIND, WAIT_KIND, DecisionError, DecisionsModule
from .model import Lifecycle, WorkKind, WorkRecord, WorkValidationError


SHEET_SCHEMA_REVISION = "work.project-sheet.v1"
DOMAIN_ID = "herzchen.work.sheet"


def contribution() -> DomainContribution:
    operation = "work.assignment.route-pin"
    event = "work.assignment.route-pinned"
    resource = "wrk.assignment"
    mutation_schema = "work.batch.v1"
    return DomainContribution(
        DOMAIN_ID, "1.0", "wrk", (), (), ("work.sheet",), (operation,), (event,),
        mutation_schema,
        (
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "handler-required", "mutation-resource:" + resource,
            "mutation-port:{}|{}|{}|{}".format(mutation_schema, operation, resource, event),
        ),
    )


class SheetError(WorkValidationError):
    """Base error for typed sheet interpretation and policy bindings."""


class ProtectedFieldError(SheetError):
    """A read-only observed or authority-bearing field was authored."""


class SheetSelectionError(SheetError):
    """A selected task/document is not part of the requested project view."""


class PolicyAuthorityError(SheetError):
    """A policy amendment lacks the required authority or exact context."""


@dataclass(frozen=True)
class SheetDefinitions:
    """The one shared field definition used for blank and existing sheets."""

    project_editable: Tuple[str, ...] = (
        "title", "name", "outcome", "scope", "approach", "acceptance",
        "protocol", "custom", "metadata", "metadata_namespace", "documents",
        "document_links", "document_changes", "tasks",
    )
    task_editable: Tuple[str, ...] = (
        "id", "alias", "aliases", "title", "name", "body", "instructions",
        "outcome", "acceptance", "fields", "metadata", "metadata_namespace",
        "custom", "order", "lifecycle", "dependencies", "depends_on",
        "documents", "document_links", "withdraw",
    )
    protected: Tuple[str, ...] = (
        "budget", "spend", "allowance", "approval", "result", "results",
        "accepted", "acceptance_state", "decision", "decisions", "observations",
        "attempts", "dispatch", "launch", "session", "worker", "execution",
        "manager", "admitted",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_revision": SHEET_SCHEMA_REVISION,
            "project_editable": list(self.project_editable),
            "task_editable": list(self.task_editable),
            "protected_read_only": list(self.protected),
            "observed_context": [
                "readiness", "assignments", "dispatches", "results", "reports",
                "candidates", "decisions", "waiting", "document_revisions",
            ],
        }


@dataclass(frozen=True)
class SheetView(Mapping[str, Any]):
    """Fresh selected sheet view with authored and observed projections."""

    project: Mapping[str, Any]
    tasks: Tuple[Mapping[str, Any], ...]
    documents: Tuple[Mapping[str, Any], ...]
    definitions: SheetDefinitions
    decision_context: Tuple[Mapping[str, Any], ...]
    readiness: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "definitions": self.definitions.to_dict(),
            "project": _safe(self.project),
            "tasks": [_safe(value) for value in self.tasks],
            "documents": [_safe(value) for value in self.documents],
            "decision_context": [_safe(value) for value in self.decision_context],
            "readiness": _safe(self.readiness),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(("definitions", "project", "tasks", "documents", "decision_context", "readiness"))

    def __len__(self) -> int:
        return 6


@dataclass(frozen=True)
class SheetApplication:
    """Batch result plus the fresh after-view for callers that want both."""

    batch: BatchResult
    view: SheetView

    def __getattr__(self, name: str) -> Any:
        return getattr(self.batch, name)

    @property
    def receipt(self) -> Any:
        return self.batch.receipt

    @property
    def project(self) -> WorkRecord:
        return self.batch.project

    @property
    def mappings(self) -> Mapping[str, ResourceRef]:
        return self.batch.mappings


@dataclass(frozen=True)
class RoutePinResult:
    assignment: Any
    receipt: Any

    def __getattr__(self, name: str) -> Any:
        return getattr(self.assignment, name)


def _safe(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    return value


def _ref(value: Any) -> Optional[ResourceRef]:
    if isinstance(value, ResourceRef):
        return value
    if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
        return value.ref
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _same_identity(left: Any, right: Any) -> bool:
    a, b = _ref(left), _ref(right)
    return a is not None and b is not None and (a.authority, a.kind, a.id) == (b.authority, b.kind, b.id)


class _SheetBatchesEngine(_ProjectBatchesEngine):
    """ProjectBatches with one DAT binding-shape adapter for sheet callers."""

    def _prepare_documents(self, project: WorkRecord, sheet: Mapping[str, Any], planned: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        prepared = super()._prepare_documents(project, sheet, planned)
        modes: dict[tuple[str, str, str], str] = {}
        sources = [(project.ref, sheet.get("documents", ())), (project.ref, sheet.get("document_links", ()))]
        for item in planned:
            sources.append((item["ref"], item["raw"].get("documents", ())))
            sources.append((item["ref"], item["raw"].get("document_links", ())))
        for owner, raw_links in sources:
            for raw in raw_links:
                namespace = raw.get("namespace", "work")
                key = raw.get("key", "document")
                modes[(owner.id, str(namespace), str(key))] = raw.get("binding", "current")
        for link in prepared["links"]:
            payload = link["payload"]
            subject = _ref(payload.get("subject"))
            document = payload.get("document")
            namespace, key = payload.get("namespace"), payload.get("key")
            if subject is None or not isinstance(document, ReferenceBinding):
                continue
            if modes.get((subject.id, str(namespace), str(key))) == "current":
                payload["document"] = ReferenceBinding(
                    ResourceRef(document.ref.authority, document.ref.kind, document.ref.id), "current"
                )
        return prepared


_SheetBatches = command_facade(_SheetBatchesEngine, "herzchen.work.sheet-batches")


class _ProjectSheetEngine:
    """Project-sheet interpretation over one supplied FND Store."""

    definitions = SheetDefinitions()

    def __init__(
        self,
        store: Any,
        *,
        actor: Optional[AuthenticatedActor] = None,
        batches: Optional[ProjectBatches] = None,
        decisions: Optional[DecisionsModule] = None,
        assignments: Optional[ResponsibilityAssignments] = None,
    ) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "get_identity"):
            raise TypeError("store must be the supplied FND writer")
        from .module import work_handler
        self.__writer = work_handler(store)
        self.reader = self.__writer.consumer()
        self.actor = actor
        self.batches = batches or _SheetBatches(self.__writer, actor=actor)
        self.graph = self.batches.graph
        self.decisions = decisions or DecisionsModule(self.__writer, actor=actor)
        self.assignments = assignments or ResponsibilityAssignments(self.__writer, actor=actor)

    # ---- common sheet commands -------------------------------------------------

    def create_pending(
        self, *, title: Optional[str] = None, outcome: str = "", curator: Any = None,
        creator: Any = None, metadata: Optional[Mapping[str, Any]] = None,
        logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None,
    ) -> BatchResult:
        """Save a durable, zero-task pending project without admission."""
        return self.batches.create_pending_project(
            title=title, outcome=outcome, curator=curator, creator=creator,
            metadata=metadata, logical_request_key=logical_request_key,
            actor=actor or self.actor,
        )

    create_pending_project = create_pending
    create = create_pending

    def apply(
        self,
        project: Any,
        sheet: Mapping[str, Any],
        *,
        logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
        decision_ref: Any = None,
        base_revision: Optional[str] = None,
        next_action: Optional[str] = None,
        with_view: bool = False,
    ) -> Any:
        """Validate editable fields then use the accepted single batch path."""
        normalized = self._validate_sheet(sheet)
        requested_keys = [str(item.get("id", item.get("alias"))) for item in sheet.get("tasks", ())] if isinstance(sheet.get("tasks", ()), (list, tuple)) else []
        batch = self.batches.apply_project_sheet(
            project, normalized, logical_request_key=logical_request_key,
            actor=actor or self.actor, decision_ref=decision_ref,
            base_revision=base_revision, next_action=next_action,
        )
        # Child writes may be dependency-topologically ordered by the adapter,
        # but the public mapping remains in the caller's stable alias order.
        if requested_keys and tuple(batch.mappings) != tuple(requested_keys):
            ordered = {key: batch.mappings[key] for key in requested_keys if key in batch.mappings}
            ordered.update({key: value for key, value in batch.mappings.items() if key not in ordered})
            batch = BatchResult(batch.project, batch.receipt, ordered, batch.status, batch.project_id, batch.materialisation)
        if with_view:
            return SheetApplication(batch, self.export(batch.project))
        return batch

    apply_sheet = apply
    apply_project_sheet = apply
    finish = apply

    def export(
        self,
        project: Any,
        *,
        task_refs: Optional[Sequence[Any]] = None,
        document_refs: Optional[Sequence[Any]] = None,
    ) -> SheetView:
        """Build a fresh selected view; no cached or client-supplied facts."""
        record = self.graph.get(project)
        if record.kind is not WorkKind.PROJECT:
            raise SheetSelectionError("sheet view target must be a project")
        records = self._ordered_project_tasks(record)
        selected_tasks = self._select(records, task_refs, "task")
        selected_ids = {item.id for item in selected_tasks}
        documents = self._documents(record, selected_ids, document_refs)
        task_views = tuple(self._task_view(item) for item in selected_tasks)
        context = tuple(self._decision_context(item) for item in selected_tasks)
        project_view = {
            "ref": record.ref,
            "authored": self._authored_project(record.payload),
            "observed": self._observed_project(record),
        }
        return SheetView(project_view, task_views, documents, self.definitions, context, _safe(record.readiness))

    read = export
    view = export
    describe = export

    # Direct structural commands are deliberately compiled through the same
    # validator/batch operation as a sheet edit.  This gives direct and sheet
    # callers identical protected-field and lifecycle semantics.
    def revise(self, target: Any, *, logical_request_key: Optional[str] = None, base_revision: Optional[str] = None, **changes: Any) -> Any:
        record = self.graph.get(target)
        self._validate_task_or_project_changes(changes, record)
        if record.kind is WorkKind.PROJECT:
            return self.apply(record, changes, logical_request_key=logical_request_key, base_revision=base_revision)
        project = self.graph.get(record.project_ref)
        changes = dict(changes, id=record.id)
        return self.apply(project, {"tasks": [changes]}, logical_request_key=logical_request_key, base_revision=base_revision)

    update = revise

    def withdraw(self, target: Any, *, logical_request_key: Optional[str] = None, base_revision: Optional[str] = None) -> Any:
        record = self.graph.get(target)
        if record.kind is WorkKind.PROJECT:
            # The accepted graph command is the relevant semantic operation
            # for a project lifecycle transition; task withdrawal compiles to
            # the parent sheet batch below.
            if base_revision is not None and record.ref.revision != base_revision:
                raise VersionConflictError("project withdrawal base revision is stale")
            return self.graph.withdraw(record, logical_request_key=logical_request_key, actor=self.actor)
        return self.revise(target, lifecycle=Lifecycle.WITHDRAWN.value, withdraw=True, logical_request_key=logical_request_key, base_revision=base_revision)

    def link_dependency(self, record: Any, prerequisite: Any, *, logical_request_key: Optional[str] = None, base_revision: Optional[str] = None) -> Any:
        target = self.graph.get(record)
        project = self.graph.get(target.project_ref)
        dependency = self.graph.get(prerequisite)
        if dependency.project_ref is None or dependency.project_ref.id != project.id:
            raise SheetError("direct dependency link must remain in the project scope")
        return self.apply(project, {"tasks": [{"id": target.id, "dependencies": [ref for ref in target.dependencies] + [dependency.ref]}]}, logical_request_key=logical_request_key, base_revision=base_revision)

    link = link_dependency

    def link_parent(self, child: Any, parent: Any, *, logical_request_key: Optional[str] = None, base_revision: Optional[str] = None) -> Any:
        child_record, parent_record = self.graph.get(child), self.graph.get(parent)
        if child_record.project_ref is None or parent_record.project_ref is None or child_record.project_ref.id != parent_record.project_ref.id:
            raise SheetError("direct parent link must remain in the project scope")
        if base_revision is not None and child_record.ref.revision != base_revision:
            raise VersionConflictError("parent link base revision is stale")
        # Arbitrary hierarchy links are owned by the accepted WorkGraph
        # command; the sheet adapter performs the same scope check first and
        # does not emulate graph mutation with a private identity writer.
        return self.graph.link_parent(child_record, parent_record, logical_request_key=logical_request_key, actor=self.actor)

    # ---- bindings absent from the accepted public ports ------------------------

    def pin_assignment_route(
        self, assignment: Any, route: Any, *, logical_request_key: Optional[str] = None,
        base_revision: Optional[str] = None, actor: Optional[AuthenticatedActor] = None,
    ) -> Any:
        """Bind a route to one assignment, never infer it from task difficulty."""
        current = self.assignments.get(assignment)
        if base_revision is not None and base_revision != current.revision:
            raise VersionConflictError("assignment route base revision is stale")
        if not isinstance(route, (str, Mapping)) or (isinstance(route, str) and not route.strip()):
            raise SheetError("assignment route must be a non-blank name or typed mapping")
        payload = dict(current.payload)
        payload["route_binding"] = _safe(route)
        key = logical_request_key or "assignment-route-" + current.id
        envelope = self.batches._envelope(
            "work.assignment.route-pin", current.ref, payload, key, actor or self.actor,
            expected_version=current.version, expected_revision=current.revision,
        )
        with self.__writer.transaction() as tx:
            receipt = self.__writer.mutate(
                envelope, event_type="work.assignment.route-pinned", result_ref=ResourceRef(current.ref.authority, current.ref.kind, current.ref.id, "rev-" + str(current.version + 1)),
                before_refs=(current.ref,), after_refs=(current.ref,),
                effects={"assignment": current.ref, "route_binding": _safe(route), "dispatch": False},
                stream="assignment:" + current.id, transaction=tx,
            )
        return RoutePinResult(self.assignments.get(current.ref), receipt)

    bind_route = pin_assignment_route
    set_assignment_route = pin_assignment_route

    def amend_policy(
        self, project: Any, policy: Mapping[str, Any], *, authority: str,
        base_revision: str, decision_ref: Any, required_authority: Optional[str] = None,
        logical_request_key: Optional[str] = None, actor: Optional[AuthenticatedActor] = None,
    ) -> Any:
        """Apply a policy namespace only when authority and exact decision pins match."""
        if not isinstance(policy, Mapping):
            raise PolicyAuthorityError("policy amendment must be typed mapping data")
        if not isinstance(authority, str) or not authority.strip():
            raise PolicyAuthorityError("policy amendment authority is required")
        if required_authority is not None and authority != required_authority:
            raise PolicyAuthorityError("policy amendment authority is not authorised")
        target = self.graph.get(project)
        if target.ref.revision != base_revision:
            raise VersionConflictError("policy amendment base revision is stale")
        if decision_ref is None:
            raise PolicyAuthorityError("policy amendment requires its exact decision reference")
        try:
            decision = self.decisions.get_decision(decision_ref)
        except DecisionError as exc:
            raise PolicyAuthorityError("policy amendment decision reference is not valid") from exc
        if not _same_identity(decision.subject_ref, target.ref):
            raise PolicyAuthorityError("policy decision does not bind this project")
        if decision.authority != authority:
            raise PolicyAuthorityError("policy amendment authority does not match the decision")
        if decision.subject_ref.revision != base_revision:
            raise PolicyAuthorityError("policy decision does not bind the exact base revision")
        namespace = {"authority": authority, "base_revision": base_revision, "decision_ref": decision.ref, "policy": _safe(dict(policy))}
        return self.apply(
            target, {"metadata_namespace": {"work.policy": namespace}},
            logical_request_key=logical_request_key, actor=actor or self.actor,
            decision_ref=decision.ref, base_revision=base_revision,
        )

    # ---- explicit adoption and template operations -----------------------------

    def adopt_existing_effort(
        self, source: Any, *, project: Any = None, logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Any:
        """Passively import an existing effort projection through the sheet.

        Prior observations, unknown fields, external budget references, and
        responsibilities are retained under a namespaced adoption record. No
        assignment, grant, session, result, or dispatch identity is cloned.
        """
        source_payload = dict(source.payload) if isinstance(source, WorkRecord) else dict(source) if isinstance(source, Mapping) else None
        if source_payload is None:
            raise SheetError("adopt-existing-effort source must be a typed mapping or WorkRecord")
        target = self.graph.get(project) if project is not None else self.graph.get(source_payload.get("project")) if source_payload.get("project") else None
        if target is None:
            raise SheetError("adopt-existing-effort requires a target project")
        raw_tasks = source_payload.get("tasks", ())
        if isinstance(source_payload.get("project"), Mapping) and not raw_tasks:
            raw_tasks = source_payload["project"].get("tasks", ())
        if not isinstance(raw_tasks, (list, tuple)):
            raise SheetError("adopt-existing-effort tasks must be an array")
        tasks = []
        observations = []
        unknown = []
        for index, raw in enumerate(raw_tasks):
            value = dict(raw.payload) if isinstance(raw, WorkRecord) else dict(raw) if isinstance(raw, Mapping) else None
            if value is None:
                raise SheetError(f"adopted task[{index}] must be a mapping")
            task = {key: value[key] for key in ("id", "alias", "aliases", "title", "name", "body", "instructions", "outcome", "acceptance", "fields", "metadata", "custom", "order", "lifecycle", "dependencies", "depends_on") if key in value}
            task.setdefault("id", task.get("alias", "adopted-task-" + str(index)))
            task.setdefault("title", task.get("name", "Adopted task"))
            tasks.append(task)
            observations.append({"id": task["id"], "results": _safe(value.get("results", value.get("observations", []))), "decisions": _safe(value.get("decisions", [])), "assignments": _safe(value.get("assignments", []))})
            unknown.append({key: _safe(item) for key, item in value.items() if key not in set(task) | {"kind", "schema_revision", "project_ref", "parent", "readiness", "results", "observations", "decisions", "assignments"}})
        adoption = {"mode": "adopt-existing-effort", "source": _safe(source_payload.get("ref", source_payload.get("id", "external"))), "unknown_fields": unknown, "observed": observations, "criteria": _safe(source_payload.get("criteria", [])), "external_budget_refs": _safe(source_payload.get("external_budget_refs", source_payload.get("budget_refs", []))), "responsibilities": _safe(source_payload.get("responsibilities", [])), "quiescent": True, "dispatch": False}
        return self.apply(
            target, {"tasks": tasks, "metadata_namespace": {"work.adoption": adoption}},
            logical_request_key=logical_request_key, actor=actor or self.actor,
        )

    adopt = adopt_existing_effort

    def instantiate_new_template(
        self, template: Any, parameters: Optional[Mapping[str, Any]] = None, *,
        project: Any = None, logical_request_key: Optional[str] = None,
        actor: Optional[AuthenticatedActor] = None,
    ) -> Any:
        """Render a new template as authored pending work; never dispatch it."""
        from herzchen.packs.templates import BLANK_TEMPLATE_ID, TemplateEngine, render_template

        if hasattr(template, "seed"):
            rendered = render_template(template, parameters)
            template_id = template.id
        else:
            engine = TemplateEngine(self.__writer, graph=self.graph, actor=actor or self.actor)
            rendered = engine.render(template, parameters)
            template_id = str(template)
        seed = rendered.seed
        if project is None:
            project_result = self.create_pending(title=(seed.get("project") or {}).get("title"), logical_request_key=(logical_request_key or "template") + "-project", actor=actor or self.actor)
            project = project_result.project
        if template_id == BLANK_TEMPLATE_ID:
            return project_result if "project_result" in locals() else self.export(project)
        tasks = []
        nodes = seed.get("tasks", seed.get("task_bundle", ()))
        if not isinstance(nodes, (list, tuple)):
            raise SheetError("template task collection must be an array")
        task_fields = {"id", "alias", "aliases", "title", "name", "body", "instructions", "outcome", "acceptance", "fields", "metadata", "metadata_namespace", "custom", "order", "lifecycle", "dependencies", "depends_on", "documents", "document_links", "withdraw"}
        for index, node in enumerate(nodes):
            value = dict(node)
            value["id"] = value.pop("local_id", value.get("id", value.get("key", "task-" + str(index))))
            value.pop("kind", None)
            value.pop("parent", None)
            for field in ("dependencies", "depends_on"):
                if field in value and isinstance(value[field], (list, tuple)):
                    value[field] = [dependency.get("$local") if isinstance(dependency, Mapping) and set(dependency) == {"$local"} else dependency for dependency in value[field]]
            extra = {key: item for key, item in value.items() if key not in task_fields}
            if extra:
                value["fields"] = dict(value.get("fields", {}), **extra)
                for key in extra:
                    value.pop(key, None)
            tasks.append(value)
        template_project = seed.get("project", {})
        sheet = {"tasks": tasks, "metadata_namespace": {"work.template": {"template_id": template_id, "parameters": _safe(dict(parameters or {})), "criteria": _safe(seed.get("criteria", ())), "auto_dispatch": False}}}
        if isinstance(template_project, Mapping):
            for field in ("title", "name", "outcome", "scope", "approach", "acceptance", "protocol", "custom", "metadata"):
                if field in template_project:
                    sheet[field] = template_project[field]
        return self.apply(project, sheet, logical_request_key=logical_request_key, actor=actor or self.actor)

    instantiate_template = instantiate_new_template

    # ---- validation -------------------------------------------------------------

    def _validate_sheet(self, sheet: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(sheet, Mapping):
            raise SheetError("project sheet must be a mapping")
        value = {str(key): item for key, item in sheet.items()}
        # Check protection before the ordinary vocabulary so an attempted
        # authority/observation rewrite gets a targeted actionable error.
        self._reject_protected(value, "project sheet")
        allowed = set(self.definitions.project_editable) | {"manager_action", "resources"}
        unknown = set(value).difference(allowed)
        if unknown:
            raise SheetError("unknown project-sheet fields: " + ", ".join(sorted(unknown)))
        for field in ("custom", "metadata", "metadata_namespace"):
            if field in value and not isinstance(value[field], Mapping):
                raise SheetError(f"{field} must be a typed mapping")
        if "custom" in value:
            self._reject_protected(value["custom"], "custom")
            self._validate_json(value["custom"], "custom")
        if "metadata" in value:
            self._reject_protected(value["metadata"], "metadata")
        for field in ("title", "name"):
            if field in value and (not isinstance(value[field], str) or not value[field].strip()):
                raise SheetError(f"{field} must be non-blank text")
        if "outcome" in value and not isinstance(value["outcome"], str):
            raise SheetError("outcome must be text")
        if "metadata_namespace" in value:
            for namespace, data in value["metadata_namespace"].items():
                if not isinstance(namespace, str) or not namespace.strip() or not isinstance(data, Mapping):
                    raise SheetError("metadata namespace values must be typed mappings")
                if namespace != "work.adoption":
                    self._reject_protected(data, f"metadata namespace {namespace!r}")
        tasks = value.get("tasks", ())
        if not isinstance(tasks, (list, tuple)):
            raise SheetError("tasks must be an array")
        for index, task in enumerate(tasks):
            if not isinstance(task, Mapping):
                raise SheetError(f"task[{index}] must be an object")
            self._reject_protected(task, f"task[{index}]")
            for field in ("custom", "metadata", "fields", "metadata_namespace"):
                if field in task and not isinstance(task[field], Mapping):
                    raise SheetError(f"task[{index}].{field} must be a typed mapping")
            if "custom" in task:
                self._reject_protected(task["custom"], f"task[{index}].custom")
            if "metadata" in task:
                self._reject_protected(task["metadata"], f"task[{index}].metadata")
            if "fields" in task:
                self._reject_protected(task["fields"], f"task[{index}].fields")
            for field in ("title", "name"):
                if field in task and (not isinstance(task[field], str) or not task[field].strip()):
                    raise SheetError(f"task[{index}].{field} must be non-blank text")
            if "lifecycle" in task:
                try:
                    Lifecycle(task["lifecycle"])
                except (TypeError, ValueError) as exc:
                    raise SheetError(f"task[{index}].lifecycle is invalid") from exc
            if "metadata_namespace" in task:
                for namespace, data in task["metadata_namespace"].items():
                    if not isinstance(data, Mapping):
                        raise SheetError(f"task[{index}].metadata_namespace values must be mappings")
                    if namespace != "work.adoption":
                        self._reject_protected(data, f"task[{index}].metadata namespace {namespace!r}")
            self._validate_json(task, f"task[{index}]")
        value["tasks"] = self._dependency_write_order(tasks)
        return value

    @staticmethod
    def _dependency_write_order(tasks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        """Put newly-created local prerequisites before their dependants.

        The accepted batch handler intentionally writes child rows in input
        order.  A sheet may still use forward aliases, so this adapter gives
        the handler a dependency-safe write order while retaining each task's
        explicit ``order`` field for the exported plan order.
        """
        pending = list(tasks)
        names = {str(item.get("id", item.get("alias"))): item for item in pending}
        names.update({str(item["alias"]): item for item in pending if item.get("alias") is not None})
        ordered: list[Mapping[str, Any]] = []
        while pending:
            progressed = False
            for item in tuple(pending):
                deps = item.get("dependencies", item.get("depends_on", ()))
                local_deps = {str(dep) for dep in deps if isinstance(dep, str) and dep in names}
                if all(names[dep] in ordered for dep in local_deps):
                    ordered.append(item)
                    pending.remove(item)
                    progressed = True
            if not progressed:
                # The semantic batch validator will produce the authoritative
                # cycle/unknown-reference error; do not hide it here.
                ordered.extend(pending)
                break
        return ordered

    def _validate_task_or_project_changes(self, changes: Mapping[str, Any], record: WorkRecord) -> None:
        if record.kind is WorkKind.PROJECT:
            self._validate_sheet(changes)
        else:
            self._validate_sheet({"tasks": [dict(changes, id=record.id)]})

    def _reject_protected(self, value: Mapping[str, Any], location: str) -> None:
        protected = {item.casefold() for item in self.definitions.protected}
        for key in value:
            if str(key).casefold() in protected:
                raise ProtectedFieldError(f"{location}.{key} is read-only observed or authority-bearing state")

    @staticmethod
    def _validate_json(value: Any, location: str) -> None:
        try:
            canonical_json(value)
        except (TypeError, ValueError) as exc:
            raise SheetError(f"{location} must contain JSON-safe typed values") from exc

    # ---- read projections -------------------------------------------------------

    def _ordered_project_tasks(self, project: WorkRecord) -> Tuple[WorkRecord, ...]:
        by_id = {item.id: item for item in self.graph.list(project=project)}
        result = []
        for raw in project.payload.get("tasks", ()):
            ref = _ref(raw)
            if ref is not None and ref.id in by_id:
                result.append(by_id[ref.id])
        result.extend(item for item in by_id.values() if item not in result)
        return tuple(result)

    def _select(self, records: Sequence[WorkRecord], selected: Optional[Sequence[Any]], kind: str) -> Tuple[WorkRecord, ...]:
        if selected is None:
            return tuple(records)
        result = []
        for value in selected:
            found = None
            for record in records:
                if value == record.id or value in record.aliases or _same_identity(value, record.ref):
                    found = record
                    break
            if found is None:
                raise SheetSelectionError(f"selected {kind} is not part of the project")
            if found not in result:
                result.append(found)
        return tuple(result)

    def _authored_project(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        fields = ("title", "name", "outcome", "scope", "approach", "acceptance", "protocol", "custom", "metadata", "metadata_namespaces", "tasks", "documents")
        return {key: _safe(payload[key]) for key in fields if key in payload}

    def _observed_project(self, project: WorkRecord) -> dict[str, Any]:
        payload = project.payload
        fields = ("lifecycle", "readiness", "manager", "budget", "worker", "execution", "external_action", "admitted", "batch_history", "last_batch")
        result = {key: _safe(payload[key]) for key in fields if key in payload}
        result["receipts"] = [event.event_id for event in self.__writer.list_events(stream="work:" + project.id)]
        return result

    def _task_view(self, task: WorkRecord) -> Mapping[str, Any]:
        authored = {key: _safe(value) for key, value in task.payload.items() if key not in set(self.definitions.protected) | {"readiness", "schema_revision", "kind", "id", "parent", "project_ref", "dependencies"}}
        authored["ref"] = task.ref
        authored["dependencies"] = [_safe(value) for value in task.payload.get("dependencies", ())]
        observed: dict[str, Any] = {key: _safe(task.payload[key]) for key in ("lifecycle", "readiness", "results", "observations", "attempts", "decisions") if key in task.payload}
        observed.update(self._assignment_observations(task.ref))
        return {"ref": task.ref, "authored": authored, "observed": observed}

    def _assignment_observations(self, task_ref: ResourceRef) -> dict[str, Any]:
        assignments, dispatches, results, reports = [], [], [], []
        rows = self.__writer.connection.execute("SELECT authority, kind, id, current_revision FROM identities WHERE authority = ? AND kind IN (?, ?, ?, ?) ORDER BY kind, id", (self.__writer.authority, ASSIGNMENT_KIND, DISPATCH_KIND, RESULT_KIND, REPORT_KIND)).fetchall()
        assignment_ids = set()
        for row in rows:
            identity = self.__writer.get_identity(ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]))
            if identity is None:
                continue
            payload = identity.payload
            scope = payload.get("scope")
            if identity.ref.kind == ASSIGNMENT_KIND and _same_identity(scope, task_ref):
                assignment_ids.add(identity.ref.id)
                assignments.append({"ref": identity.ref, "payload": payload})
        # Assignment observations point at the assignment, not the task.
        if assignment_ids:
            for row in rows:
                identity = self.__writer.get_identity(ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]))
                if identity is None or identity.ref.kind not in {DISPATCH_KIND, RESULT_KIND, REPORT_KIND}:
                    continue
                assignment_ref = _ref(identity.payload.get("assignment"))
                if assignment_ref is not None and assignment_ref.id in assignment_ids:
                    (dispatches if identity.ref.kind == DISPATCH_KIND else results if identity.ref.kind == RESULT_KIND else reports).append({"ref": identity.ref, "payload": identity.payload})
        return {"assignments": [_safe(value) for value in assignments], "dispatches": [_safe(value) for value in dispatches], "results": [_safe(value) for value in results], "reports": [_safe(value) for value in reports]}

    def _decision_context(self, task: WorkRecord) -> Mapping[str, Any]:
        candidates, decision_records, waits = [], [], []
        # Decisions intentionally retain the exact historical subject pin.
        # Match identity while ignoring revision, then ask the accepted
        # decision port to decode each record.
        rows = self.__writer.connection.execute("SELECT authority, kind, id, current_revision FROM identities WHERE authority = ? AND kind = ? ORDER BY id", (self.__writer.authority, DECISION_KIND)).fetchall()
        subject = ResourceRef(task.ref.authority, task.ref.kind, task.ref.id)
        for row in rows:
            identity = self.__writer.get_identity(ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]))
            if identity is None or not _same_identity(identity.payload.get("subject_ref"), subject):
                continue
            try:
                decision_records.append(self.decisions.get_decision(identity.ref))
            except DecisionError:
                continue
        decision_views = []
        for decision in decision_records:
            candidate = None
            try:
                candidate = self.decisions.get_candidate(decision.candidate_ref)
            except DecisionError:
                pass
            if candidate is not None:
                candidates.append({"ref": candidate.ref, "pin": candidate.pin, "owner": candidate.owner, "role": candidate.role})
            decisions_entry = {
                "ref": decision.ref, "candidate_ref": decision.candidate_ref,
                "candidate_pin": decision.candidate_pin, "criterion_ref": decision.criterion_ref,
                "authority": decision.authority, "author": decision.author,
                "rationale": decision.rationale, "disposition": decision.disposition,
                "return_condition": decision.return_condition, "applicability": decision.applicability,
                "read_only": True,
            }
            decisions_entry["assessment_result_ref"] = decision.assessment_result_ref
            decision_views.append(decisions_entry)
        rows = self.__writer.connection.execute("SELECT authority, kind, id, current_revision FROM identities WHERE authority = ? AND kind = ? ORDER BY id", (self.__writer.authority, WAIT_KIND)).fetchall()
        for row in rows:
            identity = self.__writer.get_identity(ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]))
            if identity is not None and _same_identity(identity.payload.get("subject_ref"), task.ref):
                waits.append({"ref": identity.ref, "missing_obligation": identity.payload.get("missing_obligation"), "owner": identity.payload.get("owner"), "owner_ref": identity.payload.get("owner_ref"), "awaited_ref": identity.payload.get("awaited_ref"), "current_revision": identity.payload.get("current_revision"), "revisit_condition": identity.payload.get("revisit_condition"), "dispatch": False, "read_only": True})
        return {"subject": task.ref, "candidates": _safe(candidates), "decisions": _safe(decision_views), "waiting": _safe(waits), "read_only": True}

    def _documents(self, project: WorkRecord, task_ids: set[str], selected: Optional[Sequence[Any]]) -> Tuple[Mapping[str, Any], ...]:
        wanted = None if selected is None else {_ref(value).id if _ref(value) is not None else str(value) for value in selected}
        output = []
        rows = self.__writer.connection.execute("SELECT authority, kind, id, current_revision FROM identities WHERE authority = ? AND kind = 'dat.content.association' ORDER BY id", (self.__writer.authority,)).fetchall()
        for row in rows:
            identity = self.__writer.get_identity(ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]))
            if identity is None:
                continue
            payload = identity.payload
            subject = payload.get("subject")
            subject_ref = _ref(subject)
            if subject_ref is None or (subject_ref.id != project.id and subject_ref.id not in task_ids):
                continue
            binding = payload.get("document")
            binding_ref = _ref(binding.get("ref")) if isinstance(binding, Mapping) else None
            if binding_ref is None or (wanted is not None and binding_ref.id not in wanted):
                continue
            document = self.__writer.get_identity(ResourceRef(binding_ref.authority, binding_ref.kind, binding_ref.id))
            entry: dict[str, Any] = {"association": identity.ref, "subject": subject_ref, "binding": binding, "read_only": True}
            if document is not None:
                entry["document"] = document.payload
                current = _ref(document.payload.get("current_revision"))
                if current is not None:
                    revision = self.__writer.get_identity(ResourceRef(current.authority, current.kind, current.id, current.revision))
                    if revision is not None:
                        entry["current_revision"] = revision.payload
            output.append(entry)
        return tuple(_safe(item) for item in output)


ProjectSheet = command_facade(_ProjectSheetEngine, DOMAIN_ID)
ProjectSheetService = ProjectSheet
SheetService = ProjectSheet


__all__ = [
    "PolicyAuthorityError", "ProtectedFieldError", "ProjectSheet", "ProjectSheetService",
    "RoutePinResult", "SHEET_SCHEMA_REVISION", "SheetApplication", "SheetDefinitions", "SheetError",
    "SheetSelectionError", "SheetService", "SheetView",
]
