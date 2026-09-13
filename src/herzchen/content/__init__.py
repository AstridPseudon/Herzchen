"""DAT-02 content domain, intentionally persistence-neutral until FND-03."""

from .commands import ContentCommandHandler, FNDContentWriter
from .model import (
    CONTENT_DOMAIN_ID,
    CONTENT_OWNER,
    CONTENT_SCHEMA_REVISION,
    ContentDocument,
    ContentError,
    ContentRevision,
    DocumentAssociation,
    PersistenceUnavailableError,
    association_identity,
    domain_contribution,
    revision_identity,
    validate_document_binding,
    validate_revision_owner,
)

__all__ = [
    "CONTENT_DOMAIN_ID",
    "CONTENT_OWNER",
    "CONTENT_SCHEMA_REVISION",
    "ContentCommandHandler",
    "ContentDocument",
    "ContentError",
    "ContentRevision",
    "DocumentAssociation",
    "FNDContentWriter",
    "PersistenceUnavailableError",
    "association_identity",
    "domain_contribution",
    "revision_identity",
    "validate_document_binding",
    "validate_revision_owner",
]
