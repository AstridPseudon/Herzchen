"""EDT-owned managed local authoring sessions."""

from .sessions import *
from .sessions import __all__
from .snapshots import *
from .finish import *
from .cleanup import *
from .idle import *
from .integration import *

__all__ = tuple(__all__) + (
    "SnapshotError", "InvalidSnapshotPath", "SnapshotPathEscape", "UnregisteredFileError",
    "MissingRegisteredFileError", "UnstableFileError", "UnsettledWriteError", "SnapshotPersistenceError",
    "SnapshotManifestEntry", "SnapshotFile", "DurableSnapshot", "SnapshotSaveResult",
    "capture_tree", "durable_snapshot_from_bytes", "DurableSnapshotAdapter",
    "ValidationResult", "FinishHandler", "SemanticFinishResult", "SemanticFinishAdapter",
    "CleanupError", "CleanupUnsafeError", "CleanupPathError", "CleanupIdentityError", "CleanupWriterError",
    "RegisteredFile", "CleanupObservation", "cleanup_registered_files", "cleanup_status", "CleanupManager", "safe_cleanup",
    "DEFAULT_IDLE_SECONDS", "IdleCloseError", "WriterQuiescenceError", "IdlePolicy", "IdleCloseResult",
    "IdleCloseService", "IdleCloser", "IdleCloseCoordinator", "idle_close",
    "SemanticHandler", "CallableSemanticHandler", "AuthoringTarget", "LifecycleFinishResult",
    "AuthoringLifecycle", "AuthoringLifecycleAdapter", "SharedAuthoringLifecycle",
)
