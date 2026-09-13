"""Product-neutral records for the optional Herzchen work domain.

The module deliberately contains no persistence code.  ``WorkRecord`` is a
view of one FND identity and its payload; ``WorkGraph`` in :mod:`module`
performs the domain validation and delegates durability to the supplied FND
writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


class WorkKind(str, Enum):
    PROJECT = "project"
    EFFORT = "effort"
    TASK = "task"
    CRITERION = "criterion"
    SCENARIO = "scenario"
    GATE = "gate"


class Lifecycle(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    WITHDRAWN = "withdrawn"
    COMPLETED = "completed"


@dataclass(frozen=True)
class WorkRecord:
    """A durable work identity and its current domain projection."""

    ref: Any
    kind: WorkKind
    title: str
    name: str
    aliases: Tuple[str, ...]
    parent: Optional[Any]
    dependencies: Tuple[Any, ...]
    project_ref: Optional[Any]
    lifecycle: Lifecycle
    readiness: Mapping[str, Any]
    payload: Mapping[str, Any]
    version: int

    @property
    def id(self) -> str:
        return self.ref.id

    @property
    def revision(self) -> Optional[str]:
        return self.ref.revision

    @property
    def alias(self) -> str:
        return self.aliases[0]

    @property
    def state(self) -> str:
        """Compatibility view; lifecycle and readiness remain separate."""

        return self.lifecycle.value

    @property
    def is_pending(self) -> bool:
        return self.lifecycle is Lifecycle.PENDING


@dataclass(frozen=True)
class WorkStateView:
    """Read-only state projection with no readiness or dispatch side effect."""

    ref: Any
    lifecycle: Lifecycle
    readiness: Mapping[str, Any]
    version: int
    revision: Optional[str]

    @property
    def ready(self) -> bool:
        return bool(self.readiness.get("ready", False))


class WorkError(ValueError):
    """Base error for work validation and command admission."""


class WorkNotFoundError(WorkError):
    pass


class WorkValidationError(WorkError):
    pass


class GraphCycleError(WorkValidationError):
    pass


class InvalidParentError(WorkValidationError):
    pass


class InvalidDependencyError(WorkValidationError):
    pass


__all__ = [
    "GraphCycleError",
    "InvalidDependencyError",
    "InvalidParentError",
    "Lifecycle",
    "WorkError",
    "WorkKind",
    "WorkNotFoundError",
    "WorkRecord",
    "WorkStateView",
    "WorkValidationError",
]
