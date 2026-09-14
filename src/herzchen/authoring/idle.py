"""One-shot idle-close coordination for managed authoring sessions.

This is a policy boundary, not a background scheduler.  A host may call
``close_if_idle`` from its existing poll/timer mechanism.  The function uses
the persisted/declared content-edit time, fences managed writers, delegates
capture and semantic work to EDT-03, and invokes cleanup only after the common
finish boundary has retired the token.
"""

from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime
import inspect
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Union

from herzchen.contracts import AuthoringState, CleanupStatus

from .cleanup import CleanupObservation, cleanup_registered_files
from .finish import SemanticFinishAdapter, SemanticFinishResult, ValidationResult
from .sessions import AuthoringSessionService, InvalidSessionError, SessionHandle, Snapshot
from .snapshots import DurableSnapshotAdapter


DEFAULT_IDLE_SECONDS = 15 * 60


class IdleCloseError(RuntimeError):
    """Base class for idle policy failures."""


class WriterQuiescenceError(IdleCloseError):
    """The managed writer could not be stopped or its state is unknown."""


@dataclass(frozen=True)
class IdlePolicy:
    inactivity_seconds: float = DEFAULT_IDLE_SECONDS

    def __post_init__(self) -> None:
        if isinstance(self.inactivity_seconds, bool) or self.inactivity_seconds < 0:
            raise ValueError("inactivity_seconds must be non-negative")


@dataclass(frozen=True)
class IdleCloseResult:
    status: str
    scope: Any
    session_id: str
    idle_seconds: float = 0.0
    last_content_edit: Optional[float] = None
    finish: Optional[SemanticFinishResult] = None
    cleanup: Optional[CleanupObservation] = None
    recovery_pending: bool = False
    error: Optional[str] = None

    @property
    def released(self) -> bool:
        return bool(self.finish and self.finish.finish and self.finish.finish.checkout and self.finish.finish.checkout.state != AuthoringState.OPEN)


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    signature = inspect.signature(fn)
    params = tuple(signature.parameters.values())
    positional = tuple(item.name for item in params if item.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
    accepts_kwargs = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in params)
    filtered = dict(kwargs)
    for name in positional[: len(args)]:
        filtered.pop(name, None)
    if not accepts_kwargs:
        accepted = {item.name for item in params}
        filtered = {key: value for key, value in filtered.items() if key in accepted}
    return fn(*args, **filtered)


def _epoch(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return float(value)
    return float(value)


class _PendingHandler:
    def validate(self, snapshot: Any, checkout: Any, checkout_root: str, **_: Any) -> ValidationResult:
        return ValidationResult(True)

    def apply(self, snapshot: Any, checkout: Any, tx: Any, writer: Any, **_: Any) -> None:
        return None


class IdleCloseService:
    """Coordinate one idle close attempt for an existing session handle."""

    def __init__(
        self,
        finish: Union[SemanticFinishAdapter, AuthoringSessionService, Callable[..., Any]],
        *,
        cleanup: Callable[..., CleanupObservation] = cleanup_registered_files,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.finish_adapter = finish if isinstance(finish, SemanticFinishAdapter) else None
        self.service = finish.service if isinstance(finish, SemanticFinishAdapter) else finish if isinstance(finish, AuthoringSessionService) else None
        self._finish = finish
        self._cleanup = cleanup
        self._clock = clock
        self._declared_edits: dict[str, float] = {}

    @property
    def writer(self) -> Any:
        if self.service is None:
            return None
        return self.service.writer

    def _record(self, handle: SessionHandle) -> Any:
        if self.service is None:
            return None
        return self.service.writer.get_identity(handle.scope)

    def declare_content_edit(self, handle: SessionHandle, *, timestamp: Optional[Any] = None, request_id: Optional[str] = None) -> float:
        """Persist the host's last content-edit timestamp for idle policy.

        EDT-02 predates this timestamp field, so it is an additive metadata
        annotation written through the existing session writer.  The timestamp
        is not changed by reads, heartbeats, unchanged scans, or this service's
        idle polling.
        """
        if self.service is None:
            raise IdleCloseError("content-edit declaration needs a session service")
        value = self._clock() if timestamp is None else _epoch(timestamp)
        record = self._record(handle)
        if record is None:
            raise InvalidSessionError("scope is not admitted")
        self.service._validate_record(handle, record)  # existing capability boundary; no second writer
        self._declared_edits[handle.session_id] = value
        payload = dict(record.payload)
        payload["last_content_edit_at"] = value
        payload["last_content_edit"] = value
        request = request_id or "content-edit:" + handle.session_id + ":" + str(value)
        # _update_open_metadata is the existing session-writer metadata port;
        # no independent receipt/event or persistence engine is introduced.
        self._persist_metadata(handle, request, payload)
        return value

    def _persist_metadata(self, handle: SessionHandle, request_id: str, payload: Mapping[str, Any]) -> None:
        """Persist additive idle metadata with the supplied FND/session writer."""
        if self.service is None:
            return
        service = self.service
        record = service._records(handle.target_scope, handle.actor)[0]
        if record is None:
            raise InvalidSessionError("authoring scope disappeared")
        service._validate_record(handle, record)
        digest = service._request_digest("metadata", request_id, payload)
        with service.writer.transaction() as tx:
            current = service._records(handle.target_scope, handle.actor)[0]
            if current is None:
                raise InvalidSessionError("authoring scope disappeared")
            service._validate_record(handle, current)
            service._mutate(tx, actor=handle.actor, operation="metadata", request_id=request_id, target=handle.scope, digest=digest, record=current, payload=dict(payload), effects={"last_content_edit_at": payload["last_content_edit_at"]})

    def last_content_edit(self, handle: SessionHandle, declared: Optional[Any] = None) -> Optional[float]:
        if declared is not None:
            return _epoch(declared)
        if handle.session_id in self._declared_edits:
            return self._declared_edits[handle.session_id]
        record = self._record(handle)
        payload = {} if record is None else record.payload
        for key in ("last_content_edit_at", "last_content_edit", "content_edit_at", "opened_at"):
            if payload.get(key) is not None:
                try:
                    return _epoch(payload[key])
                except (TypeError, ValueError, OverflowError):
                    return None
        return None

    @staticmethod
    def _writer_result(value: Any) -> bool:
        return value is True or value in {"quiescent", "idle", "stopped"}

    def _quiesce(self, quiesce: Optional[Callable[..., Any]], writer_check: Optional[Callable[[], Any]]) -> None:
        if quiesce is not None:
            try:
                value = _call(quiesce)
            except BaseException as exc:
                raise WriterQuiescenceError("managed writer could not be quiesced") from exc
            if value is False or value is None or (isinstance(value, str) and value in {"active", "open", "writing", "unknown"}):
                raise WriterQuiescenceError("managed writer did not acknowledge quiescence")
        if writer_check is not None:
            try:
                value = writer_check()
            except BaseException as exc:
                raise WriterQuiescenceError("managed writer state is unknown") from exc
            if not self._writer_result(value):
                raise WriterQuiescenceError("managed writer is active or unknown")

    def _finish_call(self, handle: SessionHandle, **kwargs: Any) -> SemanticFinishResult:
        if self.finish_adapter is not None:
            return self.finish_adapter.finish(handle, **kwargs)
        if self.service is not None:
            checkout_root = kwargs.pop("checkout_root")
            registered_files = kwargs.pop("registered_files", ())
            kwargs.pop("handler", None)
            snapshot_adapter = DurableSnapshotAdapter(self.service)
            tree = snapshot_adapter.capture(checkout_root, registered_files)
            snap = tree.as_session_snapshot(snapshot_adapter._ref(handle, "final", tree.tree_digest))
            result = self.service.finish(handle, capture=snap, **kwargs)
            return SemanticFinishResult(result.status, result, recovery_pending=result.recovery_pending, error=result.error)
        value = _call(self._finish, handle, **kwargs)
        return value

    def _untouched_pending_finish(self, handle: SessionHandle, checkout_root: Any, files: Iterable[Any], *, request_id: str, pending: Optional[bool]) -> Optional[SemanticFinishResult]:
        """Use the common finish boundary without inventing a blank revision.

        EDT-02 stores the opening bytes as a scalar draft.  EDT-03's normal
        tree adapter stores a packed multi-file envelope, so an unchanged
        single-file pending starter would otherwise look changed.  Capture it
        through the existing snapshot adapter first, then pass the exact
        opening bytes to the same session ``finish`` operation; no handler or
        domain application is needed for this no-change pending close.
        """
        if self.finish_adapter is None or self.service is None or pending is False:
            return None
        record = self._record(handle)
        if record is None or not bool(record.payload.get("pending")):
            return None
        try:
            tree = self.finish_adapter.snapshots.capture(checkout_root, files, settled=True)
            initial = b64decode(record.payload.get("draft_bytes_b64", ""))
            if len(tree.files) != 1 or tree.files[0].data != initial:
                return None
            checkout = self.service._payload_checkout(record.payload)
            if checkout is None:
                return None
            result = self.service.finish(
                handle,
                request_id=request_id,
                mode="idle",
                capture=Snapshot(checkout.draft_snapshot_ref, initial),
                expected_base_revision=None,
                apply=None,
                pending=True,
            )
            return SemanticFinishResult(result.status, result, tree, ValidationResult(True), recovery_pending=result.recovery_pending, error=result.error)
        except BaseException:
            # Fall through to the normal semantic capture path so a failure
            # remains an EDT-03 recovery outcome with exact bytes.
            return None

    def _cleanup_after_release(self, handle: SessionHandle, checkout_root: Any, files: Iterable[Any], *, request_id: str, writer_check: Optional[Callable[[], Any]]) -> IdleCloseResult:
        try:
            observation = self._cleanup(checkout_root, files, writer_check=writer_check)
        except BaseException as exc:
            observation = CleanupObservation(CleanupStatus.PENDING, str(checkout_root), error=str(exc))
        if self.service is not None:
            try:
                self.service.cleanup(handle, request_id=request_id + ":cleanup", status=observation.status)
            except BaseException as exc:
                return IdleCloseResult("cleanup_pending", handle.scope, handle.session_id, cleanup=observation, recovery_pending=True, error=str(exc))
        return IdleCloseResult("closed_cleaned" if observation.status == CleanupStatus.COMPLETE else "cleanup_pending", handle.scope, handle.session_id, cleanup=observation, recovery_pending=observation.status != CleanupStatus.COMPLETE, error=observation.error)

    def close_if_idle(
        self,
        handle: SessionHandle,
        *,
        request_id: str,
        checkout_root: Union[str, Any],
        registered_files: Optional[Iterable[Any]] = None,
        handler: Optional[Any] = None,
        inactivity_seconds: float = DEFAULT_IDLE_SECONDS,
        last_content_edit: Optional[Any] = None,
        now: Optional[Any] = None,
        quiesce: Optional[Callable[..., Any]] = None,
        writer_check: Optional[Callable[[], Any]] = None,
        pending: Optional[bool] = None,
        expected_base_revision: Optional[str] = None,
        hook_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> IdleCloseResult:
        """Attempt an idle close; return an honest retryable outcome."""
        if inactivity_seconds < 0 or isinstance(inactivity_seconds, bool):
            raise ValueError("inactivity_seconds must be non-negative")
        current = self._record(handle)
        if current is not None:
            checkout = current.payload.get("checkout")
            if isinstance(checkout, Mapping) and checkout.get("state") != AuthoringState.OPEN.value:
                current_files = registered_files if registered_files is not None else current.payload.get("registered_files", ())
                if checkout.get("cleanup") != CleanupStatus.COMPLETE.value:
                    return self._cleanup_after_release(handle, checkout_root, current_files or (), request_id=request_id, writer_check=writer_check)
                return IdleCloseResult("already_closed", handle.scope, handle.session_id, error="authoring session is already closed")
        edit = self.last_content_edit(handle, last_content_edit)
        observed = self._clock() if now is None else _epoch(now)
        if edit is None:
            return IdleCloseResult("recovery_pending", handle.scope, handle.session_id, recovery_pending=True, error="last content-edit timestamp is unavailable")
        idle_for = max(0.0, observed - edit)
        if idle_for < inactivity_seconds:
            return IdleCloseResult("not_idle", handle.scope, handle.session_id, idle_for, edit)
        try:
            self._quiesce(quiesce, writer_check)
        except BaseException as exc:
            return IdleCloseResult("writer_active", handle.scope, handle.session_id, idle_for, edit, recovery_pending=True, error=str(exc))

        files = registered_files
        if files is None and current is not None:
            files = current.payload.get("registered_files", ())
        try:
            finish = self._untouched_pending_finish(handle, checkout_root, files or (), request_id=request_id, pending=pending)
            if finish is None:
                finish = self._finish_call(
                    handle,
                    request_id=request_id,
                    mode="idle",
                    checkout_root=checkout_root,
                    registered_files=files or (),
                    handler=handler or _PendingHandler(),
                    expected_base_revision=expected_base_revision,
                    pending=pending,
                    **dict(hook_kwargs or {}),
                )
        except BaseException as exc:
            return IdleCloseResult("recovery_pending", handle.scope, handle.session_id, idle_for, edit, recovery_pending=True, error=str(exc))
        result = IdleCloseResult(finish.status, handle.scope, handle.session_id, idle_for, edit, finish, recovery_pending=finish.recovery_pending, error=finish.error)
        # Capture/persistence/application uncertainty intentionally retains the
        # physical files.  A rejected draft is durable and released, so it is
        # safe to clean only after that preservation boundary has completed.
        if finish.status == "failed" and finish.recovery_pending:
            return IdleCloseResult("recovery_pending", handle.scope, handle.session_id, idle_for, edit, finish, recovery_pending=True, error=finish.error)
        if finish.status not in {"finished", "pending_released", "rejected", "already_finished", "replayed"} or finish.finish is None:
            return result
        try:
            observation = self._cleanup(checkout_root, files or (), writer_check=writer_check)
        except BaseException as exc:
            observation = CleanupObservation(CleanupStatus.PENDING, str(checkout_root), error=str(exc))
        if self.service is not None:
            try:
                self.service.cleanup(handle, request_id=request_id + ":cleanup", status=observation.status)
            except BaseException as exc:
                return IdleCloseResult("cleanup_pending", handle.scope, handle.session_id, idle_for, edit, finish, observation, recovery_pending=True, error=str(exc))
        status = "closed_cleaned" if observation.status == CleanupStatus.COMPLETE else "cleanup_pending"
        return IdleCloseResult(status, handle.scope, handle.session_id, idle_for, edit, finish, observation, recovery_pending=observation.status != CleanupStatus.COMPLETE, error=observation.error or finish.error)

    def check(self, *args: Any, **kwargs: Any) -> IdleCloseResult:
        return self.close_if_idle(*args, **kwargs)

    record_content_edit = declare_content_edit


IdleCloser = IdleCloseService
IdleCloseCoordinator = IdleCloseService
idle_close = IdleCloseService.close_if_idle


__all__ = [
    "DEFAULT_IDLE_SECONDS", "IdleCloseError", "WriterQuiescenceError", "IdlePolicy", "IdleCloseResult",
    "IdleCloseService", "IdleCloser", "IdleCloseCoordinator", "idle_close",
]
