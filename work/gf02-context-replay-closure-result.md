# GF02 bounded context/replay closure worker result

Date: 2026-09-14 (Europe/Berlin)

Status: implementation and validation complete; commit delivery is blocked by
the sandbox's linked-worktree Git metadata permission. This result does not
issue a review, oracle, gate, upstream, or control decision.

## Custody and route

- Requested route/model/reasoning: `normal / gpt-5.6-luna / high`.
- Observed model/reasoning and native model/session JSONL: not exposed by this
  execution environment.
- Worker checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf02-context-replay-closure-worker-v2`.
- Supplied source HEAD/tree before this worker: commit
  `6c9bf746c5ef4509f0071603f7a3b59e908370a0`, tree
  `0e95a070db51eccb120d3797b56c837a9c93c4a1`.
- Frozen parent checkout was not edited: commit
  `994d234b349c35a9de58f296fc8f542bc210dc7c`, tree
  `229ab9cf87d318424fd0ff3c05e97fced3cd5519`, clean.
- Review source read from the frozen campaign path
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/g-foundation-review-03-result.md`:
  GF03 PASS and GF02 REWORK. It was not copied or modified.

## Implementation

Owned source changes:

- `src/herzchen/kernel/operations.py`
  - Keeps the caller's `expected_revision`, `expected_version`, `edit_token`,
    `correlation_id`, and `causation_id` in the operation request identity,
    prepared/outcome event effects, and durable reconstruction payload.
  - Separates derived create/CAS values (`None`/`0` for preparation and the
    current target revision/version for outcomes) from the original logical
    request context. The existing complete-context canonical helper and
    admitted transaction path remain in use.
  - Preserves the original request actor/context through outcome transitions;
    an explicit resolver remains the outcome event actor.
- `src/herzchen/domains/work/batches.py`
  - Resolves a same-key project-sheet retry through the original receipt and
    admitted Store before current projection, sheet planning, or stale-base
    checks.
  - An exact retry after an intervening project revision returns the original
    receipt/mapping result with no durable delta; a changed base revision
    conflicts before any child/parent write.
  - Retains the original batch request context in the parent batch projection
    and event effects, and reconstructs replay mappings from the original
    durable event.

Focused test changes:

- `tests/kernel/test_receipts_limits.py`
  - New exact test ID:
    `tests/kernel/test_receipts_limits.py::ReceiptAndLimitTests::test_all_original_context_fields_survive_transition_and_reopen`.
  - Focused file count: 14 tests.
- `tests/work/test_batches.py`
  - New exact test ID:
    `tests/work/test_batches.py::test_sheet_replay_precedes_stale_base_after_advance_and_changed_base_has_no_effect`.
  - Focused file count: 7 tests.

## Validation

Interpreter and package proof:

- Interpreter: `/opt/homebrew/bin/python3.11`, Python `3.11.16`.
- Disposable environment: `/private/tmp/gf02-context-replay-closure.ahIR0o/venv`.
- Wheel: `/private/tmp/gf02-context-replay-closure.ahIR0o/wheel/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `65b701a664f21a92b332ede567436404170850cb32053fa21c0c088cc1da3c6e`.
- Installed origin probe reported `PYTHONPATH=None`, `PYTHONHOME=None`; all
  checked `herzchen` modules resolved under the disposable venv's
  `site-packages`, including `kernel.operations` and
  `domains.work.batches`. Pytest was the system-site-packages pytest used by
  the disposable venv.

Exact passing commands and results:

```text
PYTHONDONTWRITEBYTECODE=1 env -u PYTHONPATH -u PYTHONHOME PYTHONPATH=src /private/tmp/gf02-context-replay-closure.ahIR0o/venv/bin/python -m pytest -q tests/kernel/test_receipts_limits.py tests/work/test_batches.py
21 passed in 0.28s; exit 0

PYTHONDONTWRITEBYTECODE=1 env -u PYTHONPATH -u PYTHONHOME PYTHONPATH=src /private/tmp/gf02-context-replay-closure.ahIR0o/venv/bin/python -m pytest -q tests/kernel tests/work
115 passed, 10 subtests passed in 1.30s; exit 0

PYTHONDONTWRITEBYTECODE=1 env -u PYTHONPATH -u PYTHONHOME /private/tmp/gf02-context-replay-closure.ahIR0o/venv/bin/python -m pytest -q tests/kernel/test_receipts_limits.py tests/work/test_batches.py
21 passed in 0.26s; exit 0

PYTHONDONTWRITEBYTECODE=1 env -u PYTHONPATH -u PYTHONHOME /private/tmp/gf02-context-replay-closure.ahIR0o/venv/bin/python -m pytest -q tests/kernel tests/work
115 passed, 10 subtests passed in 1.18s; exit 0
```

The focused collection was 21 tests: 14 from
`tests/kernel/test_receipts_limits.py` and 7 from `tests/work/test_batches.py`.
The affected collection was 81 kernel tests plus 34 work tests, with the
reported 10 subtests.

No-effect assertions cover unchanged identity, reference, event, receipt, and
event-sequence counts for each changed operation context field, and unchanged
counts for changed project-sheet base replay. The tests also assert unchanged
child mappings, original batch event base revision, original operation actor,
resolver event attribution, and all five fields after transition and fresh
Store reopen/reconstruction.

`git diff --check` passed. Generated wheel/build/bytecode artifacts were
removed; only the four owned implementation/test files and the two requested
evidence files remain modified/untracked.

## FND overlap and handoff

No FND Store, command-port, contract/model, or other domain source was edited.
The implementation assumes the later FND owner preserves these existing
interfaces: the admitted domain handler's
`mutate(envelope, identity_payload=..., event_type=..., result_ref=...,
before_refs=..., after_refs=..., effects=..., stream=..., transaction=...)`,
its `transaction()` context, and its `get_receipt`, `get_identity`,
`list_events`, and `consumer().snapshot_counts()` reads. Store replay must
continue canonicalizing the exact final envelope and checking an existing
receipt before current-state admission. No private writer, raw SQL path,
broad registry, alternate request model, or `digest_payload` authority input
was added.

## Commit custody

The exact scoped commit attempt failed before staging because the linked
worktree metadata is outside the writable root:

```text
fatal: Unable to create '/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf02-store-integration/.git/worktrees/Herzchen-gf02-context-replay-closure-worker-v2/index.lock': Operation not permitted
```

The worker therefore remains at the supplied HEAD/tree with four owned paths
modified and no paths staged. A manager with Git-metadata access must commit
only the four owned implementation/test paths plus this result and the dated
receipt; no push or merge was performed.
