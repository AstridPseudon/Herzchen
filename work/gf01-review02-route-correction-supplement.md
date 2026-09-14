# GF01 review-02 route-correction supplement

Date: 2026-09-14 (Europe/Berlin)

Status: immutable route-evidence supplement only. This supplement makes no gate, G-OTTO qualification, product-behavior, consumer-cutover, Runtime-origin, or Astrid-origin claim.

## Correction statement

The original GF01 review-02 route was requested as Sol/high, and the original process invoked `gpt-5.6-sol`. Its observed launch command was of the form `codex ... exec -m gpt-5.6-sol --json` and omitted `-c model_reasoning_effort=high`. Consequently, the original invocation verifies the Sol model but does not verify high reasoning; this supplement does not claim that the original process used high reasoning.

The bounded route-correction continuation was separately launched with model `gpt-5.6-sol` and the explicit binding `-c model_reasoning_effort=high`. It performed evidence correction only. No heavy test suite was rerun and no wheel was rebuilt. The original source and candidate-installed proof counts and evidence remain unchanged.

## Continuation launch evidence

- Route: `Sol/high`.
- Model: `gpt-5.6-sol`.
- Reasoning binding: explicit `model_reasoning_effort=high`.
- Started: `2026-09-14T08:21:44+02:00`.
- Session ID: `7470`.
- Thread ID: `01a09e94-27af-7073-addd-445f438347b9`.
- Parent PID: `77460`.
- Worker PID: `77464`.
- Exact recorded command: `cat <route-correction-brief> | /Users/hannahomalley/.local/bin/codex -C /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-review02-worker exec -m gpt-5.6-sol -c model_reasoning_effort=high --json -o /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review02-route-correction-jsonl.txt -`.
- Brief: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review02-route-correction-brief.md`.
- Brief SHA-256: `24bc04ede30a747081fe1165c3f00945e1befcdcb52bce0a9d9ee4d5f7b8592b`.
- Continuation launch receipt: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review02-route-correction-launch-receipt-20260914.json`.
- Continuation launch receipt SHA-256: `e0729150bbe7b8435b834fd4f8dd0aaebf59935d037ebf111174156c4ca4814e`.

## Original evidence reference

- Original launch receipt: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review02-launch-receipt-20260914.json`.
- Original launch receipt SHA-256: `1b85f65a98e2274f1901b6e50e73e66a63d1211d9b27b053e6d0e23c90346150`.
- Original session ID: `64601`.
- Original thread ID: `01a09e86-d990-7950-bd54-b8f3abb8dcf9`.
- Original parent PID: `73707`.
- Original worker PID: `73712`.
- Original result SHA-256 before route-wording correction: `cae48b5bbeb11e1121ede432bd16139d3764508db05c730f139ae0af7187c0a0`.
- Corrected result SHA-256: `e8c08996f8d5d48293cb213d1b967bb524cc1b21f10c17b0f204fe8c3b5d6367`.

The accepted baseline remains commit `ce5dd4907e712f45caf29c238d5db8a5582e5228`, tree `6616e77efc4c4bca336f43ce3a79008c7dc9ce11`. Product source, tests, the canonical map, package seed, reviewed packet, GF02, GF03, Runtime, Astrid, and all other work artifacts were outside this continuation's write scope and were not altered.
