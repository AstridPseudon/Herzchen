# GF02/C33 replay closure v3 — manager custody supplement

This supplement records the bounded v3 continuation after the normal Luna/high worker became idle without producing its final message. The worker process was safely terminated only after its latest tool state showed no active child test or file writer; no additional implementation was attempted outside the worker's existing owned diff.

## Route and custody

- Worker session/thread: `01a09edc-1141-79e2-b94c-a7f59c9e2c4f`
- Requested route: `gpt-5.6-luna`, `model_reasoning_effort=high`
- CLI PTY: `51289`; CLI PID `12009`, wrapper PID `11996`; started `2026-09-14T08:51:18Z`
- Source base before this continuation: `3582d9d129369c14be17ccc7e822001719ecfe6c`, tree `e959a37b689805ad40b4ac234030535ccb5f7507`
- Worker final message: unavailable. The resumed process was idle after the final DAT76 collection attempt, with no active child process; PID 12009 was terminated at manager direction. This is not presented as a worker completion claim.

## Owned source changes retained

- `src/herzchen/domains/assessment/module.py`: normalize only derived `AssessmentResult`/`Finding` projection objects to unpinned semantic identity in logical request payloads. Explicit revision-pinned `ResourceRef` inputs remain pinned. Mutation targets and explicit CAS fields remain revision/version-bound. This closes exact retry after linked/closed projections advance while preserving same-key changed-input conflicts.
- `src/herzchen/authoring/sessions.py`: return the actual durable recovery receipt from direct capture/application recovery. The receipt remains at the contract-defined suffixed key (`<request_id>:capture-failure` or `<request_id>:recovery`); the caller request key has no false success receipt.
- Focused tests cover derived projection retry, explicitly pinned conflict, changed-input zero-delta, direct recovery receipt boundary, and cleanup refresh.

## Validation actually completed

- Source focused command: `env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.11 -m pytest -q tests/assessment/test_accounting.py tests/authoring/test_finish.py -k 'correction_and_result_link_exact_retry_preserve_receipts_and_conflict_on_changed_input or finding_close_exact_retry_returns_original_receipt_and_changed_request_conflicts or direct_capture_failure_returns_actual_recovery_receipt or capture_failure_does_not_write_a_false_success or cleanup_refresh_replays_without_hashing_projection_or_fence'` — `5 passed`.
- Owned source suites: `70 passed, 1 skipped` (worker output; skip is the existing installed-origin-only test).
- Fresh installed wheel: `78a33ae62dca8dc4f358daa41c897d7f53c8376c48a6226d4ebb5c845a73e5ed`; site-packages origins were recorded under `/private/tmp/gf02-c33-v3-final-venv.Jg1KOW`; same five focused installed tests passed.
- DAT C33 current 76-port matrix collection was intentionally not claimed: it stopped before tests because this pre-P01 source still admits the removed `work.v1|work.revise|work.project|work.parent-linked` port. The full 76 campaign belongs on the combined P01 source candidate.

The next integrated candidate must combine GF01 through `8235d9aacbe7357e8f72cec8342eca77aab0cb58`, this custody commit, and DAT C33 `9028f0f08af1844e29fba5fa4b14aa65793d161e`; only that candidate can provide the required coherent 76-row installed proof.
