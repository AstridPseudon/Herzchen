# WRK-03 typed-revision correction result

Status: correction implemented and locally verified. No upstream push or product acceptance claim is made.

## Exact lineage

- WRK-03 source/evidence checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk03-worker`
  - source commit: `e333ea526180258e520f051f66805a89dd21c4e6`
  - source tree: `e66100bc2ce9ed23c390ce73392ab4ba97938b3c`
- Accepted FND typed-port checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-revision-worker`
  - accepted commit: `59043551e6fb4a19d7130d5aa47cf75a732e0a45`
  - accepted tree: `39bb3ac322855f3e6552813b3ce87c6834d40917`
- Correction checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk03-revision-worker`
  - branch: `wrk-03-revision-worker`
  - coordinated FND cherry-pick: `ef2220bfeb4729a1c2c92f9f5ef6a3377c930be0`
  - correction HEAD/tree at verification: `ef2220bfeb4729a1c2c92f9f5ef6a3377c930be0` / `067af4ace9a30cfcf93695c384757d8e5907be21`
- Shared interpreter: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`
- Source manifest: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`
  - SHA256: `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`

The FND files from the cherry-pick remain frozen; they were not edited or reverted.

## Correction

`src/herzchen/domains/work/batches.py` no longer directly mutates `identities`. The existing task, document-association, and document-head paths now call `store.revise_identity(...)` with the current typed reference, next FND revision, expected current revision/version, current edit token, and the supplied outer `tx`. New identities continue through `put_identity`, and the parent sheet continues to own the single `mutate(..., transaction=tx)` receipt/event boundary. No child request keys or child receipts were added.

The helper advances numeric FND revisions one step and supports the typed port’s bounded legacy-opaque-to-numeric transition. Existing-record revise/link and omission-retention behavior remains covered. Tests add existing task/document-head/association revision coverage and an injected child-failure rollback covering identities, references/revisions, associations, events, and the parent receipt.

## Changed-file hashes

Git blob hashes after the correction:

- `src/herzchen/domains/work/batches.py`: `52a1f3c5d3a91e8287c311f8d55ab9a2434242ed`
- `tests/work/test_batches.py`: `7186b9d4ee9c411ac153b763797fc87dd539e9b4`

No changes were made to `assignments.py`, `test_assignments.py`, frozen FND files, or paths outside the WRK-owned set.

## Verification commands and exits

Interpreter for all checks: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`.

- `python -m pytest -q tests/work/test_batches.py tests/work/test_assignments.py tests/kernel/test_identity_revisions.py` without `PYTHONPATH`: exit `2` during collection because the installed package did not expose `herzchen.domains`.
- `PYTHONPATH="$PWD/src" python -m pytest -q tests/work/test_batches.py tests/work/test_assignments.py tests/kernel/test_identity_revisions.py`: exit `0`; `16 passed, 10 subtests passed`.
- `PYTHONPATH="$PWD/src" python -m pytest -q`: exit `0`; `123 passed, 80 subtests passed`.
- `PYTHONPATH="$PWD/src" python -m compileall -q src tests`: exit `0`.
- `PYTHONPATH="$PWD/src" python -c 'import herzchen; import herzchen.domains.work; from herzchen.domains.work.batches import ProjectBatches; from herzchen.kernel import Store; print("import-ok")'`: exit `0`; `import-ok`.
- `git diff --check`: exit `0`.
- `rg -n 'UPDATE[[:space:]]+identities|INSERT[[:space:]]+INTO[[:space:]]+identities' src/herzchen/domains/work` followed by the absence check: exit `0`; no matches.
- Owned-path audit (`git diff --name-only`): exit `0`; only `src/herzchen/domains/work/batches.py` and `tests/work/test_batches.py` changed before this result file was added.

The frozen shared interpreter tests retain proof for stale revision, stale version, stale edit token, foreign authority, malformed payload, missing target, zero-row failure, supplied-transaction rollback, and one parent event/receipt composition in `tests/kernel/test_identity_revisions.py`. WRK tests retain same-key whole-sheet replay, changed-input conflict, concurrent-result, cross-scope, pending-project, current-vs-pinned, existing-record, omission-retention, and injected-child rollback coverage.

Generated `__pycache__` and `.pytest_cache` directories were removed after verification.

## Remaining installed integration gap

The requested interpreter’s ambient installed package is not an editable install of this correction checkout: the unqualified test command fails at collection unless `PYTHONPATH="$PWD/src"` is supplied. All source and shared-interpreter checks pass with that explicit source path. No upstream push or product-level acceptance was performed.
