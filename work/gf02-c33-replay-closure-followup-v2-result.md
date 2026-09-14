# GF02/C33 replay closure follow-up v2

Date: 2026-09-14
Route: normal / gpt-5.6-luna / `model_reasoning_effort=high`
Status: complete for the five bounded rows in this follow-up

## Custody

- Worker HEAD: `f620cd36d8f9267935e7b4ae7aa1f950a4b1db2d`
- Worker HEAD tree: `bb6c3077fa0fc9537fc712db80dc23cdbbdf5c07`
- Frozen DAT evidence supplied for classification: source `f620cd36d8f9267935e7b4ae7aa1f950a4b1db2d`, wheel SHA `21a963be445fb93315cd252510abf96ad13f7f7d3363a42414eb02b85ddcf512`
- Fresh validation wheel: `dba4580da66c08173e2557ddc239a8a5769a8c8f399af5809c050d50e0b5f420`
- Validation Python: `/opt/homebrew/bin/python3.11`, Python 3.11.16. Python 3.12 was unavailable at `/opt/homebrew/bin/python3.12`.

## Implementation

Owned implementation changes are limited to:

- `src/herzchen/domains/assessment/module.py`: `assessment.correction.create` now hashes the caller request payload before projection mutation and resolves exact replay from the original correction and result-link receipts/events. The existing stable `assessment.finding.close` replay path remains covered. Changed instruction/finding input reaches the Store replay-conflict check before mutation.
- `src/herzchen/authoring/sessions.py`: `cleanup.refresh` hashes caller session/snapshot/manifest input before issuing the generated retirement fence. Exact replay returns the original snapshot without regenerating projection/fence state; changed snapshot input conflicts without mutation. The related fence re-establishment path uses the same caller-keyed digest and does not issue a new fence before replay resolution.

The existing public handler, Store transaction, and typed-port interfaces were preserved. No Store/kernel, FND, contracts, command-port, DAT, or C33 checkout files were edited. The FND overlap assumption is that the existing `get_receipt`, `list_events`, `mutate`, and transaction signatures remain unchanged; no adapter diff is required by this worker.

## Bounded behavior and proof

The focused regressions independently assert first action, exact retry/result identity, and changed-input `ReplayConflictError`. For every retry/conflict assertion, SQLite counts for identities, record references, command receipts, and durable events are compared before and after; changed requests have no durable delta.

Focused regression IDs:

- `tests/assessment/test_accounting.py::test_correction_and_result_link_exact_retry_preserve_receipts_and_conflict_on_changed_input`
- `tests/assessment/test_accounting.py::test_finding_close_exact_retry_returns_original_receipt_and_changed_finding_conflicts`
- `tests/authoring/test_finish.py::FinishTests::test_cleanup_refresh_replays_without_hashing_projection_or_fence`
- `tests/authoring/test_finish.py::FinishTests::test_capture_failure_does_not_write_a_false_success`

Focused source run: 4 passed, 13 deselected.
Focused installed-wheel run: 4 passed, 13 deselected.
Focused C33 closure file `tests/work/test_gf02_c33_replay_closure.py`: 9 passed from source and 9 passed from the installed wheel.
Affected source suites `tests/assessment tests/authoring`: 69 passed, 1 skipped. The skip is the intentional installed-origin handoff test.
Affected installed-wheel suites: 70 passed.

The correction test covers both `assessment.correction.create` and its public-path `assessment.result.link-correction` mutation/receipt. No separate public link-correction handler exists in this checkout. The finding test retries against the advanced closed projection and changes the caller finding precondition. The cleanup test retries after the released projection has been updated, and changes snapshot bytes with the same logical key.

## `finish.recovery` classification

No source change was made for `edt-02.authoring.finish.recovery`. The supported semantic adapter capture-failure path fails during snapshot capture (`unregistered checkout files: project.json`) before calling `AuthoringSessionService.finish`; it returns `failed` with `recovery_pending=True`, leaves the original `capture-fails` success receipt absent, and does not expose a supported recovery receipt/event candidate. This matches the retained intentional no-success-receipt contract. No fabricated receipt or replay path was added.

## Evidence and working state

Exact commands, UTC timestamps, PIDs, Python/wheel identity, module origins, and exit statuses are in `work/gf02-c33-replay-closure-followup-v2-receipt-20260914/receipt.jsonl`.

The four owned source/test files and this result/receipt are intentionally unstaged for manager custody. Pre-existing untracked `build/`, `src/herzchen_contracts.egg-info/`, and the supplied follow-up brief remain untouched. No commit, review, gate, push, merge, or DAT mutation was performed.
