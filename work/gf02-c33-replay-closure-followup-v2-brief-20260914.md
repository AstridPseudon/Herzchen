# GF02/C33 replay closure follow-up v2

Route: normal `gpt-5.6-luna` with `model_reasoning_effort=high`, same worker thread continuation.

## Goal and bounded scope

Continue from manager custody commit `f620cd36d8f9267935e7b4ae7aa1f950a4b1db2d` (tree `bb6c3077fa0fc9537fc712db80dc23cdbbdf5c07`) in this checkout. Close only the remaining supported C33 owner rows observed against the fresh installed wheel:

- `assessment.correction.create`
- `assessment.finding.close`
- `assessment.result.link-correction`
- `edt-02.authoring.cleanup.refresh`
- `edt-02.authoring.finish.recovery` receipt lookup/semantics

The DAT C33 run was the accepted 77-row test file, installed from wheel SHA `21a963be445fb93315cd252510abf96ad13f7f7d3363a42414eb02b85ddcf512`, source `f620cd36d8f9267935e7b4ae7aa1f950a4b1db2d`, and reported 66 passed, 10 reproduced owner defects, and one project-parent fixture incomplete. The five WorkGraph parent-linked new-key rows are preserved as classification evidence and are outside this follow-up. Do not change the DAT checkout or its tests.

## Exact observed failures

The three assessment rows and `cleanup.refresh` fail during exact replay with `ReplayConflictError: logical request key was reused with a changed request digest`. Preserve caller intent and the original receipt/result; do not hash the post-mutation projection or generated fence into an exact retry. Changed instruction/finding/snapshot inputs with the same key must conflict with zero durable deltas.

`finish.recovery` first action emits a durable `finish.recovery` event for the capture-failure path but the DAT lookup finds no receipt in its supported candidate keys. Inspect the actual receipt/event contract and existing authoring tests before changing behavior. Capture-failure currently has explicit no-success-receipt semantics in the retained authoring tests; do not add a fabricated receipt merely to satisfy a lookup. If the supported public contract requires a recovery receipt, implement the narrow caller-keyed replay path and prove exact retry/changed input. Otherwise record the actual supported key/event and the intentional no-receipt result as bounded evidence, with no source change.

## Ownership and constraints

Owned source paths are `src/herzchen/domains/assessment/module.py` and `src/herzchen/authoring/sessions.py`; focused regression tests may be added under `tests/assessment/` or `tests/authoring/`. Do not edit Store/kernel, FND ports/contracts, DAT conformance tests, or unrelated domains. Preserve the existing GF02 changes and the original worker result/receipt.

Use public handlers and the existing Store/transaction port only. Do not add private SQL/writer paths, `sys.modules` or `PYTHONPATH` tricks, xfails, or lexical-only assertions. Keep logical caller payload separate from derived identity/projection state.

## Required proof

For each actionable row, prove first action, exact retry after projection/reopen where supported, original receipt/result identity, changed input/precondition conflict, unchanged identities/references/receipts/events on rejection, and fresh installed-wheel origins. Run the focused C33 row reproductions without modifying DAT files, plus affected assessment/authoring suites once. Record command, model/reasoning request, PID/session, timestamps, Python, wheel SHA, and exit status in JSONL. Explain whether `finish.recovery` changed or was classified as an intentional no-receipt path.

Leave changes unstaged for manager custody and write `work/gf02-c33-replay-closure-followup-v2-result.md` plus `work/gf02-c33-replay-closure-followup-v2-receipt-20260914/receipt.jsonl`. No review, gate, push, merge, FND changes, or DAT source changes.
