# WRK-04 worker result

Status: implementation complete in the isolated WRK-04 worker checkout. This
is bounded source and installed-package evidence; it is not product, Runtime,
Astrid, live-controller, or root acceptance evidence.

## Dispatch and ownership

- Worker checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk04-worker`
- Branch: `wrk-04-worker`
- Exact dispatch base commit/tree: `5a28e1fee1811d77c0a6558311c77525c36ed069` / `640ac1a230d0535bde7ab23d172e2faf76b3f101`
- Owned source: `src/herzchen/domains/assessment/`
- Owned tests: `tests/assessment/test_accounting.py`
- Owned evidence: `work/wrk-04-result.md`
- No `handoffs/WRK.json` was created because this checkout has no existing handoff directory/convention.

## Implementation

The assessment package provides one schema-free `AssessmentModule` (also
exported as `Assessment`/`AssessmentStore`) over the supplied `Store`,
`Transaction`, `LimitService`, and `OperationManager` ports. It provides:

- typed scope records with parent-obligation and criterion revision pins;
- immutable frozen input packets and explicit consumed-reference validation;
- candidate selection as a non-accepting operation;
- per-attempt invocation identities and FND-04 reservations;
- protocol-neutral `PASS`, `REWORK`, and `UNKNOWN` result records with
  protocol result and guidance payloads;
- stable finding identities, subjective/objective closure checks, correction
  links, and the same parent obligation through correction;
- authority-bound decisions with exact candidate/criterion pins, rationale,
  disposition, evidence, and return condition;
- policy-bound evidence-only acceptance and explicit UNKNOWN disposition;
- factual loop-alarm observations without progress inference or automatic
  review-stage creation.

An assessment run is one parent FND command/receipt. Invocation operation
records, reservations, invocation projection, findings, and the parent result
are composed inside its supplied transaction. An injected child failure rolls
back all of them, including operation/limit receipts and events. Routes and
resumes use new explicit attempts against the same cumulative allowance; they
do not reset consumed units. Overrun remains in the reservation ledger.

## Source and test lineage

The only adopted plan lineage is `EX-WORK` in the single extraction map. The
implementation retains its obligation/execution distinction, stable task and
accounting identity vocabulary, and protocol-neutral operation boundary.

Exact accepted-base source lineage used:

| Path | Dispatch-base blob hash |
|---|---|
| `src/herzchen/kernel/limits.py` | `d52b61d3c43dd474855aaffe0697e629c33c7f34` |
| `src/herzchen/kernel/operations.py` | `35a1573d323d6f3eff21ba9f096bfa8b1e8f8166` |
| `src/herzchen/kernel/store.py` | `0c133689d8f20fc24005b1ee5fa531a57f0e7eca` |
| `tests/kernel/test_receipts_limits.py` | `9e53e4c348f64bec3fbbc777cec7183cfc023c60` |
| `tests/conformance/fixtures/candidate_decision.py` | `82061a69384ad4b10f0f285127edb1ca5f61cded` |
| `tests/conformance/fixtures/review_choice.py` | `4bdd552986e09a07e0ae23838120b0671260609c` |

These paths were adapted as source/test lineage, not claimed as installed
origin. The new candidate blobs before this evidence file was added were:

| Path | Candidate blob hash |
|---|---|
| `src/herzchen/domains/assessment/__init__.py` | `21ebbcf7c3cba08d3b69b70b1c2c3d0157ee285b` |
| `src/herzchen/domains/assessment/model.py` | `51f6abacba30265e13ce85d3c49d671dcc979007` |
| `src/herzchen/domains/assessment/module.py` | `0d553722a5d3439a1b1e870c87844027a02966b3` |
| `tests/assessment/test_accounting.py` | `63155081d397c9ba345808545aacea79bc9b42ff` |

## Verification

Interpreter for source checks: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python` (pytest 9.1.1).

- `PYTHONPATH=src ... -m pytest -q tests/assessment/test_accounting.py` — exit `0`; **9 passed**.
- `PYTHONPATH=src ... -m pytest -q` — exit `0`; **186 passed, 80 subtests passed**.
- `... -m py_compile src/herzchen/domains/assessment/*.py tests/assessment/test_accounting.py` — exit `0`.
- `git diff --check` — exit `0`.

Disposable installed candidate:

- Python: `/opt/homebrew/bin/python3.11` (Python 3.11); pytest installed in the disposable environment.
- Wheel: `/tmp/herzchen-wrk04-wheel.mBalqG/herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `426ef0569054d5806dcf35239e7f808d7b7a716b5a39529a920fbed9eacd1904`
- Environment: `/tmp/herzchen-wrk04-candidate.POylZC`
- Command: `env -u PYTHONPATH -u PYTHONHOME /tmp/herzchen-wrk04-candidate.POylZC/bin/python -m pytest -q` — exit `0`; **186 passed, 80 subtests passed**.

Installed origins from that run:

- `herzchen`: `/private/tmp/herzchen-wrk04-candidate.POylZC/lib/python3.11/site-packages/herzchen/__init__.py`
- `herzchen.domains.assessment`: `/private/tmp/herzchen-wrk04-candidate.POylZC/lib/python3.11/site-packages/herzchen/domains/assessment/__init__.py`
- `herzchen.domains.assessment.module`: `/private/tmp/herzchen-wrk04-candidate.POylZC/lib/python3.11/site-packages/herzchen/domains/assessment/module.py`
- `herzchen.kernel.store`: `/private/tmp/herzchen-wrk04-candidate.POylZC/lib/python3.11/site-packages/herzchen/kernel/store.py`

## Criteria covered

- C13: bounded attempts, distinct result states, exact consumed pins,
  UNKNOWN charging, overrun retention, and non-resetting route/resume budget.
- C14: Megado and creative protocol lenses share the same scope/input/
  invocation/result primitives; no automatic second review stage.
- C31: exact candidate/criterion/input pins, consumed-input invalidation,
  irrelevant annotation preservation, and historical decisions.
- C39: persistent parent obligation through REWORK/correction/approval,
  designated authority binding, explicit UNKNOWN disposition, policy-bound
  no-review evidence, and no workflow/predicate graph.

## FND interface assessment

No concrete FND incompatibility was found for the required atomic whole-batch
behavior. The implementation uses the supplied transaction and receipt/event
ports and adds no table, raw-SQL writer, private counter ledger, private event
log, or private receipt path.
