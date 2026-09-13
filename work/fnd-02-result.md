# FND-02 worker result — common contracts and ownership map

Status: complete worker handoff; neutral contract baseline only.

## Contract identity

- Contract revision: `fnd-02.v1.1`
- Deterministic contract/schema digest: `28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264`
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

## Bounded correction

The PKG consumer acknowledgment identified that `DomainRegistry.register` checked
duplicate domain, operation, and namespace identities but omitted resource,
document, and event identities. Revision `fnd-02.v1.1` adds deterministic
collision rejection for all three omitted identity groups and adds one focused
negative test for each. B01–B12 and the neutral host receipt scope are
unchanged. PKG must still keep pack resources resource-only and must not add a
second registry or pack-owned DDL; live OTT receipt qualification remains a
downstream adapter condition.

## Verification evidence

Runtime: Python `3.9.6` on macOS arm64 host.

Commands and results:

```text
PYTHONPATH=src python3 -B -m unittest discover -s tests/contracts -p 'test_*.py' -v
exit 0; Ran 24 tests; OK

python3 -B - <<'PY'
import json
from pathlib import Path
paths = sorted(Path('contracts').rglob('*.json'))
for path in paths:
    json.loads(path.read_text())
print(f'JSON_PARSE_FILES={len(paths)}')
PY
JSON_PARSE_FILES=12; exit 0

PYTHONPATH=src python3 -B - <<'PY'
import hashlib
import herzchen.contracts as c
assert c.CONTRACT_REVISION == 'fnd-02.v1.1'
assert c.CONTRACT_DIGEST == hashlib.sha256(c.canonical_json(c.SCHEMA_DEFINITIONS).encode()).hexdigest()
assert len(c.CONTRACT_DIGEST) == 64
assert {'ResourceRef','DomainRegistry','CommandEnvelope','EventEnvelope','HostPort'} <= set(c.__all__)
print('IMPORT_EXPORT_DIGEST=OK')
print('REVISION=' + c.CONTRACT_REVISION)
print('DIGEST=' + c.CONTRACT_DIGEST)
PY
IMPORT_EXPORT_DIGEST=OK
REVISION=fnd-02.v1.1
DIGEST=28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264
exit 0

if rg -n '(^|[[:space:]])(import|from) (otto|astrid|runtime_protocol)|otto\.|astrid\.|runtime_protocol\.' src/herzchen/contracts; then exit 1; else echo none; fi
FORBIDDEN_IMPORTS: none; exit 0

git diff --check
DIFF_CHECK=0; exit 0
```

The unittest suite includes the small subprocess import check and JSON fixture load/round-trip/digest check. No pytest dependency was required or installed.

Known bounded gaps: FND-03 still owns the SQLite one-writer/store implementation; EDT/OTT/AST adapters and installed-origin/live-use proof remain later work; the optional host fixture reports unsupported operations but does not launch a process. The PKG duplicate-identity condition is now satisfied by this candidate but still requires downstream consumer integration; no INT-02 or installed-product claim is made.

## Commit/tree

- Correction commit/tree: recorded after the bounded correction is committed.
