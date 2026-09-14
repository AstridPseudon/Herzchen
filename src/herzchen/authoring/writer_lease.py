"""Authenticated cross-process writer exclusion for checkout retirement.

The lock file is coordination state, not an authoring data store.  Managed
writers take a shared advisory lock for every write.  Retirement takes the
exclusive lock and keeps it from final capture through durable completion and
unlink.  The generation in the authenticated lock state also revokes writers
that opened a descriptor before retirement began.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional, Tuple, Union

from herzchen.contracts import canonical_json


FENCE_FORMAT = "herzchen.edt.writer-retirement.v1"
LOCK_FORMAT = "herzchen.edt.writer-lock.v1"
_HELD_LEASE_CONSTRUCTION_TOKEN = object()


class WriterLeaseError(RuntimeError):
    """Base error for authenticated writer coordination."""


class WriterLeaseUnavailable(WriterLeaseError):
    """The requested shared/exclusive lease could not be acquired."""


class WriterLeaseAuthenticationError(WriterLeaseError):
    """A durable lock state or retirement fence is not authentic."""


class WriterLeaseStaleError(WriterLeaseAuthenticationError):
    """An authentic retirement fence has expired."""


class WriterLeaseRevokedError(WriterLeaseError):
    """A descriptor predates the current retirement generation."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalise_relative_path(value: Union[str, os.PathLike[str]]) -> str:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise WriterLeaseError("managed writer path is malformed")
    candidate = raw.replace("\\", "/")
    if os.path.isabs(raw) or (len(raw) >= 2 and raw[1] == ":"):
        raise WriterLeaseError("managed writer path must be relative")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise WriterLeaseError("managed writer path must be clean and relative")
    return "/".join(parts)


def validated_retirement_manifest(manifest: object) -> Tuple[str, ...]:
    """Return a complete canonical exact-file manifest or fail closed."""
    if not isinstance(manifest, (list, tuple)):
        raise WriterLeaseAuthenticationError("retirement manifest is absent or malformed")
    result = []
    paths = set()
    for raw in manifest:
        if not isinstance(raw, str):
            raise WriterLeaseAuthenticationError("retirement manifest entry is not canonical JSON")
        try:
            item = json.loads(raw)
        except ValueError as exc:
            raise WriterLeaseAuthenticationError("retirement manifest entry is malformed") from exc
        if not isinstance(item, Mapping) or set(item) != {"relative_path", "size", "sha256"}:
            raise WriterLeaseAuthenticationError("retirement manifest entry is partial")
        path = item.get("relative_path")
        size = item.get("size")
        digest = item.get("sha256")
        if not isinstance(path, str):
            raise WriterLeaseAuthenticationError("retirement manifest path is malformed")
        path = _normalise_relative_path(path)
        if path in paths:
            raise WriterLeaseAuthenticationError("retirement manifest contains duplicate paths")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise WriterLeaseAuthenticationError("retirement manifest size is malformed")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise WriterLeaseAuthenticationError("retirement manifest digest is malformed")
        normalised = {"relative_path": path, "size": size, "sha256": digest}
        if canonical_json(normalised) != raw:
            raise WriterLeaseAuthenticationError("retirement manifest entry is not canonical")
        paths.add(path)
        result.append(raw)
    if tuple(sorted(result)) != tuple(result):
        raise WriterLeaseAuthenticationError("retirement manifest is not deterministically ordered")
    return tuple(result)


def _root_identity(root: Union[str, os.PathLike[str]]) -> Tuple[str, int, int]:
    supplied = Path(root)
    supplied_value = os.lstat(supplied)
    if stat.S_ISLNK(supplied_value.st_mode) or not stat.S_ISDIR(supplied_value.st_mode):
        raise WriterLeaseError("checkout root must be a real directory")
    path = supplied.resolve(strict=True)
    value = os.lstat(path)
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        raise WriterLeaseError("checkout root must be a real directory")
    return str(path), int(value.st_dev), int(value.st_ino)


@dataclass(frozen=True)
class _LockState:
    root: str
    root_dev: int
    root_ino: int
    generation: int
    phase: str
    lease_id: Optional[str]
    owner_identity: Optional[str]


class FileWriterLeaseAuthority:
    """Host-held authority for one exhaustive set of managed writer IDs.

    ``secret`` and ``authority`` are stable host configuration.  Recreating
    this object after a restart with the same values can authenticate a prior
    fence and attempt a new exclusive lease; a different or missing authority
    cannot turn cleanup into success.
    """

    def __init__(
        self,
        lock_directory: Union[str, os.PathLike[str]],
        *,
        authority: str,
        secret: bytes,
        writer_identities: Iterable[str],
        fence_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        identities = tuple(sorted(set(writer_identities)))
        if not isinstance(authority, str) or not authority:
            raise ValueError("writer lease authority must be nonempty")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("writer lease secret must contain at least 32 bytes")
        if not identities or any(not isinstance(item, str) or not item for item in identities):
            raise ValueError("writer identities must be a nonempty exact set")
        if isinstance(fence_ttl_seconds, bool) or fence_ttl_seconds <= 0:
            raise ValueError("fence TTL must be positive")
        directory = Path(lock_directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = os.lstat(directory)
        if (
            stat.S_ISLNK(directory_stat.st_mode)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.geteuid()
            or stat.S_IMODE(directory_stat.st_mode) & 0o022
        ):
            raise WriterLeaseError("writer lock directory must be a real directory")
        self.lock_directory = directory.resolve(strict=True)
        self.authority = authority
        self.__secret = secret
        self.writer_identities = identities
        self.fence_ttl_seconds = float(fence_ttl_seconds)
        self._clock = clock
        self.key_id = hashlib.sha256(secret).hexdigest()[:24]

    def _lock_path(self, root: str) -> Path:
        name = hashlib.sha256(root.encode("utf-8")).hexdigest() + ".writer-lock"
        return self.lock_directory / name

    def _open_lock(self, root: str) -> int:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self._lock_path(root), flags, 0o600)
        except OSError as exc:
            raise WriterLeaseUnavailable("writer lock cannot be opened safely") from exc
        value = os.fstat(fd)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) & 0o077
        ):
            os.close(fd)
            raise WriterLeaseAuthenticationError("writer lock identity is not trusted")
        return fd

    def _mac(self, payload: Mapping[str, Any]) -> str:
        return hmac.new(self.__secret, canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    def _encode_state(self, state: _LockState) -> bytes:
        payload = {
            "format": LOCK_FORMAT,
            "authority": self.authority,
            "key_id": self.key_id,
            "managed_writers": list(self.writer_identities),
            "managed_writers_digest": _digest(list(self.writer_identities)),
            "root": state.root,
            "root_dev": state.root_dev,
            "root_ino": state.root_ino,
            "generation": state.generation,
            "phase": state.phase,
            "lease_id": state.lease_id,
            "owner_identity": state.owner_identity,
        }
        return (canonical_json({**payload, "authentication": self._mac(payload)}) + "\n").encode("utf-8")

    def _write_state(self, fd: int, state: _LockState) -> None:
        data = self._encode_state(state)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
        os.fsync(fd)

    def _read_state(self, fd: int, root: str, dev: int, ino: int) -> _LockState:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk
            if len(raw) > 1024 * 1024:
                raise WriterLeaseAuthenticationError("writer lock state is oversized")
        if not raw:
            state = _LockState(root, dev, ino, 0, "active", None, None)
            self._write_state(fd, state)
            return state
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WriterLeaseAuthenticationError("writer lock state is malformed") from exc
        if not isinstance(value, dict):
            raise WriterLeaseAuthenticationError("writer lock state is malformed")
        authentication = value.pop("authentication", None)
        if not isinstance(authentication, str) or not hmac.compare_digest(authentication, self._mac(value)):
            raise WriterLeaseAuthenticationError("writer lock state is unauthenticated")
        expected = {
            "format", "authority", "key_id", "managed_writers", "managed_writers_digest",
            "root", "root_dev", "root_ino", "generation", "phase", "lease_id", "owner_identity",
        }
        if set(value) != expected:
            raise WriterLeaseAuthenticationError("writer lock state is partial")
        if (
            value["format"] != LOCK_FORMAT
            or value["authority"] != self.authority
            or value["key_id"] != self.key_id
            or value["managed_writers"] != list(self.writer_identities)
            or value["managed_writers_digest"] != _digest(list(self.writer_identities))
            or value["root"] != root
            or value["root_dev"] != dev
            or value["root_ino"] != ino
            or not isinstance(value["generation"], int)
            or isinstance(value["generation"], bool)
            or value["generation"] < 0
            or value["phase"] not in {"active", "retiring", "unsafe", "complete"}
        ):
            raise WriterLeaseAuthenticationError("writer lock state does not match this authority or checkout")
        return _LockState(
            root, dev, ino, value["generation"], value["phase"],
            value["lease_id"], value["owner_identity"],
        )

    @staticmethod
    def _flock(fd: int, operation: int, message: str) -> None:
        try:
            fcntl.flock(fd, operation | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise WriterLeaseUnavailable(message) from exc
            raise WriterLeaseUnavailable("writer lease operation failed") from exc

    def _admit_writer(self, writer_identity: str) -> None:
        if writer_identity not in self.writer_identities:
            raise WriterLeaseAuthenticationError("writer identity is not admitted")

    def open_writer(
        self,
        checkout_root: Union[str, os.PathLike[str]],
        relative_path: Union[str, os.PathLike[str]],
        *,
        writer_identity: str,
        flags: int = os.O_WRONLY,
    ) -> "GuardedWriterDescriptor":
        """Open a descriptor whose every write revalidates the shared lease."""
        self._admit_writer(writer_identity)
        root, dev, ino = _root_identity(checkout_root)
        relative = _normalise_relative_path(relative_path)
        lock_fd = self._open_lock(root)
        try:
            self._flock(lock_fd, fcntl.LOCK_SH, "retirement exclusion is held")
            state = self._read_state(lock_fd, root, dev, ino)
            if state.phase != "active":
                raise WriterLeaseRevokedError("checkout writer generation is retired")
            path = Path(root).joinpath(*relative.split("/"))
            fd = os.open(path, flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
            value = os.fstat(fd)
            if not stat.S_ISREG(value.st_mode):
                os.close(fd)
                raise WriterLeaseError("managed writer target is not a regular file")
            return GuardedWriterDescriptor(self, root, dev, ino, relative, writer_identity, state.generation, fd)
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    @contextmanager
    def hold_retirement(
        self,
        checkout_root: Union[str, os.PathLike[str]],
        *,
        owner_identity: str,
    ) -> Iterator["HeldRetirementLease"]:
        """Acquire exclusive writer ownership and retain it through the body."""
        self._admit_writer(owner_identity)
        root, dev, ino = _root_identity(checkout_root)
        fd = self._open_lock(root)
        held: Optional[HeldRetirementLease] = None
        try:
            self._flock(fd, fcntl.LOCK_EX, "managed writer is active or retirement is already owned")
            state = self._read_state(fd, root, dev, ino)
            lease_id = secrets.token_hex(24)
            state = _LockState(root, dev, ino, state.generation + 1, "retiring", lease_id, owner_identity)
            self._write_state(fd, state)
            held = HeldRetirementLease(self, fd, state, _construction_token=_HELD_LEASE_CONSTRUCTION_TOKEN)
            yield held
        finally:
            if held is not None:
                try:
                    phase = "complete" if held.completed else "unsafe"
                    self._write_state(fd, _LockState(root, dev, ino, held.generation, phase, held.lease_id, owner_identity))
                finally:
                    held._active = False
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def authenticate_fence(
        self,
        fence: object,
        *,
        handle: Any,
        manifest: object,
        snapshot_digest: str,
        held: Optional["HeldRetirementLease"] = None,
    ) -> None:
        entries = validated_retirement_manifest(manifest)
        if not isinstance(fence, Mapping):
            raise WriterLeaseAuthenticationError("retirement fence is absent or malformed")
        value = dict(fence)
        authentication = value.pop("authentication", None)
        expected_keys = {
            "format", "authority", "key_id", "owner_identity", "managed_writers",
            "managed_writers_digest", "session_id", "token", "session_fence",
            "checkout_root", "root_dev", "root_ino", "lease_id", "lease_generation",
            "manifest_digest", "manifest_count", "snapshot_digest", "issued_at_ns", "expires_at_ns",
        }
        if set(value) != expected_keys:
            raise WriterLeaseAuthenticationError("retirement fence is partial or malformed")
        if not isinstance(authentication, str) or not hmac.compare_digest(authentication, self._mac(value)):
            raise WriterLeaseAuthenticationError("retirement fence is unauthenticated")
        if (
            value["format"] != FENCE_FORMAT
            or value["authority"] != self.authority
            or value["key_id"] != self.key_id
            or value["managed_writers"] != list(self.writer_identities)
            or value["managed_writers_digest"] != _digest(list(self.writer_identities))
            or value["session_id"] != handle.session_id
            or value["token"] != handle.token
            or value["session_fence"] != handle.fence
            or value["manifest_digest"] != _digest(list(entries))
            or value["manifest_count"] != len(entries)
            or value["snapshot_digest"] != snapshot_digest
        ):
            raise WriterLeaseAuthenticationError("retirement fence does not match the durable handoff")
        now_ns = int(self._clock() * 1_000_000_000)
        if not isinstance(value["issued_at_ns"], int) or not isinstance(value["expires_at_ns"], int):
            raise WriterLeaseAuthenticationError("retirement fence time is malformed")
        if value["issued_at_ns"] > now_ns or value["expires_at_ns"] < now_ns:
            raise WriterLeaseStaleError("retirement fence is stale")
        if held is not None:
            held.assert_held()
            if (
                value["checkout_root"] != held.root
                or value["root_dev"] != held.root_dev
                or value["root_ino"] != held.root_ino
                or value["lease_id"] != held.lease_id
                or value["lease_generation"] != held.generation
                or value["owner_identity"] != held.owner_identity
            ):
                raise WriterLeaseAuthenticationError("retirement fence is not owned by the held lease")


class HeldRetirementLease:
    """Unforgeable in-process capability backed by a held exclusive flock."""

    def __init__(
        self, authority: FileWriterLeaseAuthority, fd: int, state: _LockState,
        *, _construction_token: object = None,
    ) -> None:
        if _construction_token is not _HELD_LEASE_CONSTRUCTION_TOKEN:
            raise WriterLeaseAuthenticationError("held retirement leases are issued only by the file authority")
        self.authority = authority
        self._fd = fd
        self.root = state.root
        self.root_dev = state.root_dev
        self.root_ino = state.root_ino
        self.generation = state.generation
        self.lease_id = state.lease_id or ""
        self.owner_identity = state.owner_identity or ""
        self._active = True
        self.completed = False
        self._cleanup_manifest_digest: Optional[str] = None

    def assert_held(self, checkout_root: Optional[Union[str, os.PathLike[str]]] = None) -> None:
        if not self._active:
            raise WriterLeaseUnavailable("retirement lease is no longer held")
        value = os.fstat(self._fd)
        if not stat.S_ISREG(value.st_mode):
            raise WriterLeaseUnavailable("retirement lock identity changed")
        if checkout_root is not None:
            root, dev, ino = _root_identity(checkout_root)
            if (root, dev, ino) != (self.root, self.root_dev, self.root_ino):
                raise WriterLeaseAuthenticationError("retirement lease belongs to a different checkout")

    def issue_fence(self, handle: Any, manifest: object, *, snapshot_digest: str) -> Mapping[str, Any]:
        self.assert_held()
        entries = validated_retirement_manifest(manifest)
        issued = int(self.authority._clock() * 1_000_000_000)
        payload = {
            "format": FENCE_FORMAT,
            "authority": self.authority.authority,
            "key_id": self.authority.key_id,
            "owner_identity": self.owner_identity,
            "managed_writers": list(self.authority.writer_identities),
            "managed_writers_digest": _digest(list(self.authority.writer_identities)),
            "session_id": handle.session_id,
            "token": handle.token,
            "session_fence": handle.fence,
            "checkout_root": self.root,
            "root_dev": self.root_dev,
            "root_ino": self.root_ino,
            "lease_id": self.lease_id,
            "lease_generation": self.generation,
            "manifest_digest": _digest(list(entries)),
            "manifest_count": len(entries),
            "snapshot_digest": snapshot_digest,
            "issued_at_ns": issued,
            "expires_at_ns": issued + int(self.authority.fence_ttl_seconds * 1_000_000_000),
        }
        return {**payload, "authentication": self.authority._mac(payload)}

    def authenticate_fence(self, fence: object, *, handle: Any, manifest: object, snapshot_digest: str) -> None:
        self.authority.authenticate_fence(
            fence, handle=handle, manifest=manifest, snapshot_digest=snapshot_digest, held=self,
        )
        entries = validated_retirement_manifest(manifest)
        self._cleanup_manifest_digest = _digest(list(entries))

    def assert_cleanup_manifest(self, entries: Iterable[object]) -> None:
        """Require cleanup entries to be the exact authenticated manifest."""
        self.assert_held()
        manifest = []
        for entry in entries:
            if isinstance(entry, Mapping):
                path = entry.get("relative_path", entry.get("path"))
                size = entry.get("size")
                digest = entry.get("sha256", entry.get("digest"))
            else:
                path = getattr(entry, "relative_path", None)
                size = getattr(entry, "size", None)
                digest = getattr(entry, "sha256", None)
            manifest.append(canonical_json({"relative_path": path, "size": size, "sha256": digest}))
        manifest.sort()
        if self._cleanup_manifest_digest is None or _digest(manifest) != self._cleanup_manifest_digest:
            raise WriterLeaseAuthenticationError("cleanup manifest is not bound to the authenticated durable fence")

    def mark_complete(self) -> None:
        self.assert_held()
        self.completed = True


class GuardedWriterDescriptor:
    """An already-open descriptor whose writes require the current generation."""

    __slots__ = (
        "authority", "root", "root_dev", "root_ino", "relative_path",
        "writer_identity", "generation", "__fd", "_closed",
    )

    def __init__(
        self,
        authority: FileWriterLeaseAuthority,
        root: str,
        root_dev: int,
        root_ino: int,
        relative_path: str,
        writer_identity: str,
        generation: int,
        fd: int,
    ) -> None:
        self.authority = authority
        self.root = root
        self.root_dev = root_dev
        self.root_ino = root_ino
        self.relative_path = relative_path
        self.writer_identity = writer_identity
        self.generation = generation
        self.__fd = fd
        self._closed = False

    @contextmanager
    def _write_lease(self) -> Iterator[None]:
        if self._closed:
            raise ValueError("I/O operation on closed managed writer")
        lock_fd = self.authority._open_lock(self.root)
        try:
            self.authority._flock(lock_fd, fcntl.LOCK_SH, "retirement exclusion prevents managed write")
            state = self.authority._read_state(lock_fd, self.root, self.root_dev, self.root_ino)
            if state.phase != "active" or state.generation != self.generation:
                raise WriterLeaseRevokedError("already-open writer descriptor was revoked by retirement")
            yield
            os.fsync(self.__fd)
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def write(self, data: bytes) -> int:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("managed writer data must be bytes-like")
        with self._write_lease():
            return os.write(self.__fd, bytes(data))

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed managed writer")
        return os.lseek(self.__fd, offset, whence)

    def close(self) -> None:
        if not self._closed:
            os.close(self.__fd)
            self._closed = True

    def __enter__(self) -> "GuardedWriterDescriptor":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


__all__ = [
    "FENCE_FORMAT", "LOCK_FORMAT", "WriterLeaseError", "WriterLeaseUnavailable",
    "WriterLeaseAuthenticationError", "WriterLeaseStaleError", "WriterLeaseRevokedError",
    "validated_retirement_manifest", "FileWriterLeaseAuthority", "HeldRetirementLease",
    "GuardedWriterDescriptor",
]
