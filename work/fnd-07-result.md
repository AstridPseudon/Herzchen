# FND-07 bounded shared-read race correction

This is a bounded FND candidate evidence record for root integration review.
It makes no product, Astrid, Runtime, public-cutover, ledger, or gate verdict.

## Custody and candidate

- Invoking root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20`
- Control root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery`
- Isolated worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd07-worker`
- Baseline commit/tree: `37292c6c855e1712ad619b05244eba683f24e836` / `3d1aa21a8c04e658e7730227f61cd2a86f51bf45`
- Implementation candidate commit/tree: `cec510615fa7a3c619a0c7e73d4d5a4dae851748` / `732b5054f09bf657011383180aef791f77b73062`
- Source manifest SHA-256: `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`
- Immutable traceback SHA-256: `f96f4067625e20079e74eede66380903f9e0a181f6bb003f850b3a1da44c72bf`
- CLI route: normal substantive worker, `gpt-5.6-luna`, reasoning `high`, `codex-cli 0.150.1`
- Successful route session: `01a09d7b-94f5-7011-ae0d-4938923c2217`
- Launch time: `2026-09-14T01:15:17.165700Z`

## Changed paths

- `src/herzchen/kernel/store.py`
- `src/herzchen/authoring/finish.py`
- `tests/kernel/test_transactions.py`

The two named authoring tests were preserved unchanged. The added kernel test
keeps two barrier-synchronized public readers concurrent with a transaction
writer for 50 iterations and checks identity, receipt, and event decoding.

## Traceback and correction

`Store._connect()` deliberately uses one SQLite connection with
`check_same_thread=False`, while the existing `_transaction_lock` serialized
writer admission only. `get_identity`, `get_reference`, `get_receipt`,
`list_events`, and the foreign-key read accessed that shared connection
without the writer boundary. SQLite cursor execution/fetch and `sqlite3.Row`
decoding could therefore overlap a contender's transaction or another read.
The observed result was a blank/invalid identity field during
`Store._identity_from_row`, causing `ResourceRef`/contract validation to fail
and the loser to return `failed`.

The correction makes Store-owned public reads acquire the existing
re-entrant `_transaction_lock` and keeps execute, fetch, and row-to-contract
decoding inside that critical section. No new connection, retry, receipt/event
engine, table, schema change, or public Store method was added. The existing
transaction lock remains the sole writer boundary. Because it is an `RLock`,
a public read made by the owning thread inside an active transaction remains
valid and sees the same transaction state; nested `Store.transaction()` calls
continue to use the existing savepoint path. The adapter's small change only
runs the already-existing durable-winner reconciliation when a same-service
contender loses between its initial read and authorization; it adds no EDT
lock, retry, or second write boundary.

## Baseline evidence

The first Python 3.11 attempt without source installation was setup-only and
failed with `ModuleNotFoundError: herzchen`; it was not counted as a product
failure. With the traceback-matching Python 3.12 environment and `PYTHONPATH=src`:

- `tests/authoring` reproduced the first named failure: `1 failed, 26 passed`
  (`['failed', 'finished']` instead of `['already_finished', 'finished']`).
- The exact cross-service test reproduced the second failure: `1 failed, 1
  warning`; its worker traceback reached `Store.get_identity()` and decoded an
  invalid `kind`/`authority` field from the shared row.
- The supplied traceback file remains unchanged at its recorded digest.

## Source validation

Using the declared Python 3.11 path, both exact named tests were run 50 times
each with barrier concurrency; each set exited 0 with all iterations passing.
The same 50-run repetitions under the traceback-matching Python 3.12
environment also exited 0.

The affected source suite, `tests/authoring tests/kernel`, passed under both
interpreters:

```
Python 3.11: 75 passed, 10 subtests passed in 0.60s
Python 3.12: 75 passed, 10 subtests passed in 0.52s
```

## Fresh-wheel validation

A fresh wheel was built from implementation candidate commit `cec5106…` in
disposable environment `/tmp/fnd07-wheel.m8Lw7K` with both `PYTHONPATH` and
`PYTHONHOME` unset. The wheel was:

- `/tmp/fnd07-wheel.m8Lw7K/wheel/herzchen_contracts-0.1.0-py3-none-any.whl`
- SHA-256: `27d6fa6829e7b53a8c83430903637498f38878f22a17e002c1a1ac9810425c80`

Installed origin evidence:

```
python: /private/tmp/fnd07-wheel.m8Lw7K/venv/bin/python (3.11.16)
distribution: /private/tmp/fnd07-wheel.m8Lw7K/venv/lib/python3.11/site-packages
herzchen: /private/tmp/fnd07-wheel.m8Lw7K/venv/lib/python3.11/site-packages/herzchen/__init__.py
herzchen.authoring.finish: /private/tmp/fnd07-wheel.m8Lw7K/venv/lib/python3.11/site-packages/herzchen/authoring/finish.py
herzchen.kernel.store: /private/tmp/fnd07-wheel.m8Lw7K/venv/lib/python3.11/site-packages/herzchen/kernel/store.py
PYTHONPATH: None
PYTHONHOME: None
```

The installed exact tests passed (`2 passed in 0.13s`), each named test was
then repeated 20 times with exit 0, and the installed affected suite passed
(`75 passed, 10 subtests passed in 0.47s`).

## Downstream obligation

Root integration owns review, ledger/gate decisions, and any separate merge or
cutover. The candidate must be integrated there before any claim about the
package's wider Astrid/Runtime environment or public installation origin.

No product verdict is made by this worker.
