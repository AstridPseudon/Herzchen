"""Exclusive managed-local authoring sessions.

EDT owns the lifecycle semantics in this module.  Durable state is deliberately
represented as ordinary FND identities, references, receipts, and events.  A
writer is injected at the boundary; this module has no database or event store
of its own.

The implementation is intentionally conservative about files.  A materializer
and snapshot port may be supplied by a host, but this layer never recursively
deletes a checkout and never claims EDT-04's descriptor-relative race proof.
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

from herzchen.contracts import (
    AuthenticatedActor,
    AuthoringCheckout,
    AuthoringState,
    CleanupStatus,
    CommandEnvelope,
    CommandReceipt,
    FinishClaim,
    ReceiptStatus,
    ReplayConflictError,
    ResourceRef,
    TransactionContext,
    canonical_json,
)


FND02_CONTRACT_REVISION = "fnd-02.v1.1"
FND02_CONTRACT_DIGEST = "28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264"
AUTHORING_SCHEMA_REVISION = "edt-02.authoring.v1"


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


class AuthoringSessionService:
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
        self.writer = writer
        self.scope_resolver = scope_resolver
        self.event_waiter = event_waiter
        self.materializer = materializer
        self.snapshot_store = snapshot_store
        self._finish_lock = threading.RLock()

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
        authority = getattr(self.writer, "authority", scope.authority)
        scope_record = _as_record(self.writer.get_identity(_scope_key(scope)))
        actor_record = _as_record(self.writer.get_identity(_actor_key(actor, authority)))
        return scope_record, actor_record

    @staticmethod
    def _payload_checkout(payload: Mapping[str, Any]) -> Optional[AuthoringCheckout]:
        value = payload.get("checkout")
        return None if value is None else AuthoringCheckout.from_dict(value)

    @staticmethod
    def _active(payload: Mapping[str, Any]) -> bool:
        checkout = AuthoringSessionService._payload_checkout(payload)
        return checkout is not None and checkout.state == AuthoringState.OPEN

    @staticmethod
    def _actor_active(payload: Mapping[str, Any]) -> bool:
        return bool(payload.get("active")) and payload.get("type") == "authoring_actor"

    @staticmethod
    def _masked_read(scope: ResourceRef, payload: Optional[Mapping[str, Any]], *, holder: bool = False) -> ReadResult:
        if not payload or not AuthoringSessionService._active(payload):
            return ReadResult("available", scope)
        checkout = AuthoringSessionService._payload_checkout(payload)
        assert checkout is not None
        if holder:
            return ReadResult("open", scope, checkout, payload.get("purpose"), payload.get("activity"))
        return ReadResult("occupied", scope, None, payload.get("purpose"), payload.get("activity"))

    def read(self, target: ResourceRef, actor: Optional[AuthenticatedActor] = None, *, parent_scope: Optional[ResourceRef] = None) -> ReadResult:
        scope = self.resolve_scope(target, parent_scope=parent_scope)
        record = _as_record(self.writer.get_identity(_scope_key(scope)))
        payload = {} if record is None else record.payload
        holder = bool(actor and self._active(payload) and self._payload_checkout(payload).actor == actor)  # type: ignore[union-attr]
        return self._masked_read(scope, payload, holder=holder)

    def _request_digest(self, operation: str, request_id: str, values: Mapping[str, Any]) -> str:
        return _digest({"operation": operation, "request_id": request_id, "values": values})

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
        payload: Optional[Mapping[str, Any]] = None,
    ) -> CommandEnvelope:
        return CommandEnvelope(
            operation,
            AUTHORING_SCHEMA_REVISION,
            target,
            TransactionContext(actor, request_id, digest, revision, version, edit_token),
            dict(payload or {}),
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
        no_op: bool = False,
    ) -> CommandReceipt:
        envelope = self._envelope(
            actor, operation, request_id, target, digest,
            revision=None if record is None else record.ref.revision,
            version=0 if record is None else record.version,
            edit_token=None if record is None else record.edit_token,
            payload=payload,
        )
        return self.writer.mutate(
            envelope,
            event_type="authoring." + operation,
            effects=dict(effects),
            stream="authoring:" + target.id,
            transaction=tx,
            no_op=no_op,
        )

    def _put_refs(self, tx: Any, *refs: Optional[ResourceRef]) -> None:
        for ref in refs:
            if ref is not None:
                self.writer.put_reference(ref, transaction=tx)

    def _put_snapshot(self, tx: Any, snapshot: Snapshot) -> None:
        self.writer.put_identity(
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
        purpose: str,
        activity: str,
    ) -> Tuple[AuthoringCheckout, Snapshot, SessionHandle, Mapping[str, Any]]:
        session_id = _opaque_id("session")
        token = _opaque_id("token")
        fence = _opaque_id("fence")
        draft = Snapshot(ResourceRef(getattr(self.writer, "authority", scope.authority), "authoring-snapshot", "draft-" + session_id, sha256(initial_bytes).hexdigest()), initial_bytes)
        checkout = AuthoringCheckout(scope, target_kind, actor, session_id, token, fence, base_revision, draft.ref, None, tuple(allowed_fields))
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
        prior = self.writer.get_receipt(request_id)
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
        materialize: Optional[Callable[..., Any]] = None,
        project: Optional[Mapping[str, Any]] = None,
    ) -> OpenResult:
        scope = self.resolve_scope(target, parent_scope=parent_scope)
        actor = actor
        target_kind = target_kind or target.kind
        base_revision = base_revision or target.revision or "initial"
        initial_bytes = _bytes(initial_content)
        values = {"scope": scope.to_dict(), "target": target.to_dict(), "target_kind": target_kind, "base_revision": base_revision, "purpose": purpose, "activity": activity, "allowed_fields": tuple(allowed_fields), "initial_digest": sha256(initial_bytes).hexdigest(), "pending": pending, "project": project}
        digest = self._request_digest("open", request_id, values)
        scope_ref = _scope_key(scope)

        authority = getattr(self.writer, "authority", scope.authority)
        actor_ref = _actor_key(actor, authority)
        materializer = materialize or self.materializer
        try:
            # The supplied FND transaction/Store owner serializes the complete
            # check-and-reserve unit across all service instances.
            with self.writer.transaction() as tx:
                prior = self._prior_receipt(request_id, digest)
                if prior is not None:
                    record = _as_record(self.writer.get_identity(scope_ref))
                    if record is not None and self._active(record.payload):
                        return self._open_result("replayed", scope, record.payload, prior=prior)
                    if record is not None and record.payload.get("status") == "saved_project_edit_not_opened":
                        return self._open_result("saved_project_edit_not_opened", scope, record.payload, prior=prior)
                    return OpenResult("replayed", scope, error=prior.error_code)
                scope_record = _as_record(self.writer.get_identity(scope_ref))
                actor_record = _as_record(self.writer.get_identity(actor_ref))
                if scope_record is not None and self._active(scope_record.payload):
                    return OpenResult("occupied", scope, purpose=scope_record.payload.get("purpose"), activity=scope_record.payload.get("activity"), error="scope is occupied")
                if actor_record is not None and self._actor_active(actor_record.payload):
                    return OpenResult("actor_occupied", scope, purpose=actor_record.payload.get("purpose"), activity=actor_record.payload.get("activity"), error="actor already occupies a scope")

                checkout, draft, handle, payload = self._new_checkout(scope, actor, target_kind, base_revision, allowed_fields, initial_bytes, pending=pending, purpose=purpose, activity=activity)
                self._mutate(tx, actor=actor, operation="actor.open", request_id=request_id + ":actor", target=actor_ref, digest=digest, record=actor_record, payload={"type": "authoring_actor", "active": True, "scope": scope.to_dict(), "session_id": checkout.session_id, "purpose": purpose, "activity": activity}, effects={"scope": scope.id, "session_id": checkout.session_id})
                receipt = self._mutate(tx, actor=actor, operation="open", request_id=request_id, target=scope_ref, digest=digest, record=scope_record, payload=payload, effects={"session_id": checkout.session_id, "scope": scope.id})
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
        scope_record = _as_record(self.writer.get_identity(handle.scope))
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
        digest = self._request_digest("metadata", request_id, payload)
        with self.writer.transaction() as tx:
            current = _as_record(self.writer.get_identity(handle.scope))
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
        record = _as_record(self.writer.get_identity(handle.scope))
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
        record = _as_record(self.writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record)
        snap = _snapshot(snapshot, checkout.draft_snapshot_ref)
        if not isinstance(snapshot, Snapshot) and not isinstance(snapshot, Mapping):
            snap = Snapshot(ResourceRef(getattr(self.writer, "authority", handle.scope.authority), "authoring-snapshot", "draft-" + handle.session_id + "-" + snap.digest, snap.digest), snap.data)
        payload = dict(record.payload)
        payload["draft_bytes_b64"] = b64encode(snap.data).decode("ascii")
        payload["draft_digest"] = snap.digest
        payload["draft_snapshot_ref"] = snap.ref.to_dict()
        payload["activity"] = activity
        updated_checkout = AuthoringCheckout(checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision, snap.ref, checkout.final_snapshot_ref, checkout.allowed_fields, checkout.state, checkout.cleanup, checkout.finish_claim, checkout.unmanaged_writers)
        payload["checkout"] = updated_checkout.to_dict()
        digest = self._request_digest("autosave", request_id, {"session": handle.session_id, "snapshot": snap.digest, "bytes": len(snap.data), "activity": activity})
        with self.writer.transaction() as tx:
            current = _as_record(self.writer.get_identity(handle.scope))
            assert current is not None
            self._validate_record(handle, current)
            self._mutate(tx, actor=handle.actor, operation="autosave", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"draft_digest": snap.digest, "draft_bytes": len(snap.data)})
            self._put_snapshot(tx, snap)
            self._put_refs(tx, snap.ref)
        return snap

    def _capture(self, checkout: AuthoringCheckout, capture: Any) -> Snapshot:
        default = ResourceRef(getattr(self.writer, "authority", checkout.target_scope.authority), "authoring-snapshot", "final-" + checkout.session_id, sha256(b"").hexdigest())
        if callable(capture):
            capture = _call_flexible(capture, checkout, checkout=checkout)
        snap = _snapshot(capture, default)
        if not isinstance(capture, Snapshot) and not isinstance(capture, Mapping):
            snap = Snapshot(ResourceRef(getattr(self.writer, "authority", checkout.target_scope.authority), "authoring-snapshot", "final-" + checkout.session_id + "-" + snap.digest, snap.digest), snap.data)
        elif isinstance(capture, Mapping) and "ref" not in capture:
            snap = Snapshot(ResourceRef(getattr(self.writer, "authority", checkout.target_scope.authority), "authoring-snapshot", "final-" + checkout.session_id + "-" + snap.digest, snap.digest), snap.data, snap.manifest)
        if not isinstance(snap.ref, ResourceRef):
            raise CaptureError("capture did not provide a ResourceRef")
        if self.snapshot_store is not None:
            _call_flexible(self.snapshot_store, snap, snapshot=snap)
        return snap

    def read_snapshot(self, ref: ResourceRef) -> bytes:
        """Read exact snapshot bytes through the supplied FND identity port."""
        record = _as_record(self.writer.get_identity(ref))
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
    ) -> FinishResult:
        if mode not in {"manual", "idle"}:
            raise ValueError("finish mode must be manual or idle")
        with self._finish_lock:
            record = _as_record(self.writer.get_identity(handle.scope))
            if record is None:
                raise InvalidSessionError("scope is not admitted")
            digest = self._request_digest("finish", request_id, {"session": handle.session_id, "mode": mode, "expected_base_revision": expected_base_revision, "pending": pending})
            prior = self._prior_receipt(request_id, digest)
            if prior is not None:
                current = _as_record(self.writer.get_identity(handle.scope))
                current_checkout = None if current is None else self._payload_checkout(current.payload)
                return FinishResult("replayed", handle.scope, handle.session_id, prior, current_checkout, recovery_pending=bool(current and current.payload.get("recovery_pending")), cleanup=current_checkout.cleanup if current_checkout else CleanupStatus.NOT_REQUESTED)
            closed_checkout = self._payload_checkout(record.payload)
            if closed_checkout is not None and closed_checkout.session_id == handle.session_id and closed_checkout.token == handle.token and closed_checkout.fence == handle.fence and closed_checkout.state != AuthoringState.OPEN and closed_checkout.finish_claim is not None and closed_checkout.finish_claim.finalization_identity == "finish-" + closed_checkout.session_id:
                last_request = record.payload.get("finish_request_id")
                receipt = self.writer.get_receipt(last_request) if isinstance(last_request, str) else None
                return FinishResult("already_finished", handle.scope, handle.session_id, receipt, closed_checkout, recovery_pending=bool(record.payload.get("recovery_pending")), cleanup=closed_checkout.cleanup)
            checkout = self._validate_record(handle, record)
            try:
                snap = self._capture(checkout, capture)
            except BaseException as exc:
                draft = Snapshot(checkout.draft_snapshot_ref, b64decode(record.payload.get("draft_bytes_b64", "")))
                self._transition_recovery(handle, request_id + ":capture-failure", draft, str(exc))
                return FinishResult("recovery_pending", handle.scope, handle.session_id, final_snapshot=draft, recovery_pending=True, cleanup=CleanupStatus.PENDING, error=str(exc))
            base_expected = expected_base_revision or checkout.base_revision
            if base_expected != checkout.base_revision:
                return self._reject_finish(handle, request_id, digest, checkout, snap, "base revision mismatch", BaseRevisionMismatchError)
            is_pending = checkout.target_kind in {"project", "project-sheet", "pending-project"} and (pending if pending is not None else bool(record.payload.get("pending"))) and snap.data == b64decode(record.payload.get("draft_bytes_b64", ""))
            claim = FinishClaim("finish-" + checkout.session_id, mode, _opaque_id("claim"))
            scope_ref = handle.scope
            actor_ref = _actor_key(handle.actor, getattr(self.writer, "authority", scope_ref.authority))
            try:
                with self.writer.transaction() as tx:
                    current = _as_record(self.writer.get_identity(scope_ref))
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
                        _call_flexible(apply, snap, claimed, tx=tx, writer=self.writer, checkout=claimed, snapshot=snap)
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
                    final_payload["retirement_manifest"] = list(retirement_manifest if retirement_manifest is not None else snap.manifest)
                    final_payload["retirement_fence"] = {
                        "session_id": claimed.session_id,
                        "token": claimed.token,
                        "fence": claimed.fence,
                        "manifest_digest": _digest(list(retirement_manifest if retirement_manifest is not None else snap.manifest)),
                    }
                    receipt = self._mutate(tx, actor=handle.actor, operation="finish", request_id=request_id, target=scope_ref, digest=digest, record=_as_record(self.writer.get_identity(scope_ref)), payload=final_payload, effects={"mode": mode, "final_digest": snap.digest, "pending": is_pending})
                    actor_record = _as_record(self.writer.get_identity(actor_ref))
                    if actor_record is not None:
                        self._mutate(tx, actor=handle.actor, operation="actor.release", request_id=request_id + ":actor-release", target=actor_ref, digest=digest, record=actor_record, payload={"type": "authoring_actor", "active": False, "scope": scope_ref.to_dict(), "session_id": handle.session_id}, effects={"session_id": handle.session_id})
                    self._put_snapshot(tx, snap)
                    self._put_refs(tx, snap.ref)
                return FinishResult(result_status, scope_ref, handle.session_id, receipt, final_checkout, snap, cleanup=final_checkout.cleanup)
            except BaseRevisionMismatchError:
                raise
            except BaseException as exc:
                self._transition_recovery(handle, request_id + ":recovery", snap, str(exc))
                return FinishResult("recovery_pending", scope_ref, handle.session_id, final_snapshot=snap, recovery_pending=True, cleanup=CleanupStatus.PENDING, error=str(exc))

    def _reject_finish(self, handle: SessionHandle, request_id: str, digest: str, checkout: AuthoringCheckout, snap: Snapshot, error: str, exc_type: type[Exception]) -> FinishResult:
        self._transition_recovery(handle, request_id + ":rejected", snap, error, rejected=True)
        return FinishResult("rejected", handle.scope, handle.session_id, final_snapshot=snap, recovery_pending=False, cleanup=CleanupStatus.PENDING, error=error)

    def _transition_recovery(self, handle: SessionHandle, request_id: str, snap: Snapshot, error: str, *, rejected: bool = False) -> None:
        record = _as_record(self.writer.get_identity(handle.scope))
        if record is None:
            return
        checkout = self._payload_checkout(record.payload)
        if checkout is None:
            return
        new_checkout = AuthoringCheckout(checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision, checkout.draft_snapshot_ref, None, checkout.allowed_fields, AuthoringState.REJECTED if rejected else AuthoringState.RELEASED, CleanupStatus.PENDING, checkout.finish_claim, checkout.unmanaged_writers)
        payload = dict(record.payload)
        payload["checkout"] = new_checkout.to_dict()
        payload["final_bytes_b64"] = b64encode(snap.data).decode("ascii")
        payload["final_digest"] = snap.digest
        payload["final_snapshot_ref"] = snap.ref.to_dict()
        payload["retirement_manifest"] = list(snap.manifest)
        payload["retirement_fence"] = {
            "session_id": checkout.session_id,
            "token": checkout.token,
            "fence": checkout.fence,
            "manifest_digest": _digest(list(snap.manifest)),
        }
        payload["recovery_pending"] = not rejected
        payload["error"] = error
        actor_ref = _actor_key(handle.actor, getattr(self.writer, "authority", handle.scope.authority))
        digest = _digest({"session": handle.session_id, "error": error, "snapshot": snap.digest, "rejected": rejected})
        with self.writer.transaction() as tx:
            current = _as_record(self.writer.get_identity(handle.scope))
            if current is None:
                return
            self._mutate(tx, actor=handle.actor, operation="finish.recovery", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"recovery_pending": not rejected, "error": error})
            actor_record = _as_record(self.writer.get_identity(actor_ref))
            if actor_record is not None:
                self._mutate(tx, actor=handle.actor, operation="actor.release", request_id=request_id + ":actor", target=actor_ref, digest=digest, record=actor_record, payload={"type": "authoring_actor", "active": False, "scope": handle.scope.to_dict(), "session_id": handle.session_id}, effects={"session_id": handle.session_id})
            self._put_snapshot(tx, snap)
            self._put_refs(tx, snap.ref)

    def refresh_final_snapshot(self, handle: SessionHandle, *, request_id: str, snapshot: Snapshot) -> Snapshot:
        """Durably replace a released finish with a fresh retry capture.

        This is only used after unsafe cleanup.  The caller must have made a
        new stable capture/fence first; the resulting exact manifest is then
        persisted before physical deletion is attempted.
        """
        record = _as_record(self.writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record, require_open=False)
        if checkout.state == AuthoringState.OPEN:
            raise InvalidSessionError("fresh cleanup capture requires a released checkout")
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
        payload["retirement_manifest"] = list(snapshot.manifest)
        payload["retirement_fence"] = {
            "session_id": updated_checkout.session_id,
            "token": updated_checkout.token,
            "fence": updated_checkout.fence,
            "manifest_digest": _digest(list(snapshot.manifest)),
        }
        payload["recovery_pending"] = False
        payload.pop("error", None)
        digest = self._request_digest("cleanup.refresh", request_id, {"session": handle.session_id, "snapshot": snapshot.digest})
        with self.writer.transaction() as tx:
            current = _as_record(self.writer.get_identity(handle.scope))
            if current is None:
                raise InvalidSessionError("scope is not admitted")
            self._validate_record(handle, current, require_open=False)
            self._mutate(
                tx, actor=handle.actor, operation="cleanup.refresh", request_id=request_id,
                target=handle.scope, digest=digest, record=current, payload=payload,
                effects={"final_digest": snapshot.digest},
            )
            self._put_snapshot(tx, snapshot)
            self._put_refs(tx, snapshot.ref)
        return snapshot

    def _transition_release(self, handle: SessionHandle, request_id: str, *, status: str, project: Any = None, error: Optional[str] = None) -> None:
        record = _as_record(self.writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._validate_record(handle, record)
        released = AuthoringCheckout(checkout.target_scope, checkout.target_kind, checkout.actor, checkout.session_id, checkout.token, checkout.fence, checkout.base_revision, checkout.draft_snapshot_ref, checkout.final_snapshot_ref, checkout.allowed_fields, AuthoringState.RELEASED, CleanupStatus.PENDING, checkout.finish_claim, checkout.unmanaged_writers)
        payload = dict(record.payload)
        payload["checkout"] = released.to_dict()
        payload["status"] = status
        if project is not None:
            payload["project"] = project.to_dict() if isinstance(project, ResourceRef) else project
        if error:
            payload["error"] = error
        actor_ref = _actor_key(handle.actor, getattr(self.writer, "authority", handle.scope.authority))
        digest = _digest({"status": status, "session": handle.session_id, "error": error})
        with self.writer.transaction() as tx:
            current = _as_record(self.writer.get_identity(handle.scope))
            assert current is not None
            self._validate_record(handle, current)
            self._mutate(tx, actor=handle.actor, operation="release", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"status": status})
            actor_record = _as_record(self.writer.get_identity(actor_ref))
            if actor_record is not None:
                self._mutate(tx, actor=handle.actor, operation="actor.release", request_id=request_id + ":actor", target=actor_ref, digest=digest, record=actor_record, payload={"type": "authoring_actor", "active": False, "scope": handle.scope.to_dict(), "session_id": handle.session_id}, effects={"session_id": handle.session_id})

    def release(self, handle: SessionHandle, *, request_id: str) -> FinishResult:
        self._transition_release(handle, request_id, status="released")
        record = _as_record(self.writer.get_identity(handle.scope))
        checkout = None if record is None else self._payload_checkout(record.payload)
        return FinishResult("released", handle.scope, handle.session_id, checkout=checkout, cleanup=CleanupStatus.PENDING)

    def cleanup(self, handle: SessionHandle, *, request_id: str, status: CleanupStatus = CleanupStatus.PENDING) -> CleanupResult:
        record = _as_record(self.writer.get_identity(handle.scope))
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        checkout = self._payload_checkout(record.payload)
        if checkout is None or checkout.session_id != handle.session_id:
            raise InvalidSessionError("session is not current")
        if checkout.token != handle.token or checkout.fence != handle.fence or checkout.target_scope != handle.target_scope or checkout.actor != handle.actor:
            raise InvalidSessionError("stale authoring token or fence")
        retirement_fence = record.payload.get("retirement_fence")
        retirement_manifest = record.payload.get("retirement_manifest")
        if isinstance(retirement_fence, Mapping) and isinstance(retirement_manifest, list):
            if (
                retirement_fence.get("session_id") != checkout.session_id
                or retirement_fence.get("token") != checkout.token
                or retirement_fence.get("fence") != checkout.fence
                or retirement_fence.get("manifest_digest") != _digest(retirement_manifest)
            ):
                raise InvalidSessionError("retirement fence does not match the captured manifest")
        if checkout.state == AuthoringState.OPEN:
            raise InvalidSessionError("release must precede cleanup")
        if status == CleanupStatus.COMPLETE and checkout.unmanaged_writers:
            status = CleanupStatus.UNSAFE
        updated = checkout.mark_cleanup(status)
        payload = dict(record.payload)
        payload["checkout"] = updated.to_dict()
        payload["cleanup_outcome"] = status.value
        digest = self._request_digest("cleanup", request_id, {"session": handle.session_id, "status": status.value})
        with self.writer.transaction() as tx:
            current = _as_record(self.writer.get_identity(handle.scope))
            assert current is not None
            self._mutate(tx, actor=handle.actor, operation="cleanup", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=payload, effects={"cleanup": status.value})
        return CleanupResult(status.value, handle.scope, handle.session_id, status)


# Friendly aliases used by adapters that call the port a manager or engine.
AuthoringSessionPort = AuthoringSessionService
SessionManager = AuthoringSessionService


__all__ = [
    "AUTHORING_SCHEMA_REVISION", "FND02_CONTRACT_DIGEST", "FND02_CONTRACT_REVISION",
    "AuthoringError", "ScopeResolutionError", "OccupiedError", "ActorOccupiedError",
    "InvalidSessionError", "BaseRevisionMismatchError", "MaterializationError", "CaptureError",
    "FNDWriterPort", "Snapshot", "SessionHandle", "OpenResult", "ReadResult", "WaitResult",
    "FinishResult", "CleanupResult", "AuthoringSessionService", "AuthoringSessionPort", "SessionManager",
    "AuthoringCheckout", "AuthoringState", "FinishClaim", "CleanupStatus",
]
