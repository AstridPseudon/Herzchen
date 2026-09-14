# WRK-06 worker result

State: `worker-candidate`. `acceptance_claimed: false`; `gate_verdict_claimed: false`.

The owned handoff is [handoffs/WRK.json](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk06-worker/handoffs/WRK.json). The fresh public-API rehearsal is implemented in [tests/work/test_wrk06_handoff.py](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk06-worker/tests/work/test_wrk06_handoff.py), with the exact observed IDs, revisions, request keys, receipt/event references, counters, restart evidence, and limitations copied into the JSON handoff.

## Evidence summary

- Local fake-reviewer Megado path: `megado-scope@rev-1`, `packet-megado@rev-1`, candidate A/B at `rev-1`, selection `selection-A@rev-1`, result `assessment-A@rev-1`, invocation `assessment-A`, operation `assessment-A-invocation@rev-2`, reservation `assessment-A-reservation`, and decision `accept-A@rev-1`. Declared/actual/charged units were `2/1/1`; invocation was `committed`, verdict `PASS`, and `AssessmentResult.accepted` remained false. Same-key replay, `assess_candidate`, and `resume` returned the same result with zero duplicate event/charge.
- Atomic crash/replay: `after-invocation`, `after-finding`, and `after-parent` all reopened the same SQLite file after injection. Before and after-failure identity/receipt/event/pool counters were equal; the same logical key then committed one result, one receipt/event boundary, and one settlement. Retry assessment sequences were 6, 7, and 8 respectively.
- Creative rejection: `scene-scope@rev-1` produced `creative-rework@rev-1` with subjective `creative-rework-finding-0` and `REWORK`; `creative-correction@rev-1` retained parent `work.task/task-55b2efe480703d0fe5dd39c19e22@rev-1`. Test-only closure was rejected as `AssessmentAuthorityError`, with no receipt/event mutation.
- Candidate boundary: mismatched `candidate-B` against A's result was rejected as `StaleCandidateError` with zero receipt/event delta. The irrelevant candidate annotation stayed applicable; consumed `fixture.source/source` changed `rev-1 -> rev-2` and only applicability became stale. Historical A decision `accept-A` remained readable.
- No-review boundary: the permissive scope produced `accept-without-review@rev-1` with `no_review=true`, one decision receipt/event, and no allowance usage. The review-required scope rejected the same path as `AssessmentAuthorityError` with zero receipt/event delta.
- Waiting/restart: `wait-1@rev-1` owned by `assignment-3000e80255bf5275f3f3bb5298d1@rev-1` awaited `wait-decision@rev-1`; attention event sequence 1 was reread after close/reopen. Cursor page 2 delivered sequence 2; duplicate and reordered observations caused no work-ready state or dispatch. The renamed-review bypass raised `WaitingError` with zero receipt/event delta.
- Megado data boundary: the direct shipped `delivery.json` shape is not consumable by the baseline `TemplateEngine` because it uses `seed.work` plus separate links; direct instantiation created no child records. A clearly labeled baseline-adapted typed import produced stable local aliases `effort`, `criterion`, `implement`, and `verify`, with project/effort/task/criterion IDs recorded in the JSON. Replaying its request key left identities, receipts, events, references, pool usage, and IDs unchanged. No gate, scheduler, manager, review pool, hidden allowance, or model review was created.
- Independent second protocol: `pack/work_protocol/scene.production@1` has role slots `creator/editor/critic` and no routes. It independently revised `work.project/project-7a410df011318a36d4aafa724712@rev-2` and remained separate from the Megado import.

No green operation was treated as closing a subjective/unknown finding or as a product verdict.

## Source and test lineage

The immutable baseline was commit `6efdda1cb73fd4ca3438fd83189a69eb40d42c2b`, tree `34f7df82876d6bfa52554c1085a6bd597f25d75a`. The canonical extraction map is `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/plan/extraction-map.json` (`55da00d1d99ff60426f66b555c5728c8cd4f57641dbabe247ad115adf1787db6`), and the immutable historical seed map is `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/plan/extraction-map.json` (`c08d94ea32f394596578a3c908e35dc037c1297194d3d5994945a88093101c59`). The source manifest is `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json` (`742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`).

Exact accepted source/test paths were inspected from this worktree (blob IDs are in `handoffs/WRK.json`):

`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk06-worker/src/herzchen/domains/assessment/module.py`, `model.py`; `src/herzchen/domains/work/module.py`, `batches.py`, `assignments.py`, `decisions.py`, `sheet.py`, `model.py`; `src/herzchen/packs/templates.py`, `composition.py`; Megado and scene pack manifests/protocols/templates; and the required assessment, work, pack, conformance, and applicable kernel tests. WRK-05 sheet APIs were reused; no parallel sheet/store was created.

Dependencies consumed read-only were the local FND, DAT, and PKG handoffs recorded with hashes in `handoffs/WRK.json`. Runtime/Astrid remain source-checkout lineage only; no installed-origin or live-cutover claim is made.

## Verification

Source checkout used `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python` with `PYTHONPATH=src`. The bounded focused command in the JSON handoff passed **82 tests**. The new regression test hash is `b5bd5c1a2375246810f44efecdb6c7a493281eb9924be639a97624b7666227ab`.

The disposable Python 3.11 candidate was `/tmp/wrk06-candidate.ksQiaP/venv311`; installed proof ran with `env -u PYTHONPATH -u PYTHONHOME`, using wheel SHA-256 `bcceec60013c77c549227e20198fc84ef8593a085e6d001fdcf09a54b40fda44`, and passed the same **82 tests**. Installed origins were under `/private/tmp/wrk06-candidate.ksQiaP/venv311/lib/python3.11/site-packages/` for `herzchen`, `herzchen.contracts`, `herzchen.kernel`, `herzchen.domains.assessment`, `herzchen.domains.work`, and `herzchen.packs.templates`; they are distinct from checkout origins.

The EDT-04 target was rechecked once and passed in that single run (`1 passed in 0.07s`). The prior race output remains an explicit foundation blocker at `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/wrk-05-edt04-race-traceback-20260914.txt`, SHA-256 `f96f4067625e20079e74eede66380903f9e0a181f6bb003f850b3a1da44c72bf`; no EDT file was changed.

## Custody

Owned paths are only `handoffs/WRK.json`, `work/wrk-06-result.md`, and the narrowly justified `tests/work/test_wrk06_handoff.py`. Final commit/tree and final owned-file hashes are recorded in the JSON handoff after the final commit. This is a worker candidate for manager review, not an acceptance or product verdict.
