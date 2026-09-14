"""Exclusive managed-local authoring sessions.

EDT owns the lifecycle semantics in this module.  Durable state is deliberately
represented as ordinary FND identities, references, receipts, and events.  A
writer is injected at the boundary; this module has no database or event store
of its own.

The implementation is intentionally conservative about files.  A materializer
and snapshot port may be supplied by a host, but this layer never recursively
deletes a checkout.  It authenticates the authoring-local held retirement
lease before durable cleanup completion; descriptor-relative unlink remains in
the physical cleanup module.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass, field
from hashlib import sha256
import inspect
import secrets
import threading
import time
from typing import Any, Callable, ContextManager, Mapping, Optional, Protocol, Sequence, Tuple, Union
from herzchen.command_ports import command_facade

from herzchen.contracts import (
    AuthenticatedActor,
    AuthoringCheckout,
    AuthoringState,
    CleanupStatus,
    CommandEnvelope,
    CommandReceipt,
    DomainContribution,
    FinishClaim,
    ReceiptStatus,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
    canonical_request_digest,
)

from .writer_lease import HeldRetirementLease, WriterLeaseError, validated_retirement_manifest


FND02_CONTRACT_REVISION = "fnd-02.v1.1"
FND02_CONTRACT_DIGEST = "28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264"
AUTHORING_SCHEMA_REVISION = "edt-02.authoring.v1"


def domain_contribution() -> DomainContribution:
    """Return EDT's exact durable authoring command declaration."""
    ports = tuple(
        "mutation-port:{}|{}|{}|authoring.{}".format(
            AUTHORING_SCHEMA_REVISION, operation, resource, operation
        )
        for operation, resource in (
            ("actor.open", "authoring-actor"),
            ("actor.release", "authoring-actor"),
            ("open", "authoring-scope"),
            ("metadata", "authoring-scope"),
            ("autosave", "authoring-scope"),
            ("finish.claim", "authoring-scope"),
            ("finish", "authoring-scope"),
            ("finish.recovery", "authoring-scope"),
            ("release", "authoring-scope"),
            ("cleanup", "authoring-scope"),
            ("cleanup.refresh", "authoring-scope"),
        )
    )
    return DomainContribution(
        "herzchen.authoring.sessions", "1", "edt",
        ("authoring-actor", "authoring-scope"), (),
        ("authoring.sessions",),
        tuple(operation for operation, _resource in (
            ("actor.open", "authoring-actor"), ("actor.release", "authoring-actor"),
            ("open", "authoring-scope"), ("metadata", "authoring-scope"),
            ("autosave", "authoring-scope"), ("finish.claim", "authoring-scope"),
            ("finish", "authoring-scope"), ("finish.recovery", "authoring-scope"),
            ("release", "authoring-scope"), ("cleanup", "authoring-scope"),
            ("cleanup.refresh", "authoring-scope"),
        )),
        tuple("authoring." + operation for operation in (
            "actor.open", "actor.release", "open", "metadata", "autosave",
            "finish.claim", "finish", "finish.recovery", "release", "cleanup", "cleanup.refresh",
        )),
        AUTHORING_SCHEMA_REVISION,
        ("fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction", "handler-required") + ports,
    )


def register_authoring(store: Any) -> Any:
    """Persist EDT's declaration and return its sealed writer capability."""
    return store.register_domain_handler((domain_contribution(),))


class AuthoringError(RuntimeError):
    """Base error for authoring admission and lifecycle failures."""


class ScopeResolutionError(AuthoringError):
    """The server could not resolve a target to one canonical scope."""


class OccupiedError(AuthoringError):
    """The canonical scope is held by another active checkout."""


class ActorOccupiedError(AuthoringError):
    """The authenticated actor already holds another scope."""


class InvalidSessionError(AuthoringError):
    """The session, token, fence, or scope is not the current capability."""


class BaseRevisionMismatchError(AuthoringError):
    """The requested finish does not match the checkout base."""


class MaterializationError(AuthoringError):
    """A checkout could not be materialised after durable admission."""


class CaptureError(AuthoringError):
    """A stable exact snapshot could not be obtained."""


class FNDWriterPort(Protocol):
    """The small supplied FND writer surface consumed by EDT."""

    authority: str

    def transaction(self) -> ContextManager[Any]: ...
    def get_identity(self, ref: ResourceRef) -> Any: ...
    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]: ...
    def mutate(self, envelope: CommandEnvelope, **kwargs: Any) -> CommandReceipt: ...
    def put_identity(self, ref: ResourceRef, payload: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> Any: ...
    def put_reference(self, ref: ResourceRef, **kwargs: Any) -> ResourceRef: ...


@dataclass(frozen=True)
class Snapshot:
    """Exact bytes and their durable FND reference."""

    ref: ResourceRef
    data: bytes
    manifest: Tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        return sha256(self.data).hexdigest()


@dataclass(frozen=True)
class SessionHandle:
    """The capability returned only to the holder."""

    scope: ResourceRef
    target_scope: ResourceRef
    target_kind: str
    actor: AuthenticatedActor
    session_id: str
    token: str
    fence: str
    base_revision: str
    checkout_path: Optional[str] = None


@dataclass(frozen=True)
class OpenResult:
    status: str
    scope: ResourceRef
    handle: Optional[SessionHandle] = None
    checkout: Optional[AuthoringCheckout] = None
    purpose: Optional[str] = None
    activity: Optional[str] = None
    waitable: bool = True
    project_ref: Optional[ResourceRef] = None
    error: Optional[str] = None

    @property
    def opened(self) -> bool:
        return self.status == "opened"


@dataclass(frozen=True)
class ReadResult:
    status: str
    scope: ResourceRef
    checkout: Optional[AuthoringCheckout] = None
    purpose: Optional[str] = None
    activity: Optional[str] = None
    waitable: bool = True


@dataclass(frozen=True)
class WaitResult:
    status: str
    scope: ResourceRef
    waited_seconds: float
    read: ReadResult


@dataclass(frozen=True)
class FinishResult:
    status: str
    scope: ResourceRef
    session_id: str
    receipt: Optional[CommandReceipt] = None
    checkout: Optional[AuthoringCheckout] = None
    final_snapshot: Optional[Snapshot] = None
    recovery_pending: bool = False
    cleanup: CleanupStatus = CleanupStatus.NOT_REQUESTED
    error: Optional[str] = None


@dataclass(frozen=True)
class CleanupResult:
    status: str
    scope: ResourceRef
    session_id: str
    cleanup: CleanupStatus
    physical_deletion_deferred: bool = True


@dataclass(frozen=True)
class _Record:
    ref: ResourceRef
    version: int
    payload: Mapping[str, Any]
    edit_token: Optional[str]


def _as_record(value: Any) -> Optional[_Record]:
    if value is None:
        return None
    ref = getattr(value, "ref", None)
    payload = getattr(value, "payload", None)
    if ref is not None and payload is not None:
        return _Record(ref, int(getattr(value, "version", 0)), dict(payload), getattr(value, "edit_token", None))
    if isinstance(value, Mapping):
        ref_value = value.get("ref")
        if isinstance(ref_value, ResourceRef):
            return _Record(ref_value, int(value.get("version", 0)), dict(value.get("payload", {})), value.get("edit_token"))
    raise TypeError("FND get_identity must return an identity record or None")


def _opaque_id(prefix: str) -> str:
    return prefix + "-" + secrets.token_hex(12)


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _scope_key(scope: ResourceRef) -> ResourceRef:
    return ResourceRef(scope.authority, "authoring-scope", scope.id)


def _actor_key(actor: AuthenticatedActor, authority: str) -> ResourceRef:
    actor_id = sha256((actor.authority + "\x00" + actor.actor).encode("utf-8")).hexdigest()[:32]
    return ResourceRef(authority, "authoring-actor", actor_id)


def _bytes(value: Union[bytes, bytearray, memoryview, str]) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise TypeError("snapshot content must be bytes-like or text")


def _snapshot(value: Any, default_ref: ResourceRef) -> Snapshot:
    if isinstance(value, Snapshot):
        return value
    if isinstance(value, Mapping):
        data = _bytes(value.get("data", value.get("bytes", b"")))
        ref = value.get("ref", default_ref)
        return Snapshot(ref, data, tuple(value.get("manifest", ())))
    return Snapshot(default_ref, _bytes(value))


def _call_flexible(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call small host hooks while allowing either positional or keyword APIs."""
    signature = inspect.signature(fn)
    parameters = tuple(signature.parameters.values())
    positional_names = tuple(
        parameter.name
        for parameter in parameters
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    )
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters)
    filtered = dict(kwargs)
    for name in positional_names[: len(args)]:
        filtered.pop(name, None)
    if not accepts_kwargs:
        accepted = {parameter.name for parameter in parameters}
        filtered = {key: value for key, value in filtered.items() if key in accepted}
    return fn(*args, **filtered)


class _AuthoringSessionServiceEngine:
    """The EDT exclusive-session port over one injected FND writer."""

    def __init__(
        self,
        writer: FNDWriterPort,
        *,
        scope_resolver: Optional[Callable[..., ResourceRef]] = None,
        event_waiter: Optional[Callable[..., Any]] = None,
        materializer: Optional[Callable[..., Any]] = None,
        snapshot_store: Optional[Callable[..., Any]] = None,
    ) -> None:
        if hasattr(writer, "domain_handler"):
            writer = writer.domain_handler((domain_contribution(),))
        self.__writer = writer
        self.reader = writer.consumer()
        self.scope_resolver = scope_resolver
        self.event_waiter = event_waiter
        self.materializer = materializer
        self.snapshot_store = snapshot_store
        self._finish_lock = threading.RLock()

    def _session_transaction(self) -> Any:
        """Composition-only transaction boundary used by EDT adapters."""
        return self.__writer.transaction()

    def resolve_scope(self, target: ResourceRef, *, parent_scope: Optional[ResourceRef] = None) -> ResourceRef:
        if not isinstance(target, ResourceRef):
            raise ScopeResolutionError("target must be a ResourceRef")
        if parent_scope is not None:
            return parent_scope
        if self.scope_resolver is not None:
            resolved = _call_flexible(self.scope_resolver, target, target=target)
            if not isinstance(resolved, ResourceRef):
                raise ScopeResolutionError("scope resolver did not return a ResourceRef")
            return resolved
        if target.kind in {"task", "document", "project-task", "project-document"}:
            raise ScopeResolutionError("nested target requires its canonical parent scope")
        return target

    def _records(self, scope: ResourceRef, actor: AuthenticatedActor) -> Tuple[Optional[_Record], Optional[_Record]]:
        authority = getattr(self.__writer, "authority", scope.authority)
        scope_record = _as_record(self.__writer.get_identity(_scope_key(scope)))
        actor_record = _as_record(self.__writer.get_identity(_actor_key(actor, authority)))
        return scope_record, actor_record

    @staticmethod
    def _payload_checkout(payload: Mapping[str, Any]) -> Optional[AuthoringCheckout]:
        value = payload.get("checkout")
        return None if value is None else AuthoringCheckout.from_dict(value)

    @staticmethod
    def _active(payload: Mapping[str, Any]) -> bool:
        checkout = _AuthoringSessionServiceEngine._payload_checkout(payload)
        return checkout is not None and checkout.state == AuthoringState.OPEN

    @staticmethod
    def _actor_active(payload: Mapping[str, Any]) -> bool:
        return bool(payload.get("active")) and payload.get("type") == "authoring_actor"

    @staticmethod
    def _masked_read(scope: ResourceRef, payload: Optional[Mapping[str, Any]], *, holder: bool = False) -> ReadResult:
        if not payload or not _AuthoringSessionServiceEngine._active(payload):
            return ReadResult("available", scope)
        checkout = _AuthoringSessionServiceEngine._payload_checkout(payload)
        assert checkout is not None
        if holder:
            return ReadResult("open", scope, checkout, payload.get("purpose"), payload.get("activity"))
        return ReadResult("occupied", scope, None, payload.get("purpose"), payload.get("activity"))

    def read(self, target: ResourceRef, actor: Optional[AuthenticatedActor] = None, *, parent_scope: Optional[ResourceRef] = None) -> ReadResult:
        scope = self.resolve_scope(target, parent_scope=parent_scope)
        record = _as_record(self.__writer.get_identity(_scope_key(scope)))
        payload = {} if record is None else record.payload
        holder = bool(actor and self._active(payload) and self._payload_checkout(payload).actor == actor)  # type: ignore[union-attr]
        return self._masked_read(scope, payload, holder=holder)

    def _request_digest(
        self, operation: str, request_id: str, values: Mapping[str, Any],
        *, target: ResourceRef, actor: AuthenticatedActor,
    ) -> str:
        context = TransactionContext(actor, request_id, "0" * 64)
        return canonical_request_digest(
            logical_request_key=request_id, operation=operation,
            schema_revision=AUTHORING_SCHEMA_REVISION, target=target,
            actor=actor, payload=values, context=context,
        )

    def _envelope(
        self,
        actor: AuthenticatedActor,
        operation: str,
        request_id: str,
        target: ResourceRef,
        digest: str,
        *,
        revision: Optional[str],
        version: Optional[int],
        edit_token: Optional[str] = None,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> CommandEnvelope:
        envelope_payload = dict(payload or {})
        context = TransactionContext(
            actor, request_id, digest, revision, version, edit_token,
            correlation_id, causation_id,
        )
        canonical = canonical_request_digest(
            logical_request_key=request_id,
            operation=operation,
            schema_revision=AUTHORING_SCHEMA_REVISION,
            target=target,
            actor=actor,
            payload=envelope_payload,
            context=context,
        )
        return CommandEnvelope(
            operation,
            AUTHORING_SCHEMA_REVISION,
            target,
            TransactionContext(
                actor, request_id, canonical, revision, version, edit_token,
                correlation_id, causation_id,
            ),
            envelope_payload,
        )

    def _mutate(
        self,
        tx: Any,
        *,
        actor: AuthenticatedActor,
        operation: str,
        request_id: str,
        target: ResourceRef,
        digest: str,
        record: Optional[_Record],
        payload: Mapping[str, Any],
        effects: Mapping[str, Any],
        request_payload: Optional[Mapping[str, Any]] = None,
        no_op: bool = False,
    ) -> CommandReceipt:
        envelope = self._envelope(
            actor, operation, request_id, target, digest,
            # EDT performs the capability/base-revision checks above its FND
            # port.  Keep the durable request context stable across an exact
            # replay rather than deriving a new digest from the post-mutation
            # identity revision/version.
            revision=None,
            version=None,
            edit_token=None,
            payload=payload if request_payload is None else request_payload,
        )
        return self.__writer.mutate(
            envelope,
            event_type="authoring." + operation,
            effects=dict(effects),
            stream="authoring:" + target.id,
            transaction=tx,
            no_op=no_op,
            identity_payload=payload,
        )

    def _put_refs(self, tx: Any, *refs: Optional[ResourceRef]) -> None:
        for ref in refs:
            if ref is not None:
                self.__writer.put_reference(ref, transaction=tx)

    def _put_snapshot(self, tx: Any, snapshot: Snapshot) -> None:
        self.__writer.put_identity(
            snapshot.ref,
            {
                "type": "authoring_snapshot",
                "digest": snapshot.digest,
                "bytes_b64": b64encode(snapshot.data).decode("ascii"),
                "manifest": list(snapshot.manifest),
            },
            transaction=tx,
        )

    def _new_checkout(
        self,
        scope: ResourceRef,
        actor: AuthenticatedActor,
        target_kind: str,
        base_revision: str,
        allowed_fields: Sequence[str],
        initial_bytes: bytes,
        *,
        pending: bool,
        unmanaged_writers: bool,
        purpose: str,
        activity: str,
    ) -> Tuple[AuthoringCheckout, Snapshot, SessionHandle, Mapping[str, Any]]:
        session_id = _opaque_id("session")
        token = _opaque_id("token")
        fence = _opaque_id("fence")
        draft = Snapshot(ResourceRef(getattr(self.__writer, "authority", scope.authority), "authoring-snapshot", "draft-" + session_id, sha256(initial_bytes).hexdigest()), initial_bytes)
        checkout = AuthoringCheckout(
            scope, target_kind, actor, session_id, token, fence, base_revision,
            draft.ref, None, tuple(allowed_fields), unmanaged_writers=unmanaged_writers,
        )
        handle = SessionHandle(_scope_key(scope), scope, target_kind, actor, session_id, token, fence, base_revision)
        payload = {
            "type": "authoring_scope",
            "fnd_contract_revision": FND02_CONTRACT_REVISION,
            "fnd_contract_digest": FND02_CONTRACT_DIGEST,
            "scope": scope.to_dict(),
            "purpose": purpose,
            "activity": activity,
            "pending": bool(pending),
            "checkout": checkout.to_dict(),
            "draft_bytes_b64": b64encode(initial_bytes).decode("ascii"),
            "draft_digest": draft.digest,
            "final_bytes_b64": None,
            "project": None,
            "checkout_path": None,
            "registered_files": [],
        }
        return checkout, draft, handle, payload

    def _prior_receipt(self, request_id: str, digest: str) -> Optional[CommandReceipt]:
        prior = self.__writer.get_receipt(request_id)
        if prior is not None and prior.request_digest != digest:
            raise ReplayConflictError("logical request key was reused with a changed request digest")
        return prior

    def open(
        self,
        target: ResourceRef,
        actor: AuthenticatedActor,
        *,
        request_id: str,
        target_kind: Optional[str] = None,
        base_revision: Optional[str] = None,
        purpose: str = "authoring",
        activity: str = "editing",
        allowed_fields: Sequence[str] = (),
        initial_content: Union[bytes, str] = b"",
        parent_scope: Optional[ResourceRef] = None,
        pending: bool = False,
        unmanaged_writers: bool = False,
        materialize: Optional[Callable[..., Any]] = None,
        project: Optional[Mapping[str, Any]] = None,
    ) -> OpenResult:
        scope = self.resolve_scope(target, parent_scope=parent_scope)
        actor = actor
        target_kind = target_kind or target.kind
        base_revision = base_revision or target.revision or "initial"
        initial_bytes = _bytes(initial_content)
        if not isinstance(unmanaged_writers, bool):
            raise TypeError("unmanaged_writers must be boolean")
        values = {"scope": scope.to_dict(), "target": target.to_dict(), "target_kind": target_kind, "base_revision": base_revision, "purpose": purpose, "activity": activity, "allowed_fields": tuple(allowed_fields), "initial_digest": sha256(initial_bytes).hexdigest(), "pending": pending, "unmanaged_writers": unmanaged_writers, "project": project}
        scope_ref = _scope_key(scope)
        digest = self._request_digest("open", request_id, values, target=scope_ref, actor=actor)

        authority = getattr(self.__writer, "authority", scope.authority)
        actor_ref = _actor_key(actor, authority)
        materializer = materialize or self.materializer
        try:
            # The supplied FND transaction/Store owner serializes the complete
            # check-and-reserve unit across all service instances.
            with self.__writer.transaction() as tx:
                prior = self._prior_receipt(request_id, digest)
                if prior is not None:
                    record = _as_record(self.__writer.get_identity(scope_ref))
                    if record is not None and self._active(record.payload):
                        return self._open_result("replayed", scope, record.payload, prior=prior)
                    if record is not None and record.payload.get("status") == "saved_project_edit_not_opened":
                        return self._open_result("saved_project_edit_not_opened", scope, record.payload, prior=prior)
                    return OpenResult("replayed", scope, error=prior.error_code)
                scope_record = _as_record(self.__writer.get_identity(scope_ref))
                actor_record = _as_record(self.__writer.get_identity(actor_ref))
                if scope_record is not None and self._active(scope_record.payload):
                    return OpenResult("occupied", scope, purpose=scope_record.payload.get("purpose"), activity=scope_record.payload.get("activity"), error="scope is occupied")
                if actor_record is not None and self._actor_active(actor_record.payload):
                    return OpenResult("actor_occupied", scope, purpose=actor_record.payload.get("purpose"), activity=actor_record.payload.get("activity"), error="actor already occupies a scope")

                checkout, draft, handle, payload = self._new_checkout(
                    scope, actor, target_kind, base_revision, allowed_fields, initial_bytes,
                    pending=pending, unmanaged_writers=unmanaged_writers,
                    purpose=purpose, activity=activity,
                )
                self._mutate(tx, actor=actor, operation="actor.open", request_id=request_id + ":actor", target=actor_ref, digest=digest, record=actor_record, payload={"type": "authoring_actor", "active": True, "scope": scope.to_dict(), "session_id": checkout.session_id, "purpose": purpose, "activity": activity}, effects={"scope": scope.id, "session_id": checkout.session_id})
                receipt = self._mutate(tx, actor=actor, operation="open", request_id=request_id, target=scope_ref, digest=digest, record=scope_record, payload=payload, effects={"session_id": checkout.session_id, "scope": scope.id}, request_payload=values)
                self._put_snapshot(tx, draft)
                self._put_refs(tx, checkout.draft_snapshot_ref)
        except (OccupiedError, ActorOccupiedError):
            raise

        # Materialisation happens after durable reservation.  Failure preserves
        # the project and bytes, then explicitly releases the checkout.
        try:
            path = None
            if materializer is not None:
                result = _call_flexible(materializer, checkout, initial_bytes, checkout=checkout, initial_bytes=initial_bytes)
                if isinstance(result, Mapping):
                    path = result.get("path")
                    project = result.get("project", project)
                    registered_files = tuple(result.get("registered_files", ()))
                else:
                    path = result
                    registered_files = ()
            else:
                registered_files = ()
            if project is not None or path is not None or registered_files:
                self._update_open_metadata(handle, request_id + ":materialized", project=project, checkout_path=path, registered_files=registered_files)
                payload = dict(payload)
                if project is not None:
                    payload["project"] = project.to_dict() if isinstance(project, ResourceRef) else project
                if path is not None:
                    payload["checkout_path"] = str(path)
                if registered_files:
                    payload["registered_files"] = list(registered_files)
            return self._open_result("opened", scope, payload)
        except BaseException as exc:
            self._release_after_open_failure(handle, request_id + ":materialize-failure", project=project, error=str(exc))
            return OpenResult("saved_project_edit_not_opened", scope, project_ref=self._project_ref(project), error=str(exc))

    def create_and_open(self, *args: Any, create_project: Callable[..., Any], **kwargs: Any) -> OpenResult:
        """Reserve actor/scope first, then create and materialise the project.

        This ordering ensures actor occupancy never leaves a hidden project.
        The regular ``open`` path accepts a project result for hosts that have
        already created the durable project; this convenience method calls the
        supplied creator only after admission.
        """
        # A creator is invoked by the materializer hook after the reservation.
        original_materialize = kwargs.pop("materialize", None) or self.materializer
        project_box: dict[str, Any] = {}

        def materialize(checkout: AuthoringCheckout, initial_bytes: bytes, **_: Any) -> Any:
            project = _call_flexible(create_project, checkout, initial_bytes, checkout=checkout, initial_bytes=initial_bytes)
            project_box["project"] = project
            created_handle = SessionHandle(_scope_key(checkout.target_scope), checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision)
            self._update_open_metadata(created_handle, str(kwargs.get("request_id", "create")) + ":project-created", project=project)
            if original_materialize is None:
                return {"project": project}
            return _call_flexible(original_materialize, checkout, initial_bytes, project=project, checkout=checkout, initial_bytes=initial_bytes)

        result = self.open(*args, materialize=materialize, **kwargs)
        if result.project_ref is None and project_box.get("project") is not None:
            return OpenResult(result.status, result.scope, result.handle, result.checkout, result.purpose, result.activity, result.waitable, self._project_ref(project_box["project"]), result.error)
        return result

    @staticmethod
    def _project_ref(project: Any) -> Optional[ResourceRef]:
        if isinstance(project, ResourceRef):
            return project
        if isinstance(project, Mapping):
            ref = project.get("ref")
            if isinstance(ref, ResourceRef):
                return ref
            if isinstance(ref, Mapping):
                return ResourceRef.from_dict(ref)
        return None

    def _open_result(self, status: str, scope: ResourceRef, payload: Mapping[str, Any], *, prior: Optional[CommandReceipt] = None) -> OpenResult:
        checkout = self._payload_checkout(payload)
        if checkout is None:
            return OpenResult(status, scope, error=prior.error_code if prior else None)
        handle = SessionHandle(_scope_key(scope), checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision, payload.get("checkout_path"))
        return OpenResult(status, scope, handle, checkout, payload.get("purpose"), payload.get("activity"), project_ref=self._project_ref(payload.get("project")), error=prior.error_code if prior else None)

    def _update_open_metadata(self, handle: SessionHandle, request_id: str, *, project: Any = None, checkout_path: Any = None, registered_files: Sequence[str] = ()) -> None:
        scope_record = _as_record(self.__writer.get_identity(handle.scope))
        if scope_record is None:
            raise InvalidSessionError("authoring scope disappeared")
        self._validate_record(handle, scope_record)
        payload = dict(scope_record.payload)
        if project is not None:
            payload["project"] = project.to_dict() if isinstance(project, ResourceRef) else project
        if checkout_path is not None:
            payload["checkout_path"] = str(checkout_path)
        if registered_files:
            payload["registered_files"] = list(registered_files)
        digest = self._request_digest("metadata", request_id, payload, target=handle.scope, actor=handle.actor)
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            assert current is not None
            self._validate_record(handle, current)
            self._mutate(tx, actor=handle.actor, operation="metadata", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"metadata": True})

    def _release_after_open_failure(self, handle: SessionHandle, request_id: str, *, project: Any, error: str) -> None:
        self._transition_release(handle, request_id, status="saved_edit_not_opened", project=project, error=error)

    def _validate_record(self, handle: SessionHandle, record: _Record, *, require_open: bool = True) -> AuthoringCheckout:
        checkout = self._payload_checkout(record.payload)
        if checkout is None or checkout.session_id != handle.session_id:
            raise InvalidSessionError("session is not current")
        if checkout.token != handle.token or checkout.fence != handle.fence:
            raise InvalidSessionError("stale authoring token or fence")
        if checkout.target_scope != handle.target_scope or checkout.actor != handle.actor:
            raise InvalidSessionError("session scope or actor does not match")
        if require_open and checkout.state != AuthoringState.OPEN:
            raise InvalidSessionError("authoring session is no longer open")
        return checkout

    def authorize_mutation(self, handle: SessionHandle, target: ResourceRef, *, token: str, fence: str, expected_base_revision: str) -> AuthoringCheckout:
        """Reject direct child/bypass mutation unless the current capability matches."""
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record)
        if target != checkout.target_scope and target.kind not in {"task", "document", "project-task", "project-document"}:
            raise InvalidSessionError("mutation is outside the canonical scope")
        if token != checkout.token or fence != checkout.fence:
            raise InvalidSessionError("direct mutation lacks the active token/fence")
        if expected_base_revision != checkout.base_revision:
            raise BaseRevisionMismatchError("expected base revision does not match checkout")
        return checkout

    def validate_session(self, handle: SessionHandle, *, require_open: bool = True) -> AuthoringCheckout:
        """Return the authenticated current checkout without exposing its owner."""
        if not isinstance(handle, SessionHandle):
            raise InvalidSessionError("session handle is not typed")
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        return self._validate_record(handle, record, require_open=require_open)

    def record_content_edit(
        self, handle: SessionHandle, *, request_id: str, timestamp: float,
    ) -> float:
        """Persist the finite idle-policy metadata delta for one open session."""
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("content-edit request_id must be non-blank")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise TypeError("content-edit timestamp must be numeric")
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        self._validate_record(handle, record)
        payload = dict(record.payload)
        value = float(timestamp)
        payload["last_content_edit_at"] = value
        payload["last_content_edit"] = value
        digest = self._request_digest(
            "metadata", request_id, payload, target=handle.scope, actor=handle.actor
        )
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            if current is None:
                raise InvalidSessionError("authoring scope disappeared")
            self._validate_record(handle, current)
            self._mutate(
                tx, actor=handle.actor, operation="metadata", request_id=request_id,
                target=handle.scope, digest=digest, record=current, payload=payload,
                effects={"last_content_edit_at": value},
            )
        return value

    def wait(self, target: ResourceRef, *, timeout: float = 5.0, poll_interval: float = 0.05, actor: Optional[AuthenticatedActor] = None, parent_scope: Optional[ResourceRef] = None) -> WaitResult:
        scope = self.resolve_scope(target, parent_scope=parent_scope)
        started = time.monotonic()
        read = self.read(scope, actor)
        while read.status == "occupied" and time.monotonic() - started < max(0.0, timeout):
            remaining = max(0.0, timeout - (time.monotonic() - started))
            if self.event_waiter is not None:
                _call_flexible(self.event_waiter, scope, remaining, scope=scope, timeout=remaining)
            else:
                time.sleep(min(max(0.0, poll_interval), remaining))
            read = self.read(scope, actor)
        return WaitResult("available" if read.status == "available" else read.status, scope, time.monotonic() - started, read)

    def autosave(self, handle: SessionHandle, *, request_id: str, snapshot: Any, activity: str = "editing") -> Snapshot:
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record)
        snap = _snapshot(snapshot, checkout.draft_snapshot_ref)
        if not isinstance(snapshot, Snapshot) and not isinstance(snapshot, Mapping):
            snap = Snapshot(ResourceRef(getattr(self.__writer, "authority", handle.scope.authority), "authoring-snapshot", "draft-" + handle.session_id + "-" + snap.digest, snap.digest), snap.data)
        payload = dict(record.payload)
        payload["draft_bytes_b64"] = b64encode(snap.data).decode("ascii")
        payload["draft_digest"] = snap.digest
        payload["draft_snapshot_ref"] = snap.ref.to_dict()
        payload["activity"] = activity
        updated_checkout = AuthoringCheckout(checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision, snap.ref, checkout.final_snapshot_ref, checkout.allowed_fields, checkout.state, checkout.cleanup, checkout.finish_claim, checkout.unmanaged_writers)
        payload["checkout"] = updated_checkout.to_dict()
        request_payload = {"session": handle.session_id, "snapshot": snap.digest, "bytes": len(snap.data), "activity": activity}
        digest = self._request_digest("autosave", request_id, request_payload, target=handle.scope, actor=handle.actor)
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            assert current is not None
            self._validate_record(handle, current)
            self._mutate(tx, actor=handle.actor, operation="autosave", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"draft_digest": snap.digest, "draft_bytes": len(snap.data)}, request_payload=request_payload)
            self._put_snapshot(tx, snap)
            self._put_refs(tx, snap.ref)
        return snap

    def _capture(self, checkout: AuthoringCheckout, capture: Any) -> Snapshot:
        default = ResourceRef(getattr(self.__writer, "authority", checkout.target_scope.authority), "authoring-snapshot", "final-" + checkout.session_id, sha256(b"").hexdigest())
        if callable(capture):
            capture = _call_flexible(capture, checkout, checkout=checkout)
        snap = _snapshot(capture, default)
        if not isinstance(capture, Snapshot) and not isinstance(capture, Mapping):
            snap = Snapshot(ResourceRef(getattr(self.__writer, "authority", checkout.target_scope.authority), "authoring-snapshot", "final-" + checkout.session_id + "-" + snap.digest, snap.digest), snap.data)
        elif isinstance(capture, Mapping) and "ref" not in capture:
            snap = Snapshot(ResourceRef(getattr(self.__writer, "authority", checkout.target_scope.authority), "authoring-snapshot", "final-" + checkout.session_id + "-" + snap.digest, snap.digest), snap.data, snap.manifest)
        if not isinstance(snap.ref, ResourceRef):
            raise CaptureError("capture did not provide a ResourceRef")
        if self.snapshot_store is not None:
            _call_flexible(self.snapshot_store, snap, snapshot=snap)
        return snap

    @staticmethod
    def _finish_request_binding(
        handle: SessionHandle, request_id: str, request_digest: str,
    ) -> Mapping[str, Any]:
        """Describe the original public finish request behind a recovery.

        The recovery command has a deliberately different logical key and
        operation.  Persisting this complete binding lets a later public
        ``finish`` retry prove which failed request created that recovery
        without inventing a receipt under the caller's key.
        """
        return {
            "logical_request_key": request_id,
            "request_digest": request_digest,
            "operation": "finish",
            "target": handle.scope.to_dict(),
            "target_scope": handle.target_scope.to_dict(),
            "actor": handle.actor.to_dict(),
            "owner": domain_contribution().owner,
            "session_id": handle.session_id,
        }

    def _capture_failure_replay(
        self,
        handle: SessionHandle,
        *,
        request_id: str,
        request_digest: str,
    ) -> Optional[FinishResult]:
        """Validate and return a prior capture-failure recovery outcome.

        This path is intentionally read-only.  The suffixed recovery receipt
        is not enough on its own: its canonical digest, source finish binding,
        event actor, released capability, and durable snapshot must all agree.
        """
        recovery_key = request_id + ":capture-failure"
        receipt = self.__writer.get_receipt(recovery_key)
        if receipt is None:
            return None

        expected_source = self._finish_request_binding(handle, request_id, request_digest)
        if receipt.operation != "finish.recovery" or receipt.target != handle.scope:
            raise ReplayConflictError("capture-failure receipt is not bound to this finish target")
        record = _as_record(self.__writer.get_identity(receipt.target))
        if record is None:
            raise ReplayConflictError("capture-failure receipt has no durable recovery result")
        recovery = record.payload.get("finish_recovery")
        if not isinstance(recovery, Mapping) or recovery.get("source_request") != expected_source:
            raise ReplayConflictError("logical request key was reused with a changed finish request")
        if recovery.get("recovery_request_key") != recovery_key or recovery.get("rejected") is not False:
            raise ReplayConflictError("capture-failure recovery binding is inconsistent")

        error = recovery.get("error")
        snapshot_digest = recovery.get("snapshot_digest")
        raw_snapshot_ref = recovery.get("snapshot_ref")
        manifest = recovery.get("manifest")
        if (
            not isinstance(error, str)
            or not isinstance(snapshot_digest, str)
            or not isinstance(raw_snapshot_ref, Mapping)
            or not isinstance(manifest, (list, tuple))
        ):
            raise ReplayConflictError("capture-failure recovery result is incomplete")
        recovery_request_payload = {
            "session": handle.session_id,
            "error": error,
            "snapshot": snapshot_digest,
            "rejected": False,
            "source_request": expected_source,
        }
        expected_recovery_digest = self._request_digest(
            "finish.recovery", recovery_key, recovery_request_payload,
            target=handle.scope, actor=handle.actor,
        )
        if receipt.request_digest != expected_recovery_digest:
            raise ReplayConflictError("capture-failure receipt digest does not match its source request")

        checkout = self._validate_record(handle, record, require_open=False)
        if checkout.state != AuthoringState.RELEASED or not record.payload.get("recovery_pending"):
            raise ReplayConflictError("capture-failure recovery is not the released pending result")
        snapshot_ref = ResourceRef.from_dict(raw_snapshot_ref)
        if (
            record.payload.get("final_digest") != snapshot_digest
            or record.payload.get("final_snapshot_ref") != snapshot_ref.to_dict()
        ):
            raise ReplayConflictError("capture-failure snapshot binding is inconsistent")
        data = self.read_snapshot(snapshot_ref)
        snapshot = Snapshot(snapshot_ref, data, tuple(manifest))
        if snapshot.digest != snapshot_digest:
            raise ReplayConflictError("capture-failure snapshot digest does not match its bytes")

        events = {
            event.event_id: event
            for event in self.__writer.list_events(stream="authoring:" + handle.scope.id)
            if event.event_id in receipt.event_ids
        }
        if set(events) != set(receipt.event_ids) or not events:
            raise ReplayConflictError("capture-failure receipt event lineage is incomplete")
        if any(
            event.operation != "finish.recovery"
            or event.actor != handle.actor
            or event.effects.get("source_request") != expected_source
            or event.effects.get("owner") != domain_contribution().owner
            for event in events.values()
        ):
            raise ReplayConflictError("capture-failure receipt event binding is inconsistent")
        return FinishResult(
            "recovery_pending", handle.scope, handle.session_id, receipt,
            checkout, snapshot, True, checkout.cleanup, error,
        )

    def read_snapshot(self, ref: ResourceRef) -> bytes:
        """Read exact snapshot bytes through the supplied FND identity port."""
        record = _as_record(self.__writer.get_identity(ref))
        if record is None or record.payload.get("type") != "authoring_snapshot":
            raise CaptureError("snapshot is not durably admitted")
        data = b64decode(record.payload.get("bytes_b64", ""))
        if sha256(data).hexdigest() != record.payload.get("digest"):
            raise CaptureError("durable snapshot digest does not match its bytes")
        return data

    def finish(
        self,
        handle: SessionHandle,
        *,
        request_id: str,
        mode: str,
        capture: Any,
        expected_base_revision: Optional[str] = None,
        apply: Optional[Callable[..., Any]] = None,
        pending: Optional[bool] = None,
        retirement_manifest: Optional[Sequence[str]] = None,
        retirement_guard: Optional[object] = None,
    ) -> FinishResult:
        """Serialize the complete typed finish operation on the common owner."""
        with self.__writer.transaction():
            return self._finish_locked(
                handle, request_id=request_id, mode=mode, capture=capture,
                expected_base_revision=expected_base_revision, apply=apply,
                pending=pending, retirement_manifest=retirement_manifest,
                retirement_guard=retirement_guard,
            )

    def _finish_locked(
        self,
        handle: SessionHandle,
        *,
        request_id: str,
        mode: str,
        capture: Any,
        expected_base_revision: Optional[str] = None,
        apply: Optional[Callable[..., Any]] = None,
        pending: Optional[bool] = None,
        retirement_manifest: Optional[Sequence[str]] = None,
        retirement_guard: Optional[object] = None,
    ) -> FinishResult:
        if mode not in {"manual", "idle"}:
            raise ValueError("finish mode must be manual or idle")
        with self._finish_lock:
            request_payload = {"session": handle.session_id, "mode": mode, "expected_base_revision": expected_base_revision, "pending": pending}
            digest = self._request_digest("finish", request_id, request_payload, target=handle.scope, actor=handle.actor)
            prior = self._prior_receipt(request_id, digest)
            if prior is not None:
                current = _as_record(self.__writer.get_identity(handle.scope))
                current_checkout = None if current is None else self._payload_checkout(current.payload)
                return FinishResult("replayed", handle.scope, handle.session_id, prior, current_checkout, recovery_pending=bool(current and current.payload.get("recovery_pending")), cleanup=current_checkout.cleanup if current_checkout else CleanupStatus.NOT_REQUESTED)
            recovered = self._capture_failure_replay(
                handle, request_id=request_id, request_digest=digest,
            )
            if recovered is not None:
                return recovered
            record = _as_record(self.__writer.get_identity(handle.scope))
            if record is None:
                raise InvalidSessionError("scope is not admitted")
            closed_checkout = self._payload_checkout(record.payload)
            if closed_checkout is not None and closed_checkout.session_id == handle.session_id and closed_checkout.token == handle.token and closed_checkout.fence == handle.fence and closed_checkout.state != AuthoringState.OPEN and closed_checkout.finish_claim is not None and closed_checkout.finish_claim.finalization_identity == "finish-" + closed_checkout.session_id:
                last_request = record.payload.get("finish_request_id")
                receipt = self.__writer.get_receipt(last_request) if isinstance(last_request, str) else None
                return FinishResult("already_finished", handle.scope, handle.session_id, receipt, closed_checkout, recovery_pending=bool(record.payload.get("recovery_pending")), cleanup=closed_checkout.cleanup)
            checkout = self._validate_record(handle, record)
            try:
                snap = self._capture(checkout, capture)
            except BaseException as exc:
                draft = Snapshot(checkout.draft_snapshot_ref, b64decode(record.payload.get("draft_bytes_b64", "")))
                source_request = self._finish_request_binding(handle, request_id, digest)
                recovery_receipt = self._transition_recovery(
                    handle, request_id + ":capture-failure", draft, str(exc),
                    retirement_guard=retirement_guard, source_request=source_request,
                )
                recovered = self._capture_failure_replay(
                    handle, request_id=request_id, request_digest=digest,
                )
                if recovered is None or recovered.receipt != recovery_receipt:
                    raise InvalidSessionError("capture-failure recovery result was not durably bound")
                return recovered
            base_expected = expected_base_revision or checkout.base_revision
            if base_expected != checkout.base_revision:
                return self._reject_finish(handle, request_id, digest, checkout, snap, "base revision mismatch", BaseRevisionMismatchError, retirement_guard=retirement_guard)
            is_pending = checkout.target_kind in {"project", "project-sheet", "pending-project"} and (pending if pending is not None else bool(record.payload.get("pending"))) and snap.data == b64decode(record.payload.get("draft_bytes_b64", ""))
            claim = FinishClaim("finish-" + checkout.session_id, mode, _opaque_id("claim"))
            scope_ref = handle.scope
            actor_ref = _actor_key(handle.actor, getattr(self.__writer, "authority", scope_ref.authority))
            try:
                with self.__writer.transaction() as tx:
                    current = _as_record(self.__writer.get_identity(scope_ref))
                    if current is None:
                        raise InvalidSessionError("scope is not admitted")
                    current_checkout = self._validate_record(handle, current)
                    if current_checkout.finish_claim is not None:
                        if current_checkout.finish_claim.finalization_identity == claim.finalization_identity:
                            return FinishResult("in_progress", scope_ref, handle.session_id, cleanup=current_checkout.cleanup)
                        raise InvalidSessionError("finish claim is not current")
                    claimed = AuthoringCheckout(current_checkout.target_scope, current_checkout.target_kind, current_checkout.actor, current_checkout.session_id, current_checkout.token, current_checkout.fence, current_checkout.base_revision, current_checkout.draft_snapshot_ref, current_checkout.final_snapshot_ref, current_checkout.allowed_fields, AuthoringState.OPEN, current_checkout.cleanup, claim, current_checkout.unmanaged_writers)
                    payload = dict(current.payload)
                    payload["checkout"] = claimed.to_dict()
                    payload["finish_claim"] = claim.to_dict()
                    payload["finish_mode"] = mode
                    payload["final_bytes_b64"] = b64encode(snap.data).decode("ascii")
                    payload["final_digest"] = snap.digest
                    payload["final_snapshot_ref"] = snap.ref.to_dict()
                    self._mutate(tx, actor=handle.actor, operation="finish.claim", request_id="claim:" + claim.finalization_identity, target=scope_ref, digest=_digest({"claim": claim.to_dict(), "session": handle.session_id}), record=current, payload=payload, effects={"claim": claim.to_dict()})
                    if apply is not None and not is_pending:
                        _call_flexible(apply, snap, claimed, tx=tx, writer=self.__writer, checkout=claimed, snapshot=snap)
                    if is_pending:
                        final_checkout = AuthoringCheckout(claimed.target_scope, claimed.target_kind, claimed.actor, claimed.session_id, claimed.token, claimed.fence, claimed.base_revision, claimed.draft_snapshot_ref, None, claimed.allowed_fields, AuthoringState.RELEASED, CleanupStatus.PENDING, claim, claimed.unmanaged_writers)
                        result_status = "pending_released"
                    else:
                        final_checkout = AuthoringCheckout(claimed.target_scope, claimed.target_kind, claimed.actor, claimed.session_id, claimed.token, claimed.fence, claimed.base_revision, claimed.draft_snapshot_ref, snap.ref, claimed.allowed_fields, AuthoringState.FINISHED, CleanupStatus.PENDING, claim, claimed.unmanaged_writers)
                        result_status = "finished"
                    final_payload = dict(payload)
                    final_payload["checkout"] = final_checkout.to_dict()
                    final_payload["recovery_pending"] = False
                    final_payload["pending"] = is_pending
                    final_payload["finish_request_id"] = request_id
                    # This is the immutable retirement handoff.  Cleanup may
                    # only use these exact per-file bytes, sizes and digests;
                    # it must not derive a new baseline from the checkout.
                    selected_manifest = validated_retirement_manifest(
                        tuple(retirement_manifest if retirement_manifest is not None else snap.manifest)
                    )
                    if tuple(snap.manifest) != selected_manifest:
                        raise InvalidSessionError("retirement manifest does not match the final snapshot")
                    final_payload["retirement_manifest"] = list(selected_manifest)
                    if retirement_guard is None:
                        final_payload.pop("retirement_fence", None)
                    else:
                        if not isinstance(retirement_guard, HeldRetirementLease):
                            raise InvalidSessionError("retirement guard is not an issued held lease")
                        issuer = getattr(retirement_guard, "issue_fence", None)
                        if not callable(issuer):
                            raise InvalidSessionError("retirement guard is not a held authenticated capability")
                        final_payload["retirement_fence"] = dict(
                            issuer(handle, selected_manifest, snapshot_digest=snap.digest)
                        )
                    receipt = self._mutate(tx, actor=handle.actor, operation="finish", request_id=request_id, target=scope_ref, digest=digest, record=_as_record(self.__writer.get_identity(scope_ref)), payload=final_payload, effects={"mode": mode, "final_digest": snap.digest, "pending": is_pending}, request_payload=request_payload)
                    actor_record = _as_record(self.__writer.get_identity(actor_ref))
                    if actor_record is not None:
                        self._mutate(tx, actor=handle.actor, operation="actor.release", request_id=request_id + ":actor-release", target=actor_ref, digest=digest, record=actor_record, payload={"type": "authoring_actor", "active": False, "scope": scope_ref.to_dict(), "session_id": handle.session_id}, effects={"session_id": handle.session_id})
                    self._put_snapshot(tx, snap)
                    self._put_refs(tx, snap.ref)
                return FinishResult(result_status, scope_ref, handle.session_id, receipt, final_checkout, snap, cleanup=final_checkout.cleanup)
            except BaseRevisionMismatchError:
                raise
            except BaseException as exc:
                recovery_receipt = self._transition_recovery(handle, request_id + ":recovery", snap, str(exc), retirement_guard=retirement_guard)
                return FinishResult("recovery_pending", scope_ref, handle.session_id, recovery_receipt, final_snapshot=snap, recovery_pending=True, cleanup=CleanupStatus.PENDING, error=str(exc))

    def _reject_finish(self, handle: SessionHandle, request_id: str, digest: str, checkout: AuthoringCheckout, snap: Snapshot, error: str, exc_type: type[Exception], *, retirement_guard: Optional[object] = None) -> FinishResult:
        self._transition_recovery(handle, request_id + ":rejected", snap, error, rejected=True, retirement_guard=retirement_guard)
        return FinishResult("rejected", handle.scope, handle.session_id, final_snapshot=snap, recovery_pending=False, cleanup=CleanupStatus.PENDING, error=error)

    def reject_finish(
        self, handle: SessionHandle, *, request_id: str, snapshot: Snapshot,
        error: str, retirement_guard: Optional[object] = None,
    ) -> FinishResult:
        """Persist the exact rejected-finish outcome for a validated snapshot."""
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("rejected-finish request_id must be non-blank")
        if not isinstance(snapshot, Snapshot):
            raise TypeError("rejected finish requires a Snapshot")
        if not isinstance(error, str) or not error:
            raise ValueError("rejected finish requires a non-blank error")
        checkout = self.validate_session(handle)
        digest = self._request_digest(
            "finish", request_id,
            {"session": handle.session_id, "rejected": True, "error": error},
            target=handle.scope, actor=handle.actor,
        )
        return self._reject_finish(
            handle, request_id, digest, checkout, snapshot, error, ValueError,
            retirement_guard=retirement_guard,
        )

    def _transition_recovery(
        self, handle: SessionHandle, request_id: str, snap: Snapshot, error: str,
        *, rejected: bool = False, retirement_guard: Optional[object] = None,
        source_request: Optional[Mapping[str, Any]] = None,
    ) -> Optional[CommandReceipt]:
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            return None
        checkout = self._payload_checkout(record.payload)
        if checkout is None:
            return None
        new_checkout = AuthoringCheckout(checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision, checkout.draft_snapshot_ref, None, checkout.allowed_fields, AuthoringState.REJECTED if rejected else AuthoringState.RELEASED, CleanupStatus.PENDING, checkout.finish_claim, checkout.unmanaged_writers)
        payload = dict(record.payload)
        payload["checkout"] = new_checkout.to_dict()
        payload["final_bytes_b64"] = b64encode(snap.data).decode("ascii")
        payload["final_digest"] = snap.digest
        payload["final_snapshot_ref"] = snap.ref.to_dict()
        manifest = validated_retirement_manifest(snap.manifest)
        payload["retirement_manifest"] = list(manifest)
        if retirement_guard is None:
            payload.pop("retirement_fence", None)
        else:
            if not isinstance(retirement_guard, HeldRetirementLease):
                raise InvalidSessionError("retirement guard is not an issued held lease")
            issuer = getattr(retirement_guard, "issue_fence", None)
            if not callable(issuer):
                raise InvalidSessionError("retirement guard is not a held authenticated capability")
            payload["retirement_fence"] = dict(issuer(handle, manifest, snapshot_digest=snap.digest))
        payload["recovery_pending"] = not rejected
        payload["error"] = error
        request_payload = None
        effects: dict[str, Any] = {"recovery_pending": not rejected, "error": error}
        if source_request is not None:
            source = dict(source_request)
            request_payload = {
                "session": handle.session_id,
                "error": error,
                "snapshot": snap.digest,
                "rejected": rejected,
                "source_request": source,
            }
            payload["finish_recovery"] = {
                "source_request": source,
                "recovery_request_key": request_id,
                "snapshot_ref": snap.ref.to_dict(),
                "snapshot_digest": snap.digest,
                "manifest": list(manifest),
                "error": error,
                "rejected": rejected,
            }
            effects.update({
                "source_request": source,
                "snapshot_digest": snap.digest,
                "owner": domain_contribution().owner,
            })
        actor_ref = _actor_key(handle.actor, getattr(self.__writer, "authority", handle.scope.authority))
        digest = _digest({"session": handle.session_id, "error": error, "snapshot": snap.digest, "rejected": rejected})
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            if current is None:
                return
            recovery_receipt = self._mutate(
                tx, actor=handle.actor, operation="finish.recovery",
                request_id=request_id, target=handle.scope, digest=digest,
                record=current, payload=payload, effects=effects,
                request_payload=request_payload,
            )
            actor_record = _as_record(self.__writer.get_identity(actor_ref))
            if actor_record is not None:
                self._mutate(tx, actor=handle.actor, operation="actor.release", request_id=request_id + ":actor", target=actor_ref, digest=digest, record=actor_record, payload={"type": "authoring_actor", "active": False, "scope": handle.scope.to_dict(), "session_id": handle.session_id}, effects={"session_id": handle.session_id})
            self._put_snapshot(tx, snap)
            self._put_refs(tx, snap.ref)
        return recovery_receipt

    def record_finish_recovery(
        self, handle: SessionHandle, *, request_id: str, snapshot: Snapshot,
        error: str, retirement_guard: Optional[object] = None,
    ) -> None:
        """Persist the exact released recovery outcome for one failed finish."""
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("finish-recovery request_id must be non-blank")
        if not isinstance(snapshot, Snapshot):
            raise TypeError("finish recovery requires a Snapshot")
        if not isinstance(error, str) or not error:
            raise ValueError("finish recovery requires a non-blank error")
        self.validate_session(handle)
        self._transition_recovery(
            handle, request_id, snapshot, error,
            retirement_guard=retirement_guard,
        )

    def refresh_final_snapshot(self, handle: SessionHandle, *, request_id: str, snapshot: Snapshot, retirement_guard: object) -> Snapshot:
        """Durably replace a released finish with a fresh retry capture.

        This is only used after unsafe cleanup.  The caller must have made a
        new stable capture/fence first; the resulting exact manifest is then
        persisted before physical deletion is attempted.
        """
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record, require_open=False)
        if checkout.state == AuthoringState.OPEN:
            raise InvalidSessionError("fresh cleanup capture requires a released checkout")
        request_payload = {
            "session": handle.session_id,
            "snapshot": snapshot.digest,
            "manifest": tuple(snapshot.manifest),
        }
        digest = self._request_digest("cleanup.refresh", request_id, request_payload, target=handle.scope, actor=handle.actor)
        if not isinstance(retirement_guard, HeldRetirementLease):
            raise InvalidSessionError("retirement guard is not an issued held lease")
        issuer = getattr(retirement_guard, "issue_fence", None)
        if not callable(issuer):
            raise InvalidSessionError("retirement guard is not a held authenticated capability")
        prior = self._prior_receipt(request_id, digest)
        if prior is not None:
            with self.__writer.transaction() as tx:
                self._mutate(
                    tx, actor=handle.actor, operation="cleanup.refresh", request_id=request_id,
                    target=handle.scope, digest=digest, record=record, payload=record.payload,
                    effects={"final_digest": snapshot.digest}, request_payload=request_payload,
                )
            return snapshot
        updated_checkout = AuthoringCheckout(
            checkout.target_scope, checkout.target_kind, checkout.actor,
            checkout.session_id, checkout.token, checkout.fence,
            checkout.base_revision, checkout.draft_snapshot_ref, snapshot.ref,
            checkout.allowed_fields, checkout.state, CleanupStatus.PENDING,
            checkout.finish_claim, checkout.unmanaged_writers,
        )
        payload = dict(record.payload)
        payload["checkout"] = updated_checkout.to_dict()
        payload["final_bytes_b64"] = b64encode(snapshot.data).decode("ascii")
        payload["final_digest"] = snapshot.digest
        payload["final_snapshot_ref"] = snapshot.ref.to_dict()
        manifest = validated_retirement_manifest(snapshot.manifest)
        payload["retirement_manifest"] = list(manifest)
        payload["retirement_fence"] = dict(issuer(handle, manifest, snapshot_digest=snapshot.digest))
        payload["recovery_pending"] = False
        payload.pop("error", None)
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            if current is None:
                raise InvalidSessionError("scope is not admitted")
            self._validate_record(handle, current, require_open=False)
            self._mutate(
                tx, actor=handle.actor, operation="cleanup.refresh", request_id=request_id,
                target=handle.scope, digest=digest, record=current, payload=payload,
                effects={"final_digest": snapshot.digest}, request_payload=request_payload,
            )
            self._put_snapshot(tx, snapshot)
            self._put_refs(tx, snapshot.ref)
        return snapshot

    def _transition_release(self, handle: SessionHandle, request_id: str, *, status: str, project: Any = None, error: Optional[str] = None) -> Optional[CommandReceipt]:
        project_value = project.to_dict() if isinstance(project, ResourceRef) else project
        request_payload = {
            "session": handle.session_id,
            "status": status,
            "project": project_value,
            "error": error,
        }
        digest = self._request_digest("release", request_id, request_payload, target=handle.scope, actor=handle.actor)
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record, require_open=False)
        prior = self._prior_receipt(request_id, digest)
        if prior is not None:
            # Capability identity is still checked above, but a valid exact
            # retry is resolved from its original receipt before the now-
            # released projection can reject the request as stale.
            with self.__writer.transaction() as tx:
                self._mutate(
                    tx, actor=handle.actor, operation="release", request_id=request_id,
                    target=handle.scope, digest=digest, record=record,
                    payload=record.payload, effects={"status": status},
                    request_payload=request_payload,
                )
            return prior
        if checkout.state != AuthoringState.OPEN:
            raise InvalidSessionError("authoring session is no longer open")
        released = AuthoringCheckout(checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision, checkout.draft_snapshot_ref, checkout.final_snapshot_ref, checkout.allowed_fields, AuthoringState.RELEASED, CleanupStatus.PENDING, checkout.finish_claim, checkout.unmanaged_writers)
        payload = dict(record.payload)
        payload["checkout"] = released.to_dict()
        payload["status"] = status
        if project is not None:
            payload["project"] = project_value
        if error:
            payload["error"] = error
        actor_ref = _actor_key(handle.actor, getattr(self.__writer, "authority", handle.scope.authority))
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            assert current is not None
            self._validate_record(handle, current)
            self._mutate(tx, actor=handle.actor, operation="release", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"status": status}, request_payload=request_payload)
            actor_record = _as_record(self.__writer.get_identity(actor_ref))
            if actor_record is not None:
                actor_payload = {"type": "authoring_actor", "active": False, "scope": handle.scope.to_dict(), "session_id": handle.session_id}
                actor_request_payload = {"scope": handle.scope.to_dict(), "session": handle.session_id, "status": status}
                self._mutate(tx, actor=handle.actor, operation="actor.release", request_id=request_id + ":actor", target=actor_ref, digest=digest, record=actor_record, payload=actor_payload, effects={"session_id": handle.session_id}, request_payload=actor_request_payload)
        return self.__writer.get_receipt(request_id)

    def release(self, handle: SessionHandle, *, request_id: str) -> FinishResult:
        receipt = self._transition_release(handle, request_id, status="released")
        record = _as_record(self.__writer.get_identity(handle.scope))
        checkout = None if record is None else self._payload_checkout(record.payload)
        return FinishResult("released", handle.scope, handle.session_id, receipt=receipt, checkout=checkout, cleanup=CleanupStatus.PENDING)

    def validate_retirement_handoff(self, handle: SessionHandle, retirement_guard: object) -> Tuple[str, ...]:
        """Validate the exact durable snapshot, manifest, fence, and held lease."""
        if not isinstance(retirement_guard, HeldRetirementLease):
            raise InvalidSessionError("authenticated retirement exclusion is not held")
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._payload_checkout(record.payload)
        if checkout is None or checkout.session_id != handle.session_id:
            raise InvalidSessionError("session is not current")
        if (
            checkout.token != handle.token
            or checkout.fence != handle.fence
            or checkout.target_scope != handle.target_scope
            or checkout.actor != handle.actor
        ):
            raise InvalidSessionError("stale authoring token or fence")
        if checkout.state == AuthoringState.OPEN:
            raise InvalidSessionError("release must precede cleanup")
        try:
            manifest = validated_retirement_manifest(record.payload.get("retirement_manifest"))
        except WriterLeaseError as exc:
            raise InvalidSessionError(str(exc)) from exc
        final_digest = record.payload.get("final_digest")
        final_ref_value = record.payload.get("final_snapshot_ref")
        if not isinstance(final_digest, str) or not isinstance(final_ref_value, Mapping):
            raise InvalidSessionError("durable retirement snapshot is absent or partial")
        try:
            final_ref = ResourceRef.from_dict(final_ref_value)
        except (TypeError, ValueError, KeyError) as exc:
            raise InvalidSessionError("durable retirement snapshot reference is malformed") from exc
        snapshot_record = _as_record(self.__writer.get_identity(final_ref))
        if snapshot_record is None:
            raise InvalidSessionError("durable retirement snapshot is absent")
        encoded_bytes = snapshot_record.payload.get("bytes_b64")
        if not isinstance(encoded_bytes, str):
            raise InvalidSessionError("durable retirement snapshot bytes are absent")
        try:
            durable_bytes = b64decode(encoded_bytes, validate=True)
        except (ValueError, TypeError) as exc:
            raise InvalidSessionError("durable retirement snapshot bytes are malformed") from exc
        if (
            snapshot_record.payload.get("type") != "authoring_snapshot"
            or snapshot_record.payload.get("digest") != final_digest
            or snapshot_record.payload.get("manifest") != list(manifest)
            or sha256(durable_bytes).hexdigest() != final_digest
        ):
            raise InvalidSessionError("durable retirement manifest does not match its snapshot")
        authenticator = getattr(retirement_guard, "authenticate_fence", None)
        if not callable(authenticator):
            raise InvalidSessionError("authenticated retirement exclusion is not held")
        try:
            authenticator(
                record.payload.get("retirement_fence"),
                handle=handle,
                manifest=manifest,
                snapshot_digest=final_digest,
            )
        except BaseException as exc:
            raise InvalidSessionError(str(exc) or "retirement fence is not authenticated") from exc
        if checkout.unmanaged_writers:
            raise InvalidSessionError("checkout has unknown or unmanaged writers")
        return manifest

    def reestablish_retirement_fence(self, handle: SessionHandle, *, request_id: str, retirement_guard: object) -> Tuple[str, ...]:
        """Authenticate a prior handoff and bind it to a newly held lease."""
        if not isinstance(retirement_guard, HeldRetirementLease):
            raise InvalidSessionError("retirement exclusion cannot be re-established")
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record, require_open=False)
        if checkout.state == AuthoringState.OPEN:
            raise InvalidSessionError("release must precede retirement reacquisition")
        try:
            manifest = validated_retirement_manifest(record.payload.get("retirement_manifest"))
        except WriterLeaseError as exc:
            raise InvalidSessionError(str(exc)) from exc
        final_digest = record.payload.get("final_digest")
        if not isinstance(final_digest, str):
            raise InvalidSessionError("durable retirement snapshot digest is absent")
        authority = getattr(retirement_guard, "authority", None)
        authenticate = getattr(authority, "authenticate_fence", None)
        issue = getattr(retirement_guard, "issue_fence", None)
        assertion = getattr(retirement_guard, "assert_held", None)
        if not callable(authenticate) or not callable(issue) or not callable(assertion):
            raise InvalidSessionError("retirement exclusion cannot be re-established")
        try:
            assertion()
            old_fence = record.payload.get("retirement_fence")
            authenticate(old_fence, handle=handle, manifest=manifest, snapshot_digest=final_digest)
            if not isinstance(old_fence, Mapping) or (
                old_fence.get("checkout_root") != getattr(retirement_guard, "root", None)
                or old_fence.get("root_dev") != getattr(retirement_guard, "root_dev", None)
                or old_fence.get("root_ino") != getattr(retirement_guard, "root_ino", None)
            ):
                raise InvalidSessionError("retirement fence belongs to a different checkout")
        except BaseException as exc:
            if isinstance(exc, InvalidSessionError):
                raise
            raise InvalidSessionError(str(exc) or "retirement exclusion cannot be re-established") from exc
        request_payload = {
            "session": handle.session_id,
            "manifest": _digest(list(manifest)),
            "snapshot": final_digest,
        }
        digest = self._request_digest(
            "cleanup.refresh", request_id, request_payload,
            target=handle.scope, actor=handle.actor,
        )
        prior = self._prior_receipt(request_id, digest)
        if prior is not None:
            with self.__writer.transaction() as tx:
                self._mutate(
                    tx, actor=handle.actor, operation="cleanup.refresh", request_id=request_id,
                    target=handle.scope, digest=digest, record=record, payload=record.payload,
                    effects={"retirement_lease": None}, request_payload=request_payload,
                )
            return manifest
        new_fence = dict(issue(handle, manifest, snapshot_digest=final_digest))
        payload = dict(record.payload)
        payload["retirement_fence"] = new_fence
        payload["recovery_pending"] = False
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            if current is None:
                raise InvalidSessionError("scope is not admitted")
            self._validate_record(handle, current, require_open=False)
            self._mutate(
                tx, actor=handle.actor, operation="cleanup.refresh", request_id=request_id,
                target=handle.scope, digest=digest, record=current, payload=payload,
                effects={"retirement_lease": new_fence.get("lease_id")}, request_payload=request_payload,
            )
        return manifest

    def cleanup(self, handle: SessionHandle, *, request_id: str, status: CleanupStatus = CleanupStatus.PENDING, retirement_guard: Optional[object] = None) -> CleanupResult:
        record = _as_record(self.__writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._payload_checkout(record.payload)
        if checkout is None or checkout.session_id != handle.session_id:
            raise InvalidSessionError("session is not current")
        if checkout.token != handle.token or checkout.fence != handle.fence or checkout.target_scope != handle.target_scope or checkout.actor != handle.actor:
            raise InvalidSessionError("stale authoring token or fence")
        if checkout.state == AuthoringState.OPEN:
            raise InvalidSessionError("release must precede cleanup")
        if status == CleanupStatus.COMPLETE:
            try:
                if retirement_guard is None:
                    raise InvalidSessionError("authenticated retirement exclusion is not held")
                self.validate_retirement_handoff(handle, retirement_guard)
            except BaseException:
                status = CleanupStatus.UNSAFE
        updated = checkout.mark_cleanup(status)
        payload = dict(record.payload)
        payload["checkout"] = updated.to_dict()
        payload["cleanup_outcome"] = status.value
        request_payload = {"session": handle.session_id, "status": status.value}
        digest = self._request_digest("cleanup", request_id, request_payload, target=handle.scope, actor=handle.actor)
        with self.__writer.transaction() as tx:
            current = _as_record(self.__writer.get_identity(handle.scope))
            assert current is not None
            self._mutate(tx, actor=handle.actor, operation="cleanup", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"cleanup": status.value}, request_payload=request_payload)
        return CleanupResult(status.value, handle.scope, handle.session_id, status)


AuthoringSessionService = command_facade(_AuthoringSessionServiceEngine, "herzchen.authoring.sessions")

# Friendly aliases used by adapters that call the port a manager or engine.
AuthoringSessionPort = AuthoringSessionService
SessionManager = AuthoringSessionService


__all__ = [
    "AUTHORING_SCHEMA_REVISION", "FND02_CONTRACT_DIGEST", "FND02_CONTRACT_REVISION",
    "domain_contribution", "register_authoring",
    "AuthoringError", "ScopeResolutionError", "OccupiedError", "ActorOccupiedError",
    "InvalidSessionError", "BaseRevisionMismatchError", "MaterializationError", "CaptureError",
    "FNDWriterPort", "Snapshot", "SessionHandle", "OpenResult", "ReadResult", "WaitResult",
    "FinishResult", "CleanupResult", "AuthoringSessionService", "AuthoringSessionPort", "SessionManager",
    "AuthoringCheckout", "AuthoringState", "FinishClaim", "CleanupStatus",
]
