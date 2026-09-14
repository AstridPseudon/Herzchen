"""The sole neutral FND-03 SQLite owner and common record writer."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple, Union

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    CommandReceipt,
    ContractError,
    DomainContribution,
    DomainRegistry,
    EventEnvelope,
    ReceiptStatus,
    ReplayConflictError,
    ResourceRef,
    canonical_json,
    canonical_request_digest,
    validate_expected_state,
    validate_replay,
)

from .schema import COMPOSITION, DDL, SCHEMA_FINGERPRINT, SCHEMA_REVISION


FND02_CONTRACT_REVISION = "fnd-02.v1.1"
FND02_CONTRACT_DIGEST = "28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264"


class StoreError(RuntimeError):
    """Base error for store admission, ownership, and transaction failures."""


class StoreAdmissionError(StoreError):
    """The database is not an admitted FND-03 composition."""


class StoreExistsError(StoreAdmissionError):
    """Create was requested for an already initialized database."""


class SchemaMismatchError(StoreAdmissionError):
    """Schema revision or fingerprint does not match the declared baseline."""


class CompositionMismatchError(StoreAdmissionError):
    """The database has missing or unknown user tables."""


class WriterBusyError(StoreError):
    """Another process or store instance owns the durable writer lock."""


class ClosedStoreError(StoreError):
    """An operation was attempted after close or failed admission."""


class TargetMismatchError(StoreError):
    """The requested target/reference is not the current stored identity."""


class VersionConflictError(StoreError):
    """The expected revision or version does not match current state."""


class DescriptorDigestMismatchError(StoreAdmissionError):
    """Persisted optional-domain descriptors do not match their digest."""


class DescriptorExpectationMismatchError(StoreAdmissionError):
    """Caller-supplied descriptor composition is not exactly admitted."""


class MutationAdmissionError(StoreError):
    """A command/resource/event combination has no admitted owner handler."""


DOMAIN_KIND = "domain"
DOMAIN_DESCRIPTOR_DIGEST_KEY = "domain_descriptor_digest"
EMPTY_DOMAIN_DESCRIPTOR_DIGEST = hashlib.sha256(b"[]").hexdigest()
_OWNER_CONSTRUCTION_TOKEN = object()
_HANDLER_CONSTRUCTION_TOKEN = object()


def _authority_root(value: str) -> str:
    """Return the stable authority namespace used by admission bindings."""
    return re.split(r"[.:-]", value, maxsplit=1)[0]


# These are the finite mutation ports owned by the neutral kernel itself.  An
# optional domain must instead declare its operation/event/resource surface in
# its persisted DomainContribution.  The operation manager intentionally
# accepts a caller's typed external operation name, but only for the kernel's
# ``operation`` identity and its two fixed lifecycle events.
_CORE_MUTATION_PORTS = (
    (None, ("operation",), ("operation.prepared",), None),
    ("operation.outcome", ("operation",), ("operation.outcome",), None),
    ("limit.create", ("limit",), ("limit.created",), "fnd-04.limit.v1"),
    ("limit.reserve", ("reservation",), ("reservation.held",), "fnd-04.limit.v1"),
    ("limit.uncertain", ("reservation",), ("reservation.uncertain",), "fnd-04.limit.v1"),
    ("limit.consumed", ("reservation",), ("reservation.consumed",), "fnd-04.limit.v1"),
    ("limit.released", ("reservation",), ("reservation.released",), "fnd-04.limit.v1"),
    ("recovery.state", ("runtime-epoch",), ("recovery.state.changed",), "fnd-05.recovery.v1"),
    ("recovery.retain_unknown", ("operation",), ("recovery.operation.unknown",), "fnd-05.recovery.v1"),
    ("attention.interval", ("attention-interval",), ("attention.interval.changed",), "fnd-05.interval.v1"),
)


@dataclass(frozen=True)
class IdentityRecord:
    """A neutral durable identity and its current mutable state."""

    ref: ResourceRef
    version: int
    payload: Mapping[str, Any]
    edit_token: Optional[str]
    created_at: str
    updated_at: str

    @property
    def revision(self) -> Optional[str]:
        return self.ref.revision


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    # Contract validation, including JSON safety, is intentionally performed
    # before a write transaction is admitted by the public methods.
    return canonical_json(value)


def _ref_key(ref: ResourceRef) -> str:
    return ref.to_json()


def _descriptor_digest(descriptors: Sequence[DomainContribution]) -> str:
    ordered = sorted(descriptors, key=lambda descriptor: descriptor.domain_id)
    return hashlib.sha256(canonical_json([descriptor.to_dict() for descriptor in ordered]).encode("utf-8")).hexdigest()


def _descriptor_expectation(
    expected_domains: Sequence[DomainContribution],
    expected_domain_digest: Optional[str] = None,
) -> Tuple[Tuple[DomainContribution, ...], str]:
    expected = tuple(expected_domains)
    if any(not isinstance(descriptor, DomainContribution) for descriptor in expected):
        raise DescriptorExpectationMismatchError("expected_domains must contain DomainContribution values")
    registry = DomainRegistry()
    for descriptor in expected:
        registry.register(descriptor)
    canonical = tuple(sorted(expected, key=lambda descriptor: descriptor.domain_id))
    if expected != canonical:
        raise DescriptorExpectationMismatchError("expected_domains must be in canonical domain-id order")
    computed_digest = _descriptor_digest(canonical)
    if expected_domain_digest is not None and expected_domain_digest != computed_digest:
        raise DescriptorExpectationMismatchError("expected_domain_digest does not match expected_domains")
    return canonical, computed_digest


def _ref_json(ref: Optional[ResourceRef]) -> Optional[str]:
    return None if ref is None else ref.to_json()


_NUMERIC_REVISION = re.compile(r"^rev-([0-9]+)$")


class Transaction:
    """A supplied common writer port with nested savepoint support."""

    def __init__(self, store: "Store") -> None:
        self.store = store
        self.connection = store._connection
        self._active = False
        self._savepoint_number = 0
        self._domain_working: Dict[str, DomainContribution] = {}
        self._domain_digest = store._domain_descriptor_digest

    def _require_active(self) -> None:
        self.store._require_open()
        if not self._active:
            raise StoreError("transaction is not active")

    def _begin(self) -> None:
        self.store._require_open()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise WriterBusyError("SQLite writer admission is busy") from exc
            raise
        self._active = True
        self._domain_working = dict(self.store._domain_descriptors)
        self._domain_digest = self.store._domain_descriptor_digest

    def _commit(self) -> None:
        self._require_active()
        try:
            self.connection.execute("COMMIT")
            self.store._domain_descriptors = dict(self._domain_working)
            self.store._domain_descriptor_digest = self._domain_digest
        finally:
            self._active = False

    def _rollback(self) -> None:
        if self._active:
            try:
                self.connection.execute("ROLLBACK")
            finally:
                self._active = False

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        self._require_active()
        return self.connection.execute(sql, parameters)

    def executemany(self, sql: str, parameters: Sequence[Sequence[Any]]) -> sqlite3.Cursor:
        self._require_active()
        return self.connection.executemany(sql, parameters)

    @contextmanager
    def savepoint(self) -> Iterator["Transaction"]:
        self._require_active()
        self._savepoint_number += 1
        name = "fnd_sp_{}".format(self._savepoint_number)
        domain_snapshot = dict(self._domain_working)
        digest_snapshot = self._domain_digest
        self.connection.execute("SAVEPOINT " + name)
        try:
            yield self
        except BaseException:
            self.connection.execute("ROLLBACK TO SAVEPOINT " + name)
            self.connection.execute("RELEASE SAVEPOINT " + name)
            self._domain_working = domain_snapshot
            self._domain_digest = digest_snapshot
            raise
        else:
            self.connection.execute("RELEASE SAVEPOINT " + name)


class Store:
    """The sealed owner capability for one admitted FND-03 writer.

    Host composition code acquires this capability only through ``create`` or
    ``open``.  It supplies the object to trusted domain handlers.  Ordinary
    consumers receive :meth:`consumer`, whose concrete type contains read
    operations and deliberately has no writable connection or mutation API.
    """

    def __init__(self, connection: sqlite3.Connection, lock_fd: Optional[int], path: str, authority: str, domain_descriptors: Optional[Mapping[str, DomainContribution]] = None, *, _owner_token: object = None) -> None:
        if _owner_token is not _OWNER_CONSTRUCTION_TOKEN:
            raise StoreAdmissionError("Store owner capabilities are acquired through Store.create or Store.open")
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._lock_fd = lock_fd
        self.path = path
        self.authority = authority
        self._closed = False
        # ``check_same_thread=False`` permits service/adapter contenders to
        # share this Store, but sqlite3 cursors still must not be used by
        # multiple threads at once.  Transaction admission and Store-owned
        # reads therefore use the same re-entrant boundary.
        self._transaction_lock = threading.RLock()
        self._local = threading.local()
        self._domain_descriptors: Dict[str, DomainContribution] = dict(domain_descriptors or {})
        self._domain_descriptor_digest = _descriptor_digest(self._domain_descriptors.values())
        self._issued_handlers: set[DomainHandler] = set()

    @classmethod
    def create(cls, path: Union[os.PathLike, str], *, authority: str = "neutral-store") -> "Store":
        path_text = os.fspath(path)
        lock_fd = cls._acquire_lock(path_text)
        connection: Optional[sqlite3.Connection] = None
        try:
            connection = cls._connect(path_text)
            if cls._user_tables(connection):
                raise StoreExistsError("database already contains a user composition")
            # executescript commits any already-open transaction before
            # running.  Start the transaction inside the script so DDL and
            # metadata below remain one admission unit.
            connection.executescript("BEGIN IMMEDIATE;\n" + DDL)
            metadata = {
                "schema_revision": SCHEMA_REVISION,
                "schema_fingerprint": SCHEMA_FINGERPRINT,
                "composition": canonical_json(COMPOSITION),
                "store_authority": authority,
                "fnd02_contract_revision": FND02_CONTRACT_REVISION,
                "fnd02_contract_digest": FND02_CONTRACT_DIGEST,
                DOMAIN_DESCRIPTOR_DIGEST_KEY: EMPTY_DOMAIN_DESCRIPTOR_DIGEST,
            }
            connection.executemany("INSERT INTO store_metadata(key, value) VALUES (?, ?)", metadata.items())
            connection.execute("COMMIT")
            return cls(connection, lock_fd, path_text, authority, {}, _owner_token=_OWNER_CONSTRUCTION_TOKEN)
        except BaseException:
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                connection.close()
            cls._release_lock(lock_fd)
            raise

    @classmethod
    def open(
        cls,
        path: Union[os.PathLike, str],
        *,
        authority: str = "neutral-store",
        expected_domains: Sequence[DomainContribution] = (),
        expected_domain_digest: Optional[str] = None,
    ) -> "Store":
        path_text = os.fspath(path)
        if path_text == ":memory:":
            raise StoreAdmissionError("ordinary open requires a durable database path")
        if not os.path.exists(path_text):
            raise StoreAdmissionError("database does not exist; use create for first admission")
        lock_fd = cls._acquire_lock(path_text)
        connection: Optional[sqlite3.Connection] = None
        try:
            connection = cls._connect(path_text)
            domains = cls._verify(connection, authority, expected_domains, expected_domain_digest)
            return cls(connection, lock_fd, path_text, authority, domains, _owner_token=_OWNER_CONSTRUCTION_TOKEN)
        except BaseException:
            if connection is not None:
                connection.close()
            cls._release_lock(lock_fd)
            raise

    @staticmethod
    def _connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, timeout=0.0, isolation_level=None, check_same_thread=False)
        connection.execute("PRAGMA foreign_keys = ON")
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        if enabled != 1:
            connection.close()
            raise StoreAdmissionError("SQLite foreign-key enforcement could not be enabled")
        return connection

    @staticmethod
    def _acquire_lock(path: str) -> Optional[int]:
        if path == ":memory:":
            return None
        lock_path = path + ".fnd-owner.lock"
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(lock_fd)
                raise WriterBusyError("another store owns the durable writer lock") from exc
            return lock_fd
        except FileNotFoundError as exc:
            raise StoreAdmissionError("database parent directory does not exist") from exc

    @staticmethod
    def _release_lock(lock_fd: Optional[int]) -> None:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    @staticmethod
    def _user_tables(connection: sqlite3.Connection) -> Tuple[str, ...]:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return tuple(row[0] for row in rows)

    @classmethod
    def _verify(
        cls,
        connection: sqlite3.Connection,
        authority: str,
        expected_domains: Sequence[DomainContribution] = (),
        expected_domain_digest: Optional[str] = None,
    ) -> Dict[str, DomainContribution]:
        actual = cls._user_tables(connection)
        expected = tuple(sorted(COMPOSITION))
        if actual != expected:
            raise CompositionMismatchError("declared tables do not exactly match FND-03 composition: {}".format(actual))
        rows = dict(connection.execute("SELECT key, value FROM store_metadata").fetchall())
        if rows.get("schema_revision") != SCHEMA_REVISION or rows.get("schema_fingerprint") != SCHEMA_FINGERPRINT:
            raise SchemaMismatchError("schema revision or fingerprint is not the admitted FND-03 baseline")
        if rows.get("composition") != canonical_json(COMPOSITION):
            raise CompositionMismatchError("stored composition declaration is not the FND-03 composition")
        if rows.get("store_authority") != authority:
            raise SchemaMismatchError("store authority does not match admission")
        if rows.get("fnd02_contract_revision") != FND02_CONTRACT_REVISION or rows.get("fnd02_contract_digest") != FND02_CONTRACT_DIGEST:
            raise SchemaMismatchError("accepted FND-02 contract baseline is not present")
        descriptors: Dict[str, DomainContribution] = {}
        descriptor_rows = connection.execute(
            "SELECT authority, kind, id, payload_json FROM identities WHERE kind = ? ORDER BY authority, id",
            (DOMAIN_KIND,),
        ).fetchall()
        registry = DomainRegistry()
        for descriptor_row in descriptor_rows:
            if descriptor_row[0] != authority:
                raise StoreAdmissionError("domain descriptor authority does not match store authority")
            try:
                descriptor = DomainContribution.from_dict(json.loads(descriptor_row[3]))
                if descriptor.domain_id != descriptor_row[2]:
                    raise ContractError("domain descriptor identity does not match its record id")
                registry.register(descriptor)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise StoreAdmissionError("stored domain descriptor is invalid") from exc
            descriptors[descriptor.domain_id] = descriptor
        expected_digest = _descriptor_digest(descriptors.values())
        if rows.get(DOMAIN_DESCRIPTOR_DIGEST_KEY) != expected_digest:
            raise DescriptorDigestMismatchError("stored domain descriptor set does not match metadata digest")
        expected, caller_digest = _descriptor_expectation(expected_domains, expected_domain_digest)
        persisted = tuple(descriptors[key] for key in sorted(descriptors))
        if persisted != expected or caller_digest != expected_digest:
            raise DescriptorExpectationMismatchError("caller descriptor composition does not match admitted store")
        return descriptors

    def _require_open(self) -> None:
        if self._closed:
            raise ClosedStoreError("store is closed")

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the raw connection held by this explicit owner capability."""
        self._require_open()
        return self._connection

    def consumer(self) -> "ConsumerStore":
        """Return the supported read-only surface for ordinary consumers."""
        self._require_open()
        return ConsumerStore(self)

    def foreign_keys_enabled(self) -> bool:
        with self._transaction_lock:
            self._require_open()
            return self._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        self._require_open()
        active = getattr(self._local, "transaction", None)
        if active is not None and active._active:
            # A nested transaction is a savepoint, so a caller may handle a
            # failed unit without losing the coherent outer transaction.
            with active.savepoint() as nested:
                yield nested
            return
        with self._transaction_lock:
            transaction = Transaction(self)
            transaction._begin()
            self._local.transaction = transaction
            try:
                yield transaction
            except BaseException:
                transaction._rollback()
                raise
            else:
                transaction._commit()
            finally:
                self._local.transaction = None

    def _transaction(self) -> Any:
        """Compatibility spelling for the supplied transaction port."""
        return self.transaction()

    def close(self) -> None:
        if self._closed:
            return
        active = getattr(self._local, "transaction", None)
        if active is not None and active._active:
            active._rollback()
        try:
            self._connection.close()
        finally:
            self._release_lock(self._lock_fd)
            self._lock_fd = None
            self._closed = True

    def __enter__(self) -> "Store":
        self._require_open()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def _active_or_transaction(self, transaction: Optional[Transaction]) -> Tuple[Transaction, bool]:
        self._require_open()
        if transaction is not None:
            if transaction.store is not self or not transaction._active:
                raise StoreError("supplied transaction is not active for this store")
            return transaction, False
        active = getattr(self._local, "transaction", None)
        if active is not None and active._active:
            return active, False
        return None, True  # type: ignore[return-value]

    def put_identity(
        self,
        ref: ResourceRef,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        version: int = 0,
        edit_token: Optional[str] = None,
        transaction: Optional[Transaction] = None,
    ) -> IdentityRecord:
        if not isinstance(ref, ResourceRef):
            raise TypeError("ref must be a ResourceRef")
        if ref.authority != self.authority:
            raise TargetMismatchError("identity authority does not belong to this store")
        if not isinstance(version, int) or version < 0:
            raise ValueError("version must be a non-negative integer")
        if not isinstance(payload or {}, Mapping):
            raise TypeError("payload must be a mapping")
        payload_json = _json(dict(payload or {}))
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._put_identity(owned, ref, payload_json, version, edit_token)
        return self._put_identity(tx, ref, payload_json, version, edit_token)

    def _put_identity(self, tx: Transaction, ref: ResourceRef, payload_json: str, version: int, edit_token: Optional[str]) -> IdentityRecord:
        now = _now()
        existing = tx.execute(
            "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
            (ref.authority, ref.kind, ref.id),
        ).fetchone()
        if existing is not None:
            current = self._identity_from_row(existing)
            if current.ref.revision != ref.revision or current.version != version or _json(current.payload) != payload_json:
                raise StoreError("identity already exists with a different state")
            return current
        tx.execute(
            "INSERT INTO identities(authority, kind, id, current_revision, version, edit_token, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ref.authority, ref.kind, ref.id, ref.revision, version, edit_token, payload_json, now, now),
        )
        return IdentityRecord(ref, version, json.loads(payload_json), edit_token, now, now)

    def _identity_from_row(self, row: sqlite3.Row) -> IdentityRecord:
        return IdentityRecord(
            ResourceRef(row["authority"], row["kind"], row["id"], row["current_revision"]),
            row["version"],
            json.loads(row["payload_json"]),
            row["edit_token"],
            row["created_at"],
            row["updated_at"],
        )

    def get_identity(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            return None if row is None else self._identity_from_row(row)

    def get_record(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self.get_identity(ref)

    def revise_identity(
        self,
        ref: ResourceRef,
        payload: Mapping[str, Any],
        *,
        revision: str,
        expected_revision: Optional[str],
        expected_version: int,
        expected_edit_token: Optional[str] = None,
        transaction: Optional[Transaction] = None,
    ) -> IdentityRecord:
        """CAS-revise one admitted identity through the common writer.

        ``ref`` must be the current reference, and ``expected_revision`` must
        repeat its pin (or both must be ``None`` for an unpinned identity).
        Numeric ``rev-N`` revisions advance exactly by one.  A legacy opaque
        current revision is accepted only for one bounded transition to
        ``rev-(expected_version + 1)``; subsequent revisions are numeric.
        The method emits no receipt or event and uses a caller transaction when
        supplied, so a parent operation can own the single logical boundary.
        """
        if not isinstance(ref, ResourceRef):
            raise TypeError("ref must be a ResourceRef")
        if ref.authority != self.authority:
            raise TargetMismatchError("identity authority does not belong to this store")
        if ref.revision != expected_revision:
            raise TargetMismatchError("expected_revision must match the supplied current reference")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        payload_json = _json(dict(payload))
        # ResourceRef performs the contract's revision validation.  Revisions
        # are required for a revision operation even though identity creation
        # permits an unpinned ref.
        if revision is None:
            raise ValueError("revision must be pinned for an identity revision")
        new_ref = ResourceRef(self.authority, ref.kind, ref.id, revision)
        if expected_edit_token is not None and (
            not isinstance(expected_edit_token, str) or not expected_edit_token
        ):
            raise ValueError("expected_edit_token must be a non-blank string when supplied")

        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._revise_identity(owned, ref, new_ref, payload_json, expected_revision, expected_version, expected_edit_token)
        return self._revise_identity(tx, ref, new_ref, payload_json, expected_revision, expected_version, expected_edit_token)

    def _revise_identity(
        self,
        tx: Transaction,
        ref: ResourceRef,
        new_ref: ResourceRef,
        payload_json: str,
        expected_revision: Optional[str],
        expected_version: int,
        expected_edit_token: Optional[str],
    ) -> IdentityRecord:
        with tx.savepoint():
            row = tx.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            if row is None:
                raise TargetMismatchError("identity does not exist")
            current = self._identity_from_row(row)
            if current.ref.revision != ref.revision or current.ref.revision != expected_revision:
                raise TargetMismatchError("supplied reference is not the current identity reference")
            if current.version != expected_version:
                raise VersionConflictError("expected version does not match current version")
            if expected_edit_token is not None and current.edit_token != expected_edit_token:
                raise VersionConflictError("expected edit token does not match")

            current_numeric = None if current.revision is None else _NUMERIC_REVISION.fullmatch(current.revision)
            if current_numeric is not None:
                expected_new_revision = "rev-{}".format(int(current_numeric.group(1)) + 1)
            else:
                expected_new_revision = "rev-{}".format(expected_version + 1)
            if new_ref.revision != expected_new_revision:
                raise VersionConflictError(
                    "revision must advance exactly to {}".format(expected_new_revision)
                )

            now = _now()
            where = (
                "WHERE authority = ? AND kind = ? AND id = ? "
                "AND (current_revision = ? OR (current_revision IS NULL AND ? IS NULL)) "
                "AND version = ?"
            )
            parameters = [
                new_ref.revision,
                expected_version + 1,
                payload_json,
                now,
                ref.authority,
                ref.kind,
                ref.id,
                expected_revision,
                expected_revision,
                expected_version,
            ]
            if expected_edit_token is not None:
                where += " AND edit_token = ?"
                parameters.append(expected_edit_token)
            updated = tx.execute(
                "UPDATE identities SET current_revision = ?, version = ?, payload_json = ?, updated_at = ? " + where,
                parameters,
            )
            if updated.rowcount != 1:
                raise StoreError("identity revision affected {} rows, expected exactly one".format(updated.rowcount))
            self.put_reference(new_ref, transaction=tx)
            revised = tx.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            if revised is None:
                raise StoreError("revised identity disappeared before readback")
            return self._identity_from_row(revised)

    @property
    def domain_descriptor_digest(self) -> str:
        self._require_open()
        return self._domain_descriptor_digest

    def registered_domains(self) -> Tuple[DomainContribution, ...]:
        """Return the admitted typed optional-domain descriptors in stable order."""
        self._require_open()
        return tuple(self._domain_descriptors[key] for key in sorted(self._domain_descriptors))

    def register_domain(
        self,
        contribution: DomainContribution,
        *,
        transaction: Optional[Transaction] = None,
    ) -> DomainContribution:
        """Register one typed descriptor using the common writer transaction."""
        if not isinstance(contribution, DomainContribution):
            raise TypeError("contribution must be a DomainContribution")
        tx, own = self._active_or_transaction(transaction)
        if own:
            # Serialize the read/preflight with transaction admission.  This
            # keeps the candidate from going stale if two callers register
            # different descriptors concurrently, while the digest work stays
            # outside BEGIN IMMEDIATE.
            with self._transaction_lock:
                candidate, candidate_digest = self._validated_domain_candidate(contribution, self._domain_descriptors)
                with self.transaction() as owned:
                    return self._register_domain(owned, contribution, candidate, candidate_digest)
        candidate, candidate_digest = self._validated_domain_candidate(contribution, tx._domain_working)
        return self._register_domain(tx, contribution, candidate, candidate_digest)

    def register_domain_handler(self, contributions: Sequence[DomainContribution]) -> "DomainHandler":
        """Atomically register exact descriptors and issue their sealed handler."""
        descriptors = tuple(contributions)
        if not descriptors or any(not isinstance(item, DomainContribution) for item in descriptors):
            raise TypeError("contributions must be a non-empty sequence of DomainContribution values")
        with self.transaction() as tx:
            for contribution in descriptors:
                self.register_domain(contribution, transaction=tx)
        return self.domain_handler(descriptors)

    def domain_handler(self, contributions: Sequence[DomainContribution]) -> "DomainHandler":
        """Issue a handler only for an exact, already-persisted descriptor set."""
        descriptors = tuple(contributions)
        if not descriptors or any(not isinstance(item, DomainContribution) for item in descriptors):
            raise TypeError("contributions must be a non-empty sequence of DomainContribution values")
        for contribution in descriptors:
            if self._domain_descriptors.get(contribution.domain_id) != contribution:
                raise MutationAdmissionError(
                    "handler descriptor is not the exact registered definition: {}".format(contribution.domain_id)
                )
        handler = DomainHandler(self, descriptors, _construction_token=_HANDLER_CONSTRUCTION_TOKEN)
        self._issued_handlers.add(handler)
        return handler

    def _validated_domain_candidate(
        self,
        contribution: DomainContribution,
        existing: Mapping[str, DomainContribution],
    ) -> Tuple[Dict[str, DomainContribution], str]:
        registry = DomainRegistry()
        for descriptor in existing.values():
            registry.register(descriptor)
        registry.register(contribution)
        candidate = dict(existing)
        candidate[contribution.domain_id] = contribution
        return candidate, _descriptor_digest(candidate.values())

    def _register_domain(
        self,
        tx: Transaction,
        contribution: DomainContribution,
        candidate: Mapping[str, DomainContribution],
        candidate_digest: str,
    ) -> DomainContribution:
        with tx.savepoint():
            ref = ResourceRef(self.authority, DOMAIN_KIND, contribution.domain_id, contribution.version)
            existing = tx.execute(
                "SELECT 1 FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (ref.authority, ref.kind, ref.id),
            ).fetchone()
            if existing is not None:
                raise ContractError("duplicate domain identity: {}".format(contribution.domain_id))
            now = _now()
            tx.execute(
                "INSERT INTO identities(authority, kind, id, current_revision, version, edit_token, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ref.authority, ref.kind, ref.id, ref.revision, 1, None, _json(contribution.to_dict()), now, now),
            )
            self._store_reference(tx, ref)
            tx.execute(
                "UPDATE store_metadata SET value = ? WHERE key = ?",
                (candidate_digest, DOMAIN_DESCRIPTOR_DIGEST_KEY),
            )
            tx._domain_working = candidate
            tx._domain_digest = candidate_digest
            return contribution

    def put_reference(self, ref: ResourceRef, *, transaction: Optional[Transaction] = None) -> ResourceRef:
        """Durably retain a validated reference to an admitted identity."""
        if not isinstance(ref, ResourceRef):
            raise TypeError("ref must be a ResourceRef")
        if ref.authority != self.authority:
            raise TargetMismatchError("reference authority does not belong to this store")
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                self._store_reference(owned, ref)
        else:
            self._store_reference(tx, ref)
        return ref

    def _store_reference(self, tx: Transaction, ref: ResourceRef) -> None:
        tx.execute(
            "INSERT OR IGNORE INTO record_references(reference_key, authority, kind, id, revision, reference_json) VALUES (?, ?, ?, ?, ?, ?)",
            (_ref_key(ref), ref.authority, ref.kind, ref.id, ref.revision, ref.to_json()),
        )

    def get_reference(self, ref: ResourceRef) -> Optional[ResourceRef]:
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT reference_json FROM record_references WHERE reference_key = ?", (_ref_key(ref),)
            ).fetchone()
            return None if row is None else ResourceRef.from_dict(json.loads(row[0]))

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        with self._transaction_lock:
            self._require_open()
            row = self._connection.execute(
                "SELECT * FROM command_receipts WHERE logical_request_key = ?", (logical_request_key,)
            ).fetchone()
            return None if row is None else self._receipt_from_row(row)

    def _receipt_from_row(self, row: sqlite3.Row) -> CommandReceipt:
        target = ResourceRef(row["target_authority"], row["target_kind"], row["target_id"], row["target_revision"])
        result = None if row["result_ref_json"] is None else ResourceRef.from_dict(json.loads(row["result_ref_json"]))
        return CommandReceipt(
            row["logical_request_key"], row["request_digest"], row["operation"], target,
            ReceiptStatus(row["status"]), row["transaction_id"], tuple(json.loads(row["event_ids_json"])),
            result, row["error_code"], bool(row["replayed"]), row["observed_revision"], row["unknown_reason"],
        )

    def _insert_receipt(self, tx: Transaction, receipt: CommandReceipt) -> None:
        target = receipt.target
        tx.execute(
            "INSERT INTO command_receipts(logical_request_key, request_digest, operation, target_authority, target_kind, target_id, target_revision, status, transaction_id, event_ids_json, result_ref_json, error_code, replayed, observed_revision, unknown_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt.logical_request_key, receipt.request_digest, receipt.operation,
                target.authority, target.kind, target.id, target.revision, receipt.status.value,
                receipt.transaction_id, _json(receipt.event_ids), _ref_json(receipt.result_ref),
                receipt.error_code, int(receipt.replayed), receipt.observed_revision, receipt.unknown_reason,
            ),
        )

    def _next_sequence(self, tx: Transaction, stream: str) -> int:
        row = tx.execute(
            "SELECT next_sequence FROM event_sequences WHERE store_authority = ? AND stream = ?",
            (self.authority, stream),
        ).fetchone()
        if row is None:
            tx.execute("INSERT INTO event_sequences(store_authority, stream, next_sequence) VALUES (?, ?, ?)", (self.authority, stream, 2))
            return 1
        sequence = row[0]
        tx.execute("UPDATE event_sequences SET next_sequence = ? WHERE store_authority = ? AND stream = ?", (sequence + 1, self.authority, stream))
        return sequence

    def mutate(
        self,
        envelope: CommandEnvelope,
        *,
        event_type: str,
        result_ref: Optional[ResourceRef] = None,
        before_refs: Sequence[ResourceRef] = (),
        after_refs: Sequence[ResourceRef] = (),
        effects: Optional[Mapping[str, Any]] = None,
        stream: Optional[str] = None,
        event_schema_revision: str = "fnd-03.event.v1",
        occurred_at: Optional[str] = None,
        no_op: bool = False,
        transaction: Optional[Transaction] = None,
        _handler: Optional["DomainHandler"] = None,
        _identity_payload: Optional[Mapping[str, Any]] = None,
    ) -> CommandReceipt:
        if not isinstance(envelope, CommandEnvelope):
            raise TypeError("envelope must be a CommandEnvelope")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-blank string")
        if not isinstance(effects or {}, Mapping):
            raise TypeError("effects must be a mapping")
        if _identity_payload is not None and not isinstance(_identity_payload, Mapping):
            raise TypeError("identity payload must be a mapping")
        request_digest = canonical_request_digest(
            logical_request_key=envelope.context.logical_request_key,
            operation=envelope.operation,
            schema_revision=envelope.schema_revision,
            target=envelope.target,
            actor=envelope.context.actor,
            payload=envelope.payload,
            context=envelope.context,
        )
        envelope = replace(
            envelope,
            context=replace(envelope.context, request_digest=request_digest),
        )
        # Validate all contract-shaped values before taking the writer path.
        effects_json = _json(dict(effects or {}))
        before_refs = tuple(before_refs)
        after_refs = tuple(after_refs)
        if any(not isinstance(ref, ResourceRef) for ref in before_refs + after_refs):
            raise TypeError("before_refs and after_refs must contain ResourceRef values")
        # Resolve the trusted owner before transaction admission.  A rejected
        # combination therefore cannot allocate an identity, sequence,
        # reference, event, or receipt.
        self._admit_mutation(envelope, event_type, _handler)
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._mutate(owned, envelope, event_type, result_ref, before_refs, after_refs, effects_json, stream, event_schema_revision, occurred_at, no_op, _identity_payload)
        return self._mutate(tx, envelope, event_type, result_ref, before_refs, after_refs, effects_json, stream, event_schema_revision, occurred_at, no_op, _identity_payload)

    @staticmethod
    def _actor_bound_to_owner(envelope: CommandEnvelope, owner: str, bindings: Iterable[str] = ()) -> bool:
        actor = envelope.context.actor
        exact_authorities = {
            binding.split(":", 1)[1]
            for binding in bindings
            if binding.startswith("actor-authority:")
        }
        exact_actors = {
            binding.split(":", 1)[1]
            for binding in bindings
            if binding.startswith("actor-id:")
        }
        if exact_authorities or exact_actors:
            # Explicit descriptor bindings are exact authority constraints,
            # not namespace/root hints.  When both forms are declared both
            # constraints apply; an actor id can never stand in for a
            # declared authority (or vice versa).
            return (
                (not exact_authorities or actor.authority in exact_authorities)
                and (not exact_actors or actor.actor in exact_actors)
            )
        owner_root = _authority_root(owner)
        return (
            actor.authority == owner
            or actor.actor == owner
            or _authority_root(actor.authority) == owner_root
            or _authority_root(actor.actor) == owner_root
        )

    def _admit_mutation(self, envelope: CommandEnvelope, event_type: str, handler: Optional["DomainHandler"] = None) -> str:
        """Resolve one command to its persisted domain owner or neutral port."""
        matches = []
        for descriptor in self._domain_descriptors.values():
            if envelope.operation not in descriptor.operation_types or event_type not in descriptor.event_types:
                continue
            resources = set(descriptor.resource_types)
            bindings = set(descriptor.composition_bindings)
            resource_allowed = envelope.target.kind in resources
            resource_allowed = resource_allowed or "mutation-resource:{}".format(envelope.target.kind) in bindings
            if "mutation-resource:registered:*" in bindings:
                resource_allowed = resource_allowed or any(
                    envelope.target.kind in candidate.resource_types
                    for candidate in self._domain_descriptors.values()
                )
            if not resource_allowed:
                continue
            if envelope.schema_revision != descriptor.schema_revision:
                continue
            declared_ports = {
                binding.split(":", 1)[1]
                for binding in bindings
                if binding.startswith("mutation-port:")
            }
            if declared_ports and "|".join((
                envelope.schema_revision,
                envelope.operation,
                envelope.target.kind,
                event_type,
            )) not in declared_ports:
                wildcard_resource_port = "|".join((
                    envelope.schema_revision,
                    envelope.operation,
                    "*",
                    event_type,
                ))
                if wildcard_resource_port not in declared_ports:
                    continue
            matches.append(descriptor)
        if len(matches) == 1:
            admitted = matches[0]
            if "handler-required" in admitted.composition_bindings:
                if (
                    handler is None
                    or handler not in self._issued_handlers
                    or handler._owner is not self
                    or admitted.domain_id not in handler.domain_ids
                ):
                    raise MutationAdmissionError(
                        "mutation requires the sealed handler for admitted owner {!r}".format(admitted.owner)
                    )
                return admitted.owner
            if not self._actor_bound_to_owner(envelope, admitted.owner, admitted.composition_bindings):
                raise MutationAdmissionError(
                    "authenticated actor {!r} is not bound to admitted owner {!r}".format(
                        envelope.context.actor.actor, admitted.owner
                    )
                )
            return admitted.owner
        if len(matches) > 1:
            raise MutationAdmissionError("mutation combination resolves to more than one domain owner")

        for operation, resources, events, schema in _CORE_MUTATION_PORTS:
            operation_allowed = envelope.operation == operation
            if operation is None:
                operation_allowed = envelope.target.kind == "operation" and envelope.operation != "operation.outcome"
            if operation_allowed and envelope.target.kind in resources and event_type in events and (schema is None or envelope.schema_revision == schema):
                return "fnd"
        raise MutationAdmissionError(
            "unregistered mutation combination: operation={!r}, resource={!r}, event={!r}, schema={!r}".format(
                envelope.operation, envelope.target.kind, event_type, envelope.schema_revision
            )
        )


    def _mutate(
        self, tx: Transaction, envelope: CommandEnvelope, event_type: str,
        result_ref: Optional[ResourceRef], before_refs: Tuple[ResourceRef, ...], after_refs: Tuple[ResourceRef, ...],
        effects_json: str, stream: Optional[str], event_schema_revision: str,
        occurred_at: Optional[str], no_op: bool, identity_payload: Optional[Mapping[str, Any]],
    ) -> CommandReceipt:
        with tx.savepoint():
            existing = tx.execute(
                "SELECT * FROM command_receipts WHERE logical_request_key = ?",
                (envelope.context.logical_request_key,),
            ).fetchone()
            if existing is not None:
                prior = self._receipt_from_row(existing)
                validate_replay(prior, envelope)
                return prior

            target = envelope.target
            if target.authority != self.authority:
                raise TargetMismatchError("command target authority does not belong to this store")
            row = tx.execute(
                "SELECT * FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (target.authority, target.kind, target.id),
            ).fetchone()
            if row is None:
                if envelope.context.expected_version not in (None, 0) or envelope.context.expected_revision is not None or target.revision is not None:
                    raise TargetMismatchError("target identity is not admitted")
                current_revision, current_version, current_token, current_payload = None, 0, None, {}
            else:
                current_revision, current_version, current_token, current_payload = row["current_revision"], row["version"], row["edit_token"], json.loads(row["payload_json"])
                if target.revision is not None and target.revision != current_revision:
                    raise TargetMismatchError("target reference revision does not match current identity")
            try:
                validate_expected_state(
                    envelope.context,
                    current_revision=current_revision,
                    current_version=current_version,
                    supplied_edit_token=current_token,
                )
            except ValueError as exc:
                raise VersionConflictError(str(exc)) from exc

            if no_op:
                receipt = CommandReceipt(
                    envelope.context.logical_request_key, envelope.context.request_digest,
                    envelope.operation, target, ReceiptStatus.NOOP,
                    observed_revision=current_revision,
                )
                if row is None:
                    self._put_identity(tx, target, _json({}), 0, None)
                self._store_reference(tx, target)
                self._insert_receipt(tx, receipt)
                return receipt

            next_version = current_version + 1
            persisted_payload = envelope.payload if identity_payload is None else identity_payload
            if result_ref is None:
                revision = "rev-{}".format(next_version)
                result_ref = ResourceRef(target.authority, target.kind, target.id, revision)
            if (result_ref.authority, result_ref.kind, result_ref.id) != (target.authority, target.kind, target.id) or result_ref.revision is None:
                raise TargetMismatchError("result reference must pin the exact target identity")
            if row is None:
                created_at = _now()
                tx.execute(
                    "INSERT INTO identities(authority, kind, id, current_revision, version, edit_token, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (target.authority, target.kind, target.id, result_ref.revision, next_version, None, _json(persisted_payload), created_at, created_at),
                )
            else:
                tx.execute(
                    "UPDATE identities SET current_revision = ?, version = ?, payload_json = ?, updated_at = ? WHERE authority = ? AND kind = ? AND id = ?",
                    (result_ref.revision, next_version, _json(persisted_payload), _now(), target.authority, target.kind, target.id),
                )

            stream_name = stream or "{}:{}".format(target.kind, target.id)
            sequence = self._next_sequence(tx, stream_name)
            transaction_id = secrets.token_hex(16)
            event_id = "event-{}".format(secrets.token_hex(16))
            before = before_refs or (() if current_revision is None else (ResourceRef(target.authority, target.kind, target.id, current_revision),))
            after = after_refs or (result_ref,)
            for ref in before + after:
                self._store_reference(tx, ref)
            recorded_at = _now()
            event = EventEnvelope(
                event_id, self.authority, stream_name, result_ref, event_schema_revision,
                event_type, sequence, envelope.context.actor, envelope.operation,
                envelope.context.correlation_id, envelope.context.causation_id,
                recorded_at, occurred_at, before, after, json.loads(effects_json),
            )
            tx.execute(
                "INSERT INTO events(event_id, store_authority, stream, subject_authority, subject_kind, subject_id, subject_revision, schema_revision, event_type, sequence, actor_authority, actor_id, credential_ref, correlation_id, causation_id, operation, recorded_at, occurred_at, before_refs_json, after_refs_json, effects_json, transaction_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id, event.store_authority, event.stream, result_ref.authority, result_ref.kind,
                    result_ref.id, result_ref.revision, event.schema_revision, event.event_type, event.sequence,
                    event.actor.authority, event.actor.actor, event.actor.credential_ref, event.correlation_id,
                    event.causation_id, event.operation, event.recorded_at, event.occurred_at,
                    _json([ref.to_dict() for ref in event.before_refs]), _json([ref.to_dict() for ref in event.after_refs]),
                    _json(event.effects), transaction_id,
                ),
            )
            receipt = CommandReceipt(
                envelope.context.logical_request_key, envelope.context.request_digest,
                envelope.operation, target, ReceiptStatus.COMMITTED, transaction_id,
                (event.event_id,), result_ref, observed_revision=result_ref.revision,
            )
            self._store_reference(tx, target)
            self._insert_receipt(tx, receipt)
            return receipt

    def append_event(
        self,
        event: EventEnvelope,
        *,
        transaction_id: Optional[str] = None,
        transaction: Optional[Transaction] = None,
    ) -> EventEnvelope:
        """Append one already-formed event, idempotently by event identity."""
        if not isinstance(event, EventEnvelope):
            raise TypeError("event must be an EventEnvelope")
        if event.store_authority != self.authority:
            raise TargetMismatchError("event authority does not belong to this store")
        tx, own = self._active_or_transaction(transaction)
        if own:
            with self.transaction() as owned:
                return self._append_event(owned, event, transaction_id)
        return self._append_event(tx, event, transaction_id)

    def _append_event(self, tx: Transaction, event: EventEnvelope, transaction_id: Optional[str]) -> EventEnvelope:
        with tx.savepoint():
            existing = tx.execute("SELECT * FROM events WHERE event_id = ?", (event.event_id,)).fetchone()
            if existing is not None:
                prior = self._event_from_row(existing)
                if prior != event:
                    raise StoreError("event identity was reused with different content")
                return prior
            identity = tx.execute(
                "SELECT 1 FROM identities WHERE authority = ? AND kind = ? AND id = ?",
                (event.subject.authority, event.subject.kind, event.subject.id),
            ).fetchone()
            if identity is None:
                raise TargetMismatchError("event subject identity is not admitted")
            expected = tx.execute(
                "SELECT next_sequence FROM event_sequences WHERE store_authority = ? AND stream = ?",
                (self.authority, event.stream),
            ).fetchone()
            if expected is not None and event.sequence != expected[0]:
                raise StoreError("event sequence is not the next durable sequence")
            if expected is None and event.sequence != 1:
                raise StoreError("first event sequence must be one")
            for ref in event.before_refs + event.after_refs:
                self._store_reference(tx, ref)
            if expected is None:
                tx.execute("INSERT INTO event_sequences(store_authority, stream, next_sequence) VALUES (?, ?, ?)", (self.authority, event.stream, 2))
            else:
                tx.execute("UPDATE event_sequences SET next_sequence = ? WHERE store_authority = ? AND stream = ?", (event.sequence + 1, self.authority, event.stream))
            tx.execute(
                "INSERT INTO events(event_id, store_authority, stream, subject_authority, subject_kind, subject_id, subject_revision, schema_revision, event_type, sequence, actor_authority, actor_id, credential_ref, correlation_id, causation_id, operation, recorded_at, occurred_at, before_refs_json, after_refs_json, effects_json, transaction_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id, event.store_authority, event.stream, event.subject.authority, event.subject.kind,
                    event.subject.id, event.subject.revision, event.schema_revision, event.event_type, event.sequence,
                    event.actor.authority, event.actor.actor, event.actor.credential_ref, event.correlation_id,
                    event.causation_id, event.operation, event.recorded_at, event.occurred_at,
                    _json([ref.to_dict() for ref in event.before_refs]), _json([ref.to_dict() for ref in event.after_refs]),
                    _json(event.effects), transaction_id or "external-" + event.event_id,
                ),
            )
            return event

    def list_events(self, *, stream: Optional[str] = None) -> Tuple[EventEnvelope, ...]:
        with self._transaction_lock:
            self._require_open()
            if stream is None:
                rows = self._connection.execute("SELECT * FROM events ORDER BY store_authority, stream, sequence").fetchall()
            else:
                rows = self._connection.execute("SELECT * FROM events WHERE store_authority = ? AND stream = ? ORDER BY sequence", (self.authority, stream)).fetchall()
            return tuple(self._event_from_row(row) for row in rows)

    def _event_from_row(self, row: sqlite3.Row) -> EventEnvelope:
        subject = ResourceRef(row["subject_authority"], row["subject_kind"], row["subject_id"], row["subject_revision"])
        actor = AuthenticatedActor(row["actor_authority"], row["actor_id"], row["credential_ref"])
        return EventEnvelope(
            row["event_id"], row["store_authority"], row["stream"], subject, row["schema_revision"], row["event_type"], row["sequence"], actor,
            row["operation"], row["correlation_id"], row["causation_id"], row["recorded_at"], row["occurred_at"],
            tuple(ResourceRef.from_dict(ref) for ref in json.loads(row["before_refs_json"])),
            tuple(ResourceRef.from_dict(ref) for ref in json.loads(row["after_refs_json"])), json.loads(row["effects_json"]),
        )


class DomainHandler:
    """Sealed trusted-domain writer; the command actor remains provenance."""

    __slots__ = ("_owner", "_descriptors")

    def __init__(self, owner: Store, descriptors: Sequence[DomainContribution], *, _construction_token: object = None) -> None:
        if _construction_token is not _HANDLER_CONSTRUCTION_TOKEN or not isinstance(owner, Store):
            raise StoreAdmissionError("domain handlers are issued only by an admitted Store")
        self._owner = owner
        self._descriptors = tuple(descriptors)

    @property
    def authority(self) -> str:
        return self._owner.authority

    @property
    def domain_ids(self) -> Tuple[str, ...]:
        return tuple(item.domain_id for item in self._descriptors)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._owner.connection

    def transaction(self) -> Any:
        return self._owner.transaction()

    def mutate(self, envelope: CommandEnvelope, *, identity_payload: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> CommandReceipt:
        return self._owner.mutate(envelope, _handler=self, _identity_payload=identity_payload, **kwargs)

    def get_identity(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self._owner.get_identity(ref)

    def get_record(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self._owner.get_record(ref)

    def get_reference(self, ref: ResourceRef) -> Optional[ResourceRef]:
        return self._owner.get_reference(ref)

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        return self._owner.get_receipt(logical_request_key)

    def registered_domains(self) -> Tuple[DomainContribution, ...]:
        return self._owner.registered_domains()

    def list_events(self, *, stream: Optional[str] = None) -> Tuple[EventEnvelope, ...]:
        return self._owner.list_events(stream=stream)

    def put_identity(self, *args: Any, **kwargs: Any) -> IdentityRecord:
        return self._owner.put_identity(*args, **kwargs)

    def revise_identity(self, *args: Any, **kwargs: Any) -> IdentityRecord:
        return self._owner.revise_identity(*args, **kwargs)

    def put_reference(self, *args: Any, **kwargs: Any) -> ResourceRef:
        return self._owner.put_reference(*args, **kwargs)

    def consumer(self) -> "ConsumerStore":
        return self._owner.consumer()


class ConsumerStore:
    """Concrete read-only Store view safe to give to an ordinary consumer.

    The wrapper intentionally does not proxy unknown attributes.  In
    particular it has no ``connection``, ``transaction``, ``put_identity``,
    ``revise_identity``, ``append_event``, ``mutate``, or domain-registration
    surface.
    """

    __slots__ = ("__owner",)

    def __init__(self, owner: Store) -> None:
        if not isinstance(owner, Store):
            raise TypeError("ConsumerStore requires the sealed Store owner capability")
        self.__owner = owner

    @property
    def authority(self) -> str:
        return self.__owner.authority

    @property
    def domain_descriptor_digest(self) -> str:
        return self.__owner.domain_descriptor_digest

    def foreign_keys_enabled(self) -> bool:
        return self.__owner.foreign_keys_enabled()

    def get_identity(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self.__owner.get_identity(ref)

    def get_record(self, ref: ResourceRef) -> Optional[IdentityRecord]:
        return self.__owner.get_record(ref)

    def registered_domains(self) -> Tuple[DomainContribution, ...]:
        return self.__owner.registered_domains()

    def get_reference(self, ref: ResourceRef) -> Optional[ResourceRef]:
        return self.__owner.get_reference(ref)

    def get_receipt(self, logical_request_key: str) -> Optional[CommandReceipt]:
        return self.__owner.get_receipt(logical_request_key)

    def list_events(self, *, stream: Optional[str] = None) -> Tuple[EventEnvelope, ...]:
        return self.__owner.list_events(stream=stream)

    def snapshot_counts(self) -> Mapping[str, int]:
        """Return fresh durable counts without exposing a SQL execution port."""
        owner = self.__owner
        with owner._transaction_lock:
            owner._require_open()
            tables = ("identities", "record_references", "events", "command_receipts", "event_sequences")
            return {
                table: int(owner._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
                for table in tables
            }


SQLiteStore = Store
RealmStore = Store


__all__ = [
    "Store", "SQLiteStore", "RealmStore", "ConsumerStore", "DomainHandler", "Transaction", "IdentityRecord",
    "StoreError", "StoreAdmissionError", "StoreExistsError", "SchemaMismatchError",
    "CompositionMismatchError", "WriterBusyError", "ClosedStoreError",
    "TargetMismatchError", "VersionConflictError", "DescriptorDigestMismatchError",
    "DescriptorExpectationMismatchError", "MutationAdmissionError",
    "FND02_CONTRACT_REVISION", "FND02_CONTRACT_DIGEST", "DOMAIN_KIND",
    "DOMAIN_DESCRIPTOR_DIGEST_KEY", "EMPTY_DOMAIN_DESCRIPTOR_DIGEST",
]
