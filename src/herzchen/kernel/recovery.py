"""Neutral recovery, snapshot, cursor, and persisted interval mechanics.

FND-05 deliberately builds on the FND-03/FND-04 owner.  Recovery records are
ordinary identities and every state change goes through :meth:`Store.mutate`;
snapshots contain a consistent SQLite backup plus authenticated references to
the external bytes needed by a host.  This module does not execute external
operations and does not own a second event log or database connection.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    EventCursor,
    EventEnvelope,
    ResourceRef,
    TransactionContext,
    canonical_json,
)

from .schema import COMPOSITION, SCHEMA_FINGERPRINT, SCHEMA_REVISION
from .store import Store, StoreError, TargetMismatchError, Transaction, VersionConflictError


SNAPSHOT_FORMAT = "fnd-05.snapshot.v1"
CURSOR_FORMAT = "fnd-05.cursor.v1"
RECOVERY_KIND = "runtime-epoch"
RECOVERY_SCHEMA_REVISION = "fnd-05.recovery.v1"
INTERVAL_KIND = "attention-interval"
INTERVAL_SCHEMA_REVISION = "fnd-05.interval.v1"


class RecoveryError(StoreError):
    """Base error for neutral recovery and attention state."""


class SnapshotError(RecoveryError):
    """Snapshot creation or manifest validation failed."""


class SnapshotValidationError(SnapshotError):
    """A snapshot or restore candidate failed an integrity/expectation check."""


class RestoreActivationError(SnapshotError):
    """A verified candidate could not be activated without overwriting data."""


class CursorError(RecoveryError):
    """A bounded event cursor is malformed, out of scope, or expired."""


class CursorMalformedError(CursorError):
    """The opaque cursor cannot be decoded or fails its integrity digest."""


class CursorScopeError(CursorError):
    """The cursor does not match the requested authority, stream, or filter."""


class CursorExpiredError(CursorError):
    """The caller must establish a fresh cursor because this one expired."""


class StaleTokenError(RecoveryError):
    """A runtime/session token no longer authorizes a durable settlement."""


class UnknownTokenError(RecoveryError):
    """A token was not found in the durable recovery state."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError("invalid persisted timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _ref_dict(value: ResourceRef) -> dict[str, Any]:
    if not isinstance(value, ResourceRef):
        raise TypeError("identity must be a ResourceRef")
    return value.to_dict()


def _ref(value: Mapping[str, Any]) -> ResourceRef:
    try:
        return ResourceRef.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError("invalid persisted resource reference") from exc


def _ensure_unused(path: Path) -> None:
    if path.exists():
        raise RestoreActivationError("restore root already exists; refusing to overwrite it: {}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)


def _copy_exact(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(str(source), str(target), follow_symlinks=False)
    return _sha256_bytes(target.read_bytes())


@dataclass(frozen=True)
class SnapshotManifest:
    """The authenticated description of one consistent common-state snapshot."""

    snapshot_id: str
    store_authority: str
    source_identity: ResourceRef
    realm_identity: ResourceRef
    schema_revision: str
    schema_fingerprint: str
    composition: Tuple[str, ...]
    composition_digest: str
    database_digest: str
    database_size: int
    journal_files: Tuple[Mapping[str, Any], ...]
    event_watermarks: Mapping[str, int]
    external_objects: Tuple[Mapping[str, Any], ...]
    domain_descriptors: Tuple[Mapping[str, Any], ...]
    cursors: Tuple[Mapping[str, Any], ...]
    created_at: str
    manifest_digest: str
    format_revision: str = SNAPSHOT_FORMAT

    def _body(self) -> dict[str, Any]:
        return {
            "format_revision": self.format_revision,
            "snapshot_id": self.snapshot_id,
            "store_authority": self.store_authority,
            "source_identity": self.source_identity.to_dict(),
            "realm_identity": self.realm_identity.to_dict(),
            "schema_revision": self.schema_revision,
            "schema_fingerprint": self.schema_fingerprint,
            "composition": list(self.composition),
            "composition_digest": self.composition_digest,
            "database_digest": self.database_digest,
            "database_size": self.database_size,
            "journal_files": [dict(item) for item in self.journal_files],
            "event_watermarks": dict(self.event_watermarks),
            "external_objects": [dict(item) for item in self.external_objects],
            "domain_descriptors": [dict(item) for item in self.domain_descriptors],
            "cursors": [dict(item) for item in self.cursors],
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return dict(self._body(), manifest_digest=self.manifest_digest)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotManifest":
        if not isinstance(value, Mapping):
            raise SnapshotValidationError("snapshot manifest must be an object")
        try:
            body = dict(value)
            digest = body.pop("manifest_digest")
            manifest = cls(
                str(body["snapshot_id"]), str(body["store_authority"]), _ref(body["source_identity"]),
                _ref(body["realm_identity"]), str(body["schema_revision"]), str(body["schema_fingerprint"]),
                tuple(str(item) for item in body["composition"]), str(body["composition_digest"]),
                str(body["database_digest"]), int(body["database_size"]),
                tuple(dict(item) for item in body.get("journal_files", [])),
                {str(key): int(number) for key, number in dict(body.get("event_watermarks", {})).items()},
                tuple(dict(item) for item in body.get("external_objects", [])),
                tuple(dict(item) for item in body.get("domain_descriptors", [])),
                tuple(dict(item) for item in body.get("cursors", [])), str(body["created_at"]), str(digest),
                str(body.get("format_revision", SNAPSHOT_FORMAT)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SnapshotValidationError("snapshot manifest is incomplete") from exc
        if manifest.format_revision != SNAPSHOT_FORMAT:
            raise SnapshotValidationError("unsupported snapshot format")
        if manifest.manifest_digest != _sha256_json(manifest._body()):
            raise SnapshotValidationError("snapshot manifest digest mismatch")
        return manifest


@dataclass(frozen=True)
class RestoreCandidate:
    root: Path
    database_path: Path
    manifest: SnapshotManifest
    object_paths: Tuple[Path, ...] = ()

    @property
    def path(self) -> Path:
        return self.root

    def __fspath__(self) -> str:
        return os.fspath(self.root)


@dataclass(frozen=True)
class RestoreResult:
    candidate: RestoreCandidate
    activated_root: Optional[Path]


def _composition_digest(composition: Sequence[str]) -> str:
    return _sha256_json(list(composition))


def _manifest_at(root: Path) -> SnapshotManifest:
    try:
        with (root / "manifest.json").open("r", encoding="utf-8") as handle:
            return SnapshotManifest.from_dict(json.load(handle))
    except FileNotFoundError as exc:
        raise SnapshotValidationError("snapshot manifest is missing") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotValidationError("snapshot manifest is not valid JSON") from exc


def _validate_expectations(
    manifest: SnapshotManifest,
    *,
    expected_source_identity: ResourceRef,
    expected_realm_identity: ResourceRef,
    expected_authority: str,
    expected_composition: Sequence[str],
    expected_composition_digest: str,
    expected_schema_fingerprint: str,
) -> None:
    if not isinstance(expected_source_identity, ResourceRef) or not isinstance(expected_realm_identity, ResourceRef):
        raise TypeError("source and realm expectations must be ResourceRef values")
    if manifest.store_authority != expected_authority:
        raise SnapshotValidationError("snapshot authority does not match caller expectation")
    if manifest.source_identity != expected_source_identity or manifest.realm_identity != expected_realm_identity:
        raise SnapshotValidationError("snapshot source/realm identity does not match caller expectation")
    expected = tuple(sorted(expected_composition))
    if tuple(manifest.composition) != expected:
        raise SnapshotValidationError("snapshot composition does not match caller expectation")
    if manifest.composition_digest != expected_composition_digest or expected_composition_digest != _composition_digest(expected):
        raise SnapshotValidationError("snapshot composition digest does not match caller expectation")
    if manifest.schema_fingerprint != expected_schema_fingerprint or manifest.schema_revision != SCHEMA_REVISION:
        raise SnapshotValidationError("snapshot schema identity does not match caller expectation")


def create_snapshot(
    store: Store,
    root: Union[os.PathLike, str],
    *,
    source_identity: ResourceRef,
    realm_identity: ResourceRef,
    external_refs: Sequence[ResourceRef] = (),
    object_files: Optional[Mapping[Union[str, ResourceRef], Union[os.PathLike, str, bytes, bytearray]]] = None,
    cursors: Sequence[EventCursor] = (),
    snapshot_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> SnapshotManifest:
    """Create a consistent snapshot without opening a second Store writer.

    ``object_files`` is optional host-owned CAS evidence.  A string/path value
    is copied byte-for-byte; bytes are materialised into the snapshot.  Plain
    ``external_refs`` remain references when their bytes are not in scope.
    """
    if not isinstance(store, Store):
        raise TypeError("store must be a Store")
    if store.path == ":memory:":
        raise SnapshotError("durable snapshots require a file-backed Store")
    if not isinstance(source_identity, ResourceRef) or not isinstance(realm_identity, ResourceRef):
        raise TypeError("source_identity and realm_identity must be ResourceRef values")
    root_path = Path(root)
    _ensure_unused(root_path)
    root_path.mkdir(mode=0o700)
    database_path = root_path / "database.sqlite3"
    try:
        # The owner lock excludes every other Store writer.  Refuse an
        # in-flight local transaction, then copy the exact committed database
        # bytes and preserve any sidecars as evidence below.
        if store.connection.in_transaction:
            raise SnapshotError("snapshot cannot start inside an active Store transaction")
        _copy_exact(Path(store.path), database_path)
        database_digest = _sha256_bytes(database_path.read_bytes())
        journal_files = []
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(store.path) + suffix)
            if sidecar.exists() and sidecar.is_file():
                destination_sidecar = root_path / "journal-evidence" / ("database.sqlite3" + suffix)
                digest = _copy_exact(sidecar, destination_sidecar)
                journal_files.append({"name": suffix, "digest": digest, "size": sidecar.stat().st_size})

        external_objects = []
        for ref in external_refs:
            if not isinstance(ref, ResourceRef):
                raise TypeError("external_refs must contain ResourceRef values")
            external_objects.append({"ref": ref.to_dict(), "digest": None, "size": None})
        for key, value in (object_files or {}).items():
            ref_value = key.to_dict() if isinstance(key, ResourceRef) else {"authority": "external", "kind": "object", "id": str(key), "revision": None}
            object_root = root_path / "objects"
            object_root.mkdir(mode=0o700, exist_ok=True)
            if isinstance(value, (bytes, bytearray)):
                data = bytes(value)
                digest = _sha256_bytes(data)
                output = object_root / digest
                with output.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            else:
                input_path = Path(value)
                if not input_path.is_file():
                    raise SnapshotError("external object is not a regular file: {}".format(input_path))
                digest = _copy_exact(input_path, object_root / _sha256_bytes(input_path.read_bytes()))
                output = object_root / digest
            external_objects.append({"ref": ref_value, "digest": digest, "size": output.stat().st_size, "path": "objects/" + digest})

        event_rows = store.connection.execute(
            "SELECT stream, MAX(sequence) FROM events WHERE store_authority = ? GROUP BY stream ORDER BY stream",
            (store.authority,),
        ).fetchall()
        event_watermarks = {str(row[0]): int(row[1]) for row in event_rows}
        cursor_dicts = []
        for cursor in cursors:
            if not isinstance(cursor, EventCursor):
                raise TypeError("cursors must contain EventCursor values")
            if cursor.authority != store.authority:
                raise SnapshotValidationError("cursor authority does not match the Store")
            cursor_dicts.append(cursor.to_dict())
        composition = tuple(sorted(COMPOSITION))
        created_at = _iso(now or _utc_now())
        domain_descriptors = [descriptor.to_dict() for descriptor in store.registered_domains()]
        manifest_without_digest = {
            "format_revision": SNAPSHOT_FORMAT,
            "snapshot_id": snapshot_id or hashlib.sha256((created_at + database_digest).encode("utf-8")).hexdigest()[:24],
            "store_authority": store.authority,
            "source_identity": source_identity.to_dict(),
            "realm_identity": realm_identity.to_dict(),
            "schema_revision": SCHEMA_REVISION,
            "schema_fingerprint": SCHEMA_FINGERPRINT,
            "composition": list(composition),
            "composition_digest": _composition_digest(composition),
            "database_digest": database_digest,
            "database_size": database_path.stat().st_size,
            "journal_files": journal_files,
            "event_watermarks": event_watermarks,
            "external_objects": external_objects,
            "domain_descriptors": domain_descriptors,
            "cursors": cursor_dicts,
            "created_at": created_at,
        }
        manifest = SnapshotManifest(
            manifest_without_digest["snapshot_id"], store.authority, source_identity, realm_identity,
            SCHEMA_REVISION, SCHEMA_FINGERPRINT, composition, manifest_without_digest["composition_digest"],
            database_digest, database_path.stat().st_size, tuple(journal_files), event_watermarks,
            tuple(external_objects), tuple(domain_descriptors), tuple(cursor_dicts), created_at, _sha256_json(manifest_without_digest),
        )
        with (root_path / "manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest.to_dict(), handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        return manifest
    except BaseException:
        # The partially written snapshot remains available for diagnosis; no
        # caller data is removed or repaired after an interrupted capture.
        raise


def verify_restore_candidate(
    snapshot_root: Union[os.PathLike, str],
    candidate_root: Union[os.PathLike, str],
    *,
    expected_source_identity: ResourceRef,
    expected_realm_identity: ResourceRef,
    expected_authority: str,
    expected_composition: Sequence[str],
    expected_composition_digest: str,
    expected_schema_fingerprint: str = SCHEMA_FINGERPRINT,
) -> RestoreCandidate:
    """Verify a snapshot in a fresh root, leaving failures inspectable."""
    snapshot = Path(snapshot_root)
    candidate = Path(candidate_root)
    manifest = _manifest_at(snapshot)
    _validate_expectations(
        manifest,
        expected_source_identity=expected_source_identity,
        expected_realm_identity=expected_realm_identity,
        expected_authority=expected_authority,
        expected_composition=expected_composition,
        expected_composition_digest=expected_composition_digest,
        expected_schema_fingerprint=expected_schema_fingerprint,
    )
    _ensure_unused(candidate)
    candidate.mkdir(mode=0o700)
    source_db = snapshot / "database.sqlite3"
    if not source_db.is_file():
        raise SnapshotValidationError("snapshot database is missing")
    if source_db.stat().st_size != manifest.database_size or _sha256_bytes(source_db.read_bytes()) != manifest.database_digest:
        raise SnapshotValidationError("snapshot database bytes/digest do not match the manifest")
    candidate_db = candidate / "database.sqlite3"
    _copy_exact(source_db, candidate_db)
    object_paths = []
    for item in manifest.external_objects:
        digest = item.get("digest")
        relative = item.get("path")
        if digest is None or relative is None:
            continue
        source_object = snapshot / str(relative)
        if not source_object.is_file() or _sha256_bytes(source_object.read_bytes()) != digest:
            raise SnapshotValidationError("external object bytes/digest do not match the manifest")
        destination_object = candidate / "objects" / str(digest)
        _copy_exact(source_object, destination_object)
        object_paths.append(destination_object)

    for item in manifest.journal_files:
        name = item.get("name")
        if name not in ("-journal", "-wal", "-shm"):
            raise SnapshotValidationError("snapshot journal descriptor is invalid")
        journal = snapshot / "journal-evidence" / ("database.sqlite3" + str(name))
        if not journal.is_file() or int(item.get("size", -1)) != journal.stat().st_size or _sha256_bytes(journal.read_bytes()) != item.get("digest"):
            raise SnapshotValidationError("snapshot journal bytes/digest do not match the manifest")
        _copy_exact(journal, candidate / "journal-evidence" / ("database.sqlite3" + str(name)))

    # Ordinary open is deliberately used only as a verifier.  It admits the
    # exact existing composition and performs no migration or repair.
    try:
        domains = tuple(DomainContribution.from_dict(item) for item in manifest.domain_descriptors)
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError("snapshot domain descriptor is invalid") from exc
    checked = Store.open(candidate_db, authority=expected_authority, expected_domains=domains)
    checked.close()
    with (candidate / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest.to_dict(), handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    return RestoreCandidate(candidate, candidate_db, manifest, tuple(object_paths))


def restore_snapshot(
    snapshot_root: Union[os.PathLike, str],
    target_root: Union[os.PathLike, str],
    *,
    expected_source_identity: ResourceRef,
    expected_realm_identity: ResourceRef,
    expected_authority: str,
    expected_composition: Sequence[str],
    expected_composition_digest: str,
    expected_schema_fingerprint: str = SCHEMA_FINGERPRINT,
    candidate_root: Optional[Union[os.PathLike, str]] = None,
) -> RestoreResult:
    """Verify into an unused candidate, then atomically activate if possible."""
    target = Path(target_root)
    candidate_path = Path(candidate_root) if candidate_root is not None else target.with_name(target.name + ".restore-candidate")
    candidate = verify_restore_candidate(
        snapshot_root, candidate_path,
        expected_source_identity=expected_source_identity,
        expected_realm_identity=expected_realm_identity,
        expected_authority=expected_authority,
        expected_composition=expected_composition,
        expected_composition_digest=expected_composition_digest,
        expected_schema_fingerprint=expected_schema_fingerprint,
    )
    if target.exists():
        raise RestoreActivationError("activation target exists; preserved it and left candidate for inspection: {}".format(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(candidate.root), str(target))
    return RestoreResult(candidate, target)


@dataclass(frozen=True)
class EventFilter:
    """Explicit, serialisable visibility/filter shape for one stream."""

    event_types: Tuple[str, ...] = ()
    visibility: Tuple[str, ...] = ("public",)
    subject: Optional[ResourceRef] = None
    operation: Optional[str] = None

    def __post_init__(self) -> None:
        types = (self.event_types,) if isinstance(self.event_types, str) else tuple(self.event_types)
        visibility = (self.visibility,) if isinstance(self.visibility, str) else tuple(self.visibility)
        if types != tuple(sorted(set(types))) or any(not isinstance(item, str) or not item.strip() for item in types):
            raise CursorScopeError("event_types must be a sorted unique tuple of non-blank strings")
        if not visibility or visibility != tuple(sorted(set(visibility))) or any(not isinstance(item, str) or not item.strip() for item in visibility):
            raise CursorScopeError("visibility must be a sorted non-empty tuple of non-blank strings")
        if self.subject is not None and not isinstance(self.subject, ResourceRef):
            raise TypeError("subject must be a ResourceRef")
        if self.operation is not None and (not isinstance(self.operation, str) or not self.operation.strip()):
            raise CursorScopeError("operation must be a non-blank string")
        object.__setattr__(self, "event_types", types)
        object.__setattr__(self, "visibility", visibility)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_types": list(self.event_types),
            "visibility": list(self.visibility),
            "subject": None if self.subject is None else self.subject.to_dict(),
            "operation": self.operation,
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True)
class EventPage:
    events: Tuple[EventEnvelope, ...]
    cursor: str
    next_cursor: Optional[str]
    status: str = "ok"
    gap_from: Optional[int] = None
    gap_to: Optional[int] = None
    watermark: int = 0

    @property
    def complete(self) -> bool:
        return self.next_cursor is None and self.status == "ok"


def _token_encode(payload: Mapping[str, Any]) -> str:
    body = canonical_json(dict(payload)).encode("utf-8")
    envelope = dict(payload, integrity=_sha256_bytes(body))
    encoded = base64.urlsafe_b64encode(canonical_json(envelope).encode("utf-8")).decode("ascii").rstrip("=")
    return encoded


def _token_decode(token: str) -> dict[str, Any]:
    if not isinstance(token, str) or not token:
        raise CursorMalformedError("cursor must be a non-empty opaque string")
    try:
        padded = token + "=" * (-len(token) % 4)
        envelope = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        integrity = envelope.pop("integrity")
        if integrity != _sha256_bytes(canonical_json(envelope).encode("utf-8")):
            raise CursorMalformedError("cursor integrity digest mismatch")
        return envelope
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise CursorMalformedError("cursor is malformed") from exc


class EventCursorReader:
    """Bounded keyset reads from the one authoritative Store event stream."""

    def __init__(self, store: Store, *, cursor_ttl_seconds: int = 3600, clock: Optional[Callable[[], datetime]] = None) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be a Store")
        if isinstance(cursor_ttl_seconds, bool) or not isinstance(cursor_ttl_seconds, int) or cursor_ttl_seconds <= 0:
            raise ValueError("cursor_ttl_seconds must be a positive integer")
        self.store = store
        self.cursor_ttl_seconds = cursor_ttl_seconds
        self.clock = clock or _utc_now

    def _shape(self, stream: str, event_filter: EventFilter, limit: int) -> dict[str, Any]:
        if not isinstance(stream, str) or not stream.strip():
            raise CursorScopeError("stream must be a non-blank string")
        if not isinstance(event_filter, EventFilter):
            raise TypeError("event_filter must be EventFilter")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if event_filter.subject is not None and event_filter.subject.authority != self.store.authority:
            raise CursorScopeError("subject authority does not match the Store")
        # Page size is a read bound, not cursor scope.  Consumers may choose a
        # different bound after a restart without changing visibility shape.
        return {"stream": stream, "filter": event_filter.to_dict(), "filter_digest": event_filter.digest}

    def _new_cursor(self, shape: Mapping[str, Any], after_sequence: int, after_event_id: Optional[str], watermark: int) -> str:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        payload = {
            "format_revision": CURSOR_FORMAT,
            "authority": self.store.authority,
            "stream": shape["stream"],
            "filter": shape["filter"],
            "filter_digest": shape["filter_digest"],
            "after_sequence": after_sequence,
            "after_event_id": after_event_id,
            "watermark": watermark,
            "expires_at": _iso(now + timedelta(seconds=self.cursor_ttl_seconds)),
        }
        return _token_encode(payload)

    def _decode_cursor(self, token: str, shape: Mapping[str, Any]) -> Tuple[int, Optional[str], int]:
        payload = _token_decode(token)
        if payload.get("format_revision") != CURSOR_FORMAT:
            raise CursorMalformedError("unsupported cursor format")
        if payload.get("authority") != self.store.authority or payload.get("stream") != shape["stream"]:
            raise CursorScopeError("cursor authority or stream does not match the request")
        if payload.get("filter_digest") != shape["filter_digest"] or payload.get("filter") != shape["filter"]:
            raise CursorScopeError("cursor filter/visibility shape does not match the request")
        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, str):
            raise CursorMalformedError("cursor expiry is invalid")
        try:
            current = self.clock()
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            expired = current.astimezone(timezone.utc) >= _parse_iso(expires_at)
        except SnapshotValidationError as exc:
            raise CursorMalformedError("cursor expiry is invalid") from exc
        if expired:
            raise CursorExpiredError("cursor has expired")
        after = payload.get("after_sequence")
        watermark = payload.get("watermark")
        if isinstance(after, bool) or not isinstance(after, int) or after < 0 or isinstance(watermark, bool) or not isinstance(watermark, int) or watermark < after:
            raise CursorMalformedError("cursor sequence watermark is invalid")
        event_id = payload.get("after_event_id")
        if event_id is not None and not isinstance(event_id, str):
            raise CursorMalformedError("cursor event identity is invalid")
        return after, event_id, watermark

    def page(
        self,
        stream: str,
        *,
        cursor: Optional[str] = None,
        event_filter: Optional[EventFilter] = None,
        limit: int = 100,
    ) -> EventPage:
        event_filter = event_filter or EventFilter()
        shape = self._shape(stream, event_filter, limit)
        if cursor is None:
            after_sequence, after_event_id = 0, None
        else:
            after_sequence, after_event_id, _ = self._decode_cursor(cursor, shape)
        connection = self.store.connection
        if after_event_id is not None:
            identity_row = connection.execute(
                "SELECT event_id FROM events WHERE store_authority = ? AND stream = ? AND sequence = ?",
                (self.store.authority, stream, after_sequence),
            ).fetchone()
            if identity_row is not None and identity_row[0] != after_event_id:
                raise CursorScopeError("cursor event identity does not match the authoritative stream")
        max_row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE store_authority = ? AND stream = ?",
            (self.store.authority, stream),
        ).fetchone()
        watermark = int(max_row[0] if max_row else 0)
        where = ["store_authority = ?", "stream = ?", "sequence > ?", "sequence <= ?"]
        params: list[Any] = [self.store.authority, stream, after_sequence, watermark]
        if event_filter.event_types:
            where.append("event_type IN ({})".format(",".join("?" for _ in event_filter.event_types)))
            params.extend(event_filter.event_types)
        if event_filter.subject is not None:
            where.extend(["subject_authority = ?", "subject_kind = ?", "subject_id = ?"])
            params.extend([event_filter.subject.authority, event_filter.subject.kind, event_filter.subject.id])
        if event_filter.operation is not None:
            where.append("operation = ?")
            params.append(event_filter.operation)
        visibility_terms = ",".join("?" for _ in event_filter.visibility)
        where.append("COALESCE(json_extract(effects_json, '$.visibility'), 'public') IN ({})".format(visibility_terms))
        params.extend(event_filter.visibility)
        rows = connection.execute(
            "SELECT * FROM events WHERE " + " AND ".join(where) + " ORDER BY sequence ASC LIMIT ?",
            tuple(params + [limit + 1]),
        ).fetchall()
        # A visibility filter must not turn deliberately hidden events into a
        # false sequence gap.  Gap detection is against the authoritative
        # stream; the returned rows are the caller's accessible projection.
        raw_first = connection.execute(
            "SELECT MIN(sequence) FROM events WHERE store_authority = ? AND stream = ? AND sequence > ? AND sequence <= ?",
            (self.store.authority, stream, after_sequence, watermark),
        ).fetchone()[0]
        status = "ok"
        gap_from = gap_to = None
        if raw_first is not None and int(raw_first) > after_sequence + 1:
            status = "gap"
            gap_from, gap_to = after_sequence + 1, int(raw_first) - 1
        selected = rows[:limit]
        event_values = tuple(self.store._event_from_row(row) for row in selected)
        last_sequence = event_values[-1].sequence if event_values else after_sequence
        last_event_id = event_values[-1].event_id if event_values else after_event_id
        post_cursor = self._new_cursor(shape, last_sequence, last_event_id, watermark)
        next_cursor = post_cursor if len(rows) > limit else None
        return EventPage(event_values, post_cursor, next_cursor, status, gap_from, gap_to, watermark)

    def catch_up(self, stream: str, *, cursor: Optional[str] = None, event_filter: Optional[EventFilter] = None, limit: int = 100) -> EventPage:
        """Alias emphasizing restart/disconnect recovery semantics."""
        return self.page(stream, cursor=cursor, event_filter=event_filter, limit=limit)


@dataclass(frozen=True)
class RecoveryToken:
    source_identity: ResourceRef
    realm_identity: ResourceRef
    authority: str
    epoch: int
    fence: int
    token: str
    operation_ref: ResourceRef
    status: str = "active"
    result_ref: Optional[ResourceRef] = None
    result: Mapping[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identity": self.source_identity.to_dict(), "realm_identity": self.realm_identity.to_dict(),
            "authority": self.authority, "epoch": self.epoch, "fence": self.fence, "token": self.token,
            "operation_ref": self.operation_ref.to_dict(), "status": self.status,
            "result_ref": None if self.result_ref is None else self.result_ref.to_dict(),
            "result": dict(self.result or {}),
        }


@dataclass(frozen=True)
class EpochState:
    source_identity: ResourceRef
    realm_identity: ResourceRef
    authority: str
    epoch: int
    tokens: Tuple[RecoveryToken, ...]
    version: int
    current_revision: Optional[str]


@dataclass(frozen=True)
class SettlementRecord:
    operation_ref: ResourceRef
    token: RecoveryToken
    result_ref: Optional[ResourceRef]
    result: Mapping[str, Any]


def _default_actor(actor: Optional[AuthenticatedActor]) -> AuthenticatedActor:
    return actor or AuthenticatedActor("neutral-kernel", "recovery", "recovery")


class RecoveryManager:
    """Atomically advance epochs and fence stale runtime/session tokens."""

    def __init__(self, store: Store, source_identity: ResourceRef, realm_identity: ResourceRef, *, actor: Optional[AuthenticatedActor] = None, clock: Optional[Callable[[], datetime]] = None) -> None:
        if not isinstance(store, Store):
            raise TypeError("store must be a Store")
        if not isinstance(source_identity, ResourceRef) or not isinstance(realm_identity, ResourceRef):
            raise TypeError("source_identity and realm_identity must be ResourceRef values")
        self.store = store
        self.source_identity = source_identity
        self.realm_identity = realm_identity
        self.actor = _default_actor(actor)
        self.clock = clock or _utc_now
        self.state_ref = ResourceRef(store.authority, RECOVERY_KIND, realm_identity.id)

    def _state(self) -> Optional[EpochState]:
        identity = self.store.get_identity(self.state_ref)
        return None if identity is None else self._state_from_identity(identity)

    def _state_from_identity(self, identity: Any) -> EpochState:
        payload = identity.payload
        if payload.get("record_type") != RECOVERY_KIND:
            raise RecoveryError("recovery identity is not an admitted epoch record")
        source = _ref(payload["source_identity"])
        realm = _ref(payload["realm_identity"])
        if source != self.source_identity or realm != self.realm_identity:
            raise TargetMismatchError("recovery source/realm identity does not match this manager")
        tokens = tuple(self._token_from_dict(item) for item in payload.get("tokens", []))
        return EpochState(source, realm, payload["authority"], int(payload["epoch"]), tokens, int(identity.version), identity.ref.revision)

    def _token_from_dict(self, value: Mapping[str, Any]) -> RecoveryToken:
        result_ref = value.get("result_ref")
        return RecoveryToken(_ref(value["source_identity"]), _ref(value["realm_identity"]), str(value["authority"]), int(value["epoch"]), int(value["fence"]), str(value["token"]), _ref(value["operation_ref"]), str(value.get("status", "active")), _ref(result_ref) if result_ref else None, dict(value.get("result", {})))

    def _payload(self, epoch: int, tokens: Iterable[RecoveryToken]) -> dict[str, Any]:
        return {
            "record_type": RECOVERY_KIND, "schema_revision": RECOVERY_SCHEMA_REVISION,
            "source_identity": self.source_identity.to_dict(), "realm_identity": self.realm_identity.to_dict(),
            "authority": self.store.authority, "epoch": epoch, "tokens": [token.to_dict() for token in tokens],
        }

    def _write_state(self, previous: Optional[EpochState], payload: Mapping[str, Any], *, request_key: str, transaction: Optional[Transaction] = None) -> EpochState:
        version = 0 if previous is None else previous.version
        target = self.state_ref if previous is None else ResourceRef(self.store.authority, RECOVERY_KIND, self.realm_identity.id, previous.current_revision)
        digest = _sha256_json({"request_key": request_key, "payload": dict(payload)})
        envelope = CommandEnvelope(
            "recovery.state", RECOVERY_SCHEMA_REVISION, target,
            TransactionContext(self.actor, request_key, digest, expected_revision=previous.current_revision if previous else None, expected_version=version),
            dict(payload),
        )
        self.store.mutate(
            envelope, event_type="recovery.state.changed",
            result_ref=ResourceRef(self.store.authority, RECOVERY_KIND, self.realm_identity.id, "rev-{}".format(version + 1)),
            effects={"record_type": RECOVERY_KIND, "epoch": payload["epoch"], "tokens": payload["tokens"], "source_identity": payload["source_identity"], "realm_identity": payload["realm_identity"], "version": version + 1},
            stream="recovery:" + self.realm_identity.id, transaction=transaction,
        )
        identity = self.store.get_identity(self.state_ref)
        if identity is None:
            raise RecoveryError("recovery state did not persist")
        return self._state_from_identity(identity)

    def begin_epoch(self, boot_token: str, *, request_key: Optional[str] = None) -> EpochState:
        if not isinstance(boot_token, str) or not boot_token.strip():
            raise RecoveryError("boot_token is required")
        previous = self._state()
        epoch = 1 if previous is None else previous.epoch + 1
        retired = tuple(RecoveryToken(token.source_identity, token.realm_identity, token.authority, token.epoch, token.fence, token.token, token.operation_ref, "retired", token.result_ref, token.result) for token in (previous.tokens if previous else ()))
        key = request_key or "recovery:epoch:{}".format(boot_token)
        return self._write_state(previous, self._payload(epoch, retired), request_key=key)

    def current(self) -> Optional[EpochState]:
        return self._state()

    def issue_token(self, operation_ref: ResourceRef, *, token: Optional[str] = None, request_key: Optional[str] = None) -> RecoveryToken:
        if not isinstance(operation_ref, ResourceRef):
            raise TypeError("operation_ref must be a ResourceRef")
        state = self._state()
        if state is None:
            raise RecoveryError("begin_epoch must precede token issuance")
        active_fences = [item.fence for item in state.tokens]
        value = token or hashlib.sha256((self.realm_identity.to_json() + operation_ref.to_json() + str(state.epoch) + str(max(active_fences or [0]) + 1)).encode("utf-8")).hexdigest()
        issued = RecoveryToken(self.source_identity, self.realm_identity, self.store.authority, state.epoch, max(active_fences or [0]) + 1, value, operation_ref)
        updated = state.tokens + (issued,)
        next_state = self._write_state(state, self._payload(state.epoch, updated), request_key=request_key or "recovery:token:{}".format(value))
        return next(item for item in next_state.tokens if item.token == value)

    def retire_token(self, token: RecoveryToken, *, request_key: Optional[str] = None) -> RecoveryToken:
        self.validate_token(token)
        state = self._state()
        assert state is not None
        updated = tuple(RecoveryToken(item.source_identity, item.realm_identity, item.authority, item.epoch, item.fence, item.token, item.operation_ref, "retired" if item.token == token.token else item.status, item.result_ref, item.result) for item in state.tokens)
        next_state = self._write_state(state, self._payload(state.epoch, updated), request_key=request_key or "recovery:retire:{}".format(token.token))
        return next(item for item in next_state.tokens if item.token == token.token)

    def validate_token(self, token: RecoveryToken) -> RecoveryToken:
        if not isinstance(token, RecoveryToken):
            raise TypeError("token must be RecoveryToken")
        state = self._state()
        if state is None:
            raise StaleTokenError("no active recovery epoch")
        found = next((item for item in state.tokens if item.token == token.token), None)
        if found is None:
            raise UnknownTokenError("token is not retained in durable recovery state")
        if found != token or found.status != "active" or found.epoch != state.epoch or found.authority != self.store.authority:
            raise StaleTokenError("token is retired or belongs to an older recovery epoch")
        return found

    def settle(
        self,
        token: RecoveryToken,
        *,
        logical_request_key: str,
        result_ref: Optional[ResourceRef] = None,
        result: Optional[Mapping[str, Any]] = None,
        apply: Optional[Callable[[], Any]] = None,
    ) -> SettlementRecord:
        """Validate the fence before invoking an optional external mutation.

        ``apply`` is an adapter/CAS hook.  A stale token raises before it is
        called.  The hook's outcome is not treated as exactly-once execution;
        the durable settlement below is the common observable record.
        """
        if not isinstance(logical_request_key, str) or not logical_request_key.strip():
            raise RecoveryError("logical_request_key is required")
        if result_ref is not None and not isinstance(result_ref, ResourceRef):
            raise TypeError("result_ref must be a ResourceRef")
        result_value = dict(result or {})
        with self.store.transaction() as tx:
            state = self._state()
            if state is None:
                raise StaleTokenError("no active recovery epoch")
            found = next((item for item in state.tokens if item.token == token.token), None)
            if found is None:
                raise UnknownTokenError("token is not retained in durable recovery state")
            if found != token or found.status != "active" or found.epoch != state.epoch:
                raise StaleTokenError("stale settlement rejected before result mutation")
            if apply is not None:
                apply()
            updated = tuple(RecoveryToken(item.source_identity, item.realm_identity, item.authority, item.epoch, item.fence, item.token, item.operation_ref, "settled" if item.token == token.token else item.status, result_ref if item.token == token.token else item.result_ref, result_value if item.token == token.token else item.result) for item in state.tokens)
            committed_state = self._write_state(state, self._payload(state.epoch, updated), request_key=logical_request_key, transaction=tx)
            committed_token = next(item for item in committed_state.tokens if item.token == token.token)
            return SettlementRecord(committed_token.operation_ref, committed_token, result_ref, result_value)

    def retain_unknown_operation(self, operation_ref: ResourceRef, details: Optional[Mapping[str, Any]] = None) -> Any:
        if not isinstance(operation_ref, ResourceRef):
            raise TypeError("operation_ref must be a ResourceRef")
        if operation_ref.authority != self.store.authority:
            raise TargetMismatchError("unknown operation must belong to this Store authority")
        payload = {"record_type": "unknown-operation", "schema_revision": RECOVERY_SCHEMA_REVISION, "operation_ref": operation_ref.to_dict(), "details": dict(details or {})}
        existing = self.store.get_identity(ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id))
        if existing is not None:
            return existing
        key = "recovery:unknown:{}".format(operation_ref.id)
        digest = _sha256_json(payload)
        envelope = CommandEnvelope("recovery.retain_unknown", RECOVERY_SCHEMA_REVISION, ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id), TransactionContext(self.actor, key, digest, expected_version=0), payload)
        self.store.mutate(envelope, event_type="recovery.operation.unknown", result_ref=ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id, "rev-1"), effects=payload, stream="recovery:" + self.realm_identity.id)
        return self.store.get_identity(ResourceRef(self.store.authority, operation_ref.kind, operation_ref.id))


@dataclass(frozen=True)
class IntervalState:
    interval_ref: ResourceRef
    interval_seconds: int
    anchor: str
    last_slot: int
    in_flight: Optional[str]
    version: int
    current_revision: Optional[str]


@dataclass(frozen=True)
class IntervalDecision:
    due: bool
    request_id: Optional[str]
    missed_intervals: int
    in_flight: bool
    state: IntervalState


class IntervalController:
    """Persisted arbitrary interval gate with coalescing and one in-flight request."""

    def __init__(self, store: Store, interval_ref: ResourceRef, interval_seconds: int, *, actor: Optional[AuthenticatedActor] = None, clock: Optional[Callable[[], datetime]] = None) -> None:
        if not isinstance(store, Store) or not isinstance(interval_ref, ResourceRef):
            raise TypeError("store and interval_ref are required")
        if interval_ref.authority != store.authority or interval_ref.kind != INTERVAL_KIND or interval_ref.revision is not None:
            raise TargetMismatchError("interval_ref must be an unpinned attention-interval identity in this Store")
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or interval_seconds <= 0:
            raise ValueError("interval_seconds must be a positive integer")
        self.store = store
        self.interval_ref = interval_ref
        self.interval_seconds = interval_seconds
        self.actor = _default_actor(actor)
        self.clock = clock or _utc_now

    def _from_identity(self, identity: Any) -> IntervalState:
        payload = identity.payload
        if payload.get("record_type") != INTERVAL_KIND or int(payload["interval_seconds"]) != self.interval_seconds:
            raise RecoveryError("persisted interval configuration does not match this controller")
        return IntervalState(self.interval_ref, self.interval_seconds, str(payload["anchor"]), int(payload["last_slot"]), payload.get("in_flight"), int(identity.version), identity.ref.revision)

    def state(self) -> Optional[IntervalState]:
        identity = self.store.get_identity(self.interval_ref)
        return None if identity is None else self._from_identity(identity)

    def _payload(self, anchor: str, last_slot: int, in_flight: Optional[str]) -> dict[str, Any]:
        return {"record_type": INTERVAL_KIND, "schema_revision": INTERVAL_SCHEMA_REVISION, "interval_seconds": self.interval_seconds, "anchor": anchor, "last_slot": last_slot, "in_flight": in_flight}

    def _write(self, prior: Optional[IntervalState], payload: Mapping[str, Any], key: str) -> IntervalState:
        version = 0 if prior is None else prior.version
        target = self.interval_ref if prior is None else ResourceRef(self.store.authority, INTERVAL_KIND, self.interval_ref.id, prior.current_revision)
        digest = _sha256_json({"key": key, "payload": dict(payload)})
        envelope = CommandEnvelope("attention.interval", INTERVAL_SCHEMA_REVISION, target, TransactionContext(self.actor, key, digest, expected_revision=prior.current_revision if prior else None, expected_version=version), dict(payload))
        self.store.mutate(envelope, event_type="attention.interval.changed", result_ref=ResourceRef(self.store.authority, INTERVAL_KIND, self.interval_ref.id, "rev-{}".format(version + 1)), effects={**payload, "version": version + 1}, stream="attention:" + self.interval_ref.id)
        identity = self.store.get_identity(self.interval_ref)
        if identity is None:
            raise RecoveryError("interval state did not persist")
        return self._from_identity(identity)

    def start(self, *, anchor: Optional[datetime] = None, request_key: str = "attention.interval.start") -> IntervalState:
        prior = self.state()
        if prior is not None:
            return prior
        initial = anchor or self.clock()
        return self._write(None, self._payload(_iso(initial), 0, None), request_key)

    def poll(self, *, now: Optional[datetime] = None) -> IntervalDecision:
        state = self.state() or self.start()
        current = now or self.clock()
        elapsed = (current.astimezone(timezone.utc) - _parse_iso(state.anchor)).total_seconds()
        slot = int(elapsed // self.interval_seconds)
        if slot <= state.last_slot:
            return IntervalDecision(False, state.in_flight, 0, state.in_flight is not None, state)
        if state.in_flight is not None:
            return IntervalDecision(True, state.in_flight, max(0, slot - state.last_slot - 1), True, state)
        request_id = hashlib.sha256((self.interval_ref.to_json() + ":" + str(slot)).encode("utf-8")).hexdigest()
        try:
            next_state = self._write(state, self._payload(state.anchor, slot, request_id), "attention.interval.request:{}".format(request_id))
        except VersionConflictError:
            current = self.state() or self.start()
            return IntervalDecision(current.in_flight is not None, current.in_flight, 0, current.in_flight is not None, current)
        return IntervalDecision(True, request_id, max(0, slot - state.last_slot - 1), False, next_state)

    def complete(self, request_id: str) -> IntervalState:
        if not isinstance(request_id, str) or not request_id.strip():
            raise RecoveryError("request_id is required")
        state = self.state() or self.start()
        if state.in_flight is None:
            return state
        if state.in_flight != request_id:
            # A late/duplicate host acknowledgement is a harmless hint.  It
            # must not clear or replace the request that is actually in flight.
            return state
        return self._write(state, self._payload(state.anchor, state.last_slot, None), "attention.interval.complete:{}".format(request_id))


__all__ = [
    "SNAPSHOT_FORMAT", "CURSOR_FORMAT", "RECOVERY_KIND", "INTERVAL_KIND",
    "RecoveryError", "SnapshotError", "SnapshotValidationError", "RestoreActivationError",
    "CursorError", "CursorMalformedError", "CursorScopeError", "CursorExpiredError",
    "StaleTokenError", "UnknownTokenError", "SnapshotManifest", "RestoreCandidate", "RestoreResult",
    "create_snapshot", "verify_restore_candidate", "restore_snapshot", "EventFilter", "EventPage", "EventCursorReader",
    "RecoveryToken", "EpochState", "SettlementRecord", "RecoveryManager", "IntervalState", "IntervalDecision", "IntervalController",
]
