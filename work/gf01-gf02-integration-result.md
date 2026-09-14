# GF01/GF02 integration correction result

Status: bounded GF01 follow-up candidate evidence. The original G-FOUNDATION
verdict remains **REWORK**. This result does not issue gate acceptance,
consumer cutover, Runtime/Astrid production-origin, G-OTTO, or product claims.

## Custody and integration lineage

- GF01 checkpoint: commit `c9a797882ee128dfd6aabf63df0610251db9db0c`, tree `db71b18fdb5fddaf6a88938b251b745db399b18e`.
- Accepted disjoint GF02 source: commit `3950476ede81d03bc746d656634b9df7cd31fc4d`, tree `c7df42bfe23827f954afc9cb67c21633638cb079`, parent `046b9acfdc9ba541faff65ff3713961890684303`.
- Manager-integrated cherry-pick baseline: commit `f7712bd8a52df29619c582fbdc67deb7927f9738`, tree `33182f521d274b5720704086d7bac51d557fd66e`, parent exactly the GF01 checkpoint. The history and clean preflight confirm a conflict-free integration of the accepted GF02 change; this worker does not reattribute it as a new GF02 implementation.
- Integrated GF02 result and handoff are unchanged: `work/gf02-correction-result.md` SHA-256 `debe4a2d1575156652b15c9ac83b1f8c2ab7c2b602366dc06b7b30b346f70ce8`; `work/gf02-correction-handoff.md` SHA-256 `fcd946a681dee5e1fb38ac2498e7ae0f7e4b59240642a78862cc49fb93104c8d`.
- Requested route remains XHARD `gpt-5.6-sol` / high reasoning. The GF01 launch receipt records thread `01a09e0f-7301-75a0-b364-5520738e28f8`, Codex CLI `0.150.1`, and supervised session handle `41381`; it does not independently attest the backend model.
- No review-frozen checkout, package, control, map, DAT, WRK, PKG, EDT, GF02 source/test, or GF03 file was edited by this follow-up.

## Canonical public Store boundary

The single helper is `herzchen.contracts.canonical_request_digest`, implemented
by the accepted GF02 change at `src/herzchen/contracts/model.py:41` (integrated
blob `98a878f56cd380a6eff5b2284ece0f8b4c04d642`). No local digest helper was
added.

`Store.mutate` now invokes that helper before owner admission, transaction
selection, or replay lookup. It derives replay identity from the logical
request key, operation, schema revision, target, authenticated actor, and the
complete `CommandEnvelope.payload`. It replaces the context digest on an
immutable envelope copy, so a caller-supplied digest remains shape-compatible
but cannot choose replay identity.

The existing GF01 boundary remains strict: ordinary callers receive
`ConsumerStore`; writable methods stay on the sealed Store owner capability;
registered optional domains still require an admitted operation/resource/
event/schema combination and owner or explicit actor binding; extension
protocol mutation still requires `actor-authority:dat-auth`; unknown triples
and caller owner-string spoofing still reject before any durable delta.

Finite neutral kernel ports now retain the actual authenticated caller or
resolver. Their handler binding is possession of the sealed Store capability
plus the fixed kernel operation/resource/event/schema port, rather than
rewriting or comparing every caller identity to the string `fnd`. This does
not admit arbitrary names or relax optional-domain owner bindings.

## Changed paths

- `src/herzchen/kernel/store.py` — imports and applies the canonical GF02 helper at the public mutation boundary; retains authenticated actors on fixed neutral ports. SHA-256 `edfe530821d60c4c0d35148c44434873ec701277c70728df4000ed0d0c2a66b6`.
- `tests/kernel/test_public_mutation_admission.py` — adds direct Store replay cases for changed payload, target, operation, and actor with a reused caller digest; every rejection asserts unchanged identity/reference/event/receipt/sequence counts. SHA-256 `65009210a5e5d6be74b210719c4cc8a0d5648f7563c76c581ee886bea62a42de`.
- `work/gf01-gf02-integration-result.md` — this evidence record.

## Source verification

Verified interpreter: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`, Python `3.12.14`.

```text
env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .../int-02/bin/python -m pytest -q tests/kernel/test_public_mutation_admission.py tests/extensions/test_definition_admission.py tests/extensions/test_namespaces.py
exit 0 — 24 passed

env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .../int-02/bin/python -m pytest -q tests/kernel/test_receipts_limits.py
exit 1 — 2 failed, 10 passed

env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .../int-02/bin/python -m pytest -q tests/work/test_identity_graph.py
exit 1 — 4 failed, 2 passed

git diff --check
exit 0
```

The new direct Store test proves the persisted receipt digest equals the
canonical helper result and differs from the supplied payload-only digest.
Changed payload, target identity, admitted operation, and authenticated actor
all raise `ReplayConflictError`; the current identity, prior receipt, and all
five durable counts remain unchanged. Existing unregistered-combination,
ordinary-consumer, owner spoof, altered catalog, sibling preservation, and
PKG handler cases remain green.

## Installed candidate proof

- Wheel: `/tmp/gf01-gf02-wheel.aYEbPQ/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `b75fd02f0f4dedd202c281e0ba285596a3a473cf4f7626ee1d2bb8c1fcc21e01`; size `192725` bytes.
- Disposable venv: `/tmp/gf01-gf02-venv.JkLgBA`; Python `3.12.14`; distribution `herzchen-contracts==0.1.0`; `Requires-Dist: none`.
- All installed commands used isolated mode with `PYTHONPATH` and `PYTHONHOME` unset. The verified INT-02 pytest package was appended to the interpreter search path only as the test runner because the disposable venv contains no pytest installation; the installed Herzchen site-packages directory retained precedence.
- Installed origins: `/private/tmp/gf01-gf02-venv.JkLgBA/lib/python3.12/site-packages/herzchen/kernel/store.py` and `/private/tmp/gf01-gf02-venv.JkLgBA/lib/python3.12/site-packages/herzchen/contracts/model.py`.
- Installed GF01/admission suite: exit `0`, `24 passed`.
- Installed GF02 receipts/limits suite: exit `1`, `2 failed, 10 passed`, matching source.
- Existing installed JSON probe: exit `0`; ordinary writable paths absent, non-owner and unknown combination no-delta, four altered catalogs rejected, valid receipt/event linkage and fresh reopen coherent.

## Bounded incompatibilities

### GF02 operation-outcome pre-replay payload mismatch

`OperationManager._transition` performs a replay check before entering Store
using `next_request.envelope(...)` with `next_request.payload`. Its first
outcome write calls Store with a different full identity payload produced by
`_payload(identity_request, state, result)`. Once Store correctly owns the
canonical digest of its actual full envelope payload, an exact outcome replay
compares those two different canonical payloads and raises
`ReplayConflictError`. This affects the exact replay portions of
`test_operation_identity_replay_conflict_and_explicit_unknown_resolution` and
`test_unknown_reopen_resolution_preserves_attribution`; changed-argument,
actor-recovery, resolver-attribution, and limit canonicalization assertions
continue to pass.

Fix ownership remains GF02: construct and pre-validate the exact same final
envelope used for Store mutation, or delegate receipt replay comparison to
Store. GF01 cannot make `get_receipt` lie, trust the caller digest, or hash a
payload other than the public envelope's full payload without weakening the
requested invariant. The accepted GF02 files and tests were therefore not
edited.

### WorkGraph trusted-composition gap

The serialized `tests/work/test_identity_graph.py` run confirms two distinct
existing-consumer gaps. Three mutation tests construct a valid `WorkGraph`
without registering its contribution, so strict Store admission rejects
`work.create`. The one test that calls `graph.register()` supplies actor
authority `test` against contribution owner `wrk` without an explicit actor
binding, so owner admission rejects it.

A safe compatibility path requires the WRK/host composition owner to register
the typed contribution before the adapter mutates and to publish explicit
allowed handler/actor bindings. Store cannot infer trusted optional modules
from Python call stacks, auto-import WRK, or equate arbitrary owner strings and
actors. No broad fallback or hidden auto-registration was added.

The follow-up commit/tree and clean status must be appended by the manager if
the current execution sandbox cannot write the worktree's shared Git metadata.
The canonical external delivery location requested by the directive is
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-gf02-integration-result.md`; this tracked copy is the source artifact for that custody step.
