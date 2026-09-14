"""Versioned, product-neutral FND-02 contract records.

The module intentionally has no imports from an application, product, runtime,
database, model, scheduler, or role-specific package.  Records are immutable
at the API boundary and serialize to deterministic JSON-compatible values.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, ClassVar, Iterable, Mapping, Optional, Sequence, Tuple


CONTRACT_REVISION = "fnd-02.v1.1"
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_PATHISH = re.compile(r"(^/|^\\|^[A-Za-z]:[\\/]|[\\/]|^[A-Za-z][A-Za-z0-9+.-]*://)")
_ID = re.compile(r"^[^\x00\s]+$")


class ContractError(ValueError):
    """Raised when a contract value violates a declared invariant."""


class ReplayConflictError(ContractError):
    """The same logical request key was presented with a different digest."""


class UnsupportedOperationError(ContractError):
    """An optional host operation is not supported by the selected adapter."""


def canonical_json(value: Any) -> str:
    """Return the one JSON representation used for hashes and fixtures."""
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_request_digest(
    *,
    logical_request_key: str,
    operation: str,
    schema_revision: str,
    target: "ResourceRef",
    actor: "AuthenticatedActor",
    payload: Mapping[str, Any],
    context: Optional["TransactionContext"] = None,
    expected_revision: Optional[str] = None,
    expected_version: Optional[int] = None,
    edit_token: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> str:
    """Hash the complete admitted command semantics used for replay identity.

    The preferred call-site contract passes the immutable ``TransactionContext``
    as ``context``.  That single input carries the logical request key, actor,
    and all five request-context inputs: expected revision, expected version,
    edit token, correlation id, and causation id.  The scalar keyword form is
    retained for compatibility with existing adopters and must pass the same
    five names explicitly.  ``request_digest`` is intentionally absent from
    this material: a caller-supplied digest is only a compatibility input to
    the surrounding envelope and can never select replay identity.

    Only the supplied request context is hashed.  The helper does not inspect
    or derive current identity, version, or revision state from a store.
    """
    if context is not None:
        if not isinstance(context, TransactionContext):
            raise ContractError("context must be a TransactionContext")
        if logical_request_key != context.logical_request_key:
            raise ContractError("logical_request_key does not match context")
        if actor != context.actor:
            raise ContractError("actor does not match context")
        expected_revision = context.expected_revision
        expected_version = context.expected_version
        edit_token = context.edit_token
        correlation_id = context.correlation_id
        causation_id = context.causation_id
    if not isinstance(target, ResourceRef):
        raise ContractError("target must be a ResourceRef")
    if not isinstance(actor, AuthenticatedActor):
        raise ContractError("actor must be AuthenticatedActor")
    if not isinstance(payload, Mapping):
        raise ContractError("payload must be a mapping")
    _text(logical_request_key, "logical_request_key")
    _text(operation, "operation")
    _revision(schema_revision, "schema_revision")
    material = {
        "logical_request_key": logical_request_key,
        "operation": operation,
        "schema_revision": schema_revision,
        "target": target.to_dict(),
        "actor": actor.to_dict(),
        "transaction_context": {
            "expected_revision": expected_revision,
            "expected_version": expected_version,
            "edit_token": edit_token,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
        },
        "payload": dict(payload),
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ContractError(f"value is not JSON-safe: {type(value).__name__}")


def _text(value: Any, field: str, *, path: bool = True) -> str:
    if not isinstance(value, str) or not value or not value.strip():
        raise ContractError(f"{field} must be a non-blank string")
    if "\x00" in value:
        raise ContractError(f"{field} contains malformed control characters")
    if path and _PATHISH.search(value):
        raise ContractError(f"{field} must be an opaque identifier, not a filesystem/URI path")
    return value


def _identifier(value: Any, field: str) -> str:
    value = _text(value, field)
    if not _ID.match(value):
        raise ContractError(f"{field} must be an opaque non-whitespace identifier")
    return value


def _revision(value: Any, field: str = "revision") -> str:
    return _text(value, field, path=True)


def _optional_revision(value: Any, field: str = "revision") -> Optional[str]:
    return None if value is None else _revision(value, field)


def _digest(value: Any, field: str = "digest") -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ContractError(f"{field} must be a 64-character hexadecimal digest")
    return value.lower()


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be a JSON object")
    return dict(value)


def _tuple_text(value: Any, field: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{field} must be an array")
    result = tuple(_text(item, f"{field}[]") for item in value)
    if len(set(result)) != len(result):
        raise ContractError(f"{field} contains duplicate identities")
    return result


def _keys(value: Mapping[str, Any], allowed: Iterable[str], *, closed: bool = True) -> None:
    if closed:
        unknown = set(value).difference(allowed)
        if unknown:
            raise ContractError(f"unknown reserved fields: {', '.join(sorted(unknown))}")


class ContractRecord:
    """Common deterministic serialization helpers for exported records."""

    contract_revision: ClassVar[str] = CONTRACT_REVISION

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)

    as_dict = to_dict

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True)
class ResourceRef(ContractRecord):
    authority: str
    kind: str
    id: str
    revision: Optional[str] = None

    def __post_init__(self) -> None:
        _identifier(self.authority, "authority")
        _identifier(self.kind, "kind")
        _identifier(self.id, "id")
        _optional_revision(self.revision)

    @property
    def is_pinned(self) -> bool:
        return self.revision is not None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResourceRef":
        value = _mapping(value, "resource_ref")
        _keys(value, {"authority", "kind", "id", "revision"})
        return cls(value["authority"], value["kind"], value["id"], value.get("revision"))


@dataclass(frozen=True)
class DocumentRef(ContractRecord):
    authority: str
    kind: str
    id: str
    revision: Optional[str] = None
    role: Optional[str] = None

    def __post_init__(self) -> None:
        _identifier(self.authority, "authority")
        _identifier(self.kind, "kind")
        _identifier(self.id, "id")
        _optional_revision(self.revision)
        if self.role is not None:
            _text(self.role, "role")

    @property
    def is_pinned(self) -> bool:
        return self.revision is not None

    def as_resource(self) -> ResourceRef:
        return ResourceRef(self.authority, self.kind, self.id, self.revision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentRef":
        value = _mapping(value, "document_ref")
        _keys(value, {"authority", "kind", "id", "revision", "role"})
        return cls(value["authority"], value["kind"], value["id"], value.get("revision"), value.get("role"))


@dataclass(frozen=True)
class RevisionRef(ContractRecord):
    resource: ResourceRef
    revision: str
    semantics: str = "document"

    def __post_init__(self) -> None:
        if not isinstance(self.resource, ResourceRef):
            raise ContractError("resource must be a ResourceRef")
        _revision(self.revision)
        _text(self.semantics, "semantics")

    def __post_init_post_parse__(self) -> None:
        pass

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RevisionRef":
        value = _mapping(value, "revision_ref")
        _keys(value, {"resource", "revision", "semantics"})
        return cls(ResourceRef.from_dict(value["resource"]), value["revision"], value.get("semantics", "document"))


@dataclass(frozen=True)
class ReferenceBinding(ContractRecord):
    ref: ResourceRef
    mode: str = "current"

    def __post_init__(self) -> None:
        if not isinstance(self.ref, ResourceRef):
            raise ContractError("ref must be a ResourceRef")
        if self.mode not in {"current", "pinned"}:
            raise ContractError("mode must be current or pinned")
        if self.mode == "pinned" and self.ref.revision is None:
            raise ContractError("pinned references require an explicit revision")
        if self.mode == "current" and self.ref.revision is not None:
            raise ContractError("current references cannot carry a revision")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReferenceBinding":
        value = _mapping(value, "reference_binding")
        _keys(value, {"ref", "mode"})
        return cls(ResourceRef.from_dict(value["ref"]), value.get("mode", "current"))


@dataclass(frozen=True)
class OperationBinding(ContractRecord):
    operation: str
    schema_revision: str

    def __post_init__(self) -> None:
        _text(self.operation, "operation")
        _revision(self.schema_revision, "schema_revision")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationBinding":
        value = _mapping(value, "operation_binding")
        _keys(value, {"operation", "schema_revision"})
        return cls(value["operation"], value["schema_revision"])


@dataclass(frozen=True)
class ExtensionDescriptor(ContractRecord):
    namespace: str
    schema_revision: str
    resource_kinds: Tuple[str, ...]
    description: str
    owner: str
    profile_bindings: Tuple[str, ...] = ()
    operation_bindings: Tuple[OperationBinding, ...] = ()
    annotations: Mapping[str, Any] = None  # type: ignore[assignment]
    managed: bool = False

    def __post_init__(self) -> None:
        _text(self.namespace, "namespace")
        _revision(self.schema_revision, "schema_revision")
        _tuple_text(self.resource_kinds, "resource_kinds")
        _text(self.description, "description")
        _text(self.owner, "owner")
        _tuple_text(self.profile_bindings, "profile_bindings")
        if any(not isinstance(item, OperationBinding) for item in self.operation_bindings):
            raise ContractError("operation_bindings must contain OperationBinding values")
        object.__setattr__(self, "annotations", dict(self.annotations or {}))
        _json_value(self.annotations)
        if self.managed and (not self.owner or not self.operation_bindings):
            raise ContractError("managed namespaces require an explicit owner and operation binding")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExtensionDescriptor":
        value = _mapping(value, "extension_descriptor")
        _keys(value, {"namespace", "schema_revision", "resource_kinds", "description", "owner", "profile_bindings", "operation_bindings", "annotations", "managed"})
        return cls(
            value["namespace"], value["schema_revision"], _tuple_text(value["resource_kinds"], "resource_kinds"),
            value["description"], value["owner"], _tuple_text(value.get("profile_bindings", []), "profile_bindings"),
            tuple(OperationBinding.from_dict(item) for item in value.get("operation_bindings", [])),
            _mapping(value.get("annotations", {}), "annotations"), bool(value.get("managed", False)),
        )


class ExtensionRegistry:
    """Collision-checking registry; registration is explicit, never inferred."""

    def __init__(self) -> None:
        self._namespaces: dict[str, ExtensionDescriptor] = {}
        self._operations: dict[str, str] = {}
        self._types: dict[str, str] = {}

    def register(self, descriptor: ExtensionDescriptor) -> None:
        if descriptor.namespace in self._namespaces:
            raise ContractError(f"duplicate namespace identity: {descriptor.namespace}")
        for binding in descriptor.operation_bindings:
            if binding.operation in self._operations:
                raise ContractError(f"duplicate operation identity: {binding.operation}")
        for resource_kind in descriptor.resource_kinds:
            if resource_kind in self._types:
                raise ContractError(f"duplicate type identity: {resource_kind}")
        self._namespaces[descriptor.namespace] = descriptor
        for binding in descriptor.operation_bindings:
            self._operations[binding.operation] = descriptor.namespace
        for resource_kind in descriptor.resource_kinds:
            self._types[resource_kind] = descriptor.namespace

    def descriptors(self) -> Tuple[ExtensionDescriptor, ...]:
        return tuple(self._namespaces[key] for key in sorted(self._namespaces))


@dataclass(frozen=True)
class AuthenticatedActor(ContractRecord):
    authority: str
    actor: str
    credential_ref: str
    authenticated: bool = True

    def __post_init__(self) -> None:
        _text(self.authority, "authority")
        _text(self.actor, "actor")
        _text(self.credential_ref, "credential_ref")
        if not self.authenticated:
            raise ContractError("command actors must be authenticated")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthenticatedActor":
        value = _mapping(value, "actor")
        _keys(value, {"authority", "actor", "credential_ref", "authenticated"})
        return cls(value["authority"], value["actor"], value["credential_ref"], bool(value.get("authenticated", True)))


@dataclass(frozen=True)
class TransactionContext(ContractRecord):
    actor: AuthenticatedActor
    logical_request_key: str
    request_digest: str
    expected_revision: Optional[str] = None
    expected_version: Optional[int] = None
    edit_token: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor, AuthenticatedActor):
            raise ContractError("actor must be AuthenticatedActor")
        _text(self.logical_request_key, "logical_request_key")
        _digest(self.request_digest, "request_digest")
        _optional_revision(self.expected_revision, "expected_revision")
        if self.expected_version is not None and (not isinstance(self.expected_version, int) or self.expected_version < 0):
            raise ContractError("expected_version must be a non-negative integer")
        if self.edit_token is not None:
            _text(self.edit_token, "edit_token")
        for field, value in (("correlation_id", self.correlation_id), ("causation_id", self.causation_id)):
            if value is not None:
                _text(value, field)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransactionContext":
        value = _mapping(value, "transaction_context")
        _keys(value, {"actor", "logical_request_key", "request_digest", "expected_revision", "expected_version", "edit_token", "correlation_id", "causation_id"})
        return cls(AuthenticatedActor.from_dict(value["actor"]), value["logical_request_key"], value["request_digest"], value.get("expected_revision"), value.get("expected_version"), value.get("edit_token"), value.get("correlation_id"), value.get("causation_id"))


@dataclass(frozen=True)
class CommandEnvelope(ContractRecord):
    operation: str
    schema_revision: str
    target: ResourceRef
    context: TransactionContext
    payload: Mapping[str, Any]
    envelope_revision: str = CONTRACT_REVISION

    _RESERVED: ClassVar[frozenset[str]] = frozenset({"operation", "schema_revision", "target", "context", "payload", "envelope_revision"})

    def __post_init__(self) -> None:
        _text(self.operation, "operation")
        _revision(self.schema_revision, "schema_revision")
        if not isinstance(self.target, ResourceRef):
            raise ContractError("target must be a ResourceRef")
        if not isinstance(self.context, TransactionContext):
            raise ContractError("context must be TransactionContext")
        object.__setattr__(self, "payload", dict(_mapping(self.payload, "payload")))
        _json_value(self.payload)
        if self.envelope_revision != CONTRACT_REVISION:
            raise ContractError(f"unsupported envelope revision: {self.envelope_revision}")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CommandEnvelope":
        value = _mapping(value, "command_envelope")
        _keys(value, cls._RESERVED)
        return cls(value["operation"], value["schema_revision"], ResourceRef.from_dict(value["target"]), TransactionContext.from_dict(value["context"]), value["payload"], value.get("envelope_revision", CONTRACT_REVISION))


class ReceiptStatus(str, Enum):
    COMMITTED = "committed"
    NOOP = "no-op"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandReceipt(ContractRecord):
    logical_request_key: str
    request_digest: str
    operation: str
    target: ResourceRef
    status: ReceiptStatus
    transaction_id: Optional[str] = None
    event_ids: Tuple[str, ...] = ()
    result_ref: Optional[ResourceRef] = None
    error_code: Optional[str] = None
    replayed: bool = False
    observed_revision: Optional[str] = None
    unknown_reason: Optional[str] = None

    def __post_init__(self) -> None:
        _text(self.logical_request_key, "logical_request_key")
        _digest(self.request_digest, "request_digest")
        _text(self.operation, "operation")
        if not isinstance(self.target, ResourceRef):
            raise ContractError("target must be ResourceRef")
        if not isinstance(self.status, ReceiptStatus):
            object.__setattr__(self, "status", ReceiptStatus(self.status))
        _tuple_text(self.event_ids, "event_ids")
        if self.transaction_id is not None:
            _text(self.transaction_id, "transaction_id")
        if self.result_ref is not None and not isinstance(self.result_ref, ResourceRef):
            raise ContractError("result_ref must be ResourceRef")
        if self.error_code is not None:
            _text(self.error_code, "error_code")
        if self.observed_revision is not None:
            _revision(self.observed_revision, "observed_revision")
        if self.unknown_reason is not None:
            _text(self.unknown_reason, "unknown_reason")
        if self.status == ReceiptStatus.COMMITTED and self.transaction_id is None:
            raise ContractError("committed receipts require transaction_id")
        if self.status == ReceiptStatus.FAILED and not self.error_code:
            raise ContractError("failed receipts require error_code")
        if self.status == ReceiptStatus.UNKNOWN and not self.unknown_reason:
            raise ContractError("unknown receipts require unknown_reason")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CommandReceipt":
        value = _mapping(value, "command_receipt")
        _keys(value, {"logical_request_key", "request_digest", "operation", "target", "status", "transaction_id", "event_ids", "result_ref", "error_code", "replayed", "observed_revision", "unknown_reason"})
        return cls(value["logical_request_key"], value["request_digest"], value["operation"], ResourceRef.from_dict(value["target"]), ReceiptStatus(value["status"]), value.get("transaction_id"), _tuple_text(value.get("event_ids", []), "event_ids"), ResourceRef.from_dict(value["result_ref"]) if value.get("result_ref") else None, value.get("error_code"), bool(value.get("replayed", False)), value.get("observed_revision"), value.get("unknown_reason"))


def validate_replay(existing: CommandReceipt, incoming: CommandEnvelope) -> None:
    """Validate exact-key replay without treating a digest as permission."""
    if existing.logical_request_key != incoming.context.logical_request_key:
        raise ContractError("replay key does not match")
    if existing.request_digest != incoming.context.request_digest:
        raise ReplayConflictError("logical request key was reused with a changed request digest")


def validate_expected_state(context: TransactionContext, *, current_revision: Optional[str] = None, current_version: Optional[int] = None, supplied_edit_token: Optional[str] = None) -> None:
    if context.expected_revision is not None and context.expected_revision != current_revision:
        raise ContractError("expected revision does not match current revision")
    if context.expected_version is not None and context.expected_version != current_version:
        raise ContractError("expected version does not match current version")
    if context.edit_token is not None and context.edit_token != supplied_edit_token:
        raise ContractError("edit token does not match")


class CursorState(str, Enum):
    NORMAL = "normal"
    DUPLICATE = "duplicate"
    REORDERED = "reordered"
    GAP = "gap"
    EXPIRED = "expired"


@dataclass(frozen=True)
class EventCursor(ContractRecord):
    authority: str
    stream: str
    sequence: int = 0
    event_id: Optional[str] = None
    state: CursorState = CursorState.NORMAL

    def __post_init__(self) -> None:
        _text(self.authority, "authority")
        _text(self.stream, "stream")
        if not isinstance(self.sequence, int) or self.sequence < 0:
            raise ContractError("sequence must be a non-negative integer")
        if self.event_id is not None:
            _text(self.event_id, "event_id")
        if not isinstance(self.state, CursorState):
            object.__setattr__(self, "state", CursorState(self.state))

    def observe(self, event: "EventEnvelope") -> "EventCursor":
        if event.store_authority != self.authority or event.stream != self.stream:
            raise ContractError("event is outside cursor authority/stream scope")
        if self.state == CursorState.EXPIRED:
            return EventCursor(self.authority, self.stream, self.sequence, self.event_id, CursorState.EXPIRED)
        if event.sequence == self.sequence and event.event_id == self.event_id:
            return EventCursor(self.authority, self.stream, self.sequence, self.event_id, CursorState.DUPLICATE)
        if event.sequence <= self.sequence:
            return EventCursor(self.authority, self.stream, self.sequence, self.event_id, CursorState.REORDERED)
        if event.sequence > self.sequence + 1 and self.sequence != 0:
            return EventCursor(self.authority, self.stream, event.sequence, event.event_id, CursorState.GAP)
        return EventCursor(self.authority, self.stream, event.sequence, event.event_id, CursorState.NORMAL)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EventCursor":
        value = _mapping(value, "event_cursor")
        _keys(value, {"authority", "stream", "sequence", "event_id", "state"})
        return cls(value["authority"], value["stream"], value.get("sequence", 0), value.get("event_id"), CursorState(value.get("state", "normal")))


@dataclass(frozen=True)
class EventEnvelope(ContractRecord):
    event_id: str
    store_authority: str
    stream: str
    subject: ResourceRef
    schema_revision: str
    event_type: str
    sequence: int
    actor: AuthenticatedActor
    operation: str
    correlation_id: Optional[str]
    causation_id: Optional[str]
    recorded_at: str
    occurred_at: Optional[str] = None
    before_refs: Tuple[ResourceRef, ...] = ()
    after_refs: Tuple[ResourceRef, ...] = ()
    effects: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for field, value in (("event_id", self.event_id), ("store_authority", self.store_authority), ("stream", self.stream), ("event_type", self.event_type), ("recorded_at", self.recorded_at)):
            _text(value, field)
        if not isinstance(self.subject, ResourceRef):
            raise ContractError("subject must be ResourceRef")
        _revision(self.schema_revision, "schema_revision")
        if not isinstance(self.sequence, int) or self.sequence < 1:
            raise ContractError("event sequence must be positive")
        if not isinstance(self.actor, AuthenticatedActor):
            raise ContractError("actor must be AuthenticatedActor")
        _text(self.operation, "operation")
        for field, value in (("correlation_id", self.correlation_id), ("causation_id", self.causation_id), ("occurred_at", self.occurred_at)):
            if value is not None:
                _text(value, field)
        if any(not isinstance(ref, ResourceRef) for ref in self.before_refs + self.after_refs):
            raise ContractError("before_refs/after_refs must contain ResourceRef values")
        object.__setattr__(self, "effects", dict(self.effects or {}))
        _json_value(self.effects)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EventEnvelope":
        value = _mapping(value, "event_envelope")
        _keys(value, {"event_id", "store_authority", "stream", "subject", "schema_revision", "event_type", "sequence", "actor", "operation", "correlation_id", "causation_id", "recorded_at", "occurred_at", "before_refs", "after_refs", "effects"})
        return cls(value["event_id"], value["store_authority"], value["stream"], ResourceRef.from_dict(value["subject"]), value["schema_revision"], value["event_type"], value["sequence"], AuthenticatedActor.from_dict(value["actor"]), value["operation"], value.get("correlation_id"), value.get("causation_id"), value["recorded_at"], value.get("occurred_at"), tuple(ResourceRef.from_dict(ref) for ref in value.get("before_refs", [])), tuple(ResourceRef.from_dict(ref) for ref in value.get("after_refs", [])), value.get("effects", {}))


class AuthoringState(str, Enum):
    OPEN = "open"
    SAVED = "saved"
    FINISHED = "finished"
    RELEASED = "released"
    REJECTED = "rejected"


class CleanupStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    COMPLETE = "complete"
    UNSAFE = "unsafe"


@dataclass(frozen=True)
class FinishClaim(ContractRecord):
    finalization_identity: str
    mode: str
    claim_id: str

    def __post_init__(self) -> None:
        _text(self.finalization_identity, "finalization_identity")
        if self.mode not in {"manual", "idle"}:
            raise ContractError("finish mode must be manual or idle")
        _text(self.claim_id, "claim_id")


@dataclass(frozen=True)
class AuthoringCheckout(ContractRecord):
    target_scope: ResourceRef
    target_kind: str
    actor: AuthenticatedActor
    session_id: str
    token: str
    fence: str
    base_revision: str
    draft_snapshot_ref: ResourceRef
    final_snapshot_ref: Optional[ResourceRef]
    allowed_fields: Tuple[str, ...]
    state: AuthoringState = AuthoringState.OPEN
    cleanup: CleanupStatus = CleanupStatus.NOT_REQUESTED
    finish_claim: Optional[FinishClaim] = None
    unmanaged_writers: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.target_scope, ResourceRef) or not isinstance(self.actor, AuthenticatedActor):
            raise ContractError("target_scope and actor have invalid types")
        _text(self.target_kind, "target_kind")
        for field, value in (("session_id", self.session_id), ("token", self.token), ("fence", self.fence), ("base_revision", self.base_revision)):
            _text(value, field)
        if not isinstance(self.draft_snapshot_ref, ResourceRef):
            raise ContractError("draft_snapshot_ref must be ResourceRef")
        if self.final_snapshot_ref is not None and not isinstance(self.final_snapshot_ref, ResourceRef):
            raise ContractError("final_snapshot_ref must be ResourceRef")
        _tuple_text(self.allowed_fields, "allowed_fields")
        if not isinstance(self.state, AuthoringState):
            object.__setattr__(self, "state", AuthoringState(self.state))
        if not isinstance(self.cleanup, CleanupStatus):
            object.__setattr__(self, "cleanup", CleanupStatus(self.cleanup))
        if self.finish_claim is not None and not isinstance(self.finish_claim, FinishClaim):
            raise ContractError("finish_claim must be FinishClaim")
        if self.unmanaged_writers and self.cleanup == CleanupStatus.COMPLETE:
            raise ContractError("unmanaged writers make physical cleanup unsafe")
        if self.state == AuthoringState.FINISHED and (self.final_snapshot_ref is None or self.finish_claim is None):
            raise ContractError("finished checkout requires exact final snapshot and finish claim")

    def finish(self, claim: FinishClaim, final_snapshot_ref: ResourceRef) -> "AuthoringCheckout":
        if self.state in {AuthoringState.RELEASED, AuthoringState.REJECTED}:
            raise ContractError("released/rejected checkout cannot be finished")
        if self.finish_claim is not None and self.finish_claim.finalization_identity != claim.finalization_identity:
            raise ContractError("manual and idle finish claims must share one finalization identity")
        return AuthoringCheckout(self.target_scope, self.target_kind, self.actor, self.session_id, self.token, self.fence, self.base_revision, self.draft_snapshot_ref, final_snapshot_ref, self.allowed_fields, AuthoringState.FINISHED, self.cleanup, claim, self.unmanaged_writers)

    def mark_cleanup(self, status: CleanupStatus) -> "AuthoringCheckout":
        if status == CleanupStatus.COMPLETE and self.unmanaged_writers:
            raise ContractError("cleanup is unsafe while unmanaged writers exist")
        return AuthoringCheckout(self.target_scope, self.target_kind, self.actor, self.session_id, self.token, self.fence, self.base_revision, self.draft_snapshot_ref, self.final_snapshot_ref, self.allowed_fields, self.state, status, self.finish_claim, self.unmanaged_writers)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthoringCheckout":
        value = _mapping(value, "authoring_checkout")
        _keys(value, {"target_scope", "target_kind", "actor", "session_id", "token", "fence", "base_revision", "draft_snapshot_ref", "final_snapshot_ref", "allowed_fields", "state", "cleanup", "finish_claim", "unmanaged_writers"})
        claim = value.get("finish_claim")
        return cls(ResourceRef.from_dict(value["target_scope"]), value["target_kind"], AuthenticatedActor.from_dict(value["actor"]), value["session_id"], value["token"], value["fence"], value["base_revision"], ResourceRef.from_dict(value["draft_snapshot_ref"]), ResourceRef.from_dict(value["final_snapshot_ref"]) if value.get("final_snapshot_ref") else None, _tuple_text(value["allowed_fields"], "allowed_fields"), AuthoringState(value.get("state", "open")), CleanupStatus(value.get("cleanup", "not_requested")), FinishClaim(**claim) if claim else None, bool(value.get("unmanaged_writers", False)))


@dataclass(frozen=True)
class DomainContribution(ContractRecord):
    domain_id: str
    version: str
    owner: str
    resource_types: Tuple[str, ...]
    document_types: Tuple[str, ...]
    namespace_types: Tuple[str, ...]
    operation_types: Tuple[str, ...]
    event_types: Tuple[str, ...]
    schema_revision: str
    composition_bindings: Tuple[str, ...] = ()
    proof_refs: Tuple[ResourceRef, ...] = ()

    def __post_init__(self) -> None:
        for field, value in (("domain_id", self.domain_id), ("version", self.version), ("owner", self.owner), ("schema_revision", self.schema_revision)):
            _text(value, field)
        for field, value in (("resource_types", self.resource_types), ("document_types", self.document_types), ("namespace_types", self.namespace_types), ("operation_types", self.operation_types), ("event_types", self.event_types), ("composition_bindings", self.composition_bindings)):
            _tuple_text(value, field)
        if any(not isinstance(ref, ResourceRef) for ref in self.proof_refs):
            raise ContractError("proof_refs must contain ResourceRef values")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DomainContribution":
        value = _mapping(value, "domain_contribution")
        _keys(value, {"domain_id", "version", "owner", "resource_types", "document_types", "namespace_types", "operation_types", "event_types", "schema_revision", "composition_bindings", "proof_refs"})
        return cls(value["domain_id"], value["version"], value["owner"], _tuple_text(value["resource_types"], "resource_types"), _tuple_text(value["document_types"], "document_types"), _tuple_text(value["namespace_types"], "namespace_types"), _tuple_text(value["operation_types"], "operation_types"), _tuple_text(value["event_types"], "event_types"), value["schema_revision"], _tuple_text(value.get("composition_bindings", []), "composition_bindings"), tuple(ResourceRef.from_dict(ref) for ref in value.get("proof_refs", [])))


class DomainRegistry:
    def __init__(self) -> None:
        self._domains: dict[str, DomainContribution] = {}
        self._identities: dict[str, str] = {}

    def register(self, contribution: DomainContribution) -> None:
        if contribution.domain_id in self._domains:
            raise ContractError(f"duplicate domain identity: {contribution.domain_id}")
        identity_groups = (
            ("operation", contribution.operation_types),
            ("namespace", contribution.namespace_types),
            ("resource", contribution.resource_types),
            ("document", contribution.document_types),
            ("event", contribution.event_types),
        )
        identities: list[tuple[str, str]] = []
        for category, values in identity_groups:
            for identity in values:
                if identity in self._identities:
                    raise ContractError(f"duplicate {category} type identity: {identity}")
                if any(existing == identity for _, existing in identities):
                    raise ContractError(f"duplicate {category} type identity: {identity}")
                identities.append((category, identity))
        self._domains[contribution.domain_id] = contribution
        for category, identity in identities:
            self._identities[identity] = contribution.domain_id


@dataclass(frozen=True)
class CandidateManifest(ContractRecord):
    candidate_id: str
    manifest_revision: str
    owner: str
    resource: ResourceRef
    role: str
    output_refs: Tuple[ResourceRef, ...]
    source_refs: Tuple[ResourceRef, ...]
    input_refs: Tuple[ResourceRef, ...]
    criteria_refs: Tuple[ResourceRef, ...]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field, value in (("candidate_id", self.candidate_id), ("manifest_revision", self.manifest_revision), ("owner", self.owner), ("role", self.role)):
            _text(value, field)
        if not isinstance(self.resource, ResourceRef):
            raise ContractError("resource must be ResourceRef")
        for field, value in (("output_refs", self.output_refs), ("source_refs", self.source_refs), ("input_refs", self.input_refs), ("criteria_refs", self.criteria_refs)):
            if any(not isinstance(ref, ResourceRef) for ref in value):
                raise ContractError(f"{field} must contain ResourceRef values")
        object.__setattr__(self, "provenance", dict(_mapping(self.provenance, "provenance")))
        _json_value(self.provenance)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateManifest":
        value = _mapping(value, "candidate_manifest")
        _keys(value, {"candidate_id", "manifest_revision", "owner", "resource", "role", "output_refs", "source_refs", "input_refs", "criteria_refs", "provenance"})
        refs = lambda name: tuple(ResourceRef.from_dict(ref) for ref in value.get(name, []))
        return cls(value["candidate_id"], value["manifest_revision"], value["owner"], ResourceRef.from_dict(value["resource"]), value["role"], refs("output_refs"), refs("source_refs"), refs("input_refs"), refs("criteria_refs"), value.get("provenance", {}))


@dataclass(frozen=True)
class Reconsideration(ContractRecord):
    condition: str
    revisit_signal: str
    awaited_refs: Tuple[ResourceRef, ...] = ()

    def __post_init__(self) -> None:
        _text(self.condition, "condition")
        _text(self.revisit_signal, "revisit_signal")
        if any(not isinstance(ref, ResourceRef) for ref in self.awaited_refs):
            raise ContractError("awaited_refs must contain ResourceRef values")


class Applicability(str, Enum):
    APPLICABLE = "applicable"
    STALE = "stale"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class DecisionRecord(ContractRecord):
    decision_id: str
    subject: ResourceRef
    question: str
    decision_maker: AuthenticatedActor
    authority: ResourceRef
    candidate_refs: Tuple[ResourceRef, ...]
    criteria_refs: Tuple[ResourceRef, ...]
    evidence_refs: Tuple[ResourceRef, ...]
    disposition: str
    rationale: str
    reconsideration: Reconsideration
    action_refs: Tuple[ResourceRef, ...] = ()
    applicability: Applicability = Applicability.APPLICABLE
    decision_revision: str = "1"

    def __post_init__(self) -> None:
        _text(self.decision_id, "decision_id")
        if not isinstance(self.subject, ResourceRef) or not isinstance(self.authority, ResourceRef):
            raise ContractError("subject and authority must be ResourceRef")
        _text(self.question, "question")
        if not isinstance(self.decision_maker, AuthenticatedActor):
            raise ContractError("decision_maker must be AuthenticatedActor")
        for field, value in (("candidate_refs", self.candidate_refs), ("criteria_refs", self.criteria_refs), ("evidence_refs", self.evidence_refs), ("action_refs", self.action_refs)):
            if any(not isinstance(ref, ResourceRef) for ref in value):
                raise ContractError(f"{field} must contain ResourceRef values")
        _text(self.disposition, "disposition")
        _text(self.rationale, "rationale")
        if not isinstance(self.reconsideration, Reconsideration):
            raise ContractError("reconsideration must be explicit")
        if not isinstance(self.applicability, Applicability):
            object.__setattr__(self, "applicability", Applicability(self.applicability))
        _revision(self.decision_revision, "decision_revision")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DecisionRecord":
        value = _mapping(value, "decision_record")
        _keys(value, {"decision_id", "subject", "question", "decision_maker", "authority", "candidate_refs", "criteria_refs", "evidence_refs", "disposition", "rationale", "reconsideration", "action_refs", "applicability", "decision_revision"})
        refs = lambda name: tuple(ResourceRef.from_dict(ref) for ref in value.get(name, []))
        rec = value["reconsideration"]
        return cls(value["decision_id"], ResourceRef.from_dict(value["subject"]), value["question"], AuthenticatedActor.from_dict(value["decision_maker"]), ResourceRef.from_dict(value["authority"]), refs("candidate_refs"), refs("criteria_refs"), refs("evidence_refs"), value["disposition"], value["rationale"], Reconsideration(rec["condition"], rec["revisit_signal"], refs_from(rec.get("awaited_refs", []))), refs("action_refs"), Applicability(value.get("applicability", "applicable")), value.get("decision_revision", "1"))


def refs_from(values: Sequence[Mapping[str, Any]]) -> Tuple[ResourceRef, ...]:
    return tuple(ResourceRef.from_dict(value) for value in values)


@dataclass(frozen=True)
class ReadinessExplanation(ContractRecord):
    missing_obligation: str
    owner: str
    awaited_ref: Optional[ResourceRef]
    awaited_revision: Optional[str]
    revisit_signal: str
    decision_ref: Optional[ResourceRef] = None
    causes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.missing_obligation, "missing_obligation")
        _text(self.owner, "owner")
        if self.awaited_ref is not None and not isinstance(self.awaited_ref, ResourceRef):
            raise ContractError("awaited_ref must be ResourceRef")
        _optional_revision(self.awaited_revision, "awaited_revision")
        _text(self.revisit_signal, "revisit_signal")
        if self.decision_ref is not None and not isinstance(self.decision_ref, ResourceRef):
            raise ContractError("decision_ref must be ResourceRef")
        _tuple_text(self.causes, "causes")


class AttentionState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    HELD = "held"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AttentionRecord(ContractRecord):
    recipient: str
    cause: str
    subject: ResourceRef
    dedupe_id: str
    context_cursor: EventCursor
    state: AttentionState = AttentionState.OPEN
    disposition: Optional[str] = None
    delivery_hint: Optional[str] = None

    def __post_init__(self) -> None:
        for field, value in (("recipient", self.recipient), ("cause", self.cause), ("dedupe_id", self.dedupe_id)):
            _text(value, field)
        if not isinstance(self.subject, ResourceRef) or not isinstance(self.context_cursor, EventCursor):
            raise ContractError("subject and context_cursor have invalid types")
        if not isinstance(self.state, AttentionState):
            object.__setattr__(self, "state", AttentionState(self.state))
        if self.disposition is not None:
            _text(self.disposition, "disposition")
        if self.delivery_hint is not None:
            _text(self.delivery_hint, "delivery_hint")


class HostOperation(str, Enum):
    INVOKE = "invoke"
    RESUME = "resume"
    SEND = "send"
    INSPECT = "inspect"
    CANCEL = "cancel"
    WAIT = "wait"


@dataclass(frozen=True)
class HostIdentity(ContractRecord):
    logical_agent_id: str
    physical_session_id: Optional[str] = None

    def __post_init__(self) -> None:
        _text(self.logical_agent_id, "logical_agent_id")
        if self.physical_session_id is not None:
            _text(self.physical_session_id, "physical_session_id")


@dataclass(frozen=True)
class HostRequest(ContractRecord):
    operation: HostOperation
    identity: HostIdentity
    target: ResourceRef
    requested_profile: Optional[str] = None
    input_refs: Tuple[ResourceRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.operation, HostOperation):
            object.__setattr__(self, "operation", HostOperation(self.operation))
        if not isinstance(self.identity, HostIdentity) or not isinstance(self.target, ResourceRef):
            raise ContractError("identity and target have invalid types")
        if self.requested_profile is not None:
            _text(self.requested_profile, "requested_profile")
        if any(not isinstance(ref, ResourceRef) for ref in self.input_refs):
            raise ContractError("input_refs must contain ResourceRef values")


class HostOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HostReceipt(ContractRecord):
    operation: HostOperation
    outcome: HostOutcome
    identity: HostIdentity
    logical_request_key: str
    requested_profile: Optional[str] = None
    observed_runner: Optional[str] = None
    observed_profile: Optional[str] = None
    process_id: Optional[str] = None
    unsupported_reason: Optional[str] = None
    result_ref: Optional[ResourceRef] = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, HostOperation):
            object.__setattr__(self, "operation", HostOperation(self.operation))
        if not isinstance(self.outcome, HostOutcome):
            object.__setattr__(self, "outcome", HostOutcome(self.outcome))
        if not isinstance(self.identity, HostIdentity):
            raise ContractError("identity must be HostIdentity")
        _text(self.logical_request_key, "logical_request_key")
        for field, value in (("requested_profile", self.requested_profile), ("observed_runner", self.observed_runner), ("observed_profile", self.observed_profile), ("process_id", self.process_id), ("unsupported_reason", self.unsupported_reason)):
            if value is not None:
                _text(value, field)
        if self.outcome == HostOutcome.UNSUPPORTED and not self.unsupported_reason:
            raise ContractError("unsupported host receipts require unsupported_reason")
        if self.result_ref is not None and not isinstance(self.result_ref, ResourceRef):
            raise ContractError("result_ref must be ResourceRef")


class HostPort:
    """Small optional port; adapters declare support and never infer it."""

    def __init__(self, supported: Iterable[HostOperation] = ()) -> None:
        self.supported = frozenset(supported)

    def supports(self, operation: HostOperation) -> bool:
        return operation in self.supported

    def require(self, operation: HostOperation) -> None:
        if not self.supports(operation):
            raise UnsupportedOperationError(f"host operation unsupported: {operation.value}")


@dataclass(frozen=True)
class PackResourceDescriptor(ContractRecord):
    resource_id: str
    kind: str
    revision: str
    source_ref: ResourceRef
    digest: Optional[str] = None
    annotations: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _text(self.resource_id, "resource_id")
        _text(self.kind, "kind")
        _revision(self.revision)
        if not isinstance(self.source_ref, ResourceRef):
            raise ContractError("source_ref must be ResourceRef")
        if self.digest is not None:
            _digest(self.digest)
        object.__setattr__(self, "annotations", dict(self.annotations or {}))
        _json_value(self.annotations)


# This is intentionally a hand-authored public schema index: it is stable,
# product-neutral, and is itself the input to the deterministic digest.
SCHEMA_DEFINITIONS: Mapping[str, Any] = {
    "revision": CONTRACT_REVISION,
    "records": {
        "ResourceRef": ["authority", "kind", "id", "revision"],
        "DocumentRef": ["authority", "kind", "id", "revision", "role"],
        "ReferenceBinding": ["ref", "mode"],
        "ExtensionDescriptor": ["namespace", "schema_revision", "resource_kinds", "description", "owner", "profile_bindings", "operation_bindings", "annotations", "managed"],
        "TransactionContext": ["actor", "logical_request_key", "request_digest", "expected_revision", "expected_version", "edit_token", "correlation_id", "causation_id"],
        "CommandEnvelope": ["operation", "schema_revision", "target", "context", "payload", "envelope_revision"],
        "CommandReceipt": ["logical_request_key", "request_digest", "operation", "target", "status", "transaction_id", "event_ids", "result_ref", "error_code", "replayed", "observed_revision", "unknown_reason"],
        "EventEnvelope": ["event_id", "store_authority", "stream", "subject", "schema_revision", "event_type", "sequence", "actor", "operation", "correlation_id", "causation_id", "recorded_at", "occurred_at", "before_refs", "after_refs", "effects"],
        "AuthoringCheckout": ["target_scope", "target_kind", "actor", "session_id", "token", "fence", "base_revision", "draft_snapshot_ref", "final_snapshot_ref", "allowed_fields", "state", "cleanup", "finish_claim", "unmanaged_writers"],
        "DomainContribution": ["domain_id", "version", "owner", "resource_types", "document_types", "namespace_types", "operation_types", "event_types", "schema_revision", "composition_bindings", "proof_refs"],
        "CandidateManifest": ["candidate_id", "manifest_revision", "owner", "resource", "role", "output_refs", "source_refs", "input_refs", "criteria_refs", "provenance"],
        "DecisionRecord": ["decision_id", "subject", "question", "decision_maker", "authority", "candidate_refs", "criteria_refs", "evidence_refs", "disposition", "rationale", "reconsideration", "action_refs", "applicability", "decision_revision"],
        "ReadinessExplanation": ["missing_obligation", "owner", "awaited_ref", "awaited_revision", "revisit_signal", "decision_ref", "causes"],
        "AttentionRecord": ["recipient", "cause", "subject", "dedupe_id", "context_cursor", "state", "disposition", "delivery_hint"],
        "HostRequest": ["operation", "identity", "target", "requested_profile", "input_refs"],
        "HostReceipt": ["operation", "outcome", "identity", "logical_request_key", "requested_profile", "observed_runner", "observed_profile", "process_id", "unsupported_reason", "result_ref"],
        "PackResourceDescriptor": ["resource_id", "kind", "revision", "source_ref", "digest", "annotations"],
    },
}
CONTRACT_DIGEST = hashlib.sha256(canonical_json(SCHEMA_DEFINITIONS).encode("utf-8")).hexdigest()
SCHEMA_DIGEST = CONTRACT_DIGEST


# The small constructors below keep fixture loading explicit while allowing
# the record classes above to stay readable.  Every loader rejects reserved
# siblings rather than silently dropping them.
def _finish_claim_from_dict(value: Mapping[str, Any]) -> FinishClaim:
    value = _mapping(value, "finish_claim")
    _keys(value, {"finalization_identity", "mode", "claim_id"})
    return FinishClaim(value["finalization_identity"], value["mode"], value["claim_id"])


def _reconsideration_from_dict(value: Mapping[str, Any]) -> Reconsideration:
    value = _mapping(value, "reconsideration")
    _keys(value, {"condition", "revisit_signal", "awaited_refs"})
    return Reconsideration(value["condition"], value["revisit_signal"], refs_from(value.get("awaited_refs", [])))


def _readiness_from_dict(cls: type[ReadinessExplanation], value: Mapping[str, Any]) -> ReadinessExplanation:
    value = _mapping(value, "readiness")
    _keys(value, {"missing_obligation", "owner", "awaited_ref", "awaited_revision", "revisit_signal", "decision_ref", "causes"})
    return cls(value["missing_obligation"], value["owner"], ResourceRef.from_dict(value["awaited_ref"]) if value.get("awaited_ref") else None, value.get("awaited_revision"), value["revisit_signal"], ResourceRef.from_dict(value["decision_ref"]) if value.get("decision_ref") else None, _tuple_text(value.get("causes", []), "causes"))


def _attention_from_dict(cls: type[AttentionRecord], value: Mapping[str, Any]) -> AttentionRecord:
    value = _mapping(value, "attention")
    _keys(value, {"recipient", "cause", "subject", "dedupe_id", "context_cursor", "state", "disposition", "delivery_hint"})
    return cls(value["recipient"], value["cause"], ResourceRef.from_dict(value["subject"]), value["dedupe_id"], EventCursor.from_dict(value["context_cursor"]), AttentionState(value.get("state", "open")), value.get("disposition"), value.get("delivery_hint"))


def _host_identity_from_dict(cls: type[HostIdentity], value: Mapping[str, Any]) -> HostIdentity:
    value = _mapping(value, "host_identity")
    _keys(value, {"logical_agent_id", "physical_session_id"})
    return cls(value["logical_agent_id"], value.get("physical_session_id"))


def _host_request_from_dict(cls: type[HostRequest], value: Mapping[str, Any]) -> HostRequest:
    value = _mapping(value, "host_request")
    _keys(value, {"operation", "identity", "target", "requested_profile", "input_refs"})
    return cls(HostOperation(value["operation"]), HostIdentity.from_dict(value["identity"]), ResourceRef.from_dict(value["target"]), value.get("requested_profile"), refs_from(value.get("input_refs", [])))


def _host_receipt_from_dict(cls: type[HostReceipt], value: Mapping[str, Any]) -> HostReceipt:
    value = _mapping(value, "host_receipt")
    _keys(value, {"operation", "outcome", "identity", "logical_request_key", "requested_profile", "observed_runner", "observed_profile", "process_id", "unsupported_reason", "result_ref"})
    return cls(HostOperation(value["operation"]), HostOutcome(value["outcome"]), HostIdentity.from_dict(value["identity"]), value["logical_request_key"], value.get("requested_profile"), value.get("observed_runner"), value.get("observed_profile"), value.get("process_id"), value.get("unsupported_reason"), ResourceRef.from_dict(value["result_ref"]) if value.get("result_ref") else None)


def _pack_resource_from_dict(cls: type[PackResourceDescriptor], value: Mapping[str, Any]) -> PackResourceDescriptor:
    value = _mapping(value, "pack_resource")
    _keys(value, {"resource_id", "kind", "revision", "source_ref", "digest", "annotations"})
    return cls(value["resource_id"], value["kind"], value["revision"], ResourceRef.from_dict(value["source_ref"]), value.get("digest"), value.get("annotations", {}))


FinishClaim.from_dict = classmethod(_finish_claim_from_dict)  # type: ignore[attr-defined]
Reconsideration.from_dict = classmethod(_reconsideration_from_dict)  # type: ignore[attr-defined]
ReadinessExplanation.from_dict = classmethod(_readiness_from_dict)  # type: ignore[attr-defined]
AttentionRecord.from_dict = classmethod(_attention_from_dict)  # type: ignore[attr-defined]
HostIdentity.from_dict = classmethod(_host_identity_from_dict)  # type: ignore[attr-defined]
HostRequest.from_dict = classmethod(_host_request_from_dict)  # type: ignore[attr-defined]
HostReceipt.from_dict = classmethod(_host_receipt_from_dict)  # type: ignore[attr-defined]
PackResourceDescriptor.from_dict = classmethod(_pack_resource_from_dict)  # type: ignore[attr-defined]


__all__ = [
    "Applicability", "AttentionRecord", "AttentionState", "AuthenticatedActor", "AuthoringCheckout", "AuthoringState",
    "CandidateManifest", "CleanupStatus", "CommandEnvelope", "CommandReceipt", "ContractError", "ContractRecord",
    "CursorState", "DecisionRecord", "DocumentRef", "DomainContribution", "DomainRegistry", "EventCursor", "EventEnvelope",
    "ExtensionDescriptor", "ExtensionRegistry", "FinishClaim", "HostIdentity", "HostOperation", "HostOutcome", "HostPort",
    "HostReceipt", "HostRequest", "OperationBinding", "PackResourceDescriptor", "ReceiptStatus", "ReferenceBinding",
    "Reconsideration", "ReplayConflictError", "ReadinessExplanation", "ResourceRef", "RevisionRef", "TransactionContext",
    "UnsupportedOperationError", "canonical_json", "canonical_request_digest", "validate_expected_state", "validate_replay", "CONTRACT_REVISION",
    "CONTRACT_DIGEST", "SCHEMA_DIGEST", "SCHEMA_DEFINITIONS",
]
