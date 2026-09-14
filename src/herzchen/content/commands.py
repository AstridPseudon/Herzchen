"""DAT-02 command-envelope builders and the FND persistence seam."""

from __future__ import annotations

from typing import Any, ContextManager, Mapping, Optional, Protocol

from herzchen.contracts import CommandEnvelope, CommandReceipt, ResourceRef, TransactionContext

from .model import (
    CONTENT_SCHEMA_REVISION,
    ContentDocument,
    ContentRevision,
    DocumentAssociation,
    PersistenceUnavailableError,
    domain_contribution,
    revision_identity,
    validate_document_binding,
    validate_revision_owner,
)


class FNDContentWriter(Protocol):
    """The concrete FND-03 Store surface consumed by DAT.

    FND-03 owns the SQLite connection, schema, receipt/event machinery and
    transaction.  DAT supplies only payload validation and calls these
    methods; it never opens a connection or starts a second transaction.
    """

    authority: str

    def transaction(self) -> ContextManager[Any]:
        """Yield the caller-owned FND transaction."""

    def mutate(self, envelope: CommandEnvelope, **kwargs: Any) -> CommandReceipt:
        """Apply one mutation and emit its FND-owned receipt/event."""

    def put_identity(self, ref: ResourceRef, payload: Mapping[str, Any], **kwargs: Any) -> Any:
        """Store an auxiliary DAT identity in the active FND transaction."""

    def get_identity(self, ref: ResourceRef) -> Any:
        """Read one durable FND identity without a local cache."""


class ContentCommandHandler:
    """Validate DAT payloads and delegate persistence to a supplied FND writer."""

    def __init__(self, writer: Optional[FNDContentWriter] = None) -> None:
        if writer is not None and hasattr(writer, "domain_handler"):
            try:
                writer = writer.domain_handler((domain_contribution(),))
            except Exception:
                pass
        self._writer = writer

    @staticmethod
    def _envelope(operation: str, target: ResourceRef, context: TransactionContext, payload: Mapping[str, Any]) -> CommandEnvelope:
        return CommandEnvelope(operation, CONTENT_SCHEMA_REVISION, target, context, payload)

    def build_create_document(self, context: TransactionContext, document: ContentDocument, initial_revision: ContentRevision) -> CommandEnvelope:
        validate_revision_owner(document, initial_revision)
        if document.import_mode != "owned":
            raise ValueError("imported/pinned documents cannot create a local content revision")
        if not initial_revision.initial:
            raise ValueError("document creation requires an initial revision")
        return self._envelope(
            "dat.content.document.create",
            document.ref,
            context,
            {"document": document, "revision": initial_revision},
        )

    def build_append_revision(self, context: TransactionContext, document: ContentDocument, revision: ContentRevision) -> CommandEnvelope:
        validate_revision_owner(document, revision)
        if document.import_mode != "owned":
            raise ValueError("imported/pinned documents cannot append a local content revision")
        if revision.initial:
            raise ValueError("an appended revision cannot be marked initial")
        if revision.parent_revision is None:
            raise ValueError("an appended revision must name its parent revision")
        if context.expected_revision is not None and revision.parent_revision != context.expected_revision:
            raise ContentError("revision parent must match the expected current document revision")
        return self._envelope(
            "dat.content.revision.append",
            document.ref,
            context,
            {"document": document, "revision": revision},
        )

    def build_link(self, context: TransactionContext, association: DocumentAssociation) -> CommandEnvelope:
        target = ResourceRef(association.subject.authority, "document-association", association.identity)
        return self._envelope("dat.content.link", target, context, {"association": association})

    def build_unlink(self, context: TransactionContext, association: DocumentAssociation) -> CommandEnvelope:
        target = ResourceRef(association.subject.authority, "document-association", association.identity)
        return self._envelope(
            "dat.content.unlink",
            target,
            context,
            {"association": association, "preserve_document": True, "preserve_revisions": True},
        )

    def execute(self, envelope: CommandEnvelope) -> CommandReceipt:
        """Execute through the supplied FND-03 Store transaction."""
        if self._writer is None:
            raise PersistenceUnavailableError("FND-03 writer/schema/transaction is not available")
        if not isinstance(envelope, CommandEnvelope):
            raise TypeError("envelope must be a CommandEnvelope")
        operations = {
            "dat.content.document.create": self._execute_document_create,
            "dat.content.revision.append": self._execute_revision_append,
            "dat.content.link": self._execute_link,
            "dat.content.unlink": self._execute_unlink,
        }
        try:
            operation = operations[envelope.operation]
        except KeyError as exc:
            raise ContentError("unsupported DAT content operation: {}".format(envelope.operation)) from exc
        return operation(envelope)

    def read(self, reference: ResourceRef) -> Mapping[str, Any]:
        """Return a fresh read from FND-03; no local shadow is maintained."""
        if self._writer is None:
            raise PersistenceUnavailableError("FND-03 fresh-read API is not available")
        if not isinstance(reference, ResourceRef):
            raise TypeError("reference must be a ResourceRef")
        if reference.revision is not None:
            record = self._writer.get_identity(revision_identity(ResourceRef(reference.authority, reference.kind, reference.id), reference.revision))
            if record is None:
                return {}
            return {
                "identity": reference,
                "storage_identity": record.ref,
                "version": record.version,
                "document": record.payload.get("document"),
                "revision": record.payload.get("revision"),
                "content": record.payload.get("content"),
            }

        record = self._writer.get_identity(reference)
        if record is None:
            return {}
        payload = dict(record.payload)
        result: dict[str, Any] = {"identity": reference, "storage_identity": record.ref, "version": record.version, "payload": payload}
        if payload.get("record_type") == "dat.content.document":
            result["document"] = payload.get("document")
            current = payload.get("current_revision")
            result["current_revision"] = current
            if isinstance(current, Mapping):
                current_ref = ResourceRef.from_dict(current)
                revision_record = self._writer.get_identity(revision_identity(ResourceRef(current_ref.authority, current_ref.kind, current_ref.id), current_ref.revision))
                if revision_record is not None:
                    result["revision"] = revision_record.payload
        return result

    @staticmethod
    def _document_payload(document: ContentDocument, revision: ContentRevision) -> Mapping[str, Any]:
        return {
            "record_type": "dat.content.document",
            "document": document,
            "current_revision": revision.ref,
        }

    @staticmethod
    def _revision_payload(document: ContentDocument, revision: ContentRevision) -> Mapping[str, Any]:
        return {
            "record_type": "dat.content.revision",
            "document": document.ref,
            "revision": revision.revision,
            "parent_revision": revision.parent_revision,
            "content": revision.content,
            "content_digest": revision.content_digest,
            "author": revision.author,
            "initial": revision.initial,
        }

    @staticmethod
    def _association_payload(association: DocumentAssociation, *, active: bool) -> Mapping[str, Any]:
        return {
            "record_type": "dat.content.association",
            "association": association,
            "active": active,
        }

    def _mutate_with_revision(self, envelope: CommandEnvelope, document: ContentDocument, revision: ContentRevision, payload: Mapping[str, Any], *, event_type: str) -> CommandReceipt:
        assert self._writer is not None
        with self._writer.transaction() as transaction:
            # Mutate the document head first so replay/conflict is decided by
            # FND before the auxiliary immutable revision row is considered.
            receipt = self._writer.mutate(
                envelope,
                event_type=event_type,
                result_ref=revision.ref,
                after_refs=(revision.ref,),
                effects={"content_revision": revision.ref},
                transaction=transaction,
                identity_payload=payload,
            )
            self._writer.put_identity(
                revision_identity(revision.document, revision.revision),
                self._revision_payload(document, revision),
                version=0,
                transaction=transaction,
            )
            return receipt

    def _execute_document_create(self, envelope: CommandEnvelope) -> CommandReceipt:
        document = envelope.payload.get("document")
        revision = envelope.payload.get("revision")
        if not isinstance(document, ContentDocument) or not isinstance(revision, ContentRevision):
            raise ContentError("document.create requires ContentDocument and ContentRevision payloads")
        validate_revision_owner(document, revision)
        if not revision.initial:
            raise ContentError("document.create requires an initial revision")
        return self._mutate_with_revision(envelope, document, revision, self._document_payload(document, revision), event_type="dat.content.document.created")

    def _execute_revision_append(self, envelope: CommandEnvelope) -> CommandReceipt:
        document = envelope.payload.get("document")
        revision = envelope.payload.get("revision")
        if not isinstance(document, ContentDocument) or not isinstance(revision, ContentRevision):
            raise ContentError("revision.append requires ContentDocument and ContentRevision payloads")
        validate_revision_owner(document, revision)
        if revision.initial or revision.parent_revision is None:
            raise ContentError("revision.append requires a non-initial revision with a parent")
        if envelope.context.expected_revision is not None and revision.parent_revision != envelope.context.expected_revision:
            raise ContentError("revision parent must match the expected current document revision")
        return self._mutate_with_revision(envelope, document, revision, self._document_payload(document, revision), event_type="dat.content.revision.appended")

    def _execute_link(self, envelope: CommandEnvelope) -> CommandReceipt:
        association = envelope.payload.get("association")
        if not isinstance(association, DocumentAssociation):
            raise ContentError("link requires a DocumentAssociation payload")
        target = ResourceRef(association.subject.authority, "document-association", association.identity)
        if envelope.target != target:
            raise ContentError("link target does not match association identity")
        assert self._writer is not None
        with self._writer.transaction() as transaction:
            return self._writer.mutate(
                CommandEnvelope(envelope.operation, envelope.schema_revision, envelope.target, envelope.context, self._association_payload(association, active=True)),
                event_type="dat.content.linked",
                effects={"association": association.identity, "active": True},
                transaction=transaction,
            )

    def _execute_unlink(self, envelope: CommandEnvelope) -> CommandReceipt:
        association = envelope.payload.get("association")
        if not isinstance(association, DocumentAssociation):
            raise ContentError("unlink requires a DocumentAssociation payload")
        target = ResourceRef(association.subject.authority, "document-association", association.identity)
        if envelope.target != target:
            raise ContentError("unlink target does not match association identity")
        assert self._writer is not None
        with self._writer.transaction() as transaction:
            return self._writer.mutate(
                CommandEnvelope(envelope.operation, envelope.schema_revision, envelope.target, envelope.context, self._association_payload(association, active=False)),
                event_type="dat.content.unlinked",
                effects={"association": association.identity, "active": False, "preserved": ["document", "revisions", "other_links"]},
                transaction=transaction,
            )


__all__ = ["ContentCommandHandler", "FNDContentWriter"]
