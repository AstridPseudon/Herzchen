# FND-02 worker result — common contracts and ownership map

Status: complete worker handoff; neutral contract baseline only.

## Contract identity

- Contract revision: `fnd-02.v1`
- Deterministic contract/schema digest: `fd7c2f416ff0fcaeffe9e66b0913258cc9db3b7bc792ad6e57d1fe456267d269`
- Source manifest: `.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`
- Source manifest SHA-256: `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`

## Worker receipt

- Requested route: `normal`
- Requested model/reasoning: `gpt-5.6-luna` / `high`
- Worker session receipt: the local CLI did not expose a machine-readable model/session receipt to this checkout; no alternate model or route was selected.
- Upstream posture: no Astrid, Runtime, Otto, extraction-map, or control-ledger file was modified; no upstream push was made.

## Owned result

- `src/herzchen/contracts/` — stdlib/dataclasses/typing neutral records and public exports.
- `contracts/ownership.json` — one accountable owner, writer, consumer example and negative case for each boundary; includes `fnd`, `dat`, `edt`, `pkg`, `wrk`, `ott`, `ast`, `runtime`, and `int`.
- `contracts/boundary-decisions.json` — compact source-backed B01–B12 ratification.
- `contracts/shared-ports/` — neutral JSON fixtures for refs, command/receipt, event/cursor, authoring, domain, candidate/decision, attention/readiness, optional host, invocation, and collision/path negatives.
- `tests/contracts/` — focused round-trip, collision, rejection, cursor, authoring, candidate/decision, host, fixture, digest, and import-boundary tests.
- `pyproject.toml` — dependency-free package setup.

The neutral kernel has no inward optional-domain imports or foreign keys. Runtime remains Astrid's current writer until G-OTTO and the later AST transfer/qualification. This worker does not claim installed product origin, INT-02 validation, or a live Astrid/Runtime journey.

## Verification evidence

Runtime: Python `3.9.6` on macOS arm64 host.

Commands and results:

```text
PYTHONPATH=src python3 -m py_compile src/herzchen/contracts/model.py
exit 0

PYTHONPATH=src python3 -m unittest discover -s tests/contracts -p 'test_*.py' -v
exit 0; Ran 23 tests; OK
```

The unittest suite includes the small subprocess import check and JSON fixture load/round-trip/digest check. No pytest dependency was required or installed.

Known bounded gaps: FND-03 still owns the SQLite one-writer/store implementation; EDT/OTT/AST adapters and installed-origin/live-use proof remain later work; the optional host fixture reports unsupported operations but does not launch a process.

## Commit/tree

- Implementation commit: `d00d579a7077326956df207d4cc8a2becacc5f1d`
- Implementation tree: `cbcb7888c1b66ef4be38961d73698be8f15cafb0`
- This handoff report is a follow-up metadata commit on the same `fnd-02-worker` branch; the implementation commit above is the coherent contract result to consume.
