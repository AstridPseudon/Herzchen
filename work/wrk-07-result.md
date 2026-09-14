# WRK-07 worker result

## Outcome

Implemented candidate-bound decisions and actionable waiting in the two owned product paths:

- \`src/herzchen/domains/work/decisions.py\`
- \`tests/work/test_candidates_decisions_waiting.py\`

The module is optional and uses the supplied FND Store/transaction/mutate/receipt/event/reference APIs. It has no private database, SQL writer, allowance ledger, scheduler, review pool, or workflow predicate evaluator.

The contribution is \`herzchen.work.decisions\`, schema \`work.decisions.v1\`. It registers typed candidate, candidate-annotation, decision, wait, and manager-choice resource payloads plus their operations/events.

## Behavior delivered

- Candidate A/B identities are separate, and each candidate retains a frozen \`CandidatePin\` of exact artifact, source, spec, criteria, and consumed-input \`ResourceRef\` revisions.
- Candidate descriptions/reads are immutable projections; annotation is a separate annotation identity and does not revise the candidate pin.
- Applicability compares only the candidate pin boundary. Changed artifact/source/spec/criterion/consumed references report affected stale refs; unrelated annotations are ignored. The semantic effect/judgment remains caller-supplied typed data.
- Decisions persist subject, exact candidate ref/pin, criterion revision, evidence refs/basis, author, authority, rationale, arbitrary typed disposition, completion contract, required decision refs, assessment result ref, and return condition.
- Unknown/unsupported disposition vocabulary is retained as data. No review-required state is inferred from a template/protocol name.
- When an accepted WRK-04 assessment object is supplied, approval checks the assessment’s parent, exact candidate, exact criterion, PASS verdict, designated approver, and designated authority. Required approval additionally requires evidence basis, return condition, and current applicability.
- Decisions never set parent acceptance/closure. Invocation success and decision recording remain distinct from obligation acceptance.
- Waiting records the real missing obligation, owner/owner ref, exact awaited pin, current awaited revision, revisit condition, required decision at a cap, residual-risk and verification context, and the FND receipt event identity. Payloads explicitly carry no allowance, reservation, launch, dispatch, or next-task authority.
- Attention recovery wraps the supplied FND-05 \`EventCursorReader\` and \`EventCursor\`; duplicate, reordered, and gap observations remain attention-only and never dispatch or mark work ready.
- Timer advancement wraps the supplied \`IntervalController\`; it does not create a budget/reservation or choose a task.
- Explicit manager choice is a typed, receipted operation with available actions, residual-risk/verification context, and \`automatic_dispatch=False\`; result/metadata/timer/wait alone never choose it.
- Cap waits require the real unresolved decision reference and reject an equivalent renamed review.
- State-changing operations use one FND mutate/receipt/event boundary and rollback cleanly on injected failure.

## Source and test lineage

Dispatch base was exact HEAD \`bceac6ab24977a8d44bd87334e93a8ac0ad094b3\`, tree \`73ecbe3cd4e5dace879208e1215268c26b1ea019\`. The accepted WRK-04 assessment lineage is commit \`bb25ec35d3fd17fe1c63ec623e75d68e9f410a78\`; the accepted common base before that was \`5617d8b7aae1e5dd6ac2b270489b4ad1cbd324fa\`.

Narrow source reuse/inspection was taken from the accepted common interfaces:

| Path | git blob hash |
|---|---|
| \`src/herzchen/domains/assessment/module.py\` | \`0d553722a5d3439a1b1e870c87844027a02966b3\` |
| \`src/herzchen/domains/assessment/model.py\` | \`51f6abacba30265e13ce85d3c49d671dcc979007\` |
| \`src/herzchen/domains/work/assignments.py\` | \`b7bdeb9f328d651284a65ff6e421afd0a3909a19\` |
| \`src/herzchen/domains/work/batches.py\` | \`52a1f3c5d3a91e8287c311f8d55ab9a2434242ed\` |
| \`src/herzchen/kernel/recovery.py\` | \`5cdda99caf2c70e364e9f7e803dc4a41116e66a4\` |
| \`src/herzchen/kernel/store.py\` | \`0c133689d8f20fc24005b1ee5fa531a57f0e7eca\` |
| \`src/herzchen/content/commands.py\` | \`0438b817e939807795958fdd686cf742f40e981c\` |
| \`src/herzchen/content/model.py\` | \`e148e0da0c6829f500ed6ebdcc3727a3121c1817\` |

Retained/adapted fixture lineage:

| Path | git blob hash |
|---|---|
| \`tests/conformance/fixtures/candidate_decision.py\` | \`82061a69384ad4b10f0f285127edb1ca5f61cded\` |
| \`tests/conformance/fixtures/manager_choice.py\` | \`0ce4a6c65a6c3a971f0af80751aa4a7ca536ae01\` |
| \`tests/conformance/fixtures/attention.py\` | \`25d78943fce287823779c67e37032ed1b5a61746\` |

The only catalog reuse entry used was \`EX-WORK\` in \`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/plan/extraction-map.json\` (file SHA-256 \`c08d94ea32f394596578a3c908e35dc037c1297194d3d5994945a88093101c59\`). Catalog SHA-256: \`075f0301129f57e46003d518372747df4a68e6e086e5a63a1200ae333b53b013\`.

## Verification

All source checks used \`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python\` with \`PYTHONPATH=src\` only for checkout imports.

- \`PYTHONPATH=src ... -m py_compile src/herzchen/domains/work/decisions.py\` — exit 0.
- \`PYTHONPATH=src ... -m pytest -q tests/work/test_candidates_decisions_waiting.py\` — **8 passed**, exit 0.
- \`PYTHONPATH=src ... -m pytest -q tests/work tests/assessment tests/conformance\` — **49 passed, 70 subtests**, exit 0.
- Final disposable wheel was built with \`/opt/homebrew/bin/python3.11\`, installed into \`/tmp/herzchen-wrk07-final.8EyJKV/venv\`, and tested with \`env -u PYTHONPATH -u PYTHONHOME\`.
- Installed command: \`env -u PYTHONPATH -u PYTHONHOME /tmp/herzchen-wrk07-final.8EyJKV/venv/bin/python -m pytest -q tests/work/test_candidates_decisions_waiting.py\` — **8 passed**, exit 0.
- The first disposable probe was intentionally corrected after it revealed the probe had omitted wheel installation; the final proof above installs the exact built wheel before import/test checks.

Installed wheel:

- Path: \`/tmp/herzchen-wrk07-final.8EyJKV/herzchen_contracts-0.1.0-py3-none-any.whl\`
- SHA-256: \`df6959a8068d5c54c8237f975c398d87335bba49f58f927cf1d12878433fbb7c\`

Installed module origins, with both \`PYTHONPATH\` and \`PYTHONHOME\` unset:

- \`herzchen\`: \`/private/tmp/herzchen-wrk07-final.8EyJKV/venv/lib/python3.11/site-packages/herzchen/__init__.py\`
- \`herzchen.domains.work.decisions\`: \`/private/tmp/herzchen-wrk07-final.8EyJKV/venv/lib/python3.11/site-packages/herzchen/domains/work/decisions.py\`
- \`herzchen.domains.assessment\`: \`/private/tmp/herzchen-wrk07-final.8EyJKV/venv/lib/python3.11/site-packages/herzchen/domains/assessment/__init__.py\`
- \`herzchen.kernel.store\`: \`/private/tmp/herzchen-wrk07-final.8EyJKV/venv/lib/python3.11/site-packages/herzchen/kernel/store.py\`

## Handoff state

Owned file hashes before commit:

- \`src/herzchen/domains/work/decisions.py\`: \`9aeeb8a6e4a7f692b3e9a2d2317696431ca874a618cae5ec889dab39d14e42a8\`
- \`tests/work/test_candidates_decisions_waiting.py\`: \`3aa92aa3cf2f14d5b825644d593850ff8742762a8094dbc92a1a16843c0b0150\`

No product/runtime/Astrid/live-controller verdict is made here. No upstream merge, push, budget grant, new review/oracle pool, or automatic dispatch was performed.
