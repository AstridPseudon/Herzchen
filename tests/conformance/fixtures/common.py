"""Shared fixture primitives; intentionally independent of Herzchen/Otto."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Iterator


FIXTURE_SCHEMA = "int-02-fixture/v1"
HARNESS_MARKER = {
    "evidence_scope": "harness_input",
    "product_state": False,
    "installed_product_proof": False,
    "live_control_target": False,
}


def stable_digest(value: Any) -> str:
    """Return a repeatable digest for a JSON-compatible fixture value."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def envelope(kind: str, payload: Any, fixture_id: str) -> dict[str, Any]:
    return {
        "fixture_schema": FIXTURE_SCHEMA,
        "fixture_id": fixture_id,
        "fixture_kind": kind,
        "harness": dict(HARNESS_MARKER),
        "payload": payload,
    }


class HarnessWorkspace:
    """A temporary workspace for fixture filesystem tests."""

    def __init__(self, prefix: str = "int02-") -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix=prefix)
        self.root = Path(self._temporary.name)

    def __enter__(self) -> "HarnessWorkspace":
        return self

    def __exit__(self, *_: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        self._temporary.cleanup()

    def path(self, *parts: str) -> Path:
        target = self.root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_json(self, relative: str, value: Any) -> Path:
        target = self.path(relative)
        target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return target

    def read_json(self, relative: str) -> Any:
        return json.loads(self.path(relative).read_text())

    def files(self) -> Iterator[Path]:
        yield from sorted(path for path in self.root.rglob("*") if path.is_file())
