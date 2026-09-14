"""Canonical FND-backed commands for namespaced metadata extensions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, ContextManager, Iterable, Mapping, Optional, Protocol, Sequence
from herzchen.command_ports import command_facade

from herzchen.contracts import (
    CommandEnvelope,
    CommandReceipt,
    ContractError,
    DomainContribution,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
)

from .model import (
    DEFAULT_CATALOG,
    DEFAULT_CATALOG_DIGEST,
    CATALOG_DIGEST_BINDING_PREFIX,
    EXTENSION_SCHEMA_REVISION,
    MANAGED_NAMESPACE,
    DefinitionCatalog,
    ExtensionDefinition,
    ExtensionError,
    ManagedFieldError,
    OwnerRequiredError,
    QueryNotSupportedError,
    domain_contribution,
)


_MISSING = object()


class FNDExtensionWriter(Protocol):
    """The supplied FND-03 writer surface consumed by DAT-03."""

    authority: str

    def transaction(self) -> ContextManager[Any]: ...

    def mutate(self, envelope: CommandEnvelope, **kwargs: Any) -> CommandReceipt: ...

    def get_identity(self, ref: ResourceRef) -> Any: ...

    def register_domain(self, contribution: DomainContribution, **kwargs: Any) -> DomainContribution: ...

    def registered_domains(self) -> Sequence[DomainContribution]: ...


class SubjectNotFoundError(ExtensionError):
    """Metadata requires an already admitted FND subject identity."""


class _ExtensionCommandServiceEngine:
    """One public read/query/describe/write surface over an FND Store.

    The service has no cache and no persistence of its own.  Every operation
    reads the subject from FND at the point of use.  FND's mutate call receives
    the complete preserved identity payload after the one requested metadata
    namespace has been merged.
    """

    def __init__(self, writer: Optional[FNDExtensionWriter], catalog: DefinitionCatalog = DEFAULT_CATALOG, *, register: bool = True) -> None:
        self.__writer = writer
        self.reader = None if writer is None else writer.consumer()
        self.catalog = catalog
        self._catalog_digest = catalog.digest
        if self._catalog_digest != DEFAULT_CATALOG_DIGEST:
            raise ExtensionError("extension catalog does not match the installed typed definition admission")
        if writer is not None and register:
            self._ensure_registered()
        elif writer is not None:
            self._verify_registered()
        if writer is not None and hasattr(writer, "domain_handler"):
            self.__writer = writer.domain_handler((domain_contribution(),))

    def _require_writer(self) -> FNDExtensionWriter:
        if self.__writer is None:
            raise ExtensionError("FND-03 writer is required for extension commands")
        return self.__writer

    def _require_catalog_admitted(self) -> None:
        if self.catalog.digest != self._catalog_digest or self._catalog_digest != DEFAULT_CATALOG_DIGEST:
            raise ExtensionError("extension catalog changed after typed definition admission")

    def _verify_registered(self) -> None:
        self._require_catalog_admitted()
        contribution = domain_contribution()
        binding = CATALOG_DIGEST_BINDING_PREFIX + self._catalog_digest
        if binding not in contribution.composition_bindings:
            raise ExtensionError("DAT extension contribution does not bind the complete definition catalog")
        existing = tuple(self._require_writer().registered_domains())
        persisted = next((item for item in existing if item.domain_id == contribution.domain_id), None)
        if persisted != contribution:
            raise ExtensionError("persisted DAT extension contribution differs from the installed typed catalog")

    def _ensure_registered(self) -> None:
        writer = self._require_writer()
        self._require_catalog_admitted()
        contribution = domain_contribution()
        if tuple(self.catalog.namespaces) != tuple(sorted(contribution.namespace_types)):
            raise ExtensionError("extension catalog namespaces must match the registered DAT contribution")
        if CATALOG_DIGEST_BINDING_PREFIX + self._catalog_digest not in contribution.composition_bindings:
            raise ExtensionError("DAT extension contribution does not bind the complete definition catalog")
        existing = tuple(writer.registered_domains())
        for item in existing:
            if item.domain_id == contribution.domain_id:
                if item != contribution:
                    raise ExtensionError("persisted DAT extension contribution differs from this catalog")
                return
        writer.register_domain(contribution)

    @staticmethod
    def _metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ExtensionError("subject payload metadata must be a JSON object")
        return metadata

    def _fresh(self, subject: ResourceRef, *, allow_stale_pin: bool = False) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        self._require_catalog_admitted()
        writer = self._require_writer()
        if not isinstance(subject, ResourceRef):
            raise TypeError("subject must be a ResourceRef")
        if subject.authority != writer.authority:
            raise ExtensionError("metadata subject must belong to the FND store authority")
        record = writer.get_identity(ResourceRef(subject.authority, subject.kind, subject.id))
        if record is None:
            raise SubjectNotFoundError(f"subject identity is not admitted: {subject.to_json()}")
        if not allow_stale_pin and subject.revision is not None and subject.revision != record.ref.revision:
            raise ExtensionError("pinned subject revision is not current")
        payload = deepcopy(dict(record.payload))
        metadata = deepcopy(dict(self._metadata(payload)))
        if any(not isinstance(namespace, str) or not isinstance(fields, Mapping) for namespace, fields in metadata.items()):
            raise ExtensionError("subject metadata must map namespaces to JSON objects")
        return record, payload, metadata

    def _definition(self, namespace: str, subject: ResourceRef) -> ExtensionDefinition:
        return self.catalog.get(namespace, subject.kind)

    @staticmethod
    def _result(subject: ResourceRef, record: Any, metadata: Mapping[str, Any], definition: Optional[ExtensionDefinition], receipt: Optional[CommandReceipt], payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        definition_value = None if definition is None else definition.to_dict()
        return {
            "subject": record.ref,
            "version": record.version,
            "revision": record.ref.revision,
            "metadata": deepcopy(dict(metadata)),
            "value": None if definition is None else deepcopy(metadata.get(definition.namespace, {})),
            "definition": definition_value,
            "schema_ref": None if definition is None else definition.schema_reference,
            "receipt": receipt,
            "payload": None if payload is None else deepcopy(dict(payload)),
        }

    def describe(self, namespace: Optional[str] = None, *, resource_kind: Optional[str] = None) -> Mapping[str, Any]:
        """Read the catalog used by validation, editing, and querying."""
        self._require_catalog_admitted()
        return self.catalog.describe(namespace, resource_kind)

    def describe_role(self, role_id: str) -> Mapping[str, Any]:
        """Read one typed candidate/decision document-role definition."""
        self._require_catalog_admitted()
        return self.catalog.describe_role(role_id)

    help = describe

    def read(self, subject: ResourceRef, namespace: Optional[str] = None) -> Mapping[str, Any]:
        """Fresh-read the subject and optionally one defined namespace."""
        record, payload, metadata = self._fresh(subject)
        definition = None if namespace is None else self._definition(namespace, subject)
        return self._result(subject, record, metadata, definition, None, payload)

    read_metadata = read

    def query(self, subject: ResourceRef, namespace: Optional[str] = None, field: Optional[str] = None, *, equals: Any = _MISSING, value: Any = _MISSING) -> Mapping[str, Any]:
        """Fresh-read and perform only a definition-declared field query.

        ``equals`` and ``value`` are equivalent explicit-value spellings;
        omitting both performs a field-presence query.  The sentinel keeps an
        explicit JSON null distinguishable from the default.
        """
        if equals is not _MISSING and value is not _MISSING:
            raise TypeError("query accepts either equals or value, not both")
        expected = value if value is not _MISSING else equals
        match_value = expected is not _MISSING
        record, payload, metadata = self._fresh(subject)
        if namespace is None:
            namespaces = tuple(sorted(metadata))
            definition = None
        else:
            definition = self._definition(namespace, subject)
            namespaces = (namespace,)
        matches = []
        for name in namespaces:
            try:
                current_definition = definition if definition is not None else self.catalog.get(name, subject.kind)
            except ExtensionError:
                # Unknown sibling namespaces are retained and readable, but
                # have no typed query contract in this catalog.
                continue
            namespace_value = metadata.get(name, {})
            if field is None:
                if match_value and namespace_value != expected:
                    continue
                matches.append({"namespace": name, "value": deepcopy(namespace_value)})
                continue
            if "*" not in current_definition.query_fields and field not in current_definition.query_fields:
                raise QueryNotSupportedError(f"{field} is not a supported query for {name}")
            if not isinstance(namespace_value, Mapping) or field not in namespace_value:
                continue
            value = namespace_value[field]
            if match_value and value != expected:
                continue
            matches.append({"namespace": name, "field": field, "value": deepcopy(value)})
        return {
            "subject": record.ref,
            "version": record.version,
            "revision": record.ref.revision,
            "metadata": deepcopy(metadata),
            "definition": None if definition is None else definition.to_dict(),
            "schema_ref": None if definition is None else definition.schema_reference,
            "matches": matches,
            "receipt": None,
            "payload": payload,
        }

    def _validate_mutation(self, definition: ExtensionDefinition, fields: Mapping[str, Any], context: TransactionContext, owner: Optional[str]) -> None:
        if definition.classification == "managed" or definition.namespace == MANAGED_NAMESPACE:
            raise ManagedFieldError(f"managed namespace is not writable: {definition.namespace}")
        if not definition.writable:
            raise ManagedFieldError(f"namespace is not writable: {definition.namespace}")
        if definition.classification == "protocol":
            actor = context.actor
            authority_bindings = {
                binding.split(":", 1)[1]
                for binding in domain_contribution().composition_bindings
                if binding.startswith("actor-authority:")
            }
            if actor.authority not in authority_bindings:
                raise OwnerRequiredError(f"protocol namespace requires authenticated actor bound to {definition.owner!r}")
            if owner != definition.owner:
                raise OwnerRequiredError(f"protocol command must name its admitted owner {definition.owner!r}")
        if not isinstance(fields, Mapping):
            raise TypeError("fields must be a JSON object")
        if any(not isinstance(key, str) for key in fields):
            raise ExtensionError("metadata field names must be strings")
        protected = {
            "id", "identity", "authority", "kind", "owner", "ownership", "version", "revision",
            "archive", "archived", "promotion", "primary", "superseded", "provenance", "acceptance",
            "accepted", "permission", "permissions", "receipt", "event", "event_id", "event_stream",
            "head", "head_seq", "managed",
        }
        if definition.classification == "open_annotation":
            attempted = protected.intersection(fields)
            if attempted:
                raise ManagedFieldError(f"managed fields cannot be written as annotations: {', '.join(sorted(attempted))}")
        for key, value in fields.items():
            try:
                canonical_json(value)
            except (TypeError, ValueError, ContractError) as exc:
                raise ExtensionError(f"metadata field {key!r} must contain JSON values") from exc

    @staticmethod
    def _context_with_current(context: TransactionContext, record: Any) -> TransactionContext:
        if not isinstance(context, TransactionContext):
            raise TypeError("context must be a TransactionContext")
        if context.expected_version is None or context.expected_revision is None:
            raise ExtensionError("state-changing extension commands require expected_version and expected_revision")
        return context

    def _mutate(self, subject: ResourceRef, namespace: str, context: TransactionContext, payload: Mapping[str, Any], record: Any, metadata: Mapping[str, Any], definition: ExtensionDefinition, *, removed: bool = False, no_op: bool = False) -> Mapping[str, Any]:
        writer = self._require_writer()
        target = ResourceRef(subject.authority, subject.kind, subject.id)
        next_ref = ResourceRef(subject.authority, subject.kind, subject.id, f"rev-{record.version + 1}")
        envelope = CommandEnvelope(
            "dat.extensions.metadata.remove" if removed else "dat.extensions.metadata.set",
            EXTENSION_SCHEMA_REVISION,
            target,
            context,
            payload,
        )
        with writer.transaction() as transaction:
            receipt = writer.mutate(
                envelope,
                event_type="dat.extensions.metadata.removed" if removed else "dat.extensions.metadata.changed",
                result_ref=next_ref,
                before_refs=(record.ref,),
                after_refs=(next_ref,),
                effects={"namespace": namespace, "removed": removed, "definition": definition.definition_id},
                no_op=no_op,
                transaction=transaction,
            )
        fresh_record, fresh_payload, fresh_metadata = self._fresh(target)
        return self._result(target, fresh_record, fresh_metadata, definition, receipt, fresh_payload)

    def set(self, subject: ResourceRef, namespace: str, fields: Mapping[str, Any], context: TransactionContext, *, owner: Optional[str] = None) -> Mapping[str, Any]:
        """Merge one owned namespace and preserve all sibling payload data."""
        record, payload, metadata = self._fresh(subject, allow_stale_pin=True)
        definition = self._definition(namespace, subject)
        self._validate_mutation(definition, fields, context, owner)
        self._context_with_current(context, record)
        current_namespace = metadata.get(namespace, {})
        if not isinstance(current_namespace, Mapping):
            raise ExtensionError(f"stored namespace {namespace} must be an object")
        candidate = dict(current_namespace)
        candidate.update(dict(fields))
        definition.validate(candidate)
        next_metadata = dict(metadata)
        next_metadata[namespace] = candidate
        next_payload = dict(payload)
        next_payload["metadata"] = next_metadata
        is_no_op = next_payload == payload
        return self._mutate(subject, namespace, context, next_payload, record, metadata, definition, no_op=is_no_op)

    set_metadata = set
    set_namespace = set

    def remove(self, subject: ResourceRef, namespace: str, fields: Optional[Iterable[str]], context: TransactionContext, *, owner: Optional[str] = None) -> Mapping[str, Any]:
        """Delete only an open namespace or its named fields."""
        record, payload, metadata = self._fresh(subject, allow_stale_pin=True)
        definition = self._definition(namespace, subject)
        if definition.classification != "open_annotation":
            raise ManagedFieldError("remove is limited to open annotation namespaces")
        self._validate_mutation(definition, {}, context, owner)
        self._context_with_current(context, record)
        current_namespace = metadata.get(namespace, {})
        if not isinstance(current_namespace, Mapping):
            raise ExtensionError(f"stored namespace {namespace} must be an object")
        if fields is None:
            next_metadata = dict(metadata)
            next_metadata.pop(namespace, None)
        else:
            names = tuple(fields)
            if any(not isinstance(name, str) or not name for name in names):
                raise ExtensionError("removed field names must be non-blank strings")
            protected = {"id", "identity", "authority", "kind", "owner", "ownership", "version", "revision", "archive", "archived", "promotion", "primary", "superseded", "provenance", "acceptance", "accepted", "permission", "permissions", "receipt", "event", "event_id", "event_stream", "head", "head_seq", "managed"}
            attempted = protected.intersection(names)
            if attempted:
                raise ManagedFieldError(f"managed fields cannot be removed as annotations: {', '.join(sorted(attempted))}")
            candidate = dict(current_namespace)
            for name in names:
                candidate.pop(name, None)
            next_metadata = dict(metadata)
            if candidate:
                next_metadata[namespace] = candidate
            else:
                next_metadata.pop(namespace, None)
        next_payload = dict(payload)
        next_payload["metadata"] = next_metadata
        is_no_op = next_payload == payload
        return self._mutate(subject, namespace, context, next_payload, record, metadata, definition, removed=True, no_op=is_no_op)

    remove_metadata = remove
    remove_namespace = remove


ExtensionCommandService = command_facade(_ExtensionCommandServiceEngine, "dat.extensions")

__all__ = [
    "ExtensionCommandService", "FNDExtensionWriter", "SubjectNotFoundError",
    "ReplayConflictError",
]
