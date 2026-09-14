"""Namespaced DAT-03 definitions and JSON validation.

The catalog is deliberately persistence-neutral.  FND owns durable identities,
transactions, receipts, and events; this module owns only the typed extension
definitions that tell the command service what a namespace means.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping, Optional, Tuple

from herzchen.contracts import (
    ContractError,
    DomainContribution,
    ResourceRef,
    canonical_json,
)


EXTENSION_SCHEMA_REVISION = "dat.extensions.v1"
EXTENSION_DOMAIN_ID = "dat.extensions"
EXTENSION_OWNER = "dat"
CATALOG_DIGEST_BINDING_PREFIX = "definition-catalog-sha256:"

OPEN_NAMESPACE = "annotation.open"
PROTOCOL_NAMESPACE = "protocol.choice"
MANAGED_NAMESPACE = "managed.state"

SCHEMA_AUTHORITY = "herzchen"
SCHEMA_KIND = "dat.extensions.schema"


class ExtensionError(ContractError):
    """Base error for the bounded extension surface."""


class DefinitionNotFoundError(ExtensionError):
    """A namespace, role, or definition ID is not registered."""


class NamespaceNotSupportedError(ExtensionError):
    """A registered definition does not apply to the subject kind."""


class ManagedFieldError(ExtensionError):
    """An extension command attempted to write managed state."""


class OwnerRequiredError(ExtensionError):
    """A protocol namespace was not called by its declared owner."""


class SchemaValidationError(ExtensionError):
    """A namespace value does not satisfy its pinned standard schema."""


class QueryNotSupportedError(ExtensionError):
    """A query is not among the definition's declared supported queries."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtensionError(f"{field} must be a non-blank string")
    if "\x00" in value or "/" in value or "\\" in value or "://" in value:
        raise ExtensionError(f"{field} must be an opaque identifier")
    return value


def _description(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtensionError(f"{field} must be a non-blank string")
    if "\x00" in value:
        raise ExtensionError(f"{field} contains a NUL character")
    return value


def _texts(values: Iterable[str], field: str) -> Tuple[str, ...]:
    values = tuple(values)
    if any(not isinstance(value, str) for value in values):
        raise ExtensionError(f"{field} must contain strings")
    result = tuple(_text(value, f"{field}[]") for value in values)
    if len(set(result)) != len(result):
        raise ExtensionError(f"{field} contains duplicate values")
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExtensionError(f"{field} must be a JSON object")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise ExtensionError(f"{field} keys must be strings")
    return result


def _json_safe(value: Any, field: str) -> Any:
    try:
        canonical_json(value)
    except (TypeError, ValueError, ContractError) as exc:
        raise ExtensionError(f"{field} must contain JSON values") from exc
    return value


def schema_ref(definition_id: str, version: str) -> ResourceRef:
    """Return the stable, pinned identity of a standard definition schema."""
    return ResourceRef(SCHEMA_AUTHORITY, SCHEMA_KIND, definition_id, version)


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise SchemaValidationError(f"unsupported schema type: {expected}")


def validate_json_schema(value: Any, schema: Mapping[str, Any], path: str = "value") -> None:
    """Validate the bounded JSON-schema-like subset used by DAT-03.

    The subset is intentionally dependency-free and covers the definitions in
    this package: type, required, properties, additionalProperties, enum,
    const, items, min/max length/items, and numeric bounds.
    """
    schema = _mapping(schema, "schema")
    if "const" in schema and value != schema["const"]:
        raise SchemaValidationError(f"{path} must equal the declared constant")
    if "enum" in schema:
        choices = schema["enum"]
        if not isinstance(choices, (list, tuple)) or value not in choices:
            raise SchemaValidationError(f"{path} is not one of the declared choices")
    expected = schema.get("type")
    if expected is not None:
        expected_types = (expected,) if isinstance(expected, str) else tuple(expected)
        if not expected_types or not any(_matches_type(value, item) for item in expected_types):
            raise SchemaValidationError(f"{path} has the wrong JSON type")

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        properties = _mapping(properties, f"{path}.properties")
        required = schema.get("required", ())
        if not isinstance(required, (list, tuple)):
            raise SchemaValidationError(f"{path}.required must be an array")
        for key in required:
            if key not in value:
                raise SchemaValidationError(f"{path}.{key} is required")
        unknown = set(value).difference(properties)
        if unknown and schema.get("additionalProperties", True) is False:
            raise SchemaValidationError(f"{path} contains unknown fields: {', '.join(sorted(unknown))}")
        for key, child_schema in properties.items():
            if key in value:
                validate_json_schema(value[key], _mapping(child_schema, f"{path}.{key}.schema"), f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaValidationError(f"{path} has too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaValidationError(f"{path} has too many items")
        if "items" in schema:
            item_schema = _mapping(schema["items"], f"{path}.items.schema")
            for index, item in enumerate(value):
                validate_json_schema(item, item_schema, f"{path}[{index}]")
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaValidationError(f"{path} is shorter than minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaValidationError(f"{path} is longer than maxLength")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError(f"{path} is above maximum")


@dataclass(frozen=True)
class ExtensionDefinition:
    """One discoverable namespace definition and its editable/query shape."""

    definition_id: str
    namespace: str
    version: str
    resource_kinds: Tuple[str, ...]
    classification: str
    owner: str
    description: str
    schema: Mapping[str, Any]
    query_fields: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]
    writable: bool = True

    def __post_init__(self) -> None:
        for field, value in (("definition_id", self.definition_id), ("namespace", self.namespace), ("version", self.version), ("owner", self.owner)):
            _text(value, field)
        _texts(self.resource_kinds, "resource_kinds")
        if self.classification not in {"open_annotation", "protocol", "managed"}:
            raise ExtensionError("classification must be open_annotation, protocol, or managed")
        _description(self.description, "description")
        schema = dict(_mapping(self.schema, "schema"))
        _json_safe(schema, "schema")
        metadata = dict(_mapping(self.metadata or {}, "metadata"))
        _json_safe(metadata, "metadata")
        object.__setattr__(self, "resource_kinds", _texts(self.resource_kinds, "resource_kinds"))
        object.__setattr__(self, "query_fields", _texts(self.query_fields, "query_fields"))
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "metadata", metadata)
        if self.classification == "managed" and self.writable:
            raise ExtensionError("managed definitions cannot be writable")
        if self.classification == "protocol" and not self.owner:
            raise ExtensionError("protocol definitions require an owner")

    @property
    def schema_reference(self) -> ResourceRef:
        return schema_ref(self.definition_id, self.version)

    def supports(self, resource_kind: str) -> bool:
        return "*" in self.resource_kinds or resource_kind in self.resource_kinds

    def validate(self, value: Mapping[str, Any]) -> None:
        validate_json_schema(value, self.schema, self.namespace)

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition_id": self.definition_id,
            "namespace": self.namespace,
            "version": self.version,
            "resource_kinds": list(self.resource_kinds),
            "classification": self.classification,
            "owner": self.owner,
            "description": self.description,
            "schema": dict(self.schema),
            "schema_ref": self.schema_reference.to_dict(),
            "query_fields": list(self.query_fields),
            "metadata": dict(self.metadata),
            "writable": self.writable,
        }


@dataclass(frozen=True)
class DocumentRoleDefinition:
    """A typed, discoverable role for a DAT content document."""

    role_id: str
    document_kind: str
    version: str
    description: str
    schema: Mapping[str, Any]
    metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for field, value in (("role_id", self.role_id), ("document_kind", self.document_kind), ("version", self.version)):
            _text(value, field)
        _description(self.description, "description")
        schema = dict(_mapping(self.schema, "schema"))
        metadata = dict(_mapping(self.metadata or {}, "metadata"))
        _json_safe(schema, "schema")
        _json_safe(metadata, "metadata")
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "metadata", metadata)

    @property
    def schema_reference(self) -> ResourceRef:
        return schema_ref(self.role_id, self.version)

    def validate(self, value: Mapping[str, Any]) -> None:
        validate_json_schema(value, self.schema, self.role_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "document_kind": self.document_kind,
            "version": self.version,
            "description": self.description,
            "schema": dict(self.schema),
            "schema_ref": self.schema_reference.to_dict(),
            "metadata": dict(self.metadata),
        }


class DefinitionCatalog:
    """Collision-checked single source for definitions, help, and queries."""

    def __init__(self, definitions: Iterable[ExtensionDefinition], roles: Iterable[DocumentRoleDefinition] = ()) -> None:
        self._definitions = {}
        self._roles = {}
        schema_ids = set()
        for definition in definitions:
            if definition.namespace in self._definitions or definition.definition_id in {item.definition_id for item in self._definitions.values()}:
                raise ExtensionError(f"duplicate extension definition: {definition.definition_id}")
            if definition.schema_reference.id in schema_ids:
                raise ExtensionError(f"duplicate schema identity: {definition.schema_reference.id}")
            self._definitions[definition.namespace] = definition
            schema_ids.add(definition.schema_reference.id)
        for role in roles:
            if role.role_id in self._roles:
                raise ExtensionError(f"duplicate document role: {role.role_id}")
            if role.schema_reference.id in schema_ids:
                raise ExtensionError(f"duplicate schema identity: {role.schema_reference.id}")
            self._roles[role.role_id] = role
            schema_ids.add(role.schema_reference.id)

    @property
    def definitions(self) -> Tuple[ExtensionDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    @property
    def roles(self) -> Tuple[DocumentRoleDefinition, ...]:
        return tuple(self._roles[key] for key in sorted(self._roles))

    def to_dict(self) -> Mapping[str, Any]:
        """Return the complete typed definition set used at admission."""
        return {
            "definitions": [definition.to_dict() for definition in self.definitions],
            "document_roles": [role.to_dict() for role in self.roles],
            "schema_revision": EXTENSION_SCHEMA_REVISION,
        }

    @property
    def digest(self) -> str:
        """Bind schema, owner, policy, help, validation, query, and version."""
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def get(self, namespace: str, resource_kind: Optional[str] = None) -> ExtensionDefinition:
        try:
            definition = self._definitions[namespace]
        except KeyError as exc:
            raise DefinitionNotFoundError(f"unknown extension namespace: {namespace}") from exc
        if resource_kind is not None and not definition.supports(resource_kind):
            raise NamespaceNotSupportedError(f"{namespace} does not apply to {resource_kind}")
        return definition

    definition = get

    @property
    def namespaces(self) -> Tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def role(self, role_id: str) -> DocumentRoleDefinition:
        try:
            return self._roles[role_id]
        except KeyError as exc:
            raise DefinitionNotFoundError(f"unknown document role: {role_id}") from exc

    def describe_role(self, role_id: str) -> Mapping[str, Any]:
        return self.role(role_id).to_dict()

    def describe(self, namespace: Optional[str] = None, resource_kind: Optional[str] = None) -> Mapping[str, Any]:
        if namespace is not None:
            return self.get(namespace, resource_kind).to_dict()
        value = dict(self.to_dict())
        value["definitions"] = [definition.to_dict() for definition in self.definitions if resource_kind is None or definition.supports(resource_kind)]
        return value


OPEN_DEFINITION = ExtensionDefinition(
    "dat.extensions.annotation.open.v1",
    OPEN_NAMESPACE,
    "1",
    ("*",),
    "open_annotation",
    EXTENSION_OWNER,
    "Harmless user annotations; unknown JSON fields are retained and never grant authority.",
    {"type": "object", "additionalProperties": True},
    ("*",),
    {"doc_role": "annotation", "unknown_values": "retained"},
)

PROTOCOL_DEFINITION = ExtensionDefinition(
    "dat.extensions.protocol.choice.v1",
    PROTOCOL_NAMESPACE,
    "1",
    ("work.task", "work.project", "dat.content.document"),
    "protocol",
    "dat.protocol-owner",
    "An owner-declared protocol choice; values are schema-validated and do not become authority by annotation.",
    {
        "type": "object",
        "properties": {
            "choice": {"type": "string", "enum": ("accept", "reject", "hold")},
            "reason": {"type": "string", "minLength": 1},
            "profile": {"type": "string", "minLength": 1},
        },
        "required": ("choice",),
        "additionalProperties": False,
    },
    ("choice", "reason", "profile"),
    {"doc_role": "protocol-choice", "owner_required": True},
)

MANAGED_DEFINITION = ExtensionDefinition(
    "dat.extensions.managed.state.v1",
    MANAGED_NAMESPACE,
    "1",
    ("*",),
    "managed",
    "fnd",
    "FND-owned identity, ownership, version, archive, promotion, provenance, acceptance, receipt, event, and head state.",
    {"type": "object", "additionalProperties": True},
    (),
    {"writable": False, "protected": True},
    False,
)

CANDIDATE_ROLE = DocumentRoleDefinition(
    "candidate-manifest",
    "dat.content.document",
    "1",
    "Immutable candidate inputs, outputs, criteria, and provenance for a proposed deliverable.",
    {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string", "minLength": 1},
            "manifest_revision": {"type": "string", "minLength": 1},
            "resource": {"type": "object", "required": ("authority", "kind", "id"), "additionalProperties": True},
            "output_refs": {"type": "array", "items": {"type": "object"}},
            "source_refs": {"type": "array", "items": {"type": "object"}},
            "input_refs": {"type": "array", "items": {"type": "object"}},
            "criteria_refs": {"type": "array", "items": {"type": "object"}},
            "provenance": {"type": "object"},
        },
        "required": ("candidate_id", "manifest_revision", "resource", "provenance"),
        "additionalProperties": True,
    },
    {"doc_role": "candidate"},
)

DECISION_ROLE = DocumentRoleDefinition(
    "decision-manifest",
    "dat.content.document",
    "1",
    "Decision subject, authority, criteria, evidence, disposition, rationale, and reconsideration condition.",
    {
        "type": "object",
        "properties": {
            "decision_id": {"type": "string", "minLength": 1},
            "subject": {"type": "object", "required": ("authority", "kind", "id"), "additionalProperties": True},
            "question": {"type": "string", "minLength": 1},
            "disposition": {"type": "string", "minLength": 1},
            "rationale": {"type": "string", "minLength": 1},
            "candidate_refs": {"type": "array", "items": {"type": "object"}},
            "criteria_refs": {"type": "array", "items": {"type": "object"}},
            "evidence_refs": {"type": "array", "items": {"type": "object"}},
        },
        "required": ("decision_id", "subject", "question", "disposition", "rationale"),
        "additionalProperties": True,
    },
    {"doc_role": "decision"},
)

DEFAULT_CATALOG = DefinitionCatalog(
    (OPEN_DEFINITION, PROTOCOL_DEFINITION, MANAGED_DEFINITION),
    (CANDIDATE_ROLE, DECISION_ROLE),
)
DEFAULT_CATALOG_DIGEST = DEFAULT_CATALOG.digest


def domain_contribution() -> DomainContribution:
    """Describe the extension domain for FND's explicit registry."""
    return DomainContribution(
        EXTENSION_DOMAIN_ID,
        "1",
        EXTENSION_OWNER,
        ("dat.extensions.metadata",),
        ("dat.extensions.candidate-manifest", "dat.extensions.decision-manifest"),
        (OPEN_NAMESPACE, PROTOCOL_NAMESPACE, MANAGED_NAMESPACE),
        (
            "dat.extensions.metadata.describe",
            "dat.extensions.metadata.read",
            "dat.extensions.metadata.query",
            "dat.extensions.metadata.set",
            "dat.extensions.metadata.remove",
        ),
        ("dat.extensions.metadata.changed", "dat.extensions.metadata.removed"),
        EXTENSION_SCHEMA_REVISION,
        (
            "fnd-03.six-table-composition",
            "dat.content.document-roles",
            "handler:herzchen.extensions.ExtensionCommandService",
            "handler-required",
            "actor-authority:dat-auth",
            "mutation-resource:work.task",
            "mutation-resource:work.project",
            "mutation-resource:dat.content.document",
            "mutation-resource:registered:*",
            CATALOG_DIGEST_BINDING_PREFIX + DEFAULT_CATALOG_DIGEST,
        ),
    )


__all__ = [
    "CANDIDATE_ROLE", "CATALOG_DIGEST_BINDING_PREFIX", "DECISION_ROLE", "DEFAULT_CATALOG", "DEFAULT_CATALOG_DIGEST", "DefinitionCatalog",
    "DefinitionNotFoundError", "DocumentRoleDefinition", "EXTENSION_DOMAIN_ID",
    "EXTENSION_OWNER", "EXTENSION_SCHEMA_REVISION", "ExtensionDefinition",
    "ExtensionError", "MANAGED_DEFINITION", "MANAGED_NAMESPACE", "ManagedFieldError",
    "NamespaceNotSupportedError", "OPEN_DEFINITION", "OPEN_NAMESPACE",
    "OwnerRequiredError", "PROTOCOL_DEFINITION", "PROTOCOL_NAMESPACE",
    "QueryNotSupportedError", "SCHEMA_AUTHORITY", "SCHEMA_KIND", "SchemaValidationError",
    "domain_contribution", "schema_ref", "validate_json_schema",
]
