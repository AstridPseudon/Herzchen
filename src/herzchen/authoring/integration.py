"""One shared authoring boundary for domain-owned target handlers.

EDT owns admission, capabilities, capture, finish claims, idle policy, and
registered-file cleanup. A consumer supplies only a target-neutral semantic
handler; DAT, WRK, and PKG retain their own validation and application APIs.
This module intentionally contains no product imports, persistence, schema, or
event implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol, Union

from herzchen.contracts import AuthoringState, AuthenticatedActor, ResourceRef

from .cleanup import CleanupObservation, cleanup_registered_files
from .finish import SemanticFinishAdapter, SemanticFinishResult
from .idle import IdleCloseResult, IdleCloseService
from .sessions import AuthoringSessionService, CleanupResult, FinishResult, OpenResult, SessionHandle


class SemanticHandler(Protocol):
    """The only domain surface required by the common lifecycle."""

    def validate(self, snapshot: Any, checkout: Any, checkout_root: str, **kwargs: Any) -> Any: ...

    def apply(self, snapshot: Any, checkout: Any, tx: Any, writer: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class CallableSemanticHandler:
    """Adapt two owner callables without making a second lifecycle."""

    validator: Callable[..., Any]
    applier: Callable[..., Any]

    def validate(self, snapshot: Any, checkout: Any, checkout_root: str, **kwargs: Any) -> Any:
        return _call(self.validator, snapshot, checkout, checkout_root, **kwargs)

    def apply(self, snapshot: Any, checkout: Any, tx: Any, writer: Any, **kwargs: Any) -> Any:
        return _call(self.applier, snapshot, checkout, tx, writer, **kwargs)


@dataclass(frozen=True)
class AuthoringTarget:
    """A target-specific view over one shared EDT capability."""

    target: ResourceRef
    scope: ResourceRef
    opened: OpenResult

    @property
    def handle(self) -> SessionHandle:
        if self.opened.handle is None:
            raise RuntimeError("target did not open an authoring capability")
        return self.opened.handle


@dataclass(frozen=True)
class LifecycleFinishResult:
    """Finish plus physical cleanup, with both observations retained."""

    finish: SemanticFinishResult
    cleanup: Optional[CleanupObservation] = None
    durable_cleanup: Optional[CleanupResult] = None

    @property
    def status(self) -> str:
        return self.finish.status

    @property
    def receipt(self) -> Any:
        return None if self.finish.finish is None else self.finish.finish.receipt


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    signature = inspect.signature(fn)
    params = tuple(signature.parameters.values())
    positional = tuple(
        item.name for item in params
        if item.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    )
    filtered = dict(kwargs)
    for name in positional[: len(args)]:
        filtered.pop(name, None)
    if not any(item.kind == inspect.Parameter.VAR_KEYWORD for item in params):
        accepted = {item.name for item in params}
        filtered = {key: value for key, value in filtered.items() if key in accepted}
    return fn(*args, **filtered)


class AuthoringLifecycle:
    """The one shared project/document/pack authoring lifecycle."""

    def __init__(
        self,
        service: AuthoringSessionService,
        *,
        cleanup: Callable[..., CleanupObservation] = cleanup_registered_files,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(service, AuthoringSessionService):
            raise TypeError("service must be the supplied AuthoringSessionService")
        self.service = service
        self.finish_adapter = SemanticFinishAdapter(service)
        self.idle_service = IdleCloseService(self.finish_adapter, cleanup=cleanup, clock=clock)
        self.cleanup = cleanup

    @property
    def idle(self) -> IdleCloseService:
        return self.idle_service

    def open(
        self,
        target: ResourceRef,
        actor: AuthenticatedActor,
        *,
        request_id: str,
        target_kind: Optional[str] = None,
        base_revision: Optional[str] = None,
        initial_content: Union[bytes, str] = b"",
        scope: Optional[ResourceRef] = None,
        pending: bool = False,
        allowed_fields: Iterable[str] = (),
        purpose: str = "authoring",
        activity: str = "editing",
        materialize: Optional[Callable[..., Any]] = None,
        project: Optional[Any] = None,
    ) -> AuthoringTarget:
        # A product boundary may install a resolver on the supplied session
        # service.  Resolve before passing a parent hint so a forged parent is
        # rejected instead of becoming an EDT-only override.
        if scope is not None and self.service.scope_resolver is not None:
            canonical_scope = _call(
                self.service.scope_resolver, target,
                target=target, parent_scope=scope,
            )
            if not isinstance(canonical_scope, ResourceRef):
                raise ValueError("scope resolver did not return a ResourceRef")
        else:
            canonical_scope = self.service.resolve_scope(target, parent_scope=scope)
        opened = self.service.open(
            target, actor, request_id=request_id, target_kind=target_kind or target.kind,
            base_revision=base_revision, initial_content=initial_content,
            parent_scope=canonical_scope, pending=pending, allowed_fields=tuple(allowed_fields),
            purpose=purpose, activity=activity, materialize=materialize, project=project,
        )
        return AuthoringTarget(target, canonical_scope, opened)

    def create_and_open(
        self,
        target: ResourceRef,
        actor: AuthenticatedActor,
        *,
        request_id: str,
        create_project: Callable[..., Any],
        target_kind: str = "project-sheet",
        base_revision: str = "initial",
        initial_content: Union[bytes, str] = b"",
        pending: bool = True,
        materialize: Optional[Callable[..., Any]] = None,
        **kwargs: Any,
    ) -> AuthoringTarget:
        opened = self.service.create_and_open(
            target, actor, request_id=request_id, create_project=create_project,
            target_kind=target_kind, base_revision=base_revision,
            initial_content=initial_content, pending=pending, materialize=materialize,
            **kwargs,
        )
        return AuthoringTarget(target, opened.scope, opened)

    def read(self, target: ResourceRef, actor: Optional[AuthenticatedActor] = None, *, scope: Optional[ResourceRef] = None) -> Any:
        return self.service.read(target, actor, parent_scope=scope)

    def finish(
        self,
        target: Union[AuthoringTarget, SessionHandle],
        *,
        request_id: str,
        mode: str,
        checkout_root: Union[str, Path],
        registered_files: Any,
        handler: SemanticHandler,
        expected_base_revision: Optional[str] = None,
        pending: Optional[bool] = None,
        settled: Any = True,
        cleanup: bool = True,
        writer_check: Optional[Callable[[], Any]] = None,
        **hook_kwargs: Any,
    ) -> LifecycleFinishResult:
        handle = target.handle if isinstance(target, AuthoringTarget) else target
        result = self.finish_adapter.finish(
            handle, request_id=request_id, mode=mode, checkout_root=checkout_root,
            registered_files=registered_files, handler=handler,
            expected_base_revision=expected_base_revision, pending=pending,
            settled=settled, **hook_kwargs,
        )
        if not cleanup or not self._released(result):
            return LifecycleFinishResult(result)
        observation = self.cleanup(checkout_root, registered_files, writer_check=writer_check)
        durable = self.service.cleanup(handle, request_id=request_id + ":cleanup", status=observation.status)
        return LifecycleFinishResult(result, observation, durable)

    def idle_close(
        self,
        target: Union[AuthoringTarget, SessionHandle],
        *,
        request_id: str,
        checkout_root: Union[str, Path],
        registered_files: Any,
        handler: SemanticHandler,
        **kwargs: Any,
    ) -> IdleCloseResult:
        handle = target.handle if isinstance(target, AuthoringTarget) else target
        return self.idle_service.close_if_idle(
            handle, request_id=request_id, checkout_root=checkout_root,
            registered_files=registered_files, handler=handler, **kwargs,
        )

    def release(self, target: Union[AuthoringTarget, SessionHandle], *, request_id: str) -> FinishResult:
        handle = target.handle if isinstance(target, AuthoringTarget) else target
        return self.service.release(handle, request_id=request_id)

    def cleanup_released(
        self,
        target: Union[AuthoringTarget, SessionHandle],
        *,
        request_id: str,
        checkout_root: Union[str, Path],
        registered_files: Any,
        writer_check: Optional[Callable[[], Any]] = None,
    ) -> CleanupObservation:
        handle = target.handle if isinstance(target, AuthoringTarget) else target
        observation = self.cleanup(checkout_root, registered_files, writer_check=writer_check)
        self.service.cleanup(handle, request_id=request_id, status=observation.status)
        return observation

    @staticmethod
    def _released(result: SemanticFinishResult) -> bool:
        finish = result.finish
        if finish is not None and result.status == "rejected" and finish.final_snapshot is not None:
            return True
        return bool(
            finish is not None and finish.checkout is not None
            and finish.checkout.state != AuthoringState.OPEN
            and result.status in {"finished", "pending_released", "rejected", "already_finished", "replayed"}
        )


AuthoringLifecycleAdapter = AuthoringLifecycle
SharedAuthoringLifecycle = AuthoringLifecycle


__all__ = [
    "SemanticHandler", "CallableSemanticHandler", "AuthoringTarget", "LifecycleFinishResult",
    "AuthoringLifecycle", "AuthoringLifecycleAdapter", "SharedAuthoringLifecycle",
]
