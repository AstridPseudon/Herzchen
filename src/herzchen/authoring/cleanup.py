"""Fail-closed cleanup for registered managed-authoring files.

The session writer owns durable lifecycle state.  This module owns only the
physical, retryable cleanup that follows release.  It deliberately uses
descriptor-relative operations and never recursively removes a checkout.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple, Union

from herzchen.contracts import CleanupStatus

from .writer_lease import HeldRetirementLease


class CleanupError(RuntimeError):
    """Base class for safe-cleanup failures."""


class CleanupUnsafeError(CleanupError):
    """The captured checkout or writer state is no longer safe to clean."""


class CleanupPathError(CleanupUnsafeError):
    """A registered path is not a clean relative path below the checkout."""


class CleanupIdentityError(CleanupUnsafeError):
    """The checkout parent, file identity, type, or digest changed."""


class CleanupWriterError(CleanupUnsafeError):
    """A managed writer is active or its state is unknown."""


@dataclass(frozen=True)
class RegisteredFile:
    """A disposable file registered by an authoring session.

    ``sha256`` and ``size`` are the exact final-capture values that authorize
    retirement.  The fields remain optional at the value-object boundary so
    callers can be validated with the established narrow cleanup error, but a
    nonempty public cleanup request must supply both.
    """

    relative_path: str
    sha256: Optional[str] = None
    size: Optional[int] = None


@dataclass(frozen=True)
class CleanupObservation:
    status: CleanupStatus
    root: str
    deleted: Tuple[str, ...] = ()
    remaining: Tuple[str, ...] = ()
    error: Optional[str] = None

    @property
    def complete(self) -> bool:
        return self.status == CleanupStatus.COMPLETE


@dataclass(frozen=True)
class _Identity:
    dev: int
    ino: int
    mode: int


def _identity(value: os.stat_result) -> _Identity:
    return _Identity(int(value.st_dev), int(value.st_ino), int(value.st_mode))


def _normalise(value: Union[str, os.PathLike[str]]) -> str:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise CleanupPathError("registered cleanup path is malformed")
    candidate = raw.replace("\\", "/")
    if os.path.isabs(raw) or (len(raw) >= 2 and raw[1] == ":"):
        raise CleanupPathError("absolute cleanup paths are not allowed")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise CleanupPathError("cleanup paths must be clean relative paths")
    return "/".join(parts)


def _entries(values: Iterable[Union[str, os.PathLike[str], RegisteredFile, Mapping[str, object]]]) -> Tuple[RegisteredFile, ...]:
    result = []
    seen = set()
    for value in values:
        if isinstance(value, RegisteredFile):
            item = value
        elif isinstance(value, Mapping):
            path = value.get("relative_path", value.get("path"))
            item = RegisteredFile(path, value.get("sha256", value.get("digest")), value.get("size"))  # type: ignore[arg-type]
        else:
            item = RegisteredFile(value)
        path = _normalise(item.relative_path)
        if path in seen:
            raise CleanupPathError("duplicate registered cleanup path: " + path)
        seen.add(path)
        if item.sha256 is not None and (not isinstance(item.sha256, str) or len(item.sha256) != 64 or any(c not in "0123456789abcdef" for c in item.sha256)):
            raise CleanupIdentityError("registered cleanup digest is invalid: " + path)
        if item.size is not None and (not isinstance(item.size, int) or isinstance(item.size, bool) or item.size < 0):
            raise CleanupIdentityError("registered cleanup size is invalid: " + path)
        result.append(RegisteredFile(path, item.sha256, item.size))
    return tuple(result)


def registered_files_from_manifest(manifest: Iterable[object]) -> Tuple[RegisteredFile, ...]:
    """Convert an exact snapshot manifest to cleanup entries.

    Session snapshots carry manifest entries as canonical JSON strings across
    the existing FND boundary; durable tree snapshots expose mappings.  Both
    forms are accepted, but no form may omit its digest or size here.
    """
    converted = []
    for value in manifest:
        item = value
        if isinstance(value, str):
            try:
                item = json.loads(value)
            except ValueError as exc:
                raise CleanupIdentityError("retirement manifest is not canonical JSON") from exc
        if isinstance(item, Mapping):
            path = item.get("relative_path", item.get("path"))
            digest = item.get("sha256", item.get("digest"))
            size = item.get("size")
        else:
            path = getattr(item, "relative_path", None)
            digest = getattr(item, "sha256", None)
            size = getattr(item, "size", None)
        if not isinstance(path, (str, os.PathLike)) or not isinstance(digest, str) or not isinstance(size, int) or isinstance(size, bool):
            raise CleanupIdentityError("retirement manifest entry lacks exact path, digest, or size")
        converted.append(RegisteredFile(path, digest, size))
    return _entries(converted)


def _writer_is_quiescent(writer_check: Optional[Callable[[], object]]) -> None:
    """Apply a supplemental health probe; never treat it as ownership."""
    if writer_check is None:
        raise CleanupWriterError("managed writer state is unknown")
    try:
        value = writer_check()
    except BaseException as exc:
        raise CleanupWriterError("managed writer state is unknown") from exc
    if value is True or (isinstance(value, str) and value in {"quiescent", "idle", "stopped"}):
        return
    if value is False or (isinstance(value, str) and value in {"active", "open", "writing"}):
        raise CleanupWriterError("managed writer is active")
    raise CleanupWriterError("managed writer state is unknown")


def _writer_guard_is_held(retirement_guard: object, checkout_root: Union[str, os.PathLike[str]]) -> None:
    if not isinstance(retirement_guard, HeldRetirementLease):
        raise CleanupWriterError("authenticated retirement exclusion is not held")
    assertion = getattr(retirement_guard, "assert_held", None)
    if not callable(assertion):
        raise CleanupWriterError("retirement guard is not a held capability")
    try:
        assertion(checkout_root)
    except BaseException as exc:
        raise CleanupWriterError("authenticated retirement exclusion is not held") from exc


def _manifest_is_authenticated(retirement_guard: object, entries: Sequence[RegisteredFile]) -> None:
    assertion = getattr(retirement_guard, "assert_cleanup_manifest", None)
    if not callable(assertion):
        raise CleanupWriterError("retirement guard has no authenticated cleanup manifest")
    try:
        assertion(entries)
    except BaseException as exc:
        raise CleanupWriterError("cleanup manifest is not authenticated by the held fence") from exc


def _open_root(root: Union[str, os.PathLike[str]]) -> Tuple[Path, int, _Identity, _Identity]:
    path = Path(root)
    try:
        root_stat = os.lstat(path)
        parent_stat = os.lstat(path.parent)
    except OSError as exc:
        raise CleanupIdentityError("checkout root cannot be identified") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise CleanupIdentityError("checkout root must be a real directory")
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise CleanupIdentityError("checkout parent must be a real directory")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CleanupIdentityError("checkout root cannot be opened safely") from exc
    try:
        opened = os.fstat(fd)
        if _identity(opened) != _identity(root_stat):
            raise CleanupIdentityError("checkout root identity changed while opening")
    except BaseException:
        os.close(fd)
        raise
    return path, fd, _identity(root_stat), _identity(parent_stat)


def _validate_root(path: Path, root_identity: _Identity, parent_identity: _Identity) -> None:
    try:
        current = os.lstat(path)
        parent = os.lstat(path.parent)
    except OSError as exc:
        raise CleanupIdentityError("checkout root or parent disappeared") from exc
    if stat.S_ISLNK(current.st_mode) or _identity(current) != root_identity:
        raise CleanupIdentityError("checkout root identity changed")
    if stat.S_ISLNK(parent.st_mode) or _identity(parent) != parent_identity:
        raise CleanupIdentityError("checkout parent identity changed")


def _open_parent(root_fd: int, parts: Sequence[str]) -> Tuple[int, str]:
    if not parts:
        raise CleanupPathError("cleanup path has no file name")
    current = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            next_fd = os.open(component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
            os.close(current)
            current = next_fd
        return current, parts[-1]
    except BaseException:
        os.close(current)
        raise CleanupIdentityError("registered cleanup parent is not stable")


def _read_identity_and_digest(parent_fd: int, name: str, expected: RegisteredFile) -> Tuple[_Identity, int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise CleanupIdentityError("registered cleanup file cannot be opened: " + expected.relative_path) from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise CleanupIdentityError("registered cleanup target is not a regular file: " + expected.relative_path)
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        actual_digest = digest.hexdigest()
        if expected.sha256 is not None and actual_digest != expected.sha256:
            raise CleanupIdentityError("registered cleanup digest changed: " + expected.relative_path)
        if expected.size is not None and size != expected.size:
            raise CleanupIdentityError("registered cleanup size changed: " + expected.relative_path)
        return _identity(before), size, actual_digest
    finally:
        os.close(fd)


def _scan_files(root_fd: int, prefix: str = "") -> Tuple[str, ...]:
    """Enumerate file-like entries without following a checkout symlink."""
    found = []
    try:
        entries = os.scandir(root_fd)
    except OSError as exc:
        raise CleanupIdentityError("checkout cannot be scanned safely") from exc
    with entries:
        for entry in entries:
            relative = prefix + entry.name
            try:
                value = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CleanupIdentityError("checkout entry cannot be identified: " + relative) from exc
            if stat.S_ISDIR(value.st_mode):
                if entry.is_symlink():
                    found.append(relative)
                    continue
                try:
                    child_fd = os.open(entry.name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
                except OSError as exc:
                    raise CleanupIdentityError("checkout directory cannot be opened safely: " + relative) from exc
                try:
                    found.extend(_scan_files(child_fd, relative + "/"))
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode):
                found.append(relative)
            else:
                raise CleanupIdentityError("checkout contains an unsupported entry: " + relative)
    return tuple(sorted(found))


def cleanup_registered_files(
    checkout_root: Union[str, os.PathLike[str]],
    registered_files: Iterable[Union[str, os.PathLike[str], RegisteredFile, Mapping[str, object]]],
    *,
    retirement_guard: Optional[object] = None,
    writer_check: Optional[Callable[[], object]] = None,
    before_delete: Optional[Callable[[str], object]] = None,
    before_unlink: Optional[Callable[[str], object]] = None,
) -> CleanupObservation:
    """Delete only the supplied registered files, or return a retryable state.

    Every file is reopened with ``O_NOFOLLOW`` below the retained checkout
    descriptor, hashed, identity-checked, and checked again immediately before
    its unlink.  Parent/root replacement and any unexpected filesystem object
    fail closed.  A failure after earlier deletions returns those deletions and
    leaves all other files for a later retry.  Nonempty requests must use the
    exact digest and size captured before retirement; current bytes are never
    accepted as a just-in-time baseline.  Writer ownership must also be
    covered by an authenticated, held exclusive retirement guard for the
    entire compare/unlink sequence.  A boolean writer probe is only a
    supplemental health signal and can never substitute for that capability.
    """
    entries = _entries(registered_files)
    if entries and any(item.sha256 is None or item.size is None for item in entries):
        raise CleanupIdentityError("registered cleanup entries require exact digest and size")
    path, root_fd, root_identity, parent_identity = _open_root(checkout_root)
    deleted = []
    remaining = [item.relative_path for item in entries]
    try:
        _writer_guard_is_held(retirement_guard, path)
        _manifest_is_authenticated(retirement_guard, entries)
        if writer_check is not None:
            _writer_is_quiescent(writer_check)
        _validate_root(path, root_identity, parent_identity)
        registered_names = {item.relative_path for item in entries}
        actual_names = set(_scan_files(root_fd))
        unexpected = sorted(actual_names - registered_names)
        if unexpected:
            raise CleanupIdentityError("unexpected checkout files: " + ", ".join(unexpected))
        for item in entries:
            _writer_guard_is_held(retirement_guard, path)
            if writer_check is not None:
                _writer_is_quiescent(writer_check)
            _validate_root(path, root_identity, parent_identity)
            parts = item.relative_path.split("/")
            try:
                parent_fd, name = _open_parent(root_fd, parts)
            except CleanupError:
                raise
            try:
                expected_identity, expected_size, expected_digest = _read_identity_and_digest(parent_fd, name, item)
                if before_delete is not None:
                    result = before_delete(item.relative_path)
                    if result is False:
                        raise CleanupWriterError("cleanup deletion was not authorised")
                _writer_guard_is_held(retirement_guard, path)
                if writer_check is not None:
                    _writer_is_quiescent(writer_check)
                _validate_root(path, root_identity, parent_identity)
                current_identity, current_size, current_digest = _read_identity_and_digest(
                    parent_fd, name, RegisteredFile(item.relative_path, None, None)
                )
                if current_identity != expected_identity:
                    raise CleanupIdentityError("registered cleanup file identity changed: " + item.relative_path)
                # The second read must still equal the first exact capture,
                # not merely retain the same inode.  In-place late writes do
                # not change inode identity but must never be deleted as a
                # just-in-time cleanup baseline.
                if current_size != expected_size:
                    raise CleanupIdentityError("registered cleanup file size changed: " + item.relative_path)
                if current_digest != expected_digest:
                    raise CleanupIdentityError("registered cleanup file digest changed: " + item.relative_path)
                if before_unlink is not None:
                    result = before_unlink(item.relative_path)
                    if result is False:
                        raise CleanupWriterError("cleanup unlink was not authorised")
                    _writer_guard_is_held(retirement_guard, path)
                os.unlink(name, dir_fd=parent_fd)
            except FileNotFoundError as exc:
                raise CleanupIdentityError("registered cleanup file disappeared: " + item.relative_path) from exc
            finally:
                os.close(parent_fd)
            deleted.append(item.relative_path)
            remaining.remove(item.relative_path)
        _validate_root(path, root_identity, parent_identity)
        return CleanupObservation(CleanupStatus.COMPLETE, str(path), tuple(deleted), tuple(remaining))
    except BaseException as exc:
        if isinstance(exc, CleanupError):
            error = str(exc)
        else:
            error = str(exc) or exc.__class__.__name__
        status = CleanupStatus.UNSAFE if isinstance(exc, CleanupUnsafeError) else CleanupStatus.PENDING
        return CleanupObservation(status, str(path), tuple(deleted), tuple(remaining), error)
    finally:
        os.close(root_fd)


def cleanup_status(observation: CleanupObservation) -> CleanupStatus:
    """Small compatibility helper for callers persisting session status."""
    return observation.status


# Descriptive aliases make the narrow physical boundary easy for host code to
# discover without creating another lifecycle implementation.
CleanupManager = cleanup_registered_files
safe_cleanup = cleanup_registered_files


__all__ = [
    "CleanupError", "CleanupUnsafeError", "CleanupPathError", "CleanupIdentityError", "CleanupWriterError",
    "RegisteredFile", "CleanupObservation", "registered_files_from_manifest", "cleanup_registered_files", "cleanup_status", "CleanupManager", "safe_cleanup",
]
