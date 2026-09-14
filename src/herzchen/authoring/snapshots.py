"""Durable, target-neutral checkout tree snapshots.

The adapter in this module deliberately stops at a stable, exact byte capture.
It does not delete a checkout and it does not interpret project/document/pack
content.  The supplied :class:`AuthoringSessionService` remains the only
durable draft writer.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from hashlib import sha256
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple, Union

from herzchen.contracts import ResourceRef, canonical_json

from .sessions import AuthoringSessionService, SessionHandle, Snapshot


class SnapshotError(ValueError):
    """Base error for a checkout capture or durable draft operation."""


class InvalidSnapshotPath(SnapshotError):
    """A registered path is absolute, malformed, or escapes the checkout."""


class SnapshotPathEscape(InvalidSnapshotPath):
    """A symlink or resolved path leaves the supplied checkout root."""


class UnregisteredFileError(SnapshotError):
    """The checkout contains a regular file outside the registered set."""


class MissingRegisteredFileError(SnapshotError):
    """A registered file is absent from the checkout."""


class UnstableFileError(SnapshotError):
    """A writer changed a file while it was being captured."""


class LateWriteError(SnapshotError):
    """The checkout changed after the stable capture and before retirement."""


class UnsettledWriteError(SnapshotError):
    """The host has not declared the checkout write settled."""


class SnapshotPersistenceError(SnapshotError):
    """The common session writer could not persist an exact snapshot."""


@dataclass(frozen=True)
class SnapshotManifestEntry:
    """The deterministic manifest record for one registered relative file."""

    relative_path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _normalise_relative_path(self.relative_path)
        if not isinstance(self.size, int) or self.size < 0:
            raise SnapshotError("snapshot manifest size must be non-negative")
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise SnapshotError("snapshot manifest sha256 must be lowercase hexadecimal")

    def to_dict(self) -> dict[str, Any]:
        return {"relative_path": self.relative_path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class SnapshotFile:
    """One exact file and its manifest entry."""

    relative_path: str
    data: bytes
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise SnapshotError("snapshot file data must be bytes")
        if len(self.data) != self.size or sha256(self.data).hexdigest() != self.sha256:
            raise SnapshotError("snapshot file bytes do not match their manifest")

    @property
    def manifest_entry(self) -> SnapshotManifestEntry:
        return SnapshotManifestEntry(self.relative_path, self.size, self.sha256)


@dataclass(frozen=True)
class DurableSnapshot:
    """An immutable, exact multi-file snapshot.

    ``data`` is a deterministic JSON envelope containing every file's bytes;
    it is the exact payload handed to the session port.  ``files`` provides a
    convenient typed view without requiring handlers to decode that envelope.
    """

    root: str
    files: Tuple[SnapshotFile, ...]
    tree_digest: str
    data: bytes
    ref: Optional[ResourceRef] = None

    @property
    def manifest(self) -> Tuple[SnapshotManifestEntry, ...]:
        return tuple(item.manifest_entry for item in self.files)

    @property
    def digest(self) -> str:
        return sha256(self.data).hexdigest()

    def file_bytes(self, relative_path: str) -> bytes:
        for item in self.files:
            if item.relative_path == relative_path:
                return item.data
        raise KeyError(relative_path)

    def as_session_snapshot(self, ref: Optional[ResourceRef] = None) -> Snapshot:
        selected = ref or self.ref
        if selected is None:
            raise SnapshotError("a durable snapshot needs a session reference before persistence")
        # The session port's manifest is intentionally opaque to EDT-02.  Each
        # entry is canonical JSON so the full per-file manifest survives the
        # ordinary Snapshot/identity boundary without a second store.
        manifest = tuple(canonical_json(entry.to_dict()) for entry in self.manifest)
        return Snapshot(selected, self.data, manifest)


@dataclass(frozen=True)
class SnapshotSaveResult:
    status: str
    snapshot: Optional[DurableSnapshot] = None
    session_snapshot: Optional[Snapshot] = None
    recovery_pending: bool = False
    error: Optional[str] = None


def _normalise_relative_path(value: Union[str, os.PathLike[str]]) -> str:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise InvalidSnapshotPath("registered file path is malformed")
    if os.path.isabs(raw) or (len(raw) >= 2 and raw[1] == ":"):
        raise InvalidSnapshotPath("absolute registered paths are not allowed")
    # Checkout paths are portable POSIX relative paths.  Treat backslashes as
    # separators too, so a Windows-shaped escape cannot bypass the check on
    # POSIX hosts.
    candidate = raw.replace("\\", "/")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InvalidSnapshotPath("registered paths must be clean relative file paths")
    return "/".join(parts)


def _root_path(root: Union[str, os.PathLike[str]]) -> Path:
    path = Path(root)
    root_stat = os.lstat(path)
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise InvalidSnapshotPath("checkout root must be a real directory")
    return path


def _inside(root: Path, path: Path) -> bool:
    try:
        return os.path.commonpath((os.path.realpath(root), os.path.realpath(path))) == os.path.realpath(root)
    except ValueError:
        return False


def _checked_file(root: Path, relative_path: str) -> Path:
    path = root.joinpath(*relative_path.split("/"))
    if not _inside(root, path):
        raise SnapshotPathEscape("registered path escapes checkout root")
    current = root
    for part in relative_path.split("/"):
        current = current / part
        if os.path.islink(current):
            raise SnapshotPathEscape("symlink paths are not valid registered files")
    try:
        file_stat = os.lstat(path)
    except FileNotFoundError as exc:
        raise MissingRegisteredFileError(relative_path) from exc
    if stat.S_ISLNK(file_stat.st_mode):
        raise SnapshotPathEscape("symlink files are not valid registered files")
    if not stat.S_ISREG(file_stat.st_mode):
        raise InvalidSnapshotPath("registered path is not a regular file: " + relative_path)
    return path


def _stat_signature(value: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _scan_regular_files(root: Path) -> Tuple[str, ...]:
    found: list[str] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for dirname in tuple(dirnames):
            directory_path = Path(directory) / dirname
            if os.path.islink(directory_path):
                raise SnapshotPathEscape("symlink directory is not allowed: " + str(directory_path.relative_to(root)))
        for filename in filenames:
            path = Path(directory) / filename
            relative = path.relative_to(root).as_posix()
            if os.path.islink(path):
                raise SnapshotPathEscape("symlink file is not allowed: " + relative)
            if not stat.S_ISREG(os.lstat(path).st_mode):
                raise InvalidSnapshotPath("checkout contains a non-regular file: " + relative)
            found.append(relative)
    return tuple(sorted(found))


def _tree_digest(entries: Sequence[SnapshotManifestEntry]) -> str:
    return sha256(canonical_json([entry.to_dict() for entry in entries]).encode("utf-8")).hexdigest()


def _pack(files: Sequence[SnapshotFile], entries: Sequence[SnapshotManifestEntry], tree_digest: str) -> bytes:
    envelope = {
        "format": "herzchen.edt-03.tree.v1",
        "tree_digest": tree_digest,
        "manifest": [entry.to_dict() for entry in entries],
        "files": [{"relative_path": item.relative_path, "bytes_b64": b64encode(item.data).decode("ascii")} for item in files],
    }
    return canonical_json(envelope).encode("utf-8")


def capture_tree(
    checkout_root: Union[str, os.PathLike[str]],
    registered_files: Iterable[Union[str, os.PathLike[str]]],
    *,
    settled: Union[bool, Callable[[], bool]] = True,
) -> DurableSnapshot:
    """Capture every registered file exactly once after stable-write checks."""
    if callable(settled):
        if not bool(settled()):
            raise UnsettledWriteError("checkout writer has not settled")
    elif not settled:
        raise UnsettledWriteError("checkout writer has not settled")

    root = _root_path(checkout_root)
    normalised = tuple(sorted({_normalise_relative_path(path) for path in registered_files}))
    actual = _scan_regular_files(root)
    registered_set = set(normalised)
    actual_set = set(actual)
    extras = sorted(actual_set - registered_set)
    if extras:
        raise UnregisteredFileError("unregistered checkout files: " + ", ".join(extras))
    missing = sorted(registered_set - actual_set)
    if missing:
        raise MissingRegisteredFileError("missing registered checkout files: " + ", ".join(missing))

    captured: list[SnapshotFile] = []
    for relative_path in normalised:
        path = _checked_file(root, relative_path)
        before = os.stat(path, follow_symlinks=False)
        try:
            with open(path, "rb") as stream:
                data = stream.read()
        except OSError as exc:
            raise SnapshotError("could not read " + relative_path) from exc
        after = os.stat(path, follow_symlinks=False)
        if _stat_signature(before) != _stat_signature(after):
            raise UnstableFileError("file changed while being captured: " + relative_path)
        digest = sha256(data).hexdigest()
        if len(data) != before.st_size:
            raise UnstableFileError("file size changed while being captured: " + relative_path)
        captured.append(SnapshotFile(relative_path, data, len(data), digest))

    entries = tuple(item.manifest_entry for item in captured)
    tree_digest = _tree_digest(entries)
    return DurableSnapshot(str(root), tuple(captured), tree_digest, _pack(captured, entries, tree_digest))


def durable_snapshot_from_bytes(data: bytes, *, root: str = "", ref: Optional[ResourceRef] = None) -> DurableSnapshot:
    """Decode a persisted EDT-03 tree payload and verify every digest."""
    import json

    try:
        envelope = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SnapshotError("snapshot payload is not a valid EDT-03 tree envelope") from exc
    if envelope.get("format") != "herzchen.edt-03.tree.v1":
        raise SnapshotError("unsupported snapshot envelope")
    entries = tuple(SnapshotManifestEntry(item["relative_path"], int(item["size"]), item["sha256"]) for item in envelope.get("manifest", []))
    files: list[SnapshotFile] = []
    encoded = {item["relative_path"]: item["bytes_b64"] for item in envelope.get("files", [])}
    if len(encoded) != len(entries):
        raise SnapshotError("snapshot manifest and byte set differ")
    for entry in entries:
        raw = b64decode(encoded.get(entry.relative_path, ""), validate=True)
        if len(raw) != entry.size or sha256(raw).hexdigest() != entry.sha256:
            raise SnapshotError("snapshot file digest does not match its bytes")
        files.append(SnapshotFile(entry.relative_path, raw, entry.size, entry.sha256))
    digest = _tree_digest(entries)
    if envelope.get("tree_digest") != digest:
        raise SnapshotError("snapshot tree digest does not match its manifest")
    if _pack(files, entries, digest) != data:
        raise SnapshotError("snapshot payload is not canonical")
    return DurableSnapshot(root, tuple(files), digest, bytes(data), ref)


class DurableSnapshotAdapter:
    """Capture and persist exact drafts through one session service."""

    def __init__(self, service: AuthoringSessionService) -> None:
        self.service = service

    def _ref(self, handle: SessionHandle, kind: str, digest: str) -> ResourceRef:
        authority = getattr(self.service.reader, "authority", handle.scope.authority)
        return ResourceRef(authority, "authoring-snapshot", kind + "-" + handle.session_id + "-" + digest, digest)

    def capture(self, checkout_root: Union[str, os.PathLike[str]], registered_files: Iterable[Union[str, os.PathLike[str]]], *, settled: Union[bool, Callable[[], bool]] = True) -> DurableSnapshot:
        return capture_tree(checkout_root, registered_files, settled=settled)

    def verify_manifest(
        self,
        snapshot: DurableSnapshot,
        checkout_root: Union[str, os.PathLike[str]],
        registered_files: Iterable[Union[str, os.PathLike[str]]],
    ) -> None:
        """Prove the captured bytes still describe the checkout.

        This is deliberately a fresh stable read for verification, not a
        cleanup baseline.  Cleanup receives ``snapshot.manifest`` itself.
        """
        try:
            current = self.capture(checkout_root, registered_files, settled=True)
        except BaseException as exc:
            raise LateWriteError("checkout changed after final capture") from exc
        if current.manifest != snapshot.manifest:
            raise LateWriteError("checkout changed after final capture")

    def autosave(
        self,
        handle: SessionHandle,
        *,
        request_id: str,
        checkout_root: Union[str, os.PathLike[str]],
        registered_files: Iterable[Union[str, os.PathLike[str]]],
        activity: str = "editing",
        settled: Union[bool, Callable[[], bool]] = True,
    ) -> SnapshotSaveResult:
        tree: Optional[DurableSnapshot] = None
        session_snapshot: Optional[Snapshot] = None
        try:
            tree = self.capture(checkout_root, registered_files, settled=settled)
            ref = self._ref(handle, "draft", tree.tree_digest)
            session_snapshot = tree.as_session_snapshot(ref)
            current = self.service.reader.get_identity(handle.scope)
            if current is not None and current.payload.get("draft_digest") == session_snapshot.digest:
                return SnapshotSaveResult("no_op", tree, session_snapshot)
            self.service.autosave(handle, request_id=request_id, snapshot=session_snapshot, activity=activity)
            return SnapshotSaveResult("saved", tree, session_snapshot)
        except BaseException as exc:
            return SnapshotSaveResult("failed", tree, session_snapshot, recovery_pending=True, error=str(exc))

    def read(self, ref: ResourceRef) -> DurableSnapshot:
        record = self.service.reader.get_identity(ref)
        if record is None or record.payload.get("type") != "authoring_snapshot":
            raise SnapshotError("snapshot is not durably admitted")
        data = self.service.read_snapshot(ref)
        result = durable_snapshot_from_bytes(data, ref=ref)
        expected_manifest = tuple(record.payload.get("manifest", ()))
        actual_manifest = tuple(canonical_json(entry.to_dict()) for entry in result.manifest)
        if expected_manifest != actual_manifest:
            raise SnapshotError("durable snapshot manifest does not match its bytes")
        return result


__all__ = [
    "SnapshotError", "InvalidSnapshotPath", "SnapshotPathEscape", "UnregisteredFileError",
    "MissingRegisteredFileError", "UnstableFileError", "LateWriteError", "UnsettledWriteError", "SnapshotPersistenceError",
    "SnapshotManifestEntry", "SnapshotFile", "DurableSnapshot", "SnapshotSaveResult",
    "capture_tree", "durable_snapshot_from_bytes", "DurableSnapshotAdapter",
]
