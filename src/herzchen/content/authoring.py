"""DAT document authoring over the shared content and EDT ports.

This module is deliberately an adapter, not another persistence layer.  FND
remains the only durable writer; EDT remains the only reservation, capability,
snapshot, and cleanup authority.  Direct document commands and project-sheet
finish both enter :meth:`DocumentAuthoringHandler._apply_parsed`.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Union
from herzchen.command_ports import command_facade

from herzchen.authoring.sessions import (
    AuthoringSessionService,
    CleanupResult,
    FinishResult,
    InvalidSessionError,
    OpenResult,
    SessionHandle,
    Snapshot,
)
from herzchen.contracts import AuthenticatedActor, ReplayConflictError, ResourceRef, TransactionContext, canonical_json, canonical_request_digest

from .commands import ContentCommandHandler
from .model import (
    ContentDocument,
    ContentError,
    ContentRevision,
    DocumentAssociation,
    ReferenceBinding,
    association_identity,
    validate_document_binding,
)


AUTHORING_SCHEMA_REVISION = "dat-document-authoring.v1"


class DocumentAuthoringError(ContentError):
    """Base error for the document authoring adapter."""


class SchemaValidationError(DocumentAuthoringError):
    """A draft is recoverable, but cannot be admitted as document content."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(str(error) for error in errors)
        super().__init__("schema error: " + "; ".join(self.errors))


class ScopeAuthorizationError(DocumentAuthoringError):
    """The document target and supplied authoring capability disagree."""


class DraftPersistenceError(DocumentAuthoringError):
    """A final snapshot could not be freshly read before cleanup."""


@dataclass(frozen=True)
class DocumentDraft:
    """The one JSON-safe semantic draft shared by every front end."""

    content: Any
    document: Optional[ContentDocument] = None
    revision: Optional[str] = None
    links: Tuple[DocumentAssociation, ...] = ()
    summary: str = ""

    def to_dict(self) -> Mapping[str, Any]:
        value: dict[str, Any] = {
            "schema_revision": AUTHORING_SCHEMA_REVISION,
            "content": self.content,
            "summary": self.summary,
        }
        if self.document is not None:
            value["document"] = self.document
        if self.revision is not None:
            value["revision"] = self.revision
        if self.links:
            value["links"] = list(self.links)
        return value


@dataclass(frozen=True)
class DocumentMaterialisation:
    target: ResourceRef
    scope: ResourceRef
    open_result: OpenResult
    document: Optional[ContentDocument]
    current_revision: Optional[ResourceRef]

    @property
    def handle(self) -> SessionHandle:
        if self.open_result.handle is None:
            raise InvalidSessionError("document did not receive an authoring capability")
        return self.open_result.handle


@dataclass(frozen=True)
class DocumentApplyResult:
    target: ResourceRef
    scope: ResourceRef
    document: ContentDocument
    revision: ContentRevision
    receipts: Tuple[Any, ...]
    links: Tuple[DocumentAssociation, ...]
    summary: str

    @property
    def receipt(self) -> Any:
        return self.receipts[0] if self.receipts else None


@dataclass(frozen=True)
class DocumentFinishResult:
    finish: FinishResult
    applied: Optional[DocumentApplyResult] = None
    cleanup: Optional[CleanupResult] = None
    fresh_snapshot: Optional[Snapshot] = None
    schema_errors: Tuple[str, ...] = ()
    temporary_preserved: bool = False


def _target_ref(target: Union[ResourceRef, ContentDocument]) -> ResourceRef:
    if isinstance(target, ContentDocument):
        return target.ref
    if isinstance(target, ResourceRef):
        return target
    raise TypeError("target must be a ResourceRef or ContentDocument")


def _document_key(ref: ResourceRef) -> ResourceRef:
    return ResourceRef(ref.authority, ref.kind, ref.id)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    return canonical_json(value).encode("utf-8")


class _DocumentAuthoringHandlerEngine:
    """Common materialise/interpret/validate/apply document handler."""

    def __init__(
        self,
        writer: Any,
        *,
        authoring: Optional[AuthoringSessionService] = None,
        scope_resolver: Optional[Callable[..., ResourceRef]] = None,
        temporary_cleanup: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.__writer = writer
        self.reader = writer.consumer()
        self.content = ContentCommandHandler(writer)
        self.scope_resolver = scope_resolver
        self.temporary_cleanup = temporary_cleanup
        self.authoring = authoring or AuthoringSessionService(
            writer,
            scope_resolver=self._resolve_scope_for_session,
        )

    def _read_document(self, target: ResourceRef) -> Optional[ContentDocument]:
        read = self.content.read(_document_key(target))
        value = read.get("document")
        if value is None:
            return None
        if isinstance(value, ContentDocument):
            return value
        try:
            return ContentDocument.from_dict(value)
        except (TypeError, ValueError, ContentError) as exc:
            raise SchemaValidationError(("stored document schema is invalid: " + str(exc),)) from exc

    def _current_revision(self, target: ResourceRef) -> Optional[ResourceRef]:
        read = self.content.read(_document_key(target))
        value = read.get("current_revision")
        if value is None:
            return None
        return value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)

    def resolve_scope(
        self,
        target: Union[ResourceRef, ContentDocument],
        *,
        document: Optional[ContentDocument] = None,
        parent_scope: Optional[ResourceRef] = None,
    ) -> ResourceRef:
        """Resolve private linked documents to their owner, others to self."""
        target_ref = _document_key(_target_ref(target))
        document = document or (target if isinstance(target, ContentDocument) else self._read_document(target_ref))
        if self.scope_resolver is not None:
            resolved = self.scope_resolver(target_ref, document=document, parent_scope=parent_scope)
            if not isinstance(resolved, ResourceRef):
                raise ScopeAuthorizationError("scope resolver did not return a ResourceRef")
        elif target_ref.kind in {"project", "project-sheet", "pending-project"}:
            resolved = ResourceRef(target_ref.authority, "project", target_ref.id)
        elif document is not None and document.visibility == "private" and document.authoring_scope is not None:
            resolved = document.authoring_scope
        else:
            # A standalone/shared document is itself the canonical scope.  No
            # synthetic project identity is created.
            resolved = ResourceRef(target_ref.authority, "document", target_ref.id)
        if parent_scope is not None and parent_scope != resolved:
            raise ScopeAuthorizationError("supplied parent scope is not the document's canonical scope")
        return resolved

    def _resolve_scope_for_session(self, target: ResourceRef, **kwargs: Any) -> ResourceRef:
        return self.resolve_scope(target, document=kwargs.get("document"), parent_scope=kwargs.get("parent_scope"))

    def _parse_link(self, value: Any, target: Optional[ResourceRef]) -> DocumentAssociation:
        if isinstance(value, DocumentAssociation):
            return value
        if not isinstance(value, Mapping):
            raise SchemaValidationError(("links entries must be objects",))
        value = dict(value)
        if "document" not in value:
            if target is None:
                raise SchemaValidationError(("links[].document is required without a target",))
            mode = value.pop("mode", "current")
            value["document"] = ReferenceBinding(target, mode)
        elif isinstance(value["document"], Mapping):
            value["document"] = ReferenceBinding.from_dict(value["document"])
        elif not isinstance(value["document"], ReferenceBinding):
            raise SchemaValidationError(("links[].document must be a reference binding",))
        try:
            subject = value.get("subject")
            if isinstance(subject, Mapping):
                subject = ResourceRef.from_dict(subject)
            if not isinstance(subject, ResourceRef):
                raise ContentError("subject must be a ResourceRef")
            return DocumentAssociation(subject, value["namespace"], value["key"], value["document"], value.get("access_mode", "read"))
        except (TypeError, ValueError, ContentError) as exc:
            raise SchemaValidationError(("links entry: " + str(exc),)) from exc

    def interpret(
        self,
        draft: Any,
        *,
        target: Optional[Union[ResourceRef, ContentDocument]] = None,
    ) -> DocumentDraft:
        """Decode JSON only; prose is content and is never evaluated."""
        if isinstance(draft, DocumentDraft):
            return draft
        if isinstance(draft, (bytes, bytearray, str)):
            try:
                draft = json.loads(_bytes(draft).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SchemaValidationError(("draft must be UTF-8 JSON: " + str(exc),)) from exc
        if not isinstance(draft, Mapping):
            raise SchemaValidationError(("draft must be a JSON object",))
        allowed = {"schema_revision", "content", "document", "revision", "links", "summary"}
        unknown = sorted(set(draft).difference(allowed))
        if unknown:
            raise SchemaValidationError(("unknown draft fields: " + ", ".join(unknown),))
        errors: list[str] = []
        schema = draft.get("schema_revision", AUTHORING_SCHEMA_REVISION)
        if schema != AUTHORING_SCHEMA_REVISION:
            errors.append("schema_revision must be " + AUTHORING_SCHEMA_REVISION)
        if "content" not in draft:
            errors.append("content is required")
        document: Optional[ContentDocument] = None
        if draft.get("document") is not None:
            try:
                document = draft["document"] if isinstance(draft["document"], ContentDocument) else ContentDocument.from_dict(draft["document"])
            except (TypeError, ValueError, ContentError) as exc:
                errors.append("document: " + str(exc))
        revision = draft.get("revision")
        if revision is not None and (not isinstance(revision, str) or not revision.strip()):
            errors.append("revision must be a non-blank string")
        links: list[DocumentAssociation] = []
        links_value = draft.get("links", ())
        if links_value is not None:
            if not isinstance(links_value, (list, tuple)):
                errors.append("links must be an array")
            else:
                for item in links_value:
                    try:
                        link_target = document.ref if document is not None else (_target_ref(target) if target is not None else None)
                        links.append(self._parse_link(item, link_target))
                    except SchemaValidationError as exc:
                        errors.extend(exc.errors)
        summary = draft.get("summary", "")
        if summary and (not isinstance(summary, str) or not summary.strip()):
            errors.append("summary must be a non-blank string when supplied")
        if errors:
            raise SchemaValidationError(errors)
        summary = summary or self._summary(document, draft["content"])
        return DocumentDraft(draft["content"], document, revision, tuple(links), summary)

    @staticmethod
    def _summary(document: Optional[ContentDocument], content: Any) -> str:
        name = document.ref.id if document is not None else "document"
        if isinstance(content, Mapping):
            keys = sorted(str(key) for key in content)
            fields = ", ".join(keys[:6]) if keys else "no fields"
            return "{}: {}".format(name, fields)
        return "{}: JSON content".format(name)

    def validate(
        self,
        draft: Union[DocumentDraft, Mapping[str, Any], bytes, str],
        *,
        target: Optional[Union[ResourceRef, ContentDocument]] = None,
        document: Optional[ContentDocument] = None,
    ) -> DocumentDraft:
        parsed = self.interpret(draft, target=target)
        target_ref = _target_ref(target) if target is not None else None
        document = document or parsed.document or (self._read_document(target_ref) if target_ref is not None else None)
        errors: list[str] = []
        if document is None:
            errors.append("document is required for a new document")
        elif target_ref is not None and (document.ref.authority, document.ref.kind, document.ref.id) != (target_ref.authority, target_ref.kind, target_ref.id) and target_ref.kind not in {"project", "project-sheet", "pending-project"}:
            errors.append("document identity does not match target")
        try:
            canonical_json(parsed.content)
        except (TypeError, ValueError, ContentError) as exc:
            errors.append("content: " + str(exc))
        if document is not None:
            for link in parsed.links:
                try:
                    validate_document_binding(document, link.document)
                except ContentError as exc:
                    errors.append("links: " + str(exc))
        if errors:
            raise SchemaValidationError(errors)
        summary = parsed.summary
        if parsed.document is None and summary == self._summary(None, parsed.content):
            summary = self._summary(document, parsed.content)
        if parsed.document is document and summary == parsed.summary:
            return parsed
        return DocumentDraft(parsed.content, document, parsed.revision, parsed.links, summary)

    def materialise(
        self,
        target: Union[ResourceRef, ContentDocument],
        actor: AuthenticatedActor,
        *,
        request_id: str,
        parent_scope: Optional[ResourceRef] = None,
        initial_content: Any = None,
        base_revision: Optional[str] = None,
        allowed_fields: Sequence[str] = (),
        materialize: Optional[Callable[..., Any]] = None,
    ) -> DocumentMaterialisation:
        target_ref = _document_key(_target_ref(target))
        document = target if isinstance(target, ContentDocument) else self._read_document(target_ref)
        if document is not None and (
            not document.writable
            or document.import_mode != "owned"
            or document.access_mode not in {"write", "append"}
        ):
            raise ScopeAuthorizationError("read-only external attachments cannot be authored")
        scope = self.resolve_scope(target_ref, document=document, parent_scope=parent_scope)
        current = self._current_revision(target_ref) if document is not None else None
        if initial_content is None and current is not None:
            initial_content = self.content.read(current).get("content", {})
        if initial_content is None:
            initial_content = {}
        opened = self.authoring.open(
            target_ref,
            actor,
            request_id=request_id,
            target_kind="document" if target_ref.kind not in {"project", "project-sheet", "pending-project"} else "project-sheet",
            base_revision=base_revision or (current.revision if current is not None else "initial"),
            allowed_fields=tuple(allowed_fields),
            initial_content=_bytes(initial_content),
            parent_scope=scope,
            materialize=materialize,
        )
        return DocumentMaterialisation(target_ref, scope, opened, document, current)

    materialize = materialise

    def lifecycle_handler(self, materialisation: DocumentMaterialisation, *, request_id: str) -> Any:
        """Return the DAT semantic hooks for the shared EDT finish boundary."""
        from herzchen.authoring import CallableSemanticHandler, ValidationResult

        target = materialisation.target
        handle = materialisation.handle
        document = materialisation.document

        def raw(snapshot: Any) -> bytes:
            try:
                return snapshot.file_bytes("document.json")
            except (AttributeError, KeyError):
                return snapshot.data

        def validate(snapshot: Any, checkout: Any, checkout_root: str) -> Any:
            try:
                self.validate(raw(snapshot), target=target, document=document)
            except SchemaValidationError as exc:
                return ValidationResult(False, exc.errors)
            return ValidationResult(True)

        def apply(snapshot: Any, checkout: Any, tx: Any, writer: Any) -> Any:
            return self.apply(
                target, raw(snapshot), actor=checkout.actor, request_id=request_id,
                handle=handle, expected_base_revision=checkout.base_revision,
            )

        return CallableSemanticHandler(validate, apply)

    def read(self, target: Union[ResourceRef, ContentDocument], actor: Optional[AuthenticatedActor] = None) -> Mapping[str, Any]:
        target_ref = _target_ref(target)
        association: Optional[Mapping[str, Any]] = None
        if target_ref.kind == "document-association":
            association_read = self.content.read(target_ref)
            association = association_read.get("payload")
            binding = association.get("association", {}).get("document") if isinstance(association, Mapping) else None
            if isinstance(binding, Mapping):
                target_ref = ResourceRef.from_dict(binding["ref"])
        content_read = self.content.read(target_ref)
        document = self._read_document(target_ref)
        scope = self.resolve_scope(target_ref, document=document)
        authoring_read = self.authoring.read(target_ref, actor)
        return {
            "target": target_ref,
            "scope": scope,
            "document": document,
            "content": content_read,
            "authoring": authoring_read,
            "association": association,
            "summary": self._summary(document, content_read.get("revision", {}).get("content", {}) if isinstance(content_read.get("revision"), Mapping) else {}),
        }

    def _authorize(self, target: ResourceRef, actor: AuthenticatedActor, handle: SessionHandle, *, token: Optional[str], fence: Optional[str], base_revision: Optional[str], document: Optional[ContentDocument]) -> ResourceRef:
        scope = self.resolve_scope(target, document=document)
        if handle.target_scope != scope or handle.actor != actor:
            raise ScopeAuthorizationError("authoring capability is not for this target and actor")
        capability_target = target
        if target != handle.target_scope and target.kind not in {"task", "document", "project-task", "project-document"}:
            # EDT's generic child gate intentionally knows only its neutral
            # child kinds.  The DAT content kind remains the persistence
            # target; this proxy is used solely for the accepted capability
            # check and cannot authorize a different resolved scope.
            capability_target = ResourceRef(target.authority, "document", target.id, target.revision)
        self.authoring.authorize_mutation(
            handle,
            capability_target,
            token=token or handle.token,
            fence=fence or handle.fence,
            expected_base_revision=base_revision or handle.base_revision,
        )
        return scope

    def _context(
        self,
        actor: AuthenticatedActor,
        request_id: str,
        values: Any,
        *,
        expected_revision: Optional[str],
        expected_version: Optional[int] = None,
        operation: str,
        target: ResourceRef,
        payload: Mapping[str, Any],
    ) -> TransactionContext:
        context = TransactionContext(
            actor,
            request_id,
            "0" * 64,
            expected_revision=expected_revision,
            expected_version=expected_version,
        )
        digest = canonical_request_digest(
            logical_request_key=request_id,
            operation=operation,
            schema_revision="dat-content.v1",
            target=target,
            actor=actor,
            payload=payload,
            context=context,
        )
        return TransactionContext(
            actor,
            request_id,
            digest,
            expected_revision=expected_revision,
            expected_version=expected_version,
        )

    def _apply_parsed(
        self,
        target: ResourceRef,
        parsed: DocumentDraft,
        *,
        actor: AuthenticatedActor,
        request_id: str,
        handle: Optional[SessionHandle],
        token: Optional[str] = None,
        fence: Optional[str] = None,
        expected_base_revision: Optional[str] = None,
        transaction: Any = None,
    ) -> DocumentApplyResult:
        existing = self._read_document(target)
        document = existing or parsed.document
        if document is None:
            raise SchemaValidationError(("document is required for a new document",))
        if handle is None:
            raise InvalidSessionError("document mutation requires the active authoring capability")
        scope = self._authorize(target, actor, handle, token=token, fence=fence, base_revision=expected_base_revision, document=document)
        current = self.content.read(document.ref)
        current_revision = current.get("current_revision")
        current_revision_ref = current_revision if isinstance(current_revision, ResourceRef) else (ResourceRef.from_dict(current_revision) if current_revision else None)
        current_version = current.get("version")
        revision_name = parsed.revision or ("rev-" + _digest(parsed.content)[:24])
        all_links = tuple(parsed.links)
        for link in all_links:
            validate_document_binding(document, link.document)
        values = {"target": target, "content": parsed.content, "revision": revision_name, "links": all_links, "scope": scope}
        replay_revision = ContentRevision(
            document.ref, revision_name, parsed.content, actor,
            parent_revision=handle.base_revision if current_revision_ref is not None else None,
            initial=current_revision_ref is None,
        )
        replay_operation = "dat.content.document.create" if current_revision_ref is None else "dat.content.revision.append"
        document_payload = {"document": document, "revision": replay_revision}
        context = self._context(
            actor,
            request_id + ":document",
            values,
            expected_revision=(handle.base_revision if current_revision_ref is not None and handle is not None else None),
            expected_version=None,
            operation=replay_operation,
            target=document.ref,
            payload=document_payload,
        )
        request_digest = context.request_digest
        prior = self.__writer.get_receipt(request_id + ":document")
        if prior is not None:
            if prior.request_digest != request_digest:
                raise ReplayConflictError("logical request key was reused with a changed request digest")
            link_receipts = tuple(self.__writer.get_receipt(request_id + ":link:" + str(index)) for index in range(len(all_links)))
            if all(receipt is not None for receipt in link_receipts):
                stored = self.content.read(prior.result_ref) if prior.result_ref is not None else {}
                payload = stored
                replay_revision = ContentRevision(
                    document.ref,
                    prior.result_ref.revision if prior.result_ref is not None else revision_name,
                    payload.get("content", parsed.content),
                    AuthenticatedActor.from_dict(payload["author"]) if isinstance(payload.get("author"), Mapping) else actor,
                    parent_revision=payload.get("parent_revision"),
                    initial=bool(payload.get("initial", False)),
                )
                return DocumentApplyResult(target, scope, document, replay_revision, (prior,) + tuple(link_receipts), all_links, parsed.summary)
        current = self.content.read(document.ref)
        current_revision = current.get("current_revision")
        current_revision_ref = current_revision if isinstance(current_revision, ResourceRef) else (ResourceRef.from_dict(current_revision) if current_revision else None)
        current_version = current.get("version")
        revision = ContentRevision(document.ref, revision_name, parsed.content, actor, parent_revision=current_revision_ref.revision if current_revision_ref else None, initial=current_revision_ref is None)
        receipts: list[Any] = []

        def run(tx: Any) -> None:
            envelope = self.content.build_create_document(context, document, revision) if current_revision_ref is None else self.content.build_append_revision(context, document, revision)
            receipts.append(self.content.execute(envelope))
            for index, link in enumerate(all_links):
                link_target = ResourceRef(link.subject.authority, "document-association", link.identity)
                link_context = self._context(
                    actor,
                    request_id + ":link:" + str(index),
                    values,
                    expected_revision=None,
                    expected_version=None,
                    operation="dat.content.link",
                    target=link_target,
                    payload={"association": link},
                )
                receipts.append(self.content.execute(self.content.build_link(link_context, link)))

        if transaction is None:
            with self.__writer.transaction() as tx:
                run(tx)
        else:
            run(transaction)
        return DocumentApplyResult(target, scope, document, revision, tuple(receipts), all_links, parsed.summary)

    def apply(
        self,
        target: Union[ResourceRef, ContentDocument, DocumentMaterialisation],
        draft: Any,
        *,
        actor: Optional[AuthenticatedActor] = None,
        request_id: str,
        handle: Optional[SessionHandle] = None,
        token: Optional[str] = None,
        fence: Optional[str] = None,
        expected_base_revision: Optional[str] = None,
    ) -> DocumentApplyResult:
        if isinstance(target, DocumentMaterialisation):
            materialisation = target
            target_ref = materialisation.target
            handle = handle or materialisation.handle
            actor = actor or handle.actor
        else:
            target_ref = _target_ref(target)
        if actor is None:
            raise InvalidSessionError("actor is required for document mutation")
        parsed = self.validate(draft, target=target_ref)
        return self._apply_parsed(target_ref, parsed, actor=actor, request_id=request_id, handle=handle, token=token, fence=fence, expected_base_revision=expected_base_revision)

    def apply_project_sheet(self, project: ResourceRef, draft: Any, **kwargs: Any) -> DocumentApplyResult:
        """Project-sheet entry point; it intentionally shares ``apply``."""
        return self.apply(project, draft, **kwargs)

    def finish(
        self,
        materialisation: DocumentMaterialisation,
        *,
        request_id: str,
        mode: str = "manual",
        draft: Any = None,
        path: Optional[Union[str, Path]] = None,
        cleanup: Optional[Callable[..., Any]] = None,
        pending: Optional[bool] = None,
    ) -> DocumentFinishResult:
        if path is not None:
            raw = Path(path).read_bytes()
        elif draft is not None:
            raw = _bytes(draft)
        else:
            raise SchemaValidationError(("finish requires draft or path",))
        parsed_box: dict[str, DocumentDraft] = {}
        result_box: dict[str, DocumentApplyResult] = {}

        def apply(snapshot: Snapshot, checkout: Any, *, tx: Any = None, **_: Any) -> None:
            parsed = self.validate(snapshot.data, target=materialisation.target, document=materialisation.document)
            parsed_box["draft"] = parsed
            result_box["result"] = self._apply_parsed(
                materialisation.target,
                parsed,
                actor=checkout.actor,
                request_id=request_id,
                handle=materialisation.handle,
                expected_base_revision=checkout.base_revision,
                transaction=tx,
            )

        finished = self.authoring.finish(
            materialisation.handle,
            request_id=request_id,
            mode=mode,
            capture=raw,
            apply=apply,
            pending=pending,
        )
        if not result_box:
            errors = ()
            if isinstance(finished.error, str) and finished.error.startswith("schema error:"):
                errors = tuple(item.strip() for item in finished.error[len("schema error:"):].split(";"))
            return DocumentFinishResult(finished, schema_errors=errors, temporary_preserved=path is not None)
        if finished.final_snapshot is None:
            return DocumentFinishResult(finished, result_box.get("result"), temporary_preserved=path is not None)
        try:
            # A fresh FND read is the barrier before any host cleanup.
            persisted = Snapshot(finished.final_snapshot.ref, self.authoring.read_snapshot(finished.final_snapshot.ref), finished.final_snapshot.manifest)
        except BaseException as exc:
            return DocumentFinishResult(
                FinishResult(finished.status, finished.scope, finished.session_id, finished.receipt, finished.checkout, finished.final_snapshot, True, finished.cleanup, str(exc)),
                result_box.get("result"),
                fresh_snapshot=None,
                temporary_preserved=path is not None,
            )
        cleaner = cleanup or self.temporary_cleanup
        if path is None or cleaner is None:
            return DocumentFinishResult(finished, result_box.get("result"), fresh_snapshot=persisted, temporary_preserved=path is not None)
        try:
            cleaner(path, snapshot=persisted)
        except BaseException as exc:
            return DocumentFinishResult(FinishResult(finished.status, finished.scope, finished.session_id, finished.receipt, finished.checkout, persisted, True, finished.cleanup, str(exc)), result_box.get("result"), fresh_snapshot=persisted, temporary_preserved=True)
        cleanup_result = self.authoring.cleanup(materialisation.handle, request_id=request_id + ":cleanup")
        return DocumentFinishResult(finished, result_box.get("result"), cleanup_result, persisted, temporary_preserved=False)

    def unlink(self, association: DocumentAssociation, actor: AuthenticatedActor, *, request_id: str, handle: SessionHandle, token: Optional[str] = None, fence: Optional[str] = None, expected_base_revision: Optional[str] = None) -> Any:
        document = self._read_document(association.document.ref)
        self._authorize(association.document.ref, actor, handle, token=token, fence=fence, base_revision=expected_base_revision, document=document)
        association_ref = ResourceRef(association.subject.authority, "document-association", association.identity)
        association_read = self.content.read(association_ref)
        association_target = ResourceRef(association.subject.authority, "document-association", association.identity)
        context = self._context(
            actor,
            request_id,
            association,
            expected_revision=None,
            expected_version=None,
            operation="dat.content.unlink",
            target=association_target,
            payload={"association": association, "preserve_document": True, "preserve_revisions": True},
        )
        with self.__writer.transaction():
            return self.content.execute(self.content.build_unlink(context, association))


DocumentAuthoringHandler = command_facade(_DocumentAuthoringHandlerEngine, "dat.content.authoring")
DocumentAuthoring = DocumentAuthoringHandler
SchemaError = SchemaValidationError


__all__ = [
    "AUTHORING_SCHEMA_REVISION", "DocumentDraft", "DocumentMaterialisation", "DocumentApplyResult", "DocumentFinishResult",
    "DocumentAuthoringError", "SchemaValidationError", "SchemaError", "ScopeAuthorizationError", "DraftPersistenceError",
    "DocumentAuthoringHandler", "DocumentAuthoring",
]
