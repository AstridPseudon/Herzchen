"""The closed, neutral FND-03 SQLite composition.

This module contains declarations only.  Admission compares the complete
composition and fingerprint before an existing database is opened for use;
there is deliberately no migration or repair path here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Tuple


SCHEMA_REVISION = "fnd-03.v1"

# This is the only table composition an FND-03 store may contain.  Product
# domains persist their own records elsewhere and use the transaction port.
COMPOSITION: Tuple[str, ...] = (
    "store_metadata",
    "identities",
    "record_references",
    "event_sequences",
    "command_receipts",
    "events",
)

DDL = """
CREATE TABLE store_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE identities (
    authority TEXT NOT NULL,
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    current_revision TEXT,
    version INTEGER NOT NULL CHECK (version >= 0),
    edit_token TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (authority, kind, id)
);

CREATE TABLE record_references (
    reference_key TEXT PRIMARY KEY NOT NULL,
    authority TEXT NOT NULL,
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    revision TEXT,
    reference_json TEXT NOT NULL,
    FOREIGN KEY (authority, kind, id)
        REFERENCES identities (authority, kind, id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE event_sequences (
    store_authority TEXT NOT NULL,
    stream TEXT NOT NULL,
    next_sequence INTEGER NOT NULL CHECK (next_sequence >= 1),
    PRIMARY KEY (store_authority, stream)
);

CREATE TABLE command_receipts (
    logical_request_key TEXT PRIMARY KEY NOT NULL,
    request_digest TEXT NOT NULL,
    operation TEXT NOT NULL,
    target_authority TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_revision TEXT,
    status TEXT NOT NULL,
    transaction_id TEXT,
    event_ids_json TEXT NOT NULL,
    result_ref_json TEXT,
    error_code TEXT,
    replayed INTEGER NOT NULL CHECK (replayed IN (0, 1)),
    observed_revision TEXT,
    unknown_reason TEXT,
    FOREIGN KEY (target_authority, target_kind, target_id)
        REFERENCES identities (authority, kind, id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE events (
    event_id TEXT PRIMARY KEY NOT NULL,
    store_authority TEXT NOT NULL,
    stream TEXT NOT NULL,
    subject_authority TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    subject_revision TEXT,
    schema_revision TEXT NOT NULL,
    event_type TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    actor_authority TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    operation TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    occurred_at TEXT,
    before_refs_json TEXT NOT NULL,
    after_refs_json TEXT NOT NULL,
    effects_json TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    UNIQUE (store_authority, stream, sequence),
    FOREIGN KEY (subject_authority, subject_kind, subject_id)
        REFERENCES identities (authority, kind, id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
"""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


SCHEMA_FINGERPRINT = hashlib.sha256(
    _canonical(
        {
            "revision": SCHEMA_REVISION,
            "composition": COMPOSITION,
            "ddl": DDL,
        }
    ).encode("utf-8")
).hexdigest()


__all__ = ["COMPOSITION", "DDL", "SCHEMA_FINGERPRINT", "SCHEMA_REVISION"]
