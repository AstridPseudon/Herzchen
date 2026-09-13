# WRK-03 worker result

Status: implementation complete in the isolated worker checkout. This is
source-worktree evidence only; it is not installed integration proof.

## Identity and boundary

- Worker checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk03-worker`
- Branch: `wrk-03-worker`
- Accepted parent commit/tree: `f937ef543bca745e66fadf2d6fdf0922656085f5` / `f3a6fcf5fdebc955c0e77127f2493211df45d948`
- Worker implementation commit/tree: `d225608ff5111f132e3099c7ca1b8437f7aaf730` / `0dcf635c8c0c726e3f1eb4ba3b64fb95ebb6d208`
- DAT-03 installed dependency supplied by INT: `f937ef5` combined base; installed evidence is `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/int-03-dat03-fnd04-integration-result.md`
- Accepted WRK-02 installed identity supplied by INT: `9ba4719c`
- FND-03 source dependency: commit `98430201ff196313df0ac69a701851225c8c31a7`, tree `ddd9eaab56df1b8321443021db8283e4a75910cd`
- Exclusive product paths changed: `src/herzchen/domains/work/assignments.py`, `src/herzchen/domains/work/batches.py`, `tests/work/test_assignments.py`, `tests/work/test_batches.py`, and this receipt. No other tracked product/control path was changed.

## Implementation

`assignments.py` adds one generic responsibility/assignment projection with
role, principal, reporter, physical launcher, agent and session kept distinct;
generation fencing; append-only result/report observations; reassignment
history; and current-input-to-pinned dispatch resolution.

`batches.py` adds parent-key project-sheet application, stable sheet-local task
mappings, task ordering/dependencies/bodies, merged metadata namespaces,
document revisions/links, explicit activation, readiness/report observations,
pending creation with optional authoring reservation, materialisation failure
reconciliation by saved request/project ID, cross-scope linked partial status,
and manager-selected next actions. A sheet uses one parent `mutate()` receipt
and event. Child rows are composed in the same active supplied FND transaction;
they do not receive request keys or receipts. Invalid child state rolls back
the parent, child identities, references and receipt/event together. Existing
single-record revise/link operations remain available through WRK-02 and via
the batch service wrappers.

## FND API and authority

The implementation uses the supplied `Store.transaction()`/savepoints,
`mutate(CommandEnvelope)`, `put_identity`, `get_identity`/`get_record`,
`put_reference`/`get_reference`, `get_receipt`, `append_event`/`list_events`,
and the existing SQLite transaction connection for composing existing child
identity revisions atomically. It adds no SQLite table, schema, private
writer, private replay ledger, second event engine, workflow DSL, Runtime or
Astrid import.

The supplied FND surface has no public multi-identity revision primitive. The
bounded batch composition therefore updates existing child identity rows
through the already-active FND transaction after the single parent `mutate()`;
the Store remains the only persistence owner. This is the one concrete API
hardening gap to revisit if FND later exposes a typed multi-identity compose
operation. No installed proof was produced by this worker.

## Source import provenance

The shared interpreter imported these modules from the worker checkout:

- `herzchen.domains.work.assignments`: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk03-worker/src/herzchen/domains/work/assignments.py`
- `herzchen.domains.work.batches`: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk03-worker/src/herzchen/domains/work/batches.py`
- WRK-02 structural module: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk03-worker/src/herzchen/domains/work/module.py`
- FND Store: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk03-worker/src/herzchen/kernel/store.py`

These are source-test imports using `PYTHONPATH=src`. Installed package
origin, wheel provenance, and consumer integration remain INT/root evidence;
this receipt does not claim them.

## Commands and evidence

Interpreter for all checks: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python` (pytest 9.1.1).

- `PYTHONPATH=src ... -m pytest -q tests/work/test_assignments.py tests/work/test_batches.py tests/work/test_identity_graph.py` — exit `0`; `12 passed in 0.14s`.
- `PYTHONPATH=src ... -m pytest -q` — exit `0`; `113 passed, 70 subtests passed in 0.41s`.
- `... -m py_compile src/herzchen/domains/work/assignments.py src/herzchen/domains/work/batches.py` — exit `0`.
- Source import check for assignments, batches, WRK-02 module and FND Store — exit `0`; all four `__file__` paths were the absolute worker-checkout paths listed above.
- `git diff --check` — exit `0` before the implementation commit.
- Exclusive-path check — exit `0` before receipt creation: only the four owned implementation/test paths were uncommitted; the receipt is the fifth authorized path.

The focused negatives cover stale assignment generation, changed-input replay
conflict, invalid-child rollback with no new identity/event/receipt, explicit
pending activation, no dispatch from readiness, materialisation-open failure
and retry without a duplicate project, concurrent result retention, and
explicit cross-scope partial progress. Positive coverage includes reporter vs
launcher separation, reassignment history, current-versus-pinned dispatch,
existing-record revision, omission retention, task bodies/order/dependencies,
metadata namespaces, document revision/link changes, parent replay, and the
manager-chosen alternative action.
