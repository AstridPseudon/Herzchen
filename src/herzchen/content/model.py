"""Persistence-neutral DAT-02 content, revision, and association records.

This module owns the domain shape only.  It deliberately does not contain a
database connection, migration, event log, receipt store, or in-memory
replacement for FND-03.  The records are validated before a later FND writer
receives a command envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Optional, Tuple

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    ContractError,
    DocumentRef,
    DomainContribution,
    ReferenceBinding,
    ResourceRef,
    TransactionContext,
    canonical_json,
)


CONTENT_SCHEMA_REVISION = "dat-content.v1"
CONTENT_DOMAIN_ID = "dat.content"
CONTENT_OWNER = "dat"


class ContentError(ContractError):
    """Raised when a DAT content value violates its domain invariant."""


class PersistenceUnavailableError(ContentError):
    """Raised when a command cannot be sent because FND-03 is not supplied."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{field} must be a non-blank string")
    if "\x00" in value:
        raise ContentError(f"{field} contains a NUL character")
    if "/" in value or "\\" in value or "://" in value:
        raise ContentError(f"{field} must be an opaque identity")
    return value


def _json_content(value: Any, field: str = "content") -> Any:
    """Validate and return JSON content without accepting a private encoding."""
    try:
        canonical_json(value)
    except (TypeError, ValueError, ContractError) as exc:
        raise ContentError(f"{field} must be JSON-safe content") from exc
    return value


def _ref(value: Any, field: str) -> ResourceRef:
    if not isinstance(value, ResourceRef):
        raise ContentError(f"{field} must be a ResourceRef")
    return value


def _optional_ref(value: Any, field: str) -> Optional[ResourceRef]:
    if value is None:
        return None
    return _ref(value, field)


def _same_document(left: ResourceRef, right: ResourceRef) -> bool:
    """Compare document identity while deliberately ignoring revisions."""
    return (left.authority, left.kind, left.id) == (right.authority, right.kind, right.id)


@dataclass(frozen=True)
class ContentDocument:
    """Stable document identity and independent ownership/access metadata."""

    ref: ResourceRef
    role: str
    visibility: str
    access_mode: str
    maintainer: str
    authoring_scope: Optional[ResourceRef] = None
    source_ref: Optional[ResourceRef] = None
    import_mode: str = "owned"
    writable: bool = True

    def __post_init__(self) -> None:
        _ref(self.ref, "ref")
        if self.ref.revision is not None:
            raise ContentError("document identity must not carry a revision")
        _text(self.role, "role")
        if self.visibility not in {"private", "shared", "public"}:
            raise ContentError("visibility must be private, shared, or public")
        if self.access_mode not in {"read", "write", "append"}:
            raise ContentError("access_mode must be read, write, or append")
        _text(self.maintainer, "maintainer")
        _optional_ref(self.authoring_scope, "authoring_scope")
        _optional_ref(self.source_ref, "source_ref")
        if self.import_mode not in {"owned", "imported", "pinned"}:
            raise ContentError("import_mode must be owned, imported, or pinned")
        if self.import_mode == "owned" and self.source_ref is not None:
            raise ContentError("owned documents cannot carry a source reference")
        if self.import_mode in {"imported", "pinned"} and self.source_ref is None:
            raise ContentError("imported/pinned documents require an authoritative source_ref")
        if self.import_mode == "pinned" and self.source_ref is not None and not self.source_ref.is_pinned:
            raise ContentError("pinned documents require a pinned authoritative source_ref")
        if self.import_mode in {"imported", "pinned"} and self.writable:
            raise ContentError("repository/runtime-backed documents cannot be writable masters")
        if self.access_mode == "write" and not self.writable:
            raise ContentError("read-only documents cannot advertise write access")

    @property
    def document_ref(self) -> DocumentRef:
        return DocumentRef(self.ref.authority, self.ref.kind, self.ref.id, None, self.role)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContentDocument":
        if not isinstance(value, Mapping):
            raise ContentError("document must be an object")
        allowed = {"ref", "role", "visibility", "access_mode", "maintainer", "authoring_scope", "source_ref", "import_mode", "writable"}
        unknown = set(value).difference(allowed)
        if unknown:
            raise ContentError(f"unknown document fields: {', '.join(sorted(unknown))}")
        return cls(
            ResourceRef.from_dict(value["ref"]),
            value["role"],
            value["visibility"],
            value["access_mode"],
            value["maintainer"],
            ResourceRef.from_dict(value["authoring_scope"]) if value.get("authoring_scope") else None,
            ResourceRef.from_dict(value["source_ref"]) if value.get("source_ref") else None,
            value.get("import_mode", "owned"),
            bool(value.get("writable", True)),
        )


@dataclass(frozen=True)
class ContentRevision:
    """Immutable content value addressed by its owning document and revision."""

    document: ResourceRef
    revision: str
    content: Any
    author: AuthenticatedActor
    parent_revision: Optional[str] = None
    content_digest: Optional[str] = None
    initial: bool = False

    def __post_init__(self) -> None:
        _ref(self.document, "document")
        if self.document.revision is not None:
            raise ContentError("revision.document must be the unversioned document identity")
        _text(self.revision, "revision")
        _json_content(self.content)
        if not isinstance(self.author, AuthenticatedActor):
            raise ContentError("author must be an authenticated actor")
        if self.parent_revision is not None:
            _text(self.parent_revision, "parent_revision")
        digest = hashlib.sha256(canonical_json(self.content).encode("utf-8")).hexdigest()
        if self.content_digest is not None and self.content_digest.lower() != digest:
            raise ContentError("content_digest does not match content")
        object.__setattr__(self, "content_digest", digest)
        if self.initial and self.parent_revision is not None:
            raise ContentError("initial revision cannot have a parent revision")

    @property
    def ref(self) -> ResourceRef:
        return ResourceRef(self.document.authority, self.document.kind, self.document.id, self.revision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContentRevision":
        if not isinstance(value, Mapping):
            raise ContentError("revision must be an object")
        allowed = {"document", "revision", "content", "author", "parent_revision", "content_digest", "initial"}
        unknown = set(value).difference(allowed)
        if unknown:
            raise ContentError(f"unknown revision fields: {', '.join(sorted(unknown))}")
        return cls(
            ResourceRef.from_dict(value["document"]),
            value["revision"],
            value["content"],
            AuthenticatedActor.from_dict(value["author"]),
            value.get("parent_revision"),
            value.get("content_digest"),
            bool(value.get("initial", False)),
        )


def validate_revision_owner(document: ContentDocument, revision: ContentRevision) -> None:
    """Reject a pin that crosses authority, kind, or document identity."""
    if not isinstance(document, ContentDocument) or not isinstance(revision, ContentRevision):
        raise ContentError("document and revision must be content records")
    if revision.document != document.ref:
        raise ContentError("revision does not belong to the referenced document")
    if revision.ref.revision != revision.revision:
        raise ContentError("revision reference has an inconsistent revision")


def validate_document_binding(document: ContentDocument, binding: ReferenceBinding) -> None:
    """Validate a current/pinned binding before an association is persisted.

    FND-03 is responsible for checking that a pinned revision exists.  DAT can
    still reject an authority/kind/id mismatch locally, before handing the
    command to the shared transaction.
    """
    if not isinstance(document, ContentDocument):
        raise ContentError("document must be a ContentDocument")
    if not isinstance(binding, ReferenceBinding):
        raise ContentError("binding must be a ReferenceBinding")
    if not _same_document(document.ref, binding.ref):
        raise ContentError("document binding does not belong to the referenced document")


@dataclass(frozen=True)
class DocumentAssociation:
    """Named many-to-many edge; the document remains independently addressable."""

    subject: ResourceRef
    namespace: str
    key: str
    document: ReferenceBinding
    access_mode: str = "read"

    def __post_init__(self) -> None:
        _ref(self.subject, "subject")
        _text(self.namespace, "namespace")
        _text(self.key, "key")
        if not isinstance(self.document, ReferenceBinding):
            raise ContentError("document must be a ReferenceBinding")
        if self.document.ref.kind == "document-association":
            raise ContentError("association target must be a document, not another association")
        if self.access_mode not in {"read", "append"}:
            raise ContentError("association access_mode must be read or append")

    @property
    def identity(self) -> str:
        return association_identity(self.subject, self.namespace, self.key)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentAssociation":
        if not isinstance(value, Mapping):
            raise ContentError("association must be an object")
        allowed = {"subject", "namespace", "key", "document", "access_mode"}
        unknown = set(value).difference(allowed)
        if unknown:
            raise ContentError(f"unknown association fields: {', '.join(sorted(unknown))}")
        return cls(
            ResourceRef.from_dict(value["subject"]),
            value["namespace"],
            value["key"],
            ReferenceBinding.from_dict(value["document"]),
            value.get("access_mode", "read"),
        )


def association_identity(subject: ResourceRef, namespace: str, key: str) -> str:
    """Derive a stable edge identity without making a local foreign key."""
    _ref(subject, "subject")
    _text(namespace, "namespace")
    _text(key, "key")
    material = canonical_json({"subject": subject, "namespace": namespace, "key": key})
    return "link-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def revision_identity(document: ResourceRef, revision: str) -> ResourceRef:
    """Address one immutable revision as a distinct FND identity.

    FND-03 identities are keyed by authority/kind/id, so a revision cannot be
    represented by repeatedly overwriting the document row.  The derived
    revision identity gives each content value its own durable row while the
    document row remains the current-head navigation anchor.
    """
    _ref(document, "document")
    if document.revision is not None:
        raise ContentError("revision identity requires an unversioned document")
    _text(revision, "revision")
    material = canonical_json({"document": document, "revision": revision})
    ident = "revision-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return ResourceRef(document.authority, "dat.content.revision", ident, revision)


def domain_contribution() -> DomainContribution:
    """Describe DAT identities for FND's explicit domain registry."""
    return DomainContribution(
        CONTENT_DOMAIN_ID,
        "1",
        CONTENT_OWNER,
        ("dat.content.document", "dat.content.revision", "dat.content.association"),
        ("dat.content.document-record",),
        ("dat.content.links",),
        ("dat.content.document.create", "dat.content.revision.append", "dat.content.link", "dat.content.unlink"),
        ("dat.content.document.created", "dat.content.revision.appended", "dat.content.linked", "dat.content.unlinked"),
        CONTENT_SCHEMA_REVISION,
        (
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction",
            "handler-required", "mutation-resource:document-association",
            "mutation-resource:dat.context.packet", "mutation-resource:project.specification",
            "mutation-resource:document",
            "mutation-port:" + CONTENT_SCHEMA_REVISION + "|dat.content.document.create|*|dat.content.document.created",
            "mutation-port:" + CONTENT_SCHEMA_REVISION + "|dat.content.revision.append|*|dat.content.revision.appended",
            "mutation-port:" + CONTENT_SCHEMA_REVISION + "|dat.content.link|*|dat.content.linked",
            "mutation-port:" + CONTENT_SCHEMA_REVISION + "|dat.content.unlink|*|dat.content.unlinked",
        ),
    )


__all__ = [
    "CONTENT_DOMAIN_ID",
    "CONTENT_OWNER",
    "CONTENT_SCHEMA_REVISION",
    "ContentDocument",
    "ContentError",
    "ContentRevision",
    "DocumentAssociation",
    "PersistenceUnavailableError",
    "association_identity",
    "domain_contribution",
    "revision_identity",
    "validate_document_binding",
    "validate_revision_owner",
]
