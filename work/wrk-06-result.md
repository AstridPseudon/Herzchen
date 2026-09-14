# WRK-06 worker result

State: `worker-candidate`. `acceptance_claimed: false`; `gate_verdict_claimed: false`.

The owned handoff is [handoffs/WRK.json](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk06-pkg-correction-worker/handoffs/WRK.json). The fresh public-API rehearsal is implemented in [tests/work/test_wrk06_handoff.py](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk06-pkg-correction-worker/tests/work/test_wrk06_handoff.py), with the exact observed IDs, revisions, request keys, receipt/event references, counters, restart evidence, and limitations copied into the JSON handoff.

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

## v2 `pkg_correction` / integration supplement

This supplement preserves the preceding WRK-06 evidence and corrects only its
shipped-resource limitation. The old candidate is preserved at commit
`2c6c586b4fada18e9115f5f249b7735dc25fbd48`, tree
`8a28fa21060624dc54302175091b1f1b03af86ab`. The accepted PKG correction base
is `a2ed902e863bb55d8ae1e4155a55dc638e69f744`, tree
`67ebb127151736791a19036c77d2af3dceca5e24`; its implementation is commit
`1735eadcbf0c5a447a7c74e9ab213b225e4e5ed8`, tree
`fc8c13750d8bb1a7c3d1247d86d6233e1818e64d`. The PKG implementation wheel
SHA-256 is `9b30a88a9d38803a88d2bdb3ef44bda6503fd3e27b9c54a54053abc7317fa64f`.

The integration loaded the real bytes of
`packs/megado/templates/delivery.json` (SHA-256
`fcf99881754a155da027b2b1e775260a349376e6ccc9e5edc94ee1cecfa087f`), typed
them with the public `work_template`, and instantiated through
`TemplateEngine` with the supplied FND `Store`/`Transaction` and public DAT
composition. The source resource is
`pack/work_template/megado.delivery_seed@1.1.0`; the fresh owner project is
`work.project/project-563c9c21d45fd84d6712edbb2289@rev-1`; request key is
`megado-import`; parameters are `title=Imported effort`,
`outcome=Implement`, `proof=Demonstrate`.

The unadapted `seed.work` produced these exact local refs:

- `effort` → `work.effort/effort-8ca04c9de8d82631a6737efdf260@rev-1`, parent owner project, title `Imported effort`, outcome `Implement`, status `planning_only`.
- `implement` → `work.task/task-f34c66852415f567ea376278679c@rev-1`, parent `effort`, title `Deliver the specified outcome`, outcome `Implement`, `custom.megado.execution_class=normal`.
- `verify` → `work.task/task-8f1d4bf6b7f2c339008de2b1d2c4@rev-1`, parent `effort`, title `Demonstrate the outcome`, outcome `Demonstrate`, `custom.megado.execution_class=normal`.
- `criterion` → `work.criterion/criterion-b126299fd187ab61ced6c8236786@rev-1`, parent `effort`, title `Required observable behavior`, outcome `Demonstrate`.

The public work fields retain the complete rendered goal payload
`{local_id: goal, title: Bounded goal, content: Implement}` and both original
relation objects. `verify.dependencies` contains the unversioned
`implement` ref; `implement.dependencies` is empty and does not contain
`criterion`. The `requires` and `covers` objects remain inspectable as their
original `{from,to,relation}` payloads; `covers` was not projected into
dependencies.

DAT public readback materialized document identity
`dat.content.document/template-b6d75948c27995aefdb3a6e6d8601920`, initial and
current revision `rev-dd207585a60afdb88e0be275054916b5`, exact content
`Implement`, and association identity
`document-association/link-cc73e449daaeae6ef218558c3ddbfb10`. The association
readback reconstructs as `ReferenceBinding(ref=document identity, mode=current)`
and is active. The six committed public receipts/events are recorded in the
JSON handoff for `effort`, `criterion`, `implement`, `verify`, DAT document
create, and DAT link. A fresh `Store.open(db, expected_domains=...)` read the
same document and association. Replaying `megado-import` after reopen returned
identical work/DAT refs and receipts; identities, references, receipts, events,
and event-sequence counters were unchanged. The import added zero allowance
units, scheduler state, review pools, dispatches, gates, or model invocations.

The existing WRK fake-assessment, all named crash/replay points, creative
subjective rejection/correction, candidate A/B boundary, no-review boundary,
waiting restart/cursor occupancy/no-bypass, and independent second-protocol
cases remain in the same rehearsal. No real model review was added. The
focused PKG real-resource lineage is in
`tests/packs/test_task_templates.py` (23 tests, including
`test_shipped_delivery_seed_work_is_expanded_from_real_resource`, idempotency,
invalid-shape rollback, DAT association rollback, and typed external document
linking), with the full source focused command passing 97 tests. A disposable
Python 3.12 wheel proof used `env -u PYTHONPATH -u PYTHONHOME`; wheel
`/private/tmp/wrk06-pkg-correction-integration.9HusrK/wheel/herzchen_contracts-0.1.0-py3-none-any.whl`
has SHA-256
`e39bdbc8ea1b5b01832e482bd1342f8ee65652a79eb369077443f25e295fdebd`, and
the installed PKG+WRK focused run passed 24 tests. Installed origins were
under `/private/tmp/wrk06-pkg-correction-integration.9HusrK/venv311/lib/python3.12/site-packages/`
for `herzchen`, `herzchen.contracts`, `herzchen.kernel`, `herzchen.content`,
`herzchen.domains.assessment`, `herzchen.domains.work`, and
`herzchen.packs.templates`; these are separate from source-checkout origins
under this worktree's `src/` loaded with `PYTHONPATH=src`.

The known EDT race lineage remains explicit: the prior traceback is retained at
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/wrk-05-edt04-race-traceback-20260914.txt`
(SHA-256 `f96f4067625e20079e74eede66380903f9e0a181f6bb003f850b3a1da44c72bf`);
no EDT file was changed. This remains `state=worker-candidate` with
`acceptance_claimed=false` and `gate_verdict_claimed=false`.

## Custody

Owned paths are only `handoffs/WRK.json`, `work/wrk-06-result.md`, and the narrowly justified `tests/work/test_wrk06_handoff.py`. Final commit/tree and final owned-file hashes are recorded in the JSON handoff after the final commit. This is a worker candidate for manager review, not an acceptance or product verdict.
