"""High-level work identities and structural commands.

This is intentionally a domain adapter over the FND-03 writer.  It does not
own a database, SQL schema, receipt table, event log, scheduler, project
checkout, assessment ledger, candidate/decision store, or Runtime job.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from herzchen.command_ports import command_facade

from .model import (
    GraphCycleError,
    InvalidDependencyError,
    InvalidParentError,
    Lifecycle,
    WorkKind,
    WorkNotFoundError,
    WorkRecord,
    WorkStateView,
    WorkValidationError,
)


DOMAIN_ID = "herzchen.work"
DOMAIN_VERSION = "1.0"
DOMAIN_OWNER = "wrk"
SCHEMA_REVISION = "work.v1"
DEFAULT_TITLE = "Untitled project"
WORK_KINDS = {kind.value: kind for kind in WorkKind}
KIND_PREFIX = {kind: "work." + kind.value for kind in WorkKind}


# Ordinary commands cannot rewrite authored state after completion. Explicit
# completion/correction remains owned by the assignments port.
_COMPLETED_TASK_FIELDS = (
    "title", "name", "body", "instructions", "outcome", "acceptance",
    "fields", "metadata", "metadata_namespaces", "custom", "order",
    "aliases", "alias", "dependencies", "parent", "project_ref",
    "lifecycle", "withdraw",
)


def ensure_completed_task_unchanged(record: WorkRecord, proposed: Mapping[str, Any]) -> None:
    """Reject ordinary edits that would change an already completed task."""

    if record.kind is not WorkKind.TASK or record.lifecycle is not Lifecycle.COMPLETED:
        return
    for field in _COMPLETED_TASK_FIELDS:
        if record.payload.get(field) != proposed.get(field):
            raise WorkValidationError(
                f"completed task {record.id!r} cannot change authored field {field!r}"
            )


def _contract_types() -> Tuple[Any, ...]:
    """Load the sibling-supplied FND contracts lazily.

    Lazy loading keeps this optional module importable in a minimal install;
    every durable operation still requires the real FND contract package.
    """

    from herzchen.contracts import (  # type: ignore
        AuthenticatedActor,
        CommandEnvelope,
        DomainContribution,
        ResourceRef,
        TransactionContext,
        canonical_json,
    )

    return AuthenticatedActor, CommandEnvelope, DomainContribution, ResourceRef, TransactionContext, canonical_json


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _opaque(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        raise WorkValidationError(f"{field} must be a non-blank opaque identifier")
    return value


def contribution() -> Any:
    """Return the one typed FND registry contribution for this module."""

    DomainContribution = _contract_types()[2]
    return DomainContribution(
        domain_id=DOMAIN_ID,
        version=DOMAIN_VERSION,
        owner=DOMAIN_OWNER,
        resource_types=tuple(KIND_PREFIX[kind] for kind in WorkKind),
        document_types=(),
        namespace_types=("work", "work.metadata"),
        operation_types=(
            "work.create",
            "work.revise",
            "work.link-parent",
            "work.link-dependency",
            "work.withdraw",
            "work.state-view",
        ),
        event_types=(
            "work.created",
            "work.revised",
            "work.parent-linked",
            "work.dependency-linked",
            "work.withdrawn",
            "work.state-changed",
        ),
        schema_revision=SCHEMA_REVISION,
        composition_bindings=(
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "handler-required",
        ) + tuple(
            "mutation-port:{}|{}|{}|{}".format(SCHEMA_REVISION, operation, kind, event)
            for kind in KIND_PREFIX.values()
            for operation, event in (
                ("work.create", "work.created"),
                ("work.revise", "work.revised"),
                ("work.revise", "work.parent-linked"),
                ("work.revise", "work.dependency-linked"),
                ("work.revise", "work.state-changed"),
            )
            if not (kind == "work.project" and event == "work.parent-linked")
        ),
    )


def contributions(*, include_orchestration: bool = False) -> Tuple[Any, ...]:
    """Return the core WRK descriptors, optionally including orchestration."""
    from .assignments import contribution as assignments_contribution
    from .batches import contribution as batches_contribution
    from .decisions import contribution as decisions_contribution
    from .sheet import contribution as sheet_contribution
    from .lifecycle import contribution as lifecycle_contribution
    core = (
        contribution(), assignments_contribution(), batches_contribution(),
        sheet_contribution(), decisions_contribution(), lifecycle_contribution(),
    )
    if not include_orchestration:
        return core
    from .orchestration import contribution as orchestration_contribution
    return core + (orchestration_contribution(),)


def register_work(store: Any) -> Any:
    """Register the stable core WRK definition and return its sealed handler."""
    return store.register_domain_handler(contributions())


def register_orchestration(store: Any) -> Any:
    """Explicitly late-register the optional atomic orchestration descriptor."""
    from .orchestration import contribution as orchestration_contribution
    descriptor = orchestration_contribution()
    registered = {item.domain_id: item for item in store.registered_domains()}
    if registered.get(descriptor.domain_id) == descriptor:
        return store.domain_handler(contributions(include_orchestration=True))
    return store.register_domain_handler((descriptor,))


def work_handler(store: Any) -> Any:
    """Acquire the WRK handler only after the exact definition is registered."""
    registered = {item.domain_id: item for item in store.registered_domains()} if hasattr(store, "registered_domains") else {}
    expected = contributions(include_orchestration="herzchen.work.orchestration" in registered)
    if hasattr(store, "domain_ids"):
        required = {item.domain_id for item in expected}
        if required.issubset(set(store.domain_ids)):
            return store
    return store.domain_handler(expected)


class _WorkGraphEngine:
    """Structural work command surface backed by a supplied FND store."""

    def __init__(self, store: Any, *, actor: Any = None) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        try:
            self.__writer = work_handler(store)
        except Exception:
            from herzchen.kernel.store import DomainHandler, Store
            if not isinstance(store, Store) or isinstance(store, DomainHandler):
                raise
            self.__writer = store
        self.reader = self.__writer.consumer()
        self.default_actor = actor

    def register(self) -> Any:
        """Register this domain through FND's existing registry port."""

        self.__writer = register_work(self.__writer)
        self.reader = self.__writer.consumer()
        return contribution()

    # ---- public creation commands -------------------------------------------------

    def create_project(
        self,
        *,
        title: Optional[str] = None,
        outcome: str = "",
        alias: Optional[str] = None,
        aliases: Sequence[str] = (),
        logical_request_key: Optional[str] = None,
        actor: Any = None,
        creator: Optional[Any] = None,
        curator: Optional[Any] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> WorkRecord:
        title = DEFAULT_TITLE if title is None else self._title(title, "title")
        if not isinstance(outcome, str):
            raise WorkValidationError("outcome must be text")
        logical_request_key = self._request_key(logical_request_key)
        project_id = self._new_id(WorkKind.PROJECT, logical_request_key)
        provenance_actor = actor if actor is not None else self.default_actor
        creator_value = self._provenance_value(creator, provenance_actor)
        curator_value = self._provenance_value(curator, provenance_actor)
        payload = self._base_payload(
            WorkKind.PROJECT,
            project_id,
            title=title,
            aliases=self._aliases(alias, aliases, WorkKind.PROJECT, project_id),
            parent=None,
            project_ref=None,
            dependencies=(),
            lifecycle=Lifecycle.PENDING,
            readiness={"status": "not-evaluated", "ready": False, "dispatch": False},
        )
        payload.update(
            {
                "outcome": outcome,
                "scope": "",
                "approach": "",
                "acceptance": {},
                "tasks": [],
                "documents": [],
                "custom": {},
                "protocol": None,
                "manager": None,
                "gate": None,
                "budget": None,
                "worker": None,
                "execution": None,
                "external_action": None,
                "provenance": {"creator": creator_value, "curator": curator_value},
                "metadata": dict(metadata or {}),
            }
        )
        with self.__writer.transaction() as tx:
            self._validate_payload(payload)
            self._write_create(tx, WorkKind.PROJECT, project_id, payload, logical_request_key, actor, "work.created")
        return self.get(project_id)

    # Short alias used by host adapters.
    create_pending_project = create_project

    def create(
        self,
        kind: Union[WorkKind, str],
        *,
        project: Any = None,
        parent: Any = None,
        title: Optional[str] = None,
        name: Optional[str] = None,
        alias: Optional[str] = None,
        aliases: Sequence[str] = (),
        dependencies: Sequence[Any] = (),
        lifecycle: Union[Lifecycle, str] = Lifecycle.PENDING,
        logical_request_key: Optional[str] = None,
        actor: Any = None,
        fields: Optional[Mapping[str, Any]] = None,
    ) -> WorkRecord:
        work_kind = self._kind(kind)
        if work_kind is WorkKind.PROJECT:
            return self.create_project(title=title or name, alias=alias, aliases=aliases, logical_request_key=logical_request_key, actor=actor, metadata=fields)
        project_record = self._require(project) if project is not None else None
        parent_record = self._require(parent) if parent is not None else project_record
        logical_request_key = self._request_key(logical_request_key)
        record_id = self._new_id(work_kind, logical_request_key)
        title_value = self._title(title if title is not None else name, "title", default=work_kind.value.title())
        lifecycle_value = self._lifecycle(lifecycle)
        aliases_value = self._aliases(alias, aliases, work_kind, record_id)
        parent_ref = parent_record.ref if parent_record is not None else None
        project_ref = project_record.ref if project_record is not None else self._project_ref(parent_record)
        dep_records = tuple(self._require(dep) for dep in dependencies)
        payload = self._base_payload(
            work_kind,
            record_id,
            title=title_value,
            name=name or title_value,
            aliases=aliases_value,
            parent=parent_ref,
            project_ref=project_ref,
            dependencies=tuple(record.ref for record in dep_records),
            lifecycle=lifecycle_value,
            readiness={"status": "not-evaluated", "ready": False, "dispatch": False},
        )
        payload["fields"] = dict(fields or {})
        self._validate_new_graph(payload, parent_record, dep_records)
        with self.__writer.transaction() as tx:
            self._write_create(tx, work_kind, record_id, payload, logical_request_key, actor, "work.created")
            self._retain_links(tx, parent_ref, tuple(record.ref for record in dep_records))
        return self.get(record_id)

    def create_effort(self, project: Any, **kwargs: Any) -> WorkRecord:
        return self.create(WorkKind.EFFORT, project=project, **kwargs)

    def create_task(self, project: Any, **kwargs: Any) -> WorkRecord:
        return self.create(WorkKind.TASK, project=project, **kwargs)

    def create_criterion(self, project: Any, **kwargs: Any) -> WorkRecord:
        return self.create(WorkKind.CRITERION, project=project, **kwargs)

    def create_scenario(self, project: Any, **kwargs: Any) -> WorkRecord:
        return self.create(WorkKind.SCENARIO, project=project, **kwargs)

    def create_gate(self, project: Any, **kwargs: Any) -> WorkRecord:
        return self.create(WorkKind.GATE, project=project, **kwargs)

    # ---- structural commands ------------------------------------------------------

    def revise(
        self,
        target: Any,
        *,
        title: Optional[str] = None,
        name: Optional[str] = None,
        outcome: Optional[str] = None,
        add_alias: Optional[str] = None,
        aliases: Sequence[str] = (),
        fields: Optional[Mapping[str, Any]] = None,
        lifecycle: Optional[Union[Lifecycle, str]] = None,
        logical_request_key: Optional[str] = None,
        actor: Any = None,
    ) -> WorkRecord:
        request_key = self._request_key(logical_request_key)
        request_payload = {
            "target": self._request_locator(target),
            "title": title,
            "name": name,
            "outcome": outcome,
            "add_alias": add_alias,
            "aliases": tuple(aliases),
            "fields": None if fields is None else dict(fields),
            "lifecycle": lifecycle.value if isinstance(lifecycle, Lifecycle) else lifecycle,
        }
        replay = self._replay_revision(request_key, request_payload, actor, "work.revised")
        if replay is not None:
            return self._replay_result(replay)
        record = self._require(target)
        changes = self._revision_changes(record, title=title, name=name, outcome=outcome, add_alias=add_alias, aliases=aliases, fields=fields, lifecycle=lifecycle)
        ensure_completed_task_unchanged(record, changes)
        self._validate_payload(changes)
        with self.__writer.transaction() as tx:
            self._write_revision(tx, record, changes, request_key, actor, "work.revised", request_payload=request_payload)
        return self.get(record.ref)

    update = revise

    def link_parent(self, child: Any, parent: Any, *, logical_request_key: Optional[str] = None, actor: Any = None) -> WorkRecord:
        request_key = self._request_key(logical_request_key)
        request_payload = {"child": self._request_locator(child), "parent": self._request_locator(parent)}
        replay = self._replay_revision(request_key, request_payload, actor, "work.parent-linked")
        if replay is not None:
            return self._replay_result(replay)
        child_record = self._require(child)
        parent_record = self._require(parent)
        self._validate_parent(child_record, parent_record)
        payload = dict(child_record.payload)
        payload["parent"] = self._ref_dict(parent_record.ref)
        if child_record.kind is not WorkKind.PROJECT and not payload.get("project_ref"):
            payload["project_ref"] = self._ref_dict(self._project_ref(parent_record))
        ensure_completed_task_unchanged(child_record, payload)
        with self.__writer.transaction() as tx:
            self._write_revision(tx, child_record, payload, request_key, actor, "work.parent-linked", request_payload=request_payload)
            self._retain_links(tx, parent_record.ref, ())
        return self.get(child_record.ref)

    def link_dependency(self, record: Any, prerequisite: Any, *, logical_request_key: Optional[str] = None, actor: Any = None) -> WorkRecord:
        request_key = self._request_key(logical_request_key)
        request_payload = {"record": self._request_locator(record), "prerequisite": self._request_locator(prerequisite)}
        replay = self._replay_revision(request_key, request_payload, actor, "work.dependency-linked")
        if replay is not None:
            return self._replay_result(replay)
        record_value = self._require(record)
        prerequisite_value = self._require(prerequisite)
        dependencies = list(record_value.dependencies)
        if any(ref.id == prerequisite_value.id and ref.kind == prerequisite_value.ref.kind for ref in dependencies):
            return record_value
        proposed = dict(record_value.payload)
        proposed["dependencies"] = [self._ref_dict(ref) for ref in dependencies] + [self._ref_dict(prerequisite_value.ref)]
        ensure_completed_task_unchanged(record_value, proposed)
        self._validate_dependency_graph(record_value.ref, prerequisite_value.ref)
        with self.__writer.transaction() as tx:
            self._write_revision(tx, record_value, proposed, request_key, actor, "work.dependency-linked", request_payload=request_payload)
            self._retain_links(tx, None, (prerequisite_value.ref,))
        return self.get(record_value.ref)

    def withdraw(self, target: Any, *, logical_request_key: Optional[str] = None, actor: Any = None) -> WorkRecord:
        return self.revise(target, lifecycle=Lifecycle.WITHDRAWN, logical_request_key=logical_request_key, actor=actor)

    def set_lifecycle(self, target: Any, lifecycle: Union[Lifecycle, str], *, logical_request_key: Optional[str] = None, actor: Any = None) -> WorkRecord:
        return self.revise(target, lifecycle=lifecycle, logical_request_key=logical_request_key, actor=actor)

    def set_readiness(self, target: Any, observation: Mapping[str, Any], *, logical_request_key: Optional[str] = None, actor: Any = None) -> WorkRecord:
        request_key = self._request_key(logical_request_key)
        request_payload = {"target": self._request_locator(target), "observation": dict(observation) if isinstance(observation, Mapping) else observation}
        replay = self._replay_revision(request_key, request_payload, actor, "work.state-changed")
        if replay is not None:
            return self._replay_result(replay)
        record = self._require(target)
        if not isinstance(observation, Mapping):
            raise WorkValidationError("readiness observation must be a mapping")
        readiness = dict(observation)
        readiness["dispatch"] = False
        payload = dict(record.payload)
        payload["readiness"] = readiness
        with self.__writer.transaction() as tx:
            self._write_revision(tx, record, payload, request_key, actor, "work.state-changed", request_payload=request_payload)
        return self.get(record.ref)

    def state_view(self, target: Any) -> WorkStateView:
        record = self._require(target)
        return WorkStateView(record.ref, record.lifecycle, dict(record.readiness), record.version, record.revision)

    observe_readiness = state_view

    # ---- reads --------------------------------------------------------------------

    def get(self, target: Any) -> WorkRecord:
        record = self._resolve(target)
        if record is None:
            raise WorkNotFoundError(f"work record not found: {target!r}")
        return record

    def resolve(self, target: Any) -> WorkRecord:
        return self.get(target)

    def list(self, *, project: Any = None, kind: Optional[Union[WorkKind, str]] = None) -> Tuple[WorkRecord, ...]:
        records = list(self._all_records())
        if kind is not None:
            desired = self._kind(kind)
            records = [record for record in records if record.kind is desired]
        if project is not None:
            project_record = self._require(project)
            records = [record for record in records if record.project_ref is not None and record.project_ref.id == project_record.ref.id]
        return tuple(sorted(records, key=lambda record: (record.kind.value, record.id)))

    # ---- FND composition helpers --------------------------------------------------

    def _write_create(self, tx: Any, kind: WorkKind, record_id: str, payload: Mapping[str, Any], request_key: str, actor: Any, event_type: str) -> Any:
        ref = self._ref(kind, record_id)
        envelope = self._envelope("work.create", ref, payload, request_key, actor, expected_version=0)
        receipt = self.__writer.mutate(envelope, event_type=event_type, result_ref=self._pinned(ref, 1), effects={"kind": kind.value, "id": record_id}, stream="work:" + record_id, transaction=tx)
        self._retain_links(tx, self._payload_ref(payload.get("parent")), tuple(self._payload_ref(value) for value in payload.get("dependencies", ())))
        return receipt

    def _write_revision(self, tx: Any, record: WorkRecord, payload: Mapping[str, Any], request_key: str, actor: Any, event_type: str, *, request_payload: Optional[Mapping[str, Any]] = None) -> Any:
        envelope = self._envelope("work.revise", record.ref, payload, request_key, actor, expected_version=record.version, expected_revision=record.revision)
        if request_payload is not None:
            envelope = self._envelope("work.revise", record.ref, request_payload, request_key, actor, expected_version=record.version, expected_revision=record.revision)
        return self.__writer.mutate(envelope, identity_payload=payload, event_type=event_type, effects={"kind": record.kind.value, "id": record.id, "result_payload": dict(payload)}, stream="work:" + record.id, transaction=tx)

    def _replay_revision(self, request_key: str, request_payload: Mapping[str, Any], actor: Any, event_type: str) -> Any:
        prior = self.__writer.get_receipt(request_key)
        if prior is None:
            return None
        target = prior.target
        expected_version = None
        if target.revision is not None and target.revision.startswith("rev-"):
            try:
                expected_version = int(target.revision.removeprefix("rev-"))
            except ValueError:
                expected_version = None
        envelope = self._envelope("work.revise", target, request_payload, request_key, actor, expected_version=expected_version, expected_revision=target.revision)
        with self.__writer.transaction() as tx:
            return self.__writer.mutate(
                envelope, event_type=event_type, result_ref=prior.result_ref,
                stream="work:" + target.id, transaction=tx,
            )

    def _replay_result(self, receipt: Any) -> WorkRecord:
        target = receipt.target
        event = next((item for item in self.__writer.list_events(stream="work:" + target.id) if item.event_id in receipt.event_ids), None)
        if event is not None and isinstance(event.effects.get("result_payload"), Mapping):
            revision = receipt.result_ref or target
            return self._from_payload(revision, self._revision_version(revision.revision), event.effects["result_payload"])
        return self.get(self._unPinned(receipt.result_ref or target))

    @staticmethod
    def _revision_version(revision: Optional[str]) -> int:
        if revision is None or not revision.startswith("rev-"):
            return 0
        try:
            return int(revision.removeprefix("rev-"))
        except ValueError:
            return 0

    @staticmethod
    def _unPinned(ref: Any) -> Any:
        if ref is None:
            return ref
        ResourceRef = _contract_types()[3]
        if isinstance(ref, ResourceRef):
            return ResourceRef(ref.authority, ref.kind, ref.id)
        return ref

    def _request_locator(self, value: Any) -> Any:
        ResourceRef = _contract_types()[3]
        if isinstance(value, ResourceRef):
            return value.to_dict()
        if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
            return value.ref.to_dict()
        return value

    def _envelope(self, operation: str, ref: Any, payload: Mapping[str, Any], request_key: str, actor: Any, *, expected_version: Optional[int] = None, expected_revision: Optional[str] = None) -> Any:
        AuthenticatedActor, CommandEnvelope, _, _, TransactionContext, _ = _contract_types()
        selected_actor = actor or self.default_actor or AuthenticatedActor("herzchen.work", "work-module", "herzchen.work")
        if not isinstance(selected_actor, AuthenticatedActor):
            raise TypeError("actor must be an FND AuthenticatedActor")
        return CommandEnvelope(
            operation=operation,
            schema_revision=SCHEMA_REVISION,
            target=ref,
            context=TransactionContext(
                actor=selected_actor,
                logical_request_key=request_key,
                request_digest=_digest({"operation": operation, "target": ref.to_dict(), "payload": payload}),
                expected_revision=expected_revision,
                expected_version=expected_version,
            ),
            payload=dict(payload),
        )

    def _retain_links(self, tx: Any, parent: Any, dependencies: Sequence[Any]) -> None:
        for ref in tuple([parent] if parent is not None else []) + tuple(ref for ref in dependencies if ref is not None):
            self.__writer.put_reference(ref, transaction=tx)

    # ---- validation and conversion ------------------------------------------------

    def _all_records(self) -> Tuple[WorkRecord, ...]:
        rows = self.__writer.connection.execute("SELECT * FROM identities WHERE authority = ? AND kind LIKE 'work.%' ORDER BY kind, id", (self.__writer.authority,)).fetchall()
        ResourceRef = _contract_types()[3]
        records = []
        for row in rows:
            ref = ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"])
            identity = self.__writer.get_identity(ref)
            if identity is not None:
                records.append(self._from_identity(identity))
        return tuple(records)

    def _from_identity(self, identity: Any) -> WorkRecord:
        return self._from_payload(identity.ref, identity.version, identity.payload)

    def _from_payload(self, ref: Any, version: int, payload_value: Mapping[str, Any]) -> WorkRecord:
        payload = dict(payload_value)
        kind = self._kind(payload.get("kind", ref.kind.removeprefix("work.")))
        parent = self._payload_ref(payload.get("parent"))
        deps = tuple(self._payload_ref(ref) for ref in payload.get("dependencies", ()))
        project_ref = self._payload_ref(payload.get("project_ref"))
        lifecycle = self._lifecycle(payload.get("lifecycle", Lifecycle.PENDING))
        aliases = tuple(payload.get("aliases", ()))
        if not aliases:
            aliases = (payload.get("alias", ref.id),)
        return WorkRecord(ref, kind, payload.get("title", payload.get("name", kind.value.title())), payload.get("name", payload.get("title", kind.value.title())), aliases, parent, deps, project_ref, lifecycle, dict(payload.get("readiness", {})), payload, version)

    def _resolve(self, target: Any) -> Optional[WorkRecord]:
        ResourceRef = _contract_types()[3]
        if isinstance(target, WorkRecord):
            # A record object is a convenient locator, not a write lease.  A
            # fresh supported read avoids using a stale pinned revision after
            # another operation in the same work graph has committed.
            return self._resolve(target.ref)
        if isinstance(target, ResourceRef):
            identity = self.__writer.get_record(target)
            return None if identity is None else self._from_identity(identity)
        if isinstance(target, Mapping):
            if "id" in target:
                return self._resolve(target["id"])
            if "ref" in target:
                return self._resolve(target["ref"])
        if not isinstance(target, str):
            return None
        for record in self._all_records():
            if record.id == target or target in record.aliases:
                return record
        return None

    def _require(self, target: Any) -> WorkRecord:
        record = self._resolve(target)
        if record is None:
            raise WorkNotFoundError(f"work record not found: {target!r}")
        return record

    def _kind(self, kind: Union[WorkKind, str]) -> WorkKind:
        if isinstance(kind, WorkKind):
            return kind
        if isinstance(kind, str):
            text = kind.removeprefix("work.")
            try:
                return WorkKind(text)
            except ValueError:
                pass
        raise WorkValidationError(f"unknown work kind: {kind!r}")

    def _ref(self, kind: WorkKind, record_id: str) -> Any:
        return _contract_types()[3](self.__writer.authority, KIND_PREFIX[kind], record_id)

    def _pinned(self, ref: Any, version: int) -> Any:
        return _contract_types()[3](ref.authority, ref.kind, ref.id, "rev-" + str(version))

    def _project_ref(self, record: Optional[WorkRecord]) -> Optional[Any]:
        if record is None:
            return None
        return record.ref if record.kind is WorkKind.PROJECT else record.project_ref

    def _ref_dict(self, ref: Any) -> Dict[str, Any]:
        return {"authority": ref.authority, "kind": ref.kind, "id": ref.id}

    def _payload_ref(self, value: Any) -> Optional[Any]:
        if value is None:
            return None
        ResourceRef = _contract_types()[3]
        if isinstance(value, ResourceRef):
            return value
        if isinstance(value, Mapping):
            return ResourceRef(value["authority"], value["kind"], value["id"], value.get("revision"))
        return None

    def _base_payload(self, kind: WorkKind, record_id: str, *, title: str, name: Optional[str] = None, aliases: Sequence[str], parent: Any, project_ref: Any, dependencies: Sequence[Any], lifecycle: Lifecycle, readiness: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "schema_revision": SCHEMA_REVISION,
            "kind": kind.value,
            "id": record_id,
            "title": title,
            "name": name or title,
            "alias": aliases[0],
            "aliases": list(aliases),
            "parent": self._ref_dict(parent) if parent is not None else None,
            "project_ref": self._ref_dict(project_ref) if project_ref is not None else None,
            "dependencies": [self._ref_dict(ref) for ref in dependencies],
            "lifecycle": lifecycle.value,
            "readiness": dict(readiness),
        }

    def _revision_changes(self, record: WorkRecord, *, title: Optional[str] = None, name: Optional[str] = None, outcome: Optional[str] = None, add_alias: Optional[str] = None, aliases: Sequence[str] = (), fields: Optional[Mapping[str, Any]] = None, lifecycle: Optional[Union[Lifecycle, str]] = None) -> Dict[str, Any]:
        payload = dict(record.payload)
        if title is not None:
            payload["title"] = self._title(title, "title")
        if name is not None:
            payload["name"] = self._title(name, "name")
        if outcome is not None:
            if not isinstance(outcome, str):
                raise WorkValidationError("outcome must be text")
            payload["outcome"] = outcome
        retained = list(payload.get("aliases", (record.alias,)))
        for value in tuple(aliases) + ((add_alias,) if add_alias else ()):
            _opaque(value, "alias")
            if value not in retained:
                retained.append(value)
        payload["aliases"] = retained
        payload["alias"] = retained[0]
        if fields is not None:
            if not isinstance(fields, Mapping):
                raise WorkValidationError("fields must be a mapping")
            payload["fields"] = dict(fields)
        if lifecycle is not None:
            payload["lifecycle"] = self._lifecycle(lifecycle).value
        return payload

    def _validate_payload(self, payload: Mapping[str, Any]) -> None:
        if payload.get("kind") not in WORK_KINDS:
            raise WorkValidationError("payload has an unknown work kind")
        _opaque(payload.get("id", ""), "id")
        self._title(payload.get("title", ""), "title")
        aliases = payload.get("aliases", ())
        if not aliases or len(set(aliases)) != len(aliases):
            raise WorkValidationError("a work record requires unique retained aliases")
        for alias in aliases:
            _opaque(alias, "alias")
        self._lifecycle(payload.get("lifecycle", Lifecycle.PENDING))
        if not isinstance(payload.get("readiness", {}), Mapping):
            raise WorkValidationError("readiness must be a mapping")

    def _validate_new_graph(self, payload: Mapping[str, Any], parent: Optional[WorkRecord], dependencies: Sequence[WorkRecord]) -> None:
        self._validate_payload(payload)
        if parent is not None:
            candidate = WorkRecord(self._ref(self._kind(payload["kind"]), payload["id"]), self._kind(payload["kind"]), payload["title"], payload["name"], tuple(payload["aliases"]), self._payload_ref(payload.get("parent")), tuple(self._payload_ref(ref) for ref in payload.get("dependencies", ())), self._payload_ref(payload.get("project_ref")), self._lifecycle(payload["lifecycle"]), payload["readiness"], payload, 0)
            self._validate_parent(candidate, parent)
        self._validate_dependency_set(self._ref(self._kind(payload["kind"]), payload["id"]), tuple(ref.ref for ref in dependencies))

    def _validate_parent(self, child: WorkRecord, parent: WorkRecord) -> None:
        if child.ref.id == parent.ref.id:
            raise InvalidParentError("a work record cannot parent itself")
        if child.kind is WorkKind.PROJECT:
            raise InvalidParentError("projects cannot have a parent")
        if parent.kind not in {WorkKind.PROJECT, WorkKind.EFFORT, WorkKind.TASK, WorkKind.CRITERION, WorkKind.SCENARIO, WorkKind.GATE}:
            raise InvalidParentError("parent is not a work record")
        current = parent
        seen = {child.ref.id}
        while current.parent is not None:
            if current.ref.id in seen:
                raise GraphCycleError("hierarchy cycle rejected")
            seen.add(current.ref.id)
            next_record = self._resolve(current.parent)
            if next_record is None:
                break
            current = next_record

    def _validate_dependency_set(self, target_ref: Any, dependencies: Sequence[Any]) -> None:
        for dependency in dependencies:
            if dependency.id == target_ref.id and dependency.kind == target_ref.kind:
                raise GraphCycleError("dependency self-cycle rejected")
        self._validate_dependency_graph_many(target_ref, dependencies)

    def _validate_dependency_graph(self, target_ref: Any, prerequisite_ref: Any) -> None:
        self._validate_dependency_set(target_ref, (prerequisite_ref,))

    def _validate_dependency_graph_many(self, target_ref: Any, dependencies: Sequence[Any]) -> None:
        adjacency: Dict[str, List[str]] = {}
        for record in self._all_records():
            adjacency[record.ref.id] = [ref.id for ref in record.dependencies]
        adjacency.setdefault(target_ref.id, [])
        adjacency[target_ref.id] = list(dict.fromkeys(adjacency[target_ref.id] + [ref.id for ref in dependencies]))
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting:
                raise GraphCycleError("dependency cycle rejected")
            if node in visited:
                return
            visiting.add(node)
            for prerequisite in adjacency.get(node, ()):
                visit(prerequisite)
            visiting.remove(node)
            visited.add(node)
        for node in tuple(adjacency):
            visit(node)

    def _lifecycle(self, value: Union[Lifecycle, str]) -> Lifecycle:
        if isinstance(value, Lifecycle):
            return value
        try:
            return Lifecycle(value)
        except (ValueError, TypeError) as exc:
            raise WorkValidationError(f"unknown lifecycle: {value!r}") from exc

    def _title(self, value: Optional[str], field: str, *, default: Optional[str] = None) -> str:
        if value is None:
            value = default
        if not isinstance(value, str) or not value.strip():
            raise WorkValidationError(f"{field} must be non-blank")
        return value

    def _aliases(self, alias: Optional[str], aliases: Sequence[str], kind: WorkKind, record_id: str) -> Tuple[str, ...]:
        values = [alias] if alias else []
        values.extend(aliases)
        if not values:
            values.append(kind.value + "-" + record_id[-10:])
        for value in values:
            _opaque(value, "alias")
        if len(set(values)) != len(values):
            raise WorkValidationError("aliases must be unique")
        return tuple(values)

    def _request_key(self, value: Optional[str]) -> str:
        return _opaque(value or "request-" + uuid.uuid4().hex, "logical_request_key")

    def _new_id(self, kind: WorkKind, request_key: str) -> str:
        return "".join((kind.value, "-", hashlib.sha256((DOMAIN_ID + ":" + kind.value + ":" + request_key).encode("utf-8")).hexdigest()[:28]))

    def _provenance_value(self, value: Any, actor: Any) -> Any:
        selected = value if value is not None else actor
        if selected is None:
            return None
        if hasattr(selected, "to_dict"):
            return selected.to_dict()
        if isinstance(selected, str):
            return selected
        if isinstance(selected, Mapping):
            return dict(selected)
        raise WorkValidationError("provenance must be text, mapping, or an FND actor")


# Names used by early consumers and worker handoff examples.
WorkGraph = command_facade(_WorkGraphEngine, DOMAIN_ID)
WorkModule = WorkGraph
WorkStore = WorkGraph


__all__ = [
    "DEFAULT_TITLE",
    "DOMAIN_ID",
    "DOMAIN_OWNER",
    "DOMAIN_VERSION",
    "SCHEMA_REVISION",
    "WorkGraph",
    "WorkModule",
    "WorkStore",
    "contribution",
]
