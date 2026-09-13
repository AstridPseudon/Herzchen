"""Discoverable DAT-03 metadata definitions and FND-backed commands."""

from .commands import ExtensionCommandService, FNDExtensionWriter, SubjectNotFoundError
from herzchen.contracts import ReplayConflictError
from .model import (
    CANDIDATE_ROLE,
    DECISION_ROLE,
    DEFAULT_CATALOG,
    DefinitionCatalog,
    DefinitionNotFoundError,
    DocumentRoleDefinition,
    EXTENSION_DOMAIN_ID,
    EXTENSION_OWNER,
    EXTENSION_SCHEMA_REVISION,
    ExtensionDefinition,
    ExtensionError,
    MANAGED_DEFINITION,
    MANAGED_NAMESPACE,
    ManagedFieldError,
    NamespaceNotSupportedError,
    OPEN_DEFINITION,
    OPEN_NAMESPACE,
    OwnerRequiredError,
    PROTOCOL_DEFINITION,
    PROTOCOL_NAMESPACE,
    QueryNotSupportedError,
    SCHEMA_AUTHORITY,
    SCHEMA_KIND,
    SchemaValidationError,
    domain_contribution,
    schema_ref,
    validate_json_schema,
)

__all__ = [
    "CANDIDATE_ROLE", "DECISION_ROLE", "DEFAULT_CATALOG", "DefinitionCatalog",
    "DefinitionNotFoundError", "DocumentRoleDefinition", "EXTENSION_DOMAIN_ID",
    "EXTENSION_OWNER", "EXTENSION_SCHEMA_REVISION", "ExtensionCommandService",
    "ExtensionDefinition", "ExtensionError", "FNDExtensionWriter",
    "MANAGED_DEFINITION", "MANAGED_NAMESPACE", "ManagedFieldError",
    "NamespaceNotSupportedError", "OPEN_DEFINITION", "OPEN_NAMESPACE",
    "OwnerRequiredError", "PROTOCOL_DEFINITION", "PROTOCOL_NAMESPACE",
    "QueryNotSupportedError", "SCHEMA_AUTHORITY", "SCHEMA_KIND",
    "SchemaValidationError", "SubjectNotFoundError", "ReplayConflictError", "domain_contribution",
    "schema_ref", "validate_json_schema",
]
