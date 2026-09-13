"""Small target-neutral semantic finish adapter.

Handlers own product meaning and domain deltas.  This module only captures a
stable tree, asks the handler to validate it, and delegates the durable finish
boundary to ``AuthoringSessionService``.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Union

from herzchen.contracts import AuthoringCheckout, ResourceRef

from .sessions import AuthoringSessionService, FinishResult, SessionHandle
from .snapshots import DurableSnapshot, DurableSnapshotAdapter, SnapshotError


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    diagnostics: Any = None


class FinishHandler(Protocol):
    """Injected semantic hooks for a project/document/pack-shaped target."""

    def validate(self, snapshot: DurableSnapshot, checkout: AuthoringCheckout, checkout_root: str, **kwargs: Any) -> Any: ...

    def apply(self, snapshot: DurableSnapshot, checkout: AuthoringCheckout, tx: Any, writer: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class SemanticFinishResult:
    status: str
    finish: Optional[FinishResult] = None
    snapshot: Optional[DurableSnapshot] = None
    validation: Optional[ValidationResult] = None
    application: Any = None
    recovery_pending: bool = False
    error: Optional[str] = None


def _call_hook(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
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


def _validation(value: Any) -> ValidationResult:
    if isinstance(value, ValidationResult):
        return value
    if isinstance(value, bool):
        return ValidationResult(value)
    if value is None:
        return ValidationResult(True)
    if isinstance(value, Mapping):
        valid = bool(value.get("valid", value.get("ok", False)))
        diagnostics = value.get("diagnostics", value.get("errors"))
        return ValidationResult(valid, diagnostics)
    valid = getattr(value, "valid", getattr(value, "ok", False))
    return ValidationResult(bool(valid), getattr(value, "diagnostics", None))


def _diagnostic_text(value: Any) -> str:
    if value is None:
        return "handler rejected snapshot"
    if isinstance(value, str):
        return value
    return repr(value)


class SemanticFinishAdapter:
    """One common finish boundary for injected semantic handlers."""

    def __init__(self, service: AuthoringSessionService, snapshot_adapter: Optional[DurableSnapshotAdapter] = None) -> None:
        self.service = service
        self.snapshots = snapshot_adapter or DurableSnapshotAdapter(service)

    def finish(
        self,
        handle: SessionHandle,
        *,
        request_id: str,
        mode: str,
        checkout_root: Union[str, Path],
        registered_files: Any,
        handler: FinishHandler,
        expected_base_revision: Optional[str] = None,
        pending: Optional[bool] = None,
        settled: Any = True,
        **hook_kwargs: Any,
    ) -> SemanticFinishResult:
        """Capture and validate outside the short common writer transaction."""
        # Exact request replay is deliberately delegated unchanged.  The
        # session service checks the request receipt before invoking capture,
        # so a lost response cannot cause a second handler application.
        prior = self.service.writer.get_receipt(request_id)
        if prior is not None:
            try:
                result = self.service.finish(
                    handle,
                    request_id=request_id,
                    mode=mode,
                    capture=lambda *_args, **_kwargs: b"replay-capture-not-used",
                    expected_base_revision=expected_base_revision,
                    pending=pending,
                )
                return SemanticFinishResult(result.status, result, recovery_pending=result.recovery_pending, error=result.error)
            except BaseException as exc:
                return SemanticFinishResult("failed", recovery_pending=True, error=str(exc))

        # A manual/idle loser must use the session port's existing shared
        # finish-claim/release decision.  Do not pre-authorize a closed
        # checkout, because that would turn a valid already-finished response
        # into an adapter-only failure.
        current = self.service.writer.get_identity(handle.scope)
        current_checkout = None if current is None else current.payload.get("checkout")
        if isinstance(current_checkout, Mapping) and current_checkout.get("session_id") == handle.session_id and current_checkout.get("state") != "open":
            try:
                result = self.service.finish(
                    handle,
                    request_id=request_id,
                    mode=mode,
                    capture=lambda *_args, **_kwargs: b"closed-capture-not-used",
                    expected_base_revision=expected_base_revision,
                    pending=pending,
                )
                return SemanticFinishResult(result.status, result, recovery_pending=result.recovery_pending, error=result.error)
            except BaseException as exc:
                return SemanticFinishResult("failed", recovery_pending=True, error=str(exc))

        try:
            tree = self.snapshots.capture(checkout_root, registered_files, settled=settled)
            # Token, fence, and base admission are checked before the handler
            # is allowed to inspect/apply semantic changes.
            expected = expected_base_revision or handle.base_revision
            checkout = self.service.authorize_mutation(
                handle, handle.target_scope, token=handle.token, fence=handle.fence, expected_base_revision=expected
            )
            validation = _validation(_call_hook(handler.validate, tree, checkout, str(checkout_root), checkout_root=str(checkout_root), **hook_kwargs))
            ref = self.snapshots._ref(handle, "final", tree.tree_digest)
            session_snapshot = tree.as_session_snapshot(ref)
            if not validation.valid:
                # Use the session port's existing rejected-draft transition;
                # no domain handler or second receipt/event engine is involved.
                digest = self.service._request_digest(
                    "finish", request_id,
                    {"session": handle.session_id, "mode": mode, "expected_base_revision": expected_base_revision, "pending": pending},
                )
                rejected = self.service._reject_finish(
                    handle, request_id, digest, checkout, session_snapshot, _diagnostic_text(validation.diagnostics), ValueError
                )
                return SemanticFinishResult("rejected", rejected, tree, validation, error=_diagnostic_text(validation.diagnostics))

            application_box: dict[str, Any] = {}

            def apply(_session_snapshot: Any, claimed: AuthoringCheckout, *, tx: Any, writer: Any, **_: Any) -> None:
                application_box["value"] = _call_hook(
                    handler.apply,
                    tree,
                    claimed,
                    tx,
                    writer,
                    snapshot=tree,
                    checkout=claimed,
                    transaction=tx,
                    tx=tx,
                    writer=writer,
                    checkout_root=str(checkout_root),
                    **hook_kwargs,
                )

            result = self.service.finish(
                handle,
                request_id=request_id,
                mode=mode,
                capture=session_snapshot,
                expected_base_revision=expected_base_revision,
                apply=apply,
                pending=pending,
            )
            return SemanticFinishResult(result.status, result, tree, validation, application_box.get("value"), result.recovery_pending, result.error)
        except BaseException as exc:
            return SemanticFinishResult("failed", snapshot=locals().get("tree"), recovery_pending=True, error=str(exc))


__all__ = ["ValidationResult", "FinishHandler", "SemanticFinishResult", "SemanticFinishAdapter"]
