#!/usr/bin/env python3
"""Strict C33 acceptance check for an independent inventory, matrix, and result.

The independent inventory is authoritative for the candidate descriptor set;
the matrix and result must match it exactly.  Its size is deliberately read
from the artifacts rather than encoded here, so a changed inventory cannot
pass by accident.  This check is evidence-only: it does not run the product
or convert the harness pass count into acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> tuple[Any, list[str]]:
    duplicate_keys: list[str] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                duplicate_keys.append(key)
            value[key] = item
        return value

    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=pairs), duplicate_keys


def _fail(messages: list[str]) -> int:
    for message in messages:
        print(f"FAIL: {message}", file=sys.stderr)
    return 1


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True, help="independent candidate persisted-descriptor export")
    parser.add_argument("--matrix", type=Path, default=here / "c33-persisted-port-matrix-20260914.json")
    parser.add_argument("--result", type=Path, default=here / "c33-persisted-port-result-20260914.json")
    args = parser.parse_args()

    errors: list[str] = []
    try:
        inventory, inventory_duplicates = _load_json(args.inventory)
        matrix, matrix_duplicates = _load_json(args.matrix)
        result, result_duplicates = _load_json(args.result)
    except (OSError, json.JSONDecodeError) as exc:
        return _fail([f"cannot load evidence: {exc}"])

    if inventory_duplicates:
        errors.append(f"inventory contains duplicate JSON keys: {sorted(set(inventory_duplicates))}")
    if matrix_duplicates:
        errors.append(f"matrix contains duplicate JSON keys: {sorted(set(matrix_duplicates))}")
    if result_duplicates:
        errors.append(f"result contains duplicate JSON keys: {sorted(set(result_duplicates))}")
    if not isinstance(inventory, dict) or not isinstance(matrix, dict) or not isinstance(result, dict):
        return _fail(errors + ["inventory, matrix, and result must be JSON objects"])

    exported = inventory.get("descriptors")
    if not isinstance(exported, list) or not all(isinstance(item, str) for item in exported):
        errors.append("inventory.descriptors is not a list of strings")
        exported = []
    exported_digest = hashlib.sha256(
        json.dumps(exported, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    if inventory.get("descriptor_count") != len(exported):
        errors.append("inventory descriptor_count does not equal descriptor export length")
    if inventory.get("catalog_digest") != exported_digest:
        errors.append("inventory catalog_digest does not match its descriptor export")
    candidate = inventory.get("candidate")
    if not isinstance(candidate, dict):
        errors.append("inventory.candidate source/wheel/catalog pin is missing")
        candidate = {}
    for field in ("source_commit", "source_tree", "wheel_sha256", "catalog_digest"):
        if not isinstance(candidate.get(field), str) or not candidate[field]:
            errors.append(f"inventory candidate pin missing {field}")

    matrix_rows = matrix.get("rows")
    rows = result.get("rows")
    if not isinstance(matrix_rows, list):
        errors.append("matrix.rows is not a list")
        matrix_rows = []
    if not isinstance(rows, dict):
        errors.append("result.rows is not an object")
        rows = {}

    declared_count = matrix.get("row_count")
    if declared_count != len(matrix_rows):
        errors.append(f"matrix row_count={declared_count!r} does not equal matrix length={len(matrix_rows)}")

    admitted: list[str] = []
    for index, entry in enumerate(matrix_rows):
        if not isinstance(entry, dict):
            errors.append(f"matrix inventory entry {index} is not an object")
            continue
        key = entry.get("matrix_key")
        if not isinstance(key, str) or not key.startswith("mutation-port:"):
            errors.append(f"matrix inventory entry {index} has no valid mutation-port matrix_key")
            continue
        admitted.append(key)

    duplicate_admitted = sorted({key for key in admitted if admitted.count(key) > 1})
    if duplicate_admitted:
        errors.append(f"duplicate admitted descriptors: {duplicate_admitted}")

    admitted_set = set(admitted)
    exported_set = set(exported)
    duplicate_exported = sorted({key for key in exported if exported.count(key) > 1})
    if duplicate_exported:
        errors.append(f"duplicate independent inventory descriptors: {duplicate_exported}")
    if exported_set != admitted_set:
        errors.append(
            "independent inventory and matrix differ: "
            f"inventory_only={sorted(exported_set - admitted_set)}, "
            f"matrix_only={sorted(admitted_set - exported_set)}"
        )
    source = result.get("source")
    wheel = result.get("wheel")
    if not isinstance(source, dict) or not isinstance(wheel, dict):
        errors.append("result source/wheel pin is missing")
    else:
        for field in ("commit", "tree"):
            if source.get(field) != candidate.get("source_" + field):
                errors.append(f"result source {field} does not match independent inventory pin")
        if wheel.get("sha256") != candidate.get("wheel_sha256"):
            errors.append("result wheel sha256 does not match independent inventory pin")
    if candidate.get("catalog_digest") != exported_digest:
        errors.append("candidate catalog_digest does not match independent descriptor export")
    result_set = set(rows)
    missing = sorted(admitted_set - result_set)
    extra = sorted(result_set - admitted_set)
    if missing:
        errors.append(f"missing result rows for admitted descriptors: {missing}")
    if extra:
        errors.append(f"result contains rows outside the admitted inventory: {extra}")

    required_sections = ("before", "action", "replay", "reject", "reopen")
    for key in sorted(admitted_set & result_set):
        row = rows[key]
        if not isinstance(row, dict):
            errors.append(f"result row {key} is not an object")
            continue
        if row.get("status") != "passed":
            errors.append(f"admitted row {key} status is {row.get('status')!r}, expected 'passed'")
        absent = [section for section in required_sections if section not in row]
        if absent:
            errors.append(f"admitted row {key} lacks evidence sections: {absent}")

    # Every admitted row must prove a real changed-request rejection. A
    # no-delta result from a valid exact replay is not a rejection and must
    # never be relabeled as one by the harness.
    for key in sorted(admitted_set & result_set):
        row = rows[key]
        rejection = row.get("reject") if isinstance(row, dict) else None
        if not isinstance(rejection, dict):
            errors.append(f"admitted row {key} lacks reject evidence")
            continue
        error = rejection.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("type"), str):
            errors.append(f"admitted row {key} lacks a typed changed-request rejection")
        elif error.get("type") == "RejectedWithoutException":
            errors.append(f"admitted row {key} uses synthetic RejectedWithoutException; changed request was not rejected")
        if rejection.get("counts_unchanged") is not True or rejection.get("events_unchanged") is not True:
            errors.append(f"admitted row {key} changed-request rejection did not prove zero durable/event delta")

    if errors:
        return _fail(errors)

    print(f"C33 strict acceptance: {len(admitted)} admitted descriptors, all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
