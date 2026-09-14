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

from herzchen.contracts import AuthoringCheckout, AuthoringState, CleanupStatus, ResourceRef

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
        self.reader = service.reader
        self.snapshots = snapshot_adapter or DurableSnapshotAdapter(service)

    @staticmethod
    def _writer_is_quiescent(
        quiesce: Optional[Callable[..., Any]],
        writer_check: Optional[Callable[..., Any]],
    ) -> None:
        """Require the host's managed-writer fence at each lifecycle edge."""
        if quiesce is not None:
            try:
                value = _call_hook(quiesce)
            except BaseException as exc:
                raise SnapshotError("managed writer could not be quiesced") from exc
            if value is False or value is None or (isinstance(value, str) and value in {"active", "open", "writing", "unknown"}):
                raise SnapshotError("managed writer did not acknowledge quiescence")
        if writer_check is not None:
            try:
                value = _call_hook(writer_check)
            except BaseException as exc:
                raise SnapshotError("managed writer state is unknown") from exc
            if value is not True and not (isinstance(value, str) and value in {"quiescent", "idle", "stopped"}):
                raise SnapshotError("managed writer state is active or unknown")

    def _late_write_recovery(
        self,
        handle: SessionHandle,
        tree: DurableSnapshot,
        *,
        mode: str,
        request_id: str,
        error: str,
    ) -> SemanticFinishResult:
        """Durably retain the pre-late-write capture and release for retry."""
        session_snapshot = tree.as_session_snapshot(self.snapshots._ref(handle, "final", tree.tree_digest))
        self.service._transition_recovery(handle, request_id + ":late-write", session_snapshot, error)
        record = self.service.reader.get_identity(handle.scope)
        checkout = None
        if record is not None:
            try:
                checkout = self.service._payload_checkout(record.payload)
            except (TypeError, ValueError, KeyError):
                checkout = None
        finish = FinishResult(
            "recovery_pending", handle.scope, handle.session_id,
            checkout=checkout, final_snapshot=session_snapshot,
            recovery_pending=True, cleanup=checkout.cleanup if checkout is not None else CleanupStatus.PENDING,
            error=error,
        )
        return SemanticFinishResult("recovery_pending", finish, tree, recovery_pending=True, error=error)

    def _reconcile_completed_finish(
        self,
        handle: SessionHandle,
        *,
        mode: str,
        expected_base_revision: Optional[str],
        pending: Optional[bool],
        final_digest: str,
    ) -> Optional[FinishResult]:
        """Return the durable winner for a same-operation cross-service race.

        ``AuthoringSessionService`` owns the claim transaction.  Two service
        instances can therefore both reach that boundary without sharing its
        per-instance lock.  Once one transaction closes the checkout, the
        other instance must inspect the durable claim and finish receipt.  A
        digest and capability check keeps that reconciliation from turning a
        changed or foreign attempt into a success response.
        """
        record = self.service.reader.get_identity(handle.scope)
        if record is None:
            return None
        payload = getattr(record, "payload", None)
        if not isinstance(payload, Mapping):
            return None
        raw_checkout = payload.get("checkout")
        if not isinstance(raw_checkout, Mapping):
            return None
        try:
            checkout = AuthoringCheckout.from_dict(raw_checkout)
        except (TypeError, ValueError, KeyError):
            return None
        if checkout.session_id != handle.session_id or checkout.token != handle.token or checkout.fence != handle.fence:
            return None
        if checkout.target_scope != handle.target_scope or checkout.actor != handle.actor:
            return None
        if checkout.state not in {AuthoringState.FINISHED, AuthoringState.RELEASED}:
            return None
        claim = checkout.finish_claim
        if claim is None or claim.finalization_identity != "finish-" + handle.session_id:
            return None
        if payload.get("final_digest") != final_digest:
            return None
        if payload.get("finish_mode") not in {"manual", "idle"} or mode not in {"manual", "idle"}:
            return None
        durable_pending = bool(payload.get("pending", False))
        if pending is not None and durable_pending != bool(pending):
            return None
        expected = expected_base_revision or handle.base_revision
        if expected != checkout.base_revision:
            return None
        finish_request_id = payload.get("finish_request_id")
        if not isinstance(finish_request_id, str):
            return None
        receipt = self.service.reader.get_receipt(finish_request_id)
        if receipt is None or getattr(receipt, "operation", None) != "finish":
            return None
        status = getattr(getattr(receipt, "status", None), "value", getattr(receipt, "status", None))
        if status != "committed":
            return None
        return FinishResult(
            "already_finished",
            handle.scope,
            handle.session_id,
            receipt,
            checkout,
            recovery_pending=False,
            cleanup=checkout.cleanup,
        )

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
        quiesce: Optional[Callable[..., Any]] = None,
        writer_check: Optional[Callable[..., Any]] = None,
        capture_barrier: Optional[Callable[..., Any]] = None,
        **hook_kwargs: Any,
    ) -> SemanticFinishResult:
        """Capture and validate outside the short common writer transaction."""
        # Capture and the post-barrier verification must inspect the same
        # registered set even when a host supplied a one-shot iterator.
        registered_files = tuple(registered_files)
        # Exact request replay is deliberately delegated unchanged.  The
        # session service checks the request receipt before invoking capture,
        # so a lost response cannot cause a second handler application.
        prior = self.service.reader.get_receipt(request_id)
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
        current = self.service.reader.get_identity(handle.scope)
        current_checkout = None if current is None else current.payload.get("checkout")
        if isinstance(current_checkout, Mapping) and current_checkout.get("session_id") == handle.session_id and current_checkout.get("state") != "open":
            try:
                tree = self.snapshots.capture(checkout_root, registered_files, settled=settled)
                result = self._reconcile_completed_finish(
                    handle,
                    mode=mode,
                    expected_base_revision=expected_base_revision,
                    pending=pending,
                    final_digest=tree.digest,
                )
                if result is not None:
                    return SemanticFinishResult("already_finished", result, tree)
                return SemanticFinishResult(
                    "failed",
                    snapshot=tree,
                    recovery_pending=True,
                    error="closed checkout does not match a durable completed finish",
                )
            except BaseException as exc:
                return SemanticFinishResult("failed", recovery_pending=True, error=str(exc))

        try:
            # ``settled`` remains a capture hint for legacy callers; a host
            # with a managed writer must also provide the real quiescence
            # check.  The check is repeated after the deterministic barrier.
            if quiesce is not None:
                self._writer_is_quiescent(quiesce, writer_check)
            tree = self.snapshots.capture(checkout_root, registered_files, settled=settled)
            if capture_barrier is not None:
                _call_hook(
                    capture_barrier, tree,
                    snapshot=tree, checkout_root=str(checkout_root),
                    registered_files=registered_files,
                )
            try:
                if quiesce is not None:
                    self._writer_is_quiescent(quiesce, writer_check)
                self.snapshots.verify_manifest(tree, checkout_root, registered_files)
            except BaseException as exc:
                return self._late_write_recovery(
                    handle, tree, mode=mode, request_id=request_id,
                    error=str(exc) or "checkout changed after final capture",
                )
            # Token, fence, and base admission are checked before the handler
            # is allowed to inspect/apply semantic changes.
            expected = expected_base_revision or handle.base_revision
            try:
                checkout = self.service.authorize_mutation(
                    handle, handle.target_scope, token=handle.token, fence=handle.fence, expected_base_revision=expected
                )
            except BaseException:
                # A same-service contender can lose after the adapter's
                # initial read but before authorization.  Reuse the existing
                # durable-winner reconciliation; do not add an EDT lock or a
                # second finish writer.
                reconciled = self._reconcile_completed_finish(
                    handle,
                    mode=mode,
                    expected_base_revision=expected_base_revision,
                    pending=pending,
                    final_digest=tree.digest,
                )
                if reconciled is not None:
                    return SemanticFinishResult("already_finished", reconciled, tree)
                raise
            validation = _validation(_call_hook(handler.validate, tree, checkout, str(checkout_root), checkout_root=str(checkout_root), **hook_kwargs))
            ref = self.snapshots._ref(handle, "final", tree.tree_digest)
            session_snapshot = tree.as_session_snapshot(ref)
            if not validation.valid:
                # Use the session port's existing rejected-draft transition;
                # no domain handler or second receipt/event engine is involved.
                digest = self.service._request_digest(
                    "finish", request_id,
                    {"session": handle.session_id, "mode": mode, "expected_base_revision": expected_base_revision, "pending": pending},
                    target=handle.scope, actor=handle.actor,
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

            try:
                # Use the supplied common writer transaction around the
                # session port.  Store implements nested transactions as
                # savepoints, so this serializes separate services on the
                # durable writer without an EDT lock or a second boundary.
                with self.service._session_transaction():
                    result = self.service.finish(
                        handle,
                        request_id=request_id,
                        mode=mode,
                        capture=session_snapshot,
                        expected_base_revision=expected_base_revision,
                        apply=apply,
                        pending=pending,
                    )
            except BaseException as exc:
                reconciled = self._reconcile_completed_finish(
                    handle,
                    mode=mode,
                    expected_base_revision=expected_base_revision,
                    pending=pending,
                    final_digest=tree.digest,
                )
                if reconciled is not None:
                    return SemanticFinishResult("already_finished", reconciled, tree, validation)
                raise
            if result.status in {"in_progress", "already_finished", "recovery_pending"}:
                reconciled = self._reconcile_completed_finish(
                    handle,
                    mode=mode,
                    expected_base_revision=expected_base_revision,
                    pending=pending,
                    final_digest=tree.digest,
                )
                if reconciled is not None:
                    return SemanticFinishResult("already_finished", reconciled, tree, validation)
            return SemanticFinishResult(result.status, result, tree, validation, application_box.get("value"), result.recovery_pending, result.error)
        except BaseException as exc:
            return SemanticFinishResult("failed", snapshot=locals().get("tree"), recovery_pending=True, error=str(exc))


__all__ = ["ValidationResult", "FinishHandler", "SemanticFinishResult", "SemanticFinishAdapter"]
