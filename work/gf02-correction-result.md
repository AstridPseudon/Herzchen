# GF02 exact replay and recovered actor correction

Status: one committed GF02 candidate; this worker preserves the original G-FOUNDATION `REWORK` verdict and does not issue gate acceptance.

## Scope and frozen inputs

- Route: normal implementation worker, requested `gpt-5.6-luna`, high reasoning.
- Worker: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf02-correction-worker`, branch `gf02-correction-worker`.
- Baseline: commit `046b9acfdc9ba541faff65ff3713961890684303`, tree `047a43ba687f45c298139b595756dac84ab729da`.
- Review: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/g-foundation-review-01-result.md`, verdict `REWORK`.
- Baseline failure receipt retained unchanged: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/g-foundation-rework-baseline-20260914.md`; raw output SHA-256 `77a1d929aa3fa0b293ffcd7db94be81dd8acd3e138fb6b7ee10ab572208e7ab4`.
- Governing lineage read: FND C03/C33/C34, `architecture/shared-contracts.md:20-30`, FND-03/FND-04/FND-05, and retained Runtime assertion `local/sources/Runtime-afccb430e2/tests/test_runtime_exact_idempotency.py:70` (changed arguments must return 409).

## Correction

`canonical_request_digest` in `src/herzchen/contracts/model.py:41` is the single semantic digest helper. It binds logical key, operation, schema revision, target, authenticated actor, and JSON payload. `OperationRequest` adds adapter, physical invocation, and external owner references to that semantic payload; `LimitService` uses the same helper for pool creation, reservations, and transitions. Caller-provided digest-shaped values remain accepted for compatibility but are not used as replay identity.

Operation records now persist `request_actor` in the identity and event effects (`src/herzchen/kernel/operations.py:182-211`). `get()` recovers that actor, or the first prepared-event actor for legacy identity payloads; it never fabricates `neutral-store/record-reader`. `resolve_unknown(..., resolver=...)` requires an authenticated resolver. The outcome event is attributed to the resolver while the returned/recovered operation request retains the original actor. Transition digests include outcome semantics and resolver identity, so exact resolution replays once and changed/stale/foreign transition reuse conflicts before mutation.

## Exact source/test lineage

- Reviewed defect anchors: `operations.py:52`, `model.py:439`, `limits.py:151`, `operations.py:158`, `operations.py:198` in the frozen review checkout.
- Retained/adapted test: `tests/kernel/test_receipts_limits.py:58` previously asserted the inverted changed-payload replay; it now asserts `ReplayConflictError`.
- New exact checks: `tests/kernel/test_receipts_limits.py:83` (`test_same_key_changed_arguments_conflict_even_with_reused_digest`) and `:114` (`test_unknown_reopen_resolution_preserves_attribution`). Additional reopen/single-effect and limit canonical replay checks begin at `:153` and `:166`.
- No changes to Store, extension modules, public ownership files, DAT/WRK/PKG/EDT/OTT modules, control records, extraction map, package seed, or the review-frozen checkout.

## Source proof

Interpreter: `/opt/homebrew/bin/python3.11` (Python 3.11.16); source proof intentionally used `PYTHONPATH=src`, `PYTHONHOME` unset.

1. `env -u PYTHONHOME PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/kernel/test_receipts_limits.py -k 'same_key_changed_arguments_conflict_even_with_reused_digest or unknown_reopen_resolution_preserves_attribution or exact_request_replay_after_reopen_is_single_effect or limit_replay_uses_canonical_semantics_after_reopen'` — exit 0; `4 passed, 8 deselected`.
2. `env -u PYTHONHOME PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/kernel` — exit 0; `52 passed, 10 subtests passed`.
3. `env -u PYTHONHOME PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/kernel tests/conformance tests/assessment/test_accounting.py` — exit 0; `80 passed, 80 subtests passed`.

Fresh before/action/fresh-after probe output:

```json
{"before": {"events": 1, "physical_refs": 1, "receipts": 1, "state": "prepared"}, "rejected_action": {"error": "ReplayConflictError", "events": 1, "physical_refs": 1, "receipts": 1, "state": "prepared"}, "fresh_after_reopen": {"events": 3, "original_actor": "original-actor", "outcome_actor": "resolver", "receipt_replayed": true, "state": "committed"}}
```

## Installed proof

Wheel build command: `/opt/homebrew/bin/python3.11 -m pip wheel --no-deps --wheel-dir /tmp/gf02-candidate.y6Yu1E .` — exit 0. Wheel: `/tmp/gf02-candidate.y6Yu1E/herzchen_contracts-0.1.0-py3-none-any.whl`; SHA-256 `f68ffcb528df7a7411ad63410333213ae99336ee645ca7313636b8ac65600284`.

Installed environment: `/tmp/gf02-candidate.y6Yu1E/venv`, Python 3.11.16, `PYTHONPATH` and `PYTHONHOME` both unset. Origins:

- `herzchen`: `/private/tmp/gf02-candidate.y6Yu1E/venv/lib/python3.11/site-packages/herzchen/__init__.py`
- `herzchen.contracts`: `/private/tmp/gf02-candidate.y6Yu1E/venv/lib/python3.11/site-packages/herzchen/contracts/__init__.py`
- `herzchen.kernel`: `/private/tmp/gf02-candidate.y6Yu1E/venv/lib/python3.11/site-packages/herzchen/kernel/__init__.py`
- `herzchen.kernel.operations`: `/private/tmp/gf02-candidate.y6Yu1E/venv/lib/python3.11/site-packages/herzchen/kernel/operations.py`
- `herzchen.kernel.limits`: `/private/tmp/gf02-candidate.y6Yu1E/venv/lib/python3.11/site-packages/herzchen/kernel/limits.py`

Commands and exit statuses:

1. `env -u PYTHONPATH -u PYTHONHOME /tmp/gf02-candidate.y6Yu1E/venv/bin/python -m pytest -q tests/kernel/test_receipts_limits.py` — exit 0; `12 passed`.
2. `env -u PYTHONPATH -u PYTHONHOME /tmp/gf02-candidate.y6Yu1E/venv/bin/python -m pytest -q tests/kernel` — exit 0; `52 passed, 10 subtests passed`.
3. `env -u PYTHONPATH -u PYTHONHOME /tmp/gf02-candidate.y6Yu1E/venv/bin/python -m pytest -q tests/conformance/test_fixtures.py tests/conformance/test_matrix.py tests/conformance/test_rehearsal.py tests/assessment/test_accounting.py` — exit 0; `26 passed, 70 subtests passed`.

## Invocation receipt

- Requested route/model/reasoning: normal / `gpt-5.6-luna` / high.
- CLI observed: `/Users/hannahomalley/.local/bin/codex`, `codex-cli 0.150.1`.
- Worker shell/worktree process and tool session identifiers are not exposed as a durable model-session receipt in this environment; no identifier is inferred. The recorded subprocess IDs for the long-running test calls were tool-local sessions `47343`, `45941`, `29625`, and `90788`, not model identity claims.
- Start/end evidence: command execution window 2026-09-14 06:04–06:06 +0200; the explicit fresh probe completed at 2026-09-14T04:06:36Z. No external invocation was made.

## Remaining limits and coordination

GF01 remains an independent `REWORK`: Store public writer/admission ownership is unchanged and must be corrected by its owner. GF03 writer-retirement/final-byte fencing remains unchanged. This result does not claim G-FOUNDATION acceptance, consumer cutover, Runtime/Astrid production origin, G-OTTO, or product behavior. FND coordination should consume the exported canonical helper for any future operation/limit callers; no GF01/DAT file change is required for this candidate.

Artifact SHA-256 values for this result and the companion handoff are reported after commit because each file cannot contain its own final digest.
