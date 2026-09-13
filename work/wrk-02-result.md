# WRK-02 worker receipt

## Outcome and custody

- Task: `WRK-02`, normal route, configured worker `worker_normal` = GPT-5.6 Luna, high reasoning.
- Correction version: `WRK-02-correction-1` (2026-09-14): default-actor provenance fallback and structural-only scope correction.
- Exclusive source writes: `src/herzchen/domains/work/`, `tests/work/test_identity_graph.py`, and this receipt only.
- Worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk02-worker`.
- Base before mutation: `5a283db00e8c5943f2080bf019f9483ada8eb821`, tree `261ba0353eb495cb0d82f0b8c2bb9755d70b4ce1`.
- Source manifest: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`, SHA-256 `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.
- Corrected FND-02 baseline consumed: `fnd-02.v1.1`, digest `28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264` as declared by the supplied FND-03 writer.
- Supplied FND-03 source read-only: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-worker`, commit `98430201ff196313df0ac69a701851225c8c31a7`, tree `ddd9eaab56df1b8321443021db8283e4a75910cd`.
- FND-03 source was not edited. Astrid, Runtime, package/control roots, DAT, EDT, FND contracts/kernel, and task/criteria files were not edited.

## Implemented contribution

`herzchen.work` version `1.0`, owner `wrk`, schema `work.v1`.

- Resource types: `work.project`, `work.effort`, `work.task`, `work.criterion`, `work.scenario`, `work.gate`.
- Document types: none. Full project-sheet parsing/admission is deferred to WRK-03.
- Namespaces: `work`, `work.metadata`.
- Operations: `work.create`, `work.revise`, `work.link-parent`, `work.link-dependency`, `work.withdraw`, `work.state-view`.
- Events: `work.created`, `work.revised`, `work.parent-linked`, `work.dependency-linked`, `work.withdrawn`, `work.state-changed`.
- Composition bindings: `fnd-03.identities`, `fnd-03.record_references`, `fnd-03.transaction`.
- FND identities used: one `ResourceRef(authority=store.authority, kind=work.<kind>, id=<immutable-id>, revision=<FND revision>)` per project/effort/task/criterion/scenario/gate; structural parent/dependency/project references are retained as unpinned references in each payload. Domain registration uses FND `DomainContribution` and its descriptor identity.
- No WRK SQL tables, migration, store, event engine, command-receipt owner, model/runtime import, or per-project reuse ledger was added.

## Behaviour delivered

- Stable immutable IDs are derived from the logical request key when supplied and otherwise from a generated request key; title/name changes preserve IDs and retained aliases.
- Direct create/revise/link-parent/link-dependency/withdraw/state-view handlers share one graph validator. Hierarchy and dependency cycles are rejected before mutation or rolled back by the outer supplied FND transaction.
- Projects, efforts, tasks, criteria, scenarios, and gates remain separate records. Runtime execution jobs, retries, provider actions, candidates, decisions, assessment accounting, readiness dispatch, and authoring checkout/materialisation/cleanup are not represented as work records.
- Pending creation defaults to `Untitled project`, empty outcome, zero tasks, lifecycle `pending`, and no protocol/manager/gate/budget/worker/execution/external action. Creator/curator provenance is retained.
- When `WorkGraph` is constructed with an `AuthenticatedActor`, pending project creation uses that default actor for omitted creator and curator provenance; an explicit per-call actor still takes precedence.
- Lifecycle and readiness are separate payload fields. Readiness observations force `dispatch: false`; a satisfied observation never activates or dispatches work.
- WRK-02 exposes only structural single-record create/revise/link/withdraw/readiness/read commands. Omitted fields in a single-record revise remain retained, and WRK-02 has no delete-by-omission behavior.
- Same logical key/exact digest replays through FND's receipt table; same key/changed digest raises FND `ReplayConflictError`. Failed graph validation leaves the FND event/identity counts unchanged.

## Source/test lineage and reuse

- Actual Megado source read at `/Users/hannahomalley/Documents/Codex/2026-09-10/have-a-setup-worker-clone-this/work/poms-skills-handover-20260910/megado/SKILL.md`, source commit `d849898cd0c191cffc5ababbb5ea7d2c188e8ed0`, tree `9644eb21632a98a51af7051ceeb294f851a7c70f`; used for record/authority/transaction semantics only, not a scheduler or kernel.
- WRK alignment read at `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/history/megado_herzchen_alignment.md`, SHA-256 `6581c6d24fcfdae709e1a7ea16ad4e6e8f8892ca753f39dd1b3be5b3a1e0349f`; retained the project/effort/work-item versus assignment/execution distinction and six-concern projection boundary.
- Blank-project contract read at `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/architecture/BLANK-PROJECT.md`, SHA-256 `8ff0f18e3e69ee529518ffacab955b605514269ba873152502305255a5fa7008`; retained sparse pending creation/retention and left checkout ownership to EDT.
- Parked brief SHA-256 `c45b4ac0c51f541c71eee544bc438c15c17a8467c56ced682cc38ef48eb544ee`; accepted WRK-01 result SHA-256 `6ab8eb68349231e88986eac1c3f0d0c2a6f2b199f134a2b7c7f140b495998256`.
- New code is justified by WRK-01 EX-WORK evidence: no inspected source supplied high-level work identity/alias/parent/dependency graph semantics; existing Runtime task/run/retry records were retained as execution-job authority and not relabelled.
- Focused test lineage is `tests/work/test_identity_graph.py`, SHA-256 at correction capture `ac53295cd12a82d42efc6a60344bca3a92538848fc39d28e06402fecd6b9693f`.

## Correction validation evidence

Commands:

1. `PYTHONPATH="/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-wrk02-worker/src:/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-worker/src" /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/work/test_identity_graph.py` — passed, `6 passed in 0.08s`.
2. `python3 -m compileall -q src` — passed (exit code 0).
3. `git diff --check` — passed (exit code 0).

Observed fresh-read deltas from the harness:

- Domain registration persisted the one typed `herzchen.work` descriptor through FND's domain registry; no product table was added.
- Blank creation persisted one project identity, one `work.created` receipt/event, the default title, empty outcome, zero tasks, and sparse pending fields before any edit.
- Effort/task/criterion creation persisted separate identities and unpinned parent/project references. A title edit produced a new FND revision while retaining the original ID and aliases; omitted fields remained readable.
- Valid parent and dependency linking each produced a separate FND mutation/event. A proposed dependency cycle and hierarchy cycle raised `GraphCycleError`; fresh event count and target payloads were unchanged.
- Reopening required the supplied FND admission expectation `Store.open(..., expected_domains=(contribution(),))`; the fresh graph read retained the pending/project records. This is FND admission behavior, not a WRK-owned workaround.
- Same-key exact replay returned the same project identity and did not add an event. Same-key changed-input replay raised FND `ReplayConflictError` without mutation.
- Readiness became an observation with `dispatch: false` while lifecycle remained `pending`; withdrawal changed lifecycle only.

Source-only import lineage:

- `herzchen.domains.work`: this WRK worktree `src/herzchen/domains/work/__init__.py`.
- The focused test imports the WRK `herzchen` namespace first, appends only `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-worker/src/herzchen` to `herzchen.__path__`, then resolves `herzchen.contracts` and `herzchen.kernel` from the supplied FND-03 source.
- No `runtime`, `astrid`, model, scheduler, or product package is imported by the work module; source audit found no `sqlite3`, `CREATE TABLE`, or competing writer.
- This is source-only lineage; no installed-wheel proof is claimed.

## Boundaries, missing neutral API, and blocked proof

- The supplied FND port has no high-level neutral `atomic_graph_mutate` convenience operation. WRK composes per-identity FND `mutate` calls, references, and receipt/events inside one supplied transaction/savepoint. This is the only missing neutral convenience API identified; no substitute store was created.
- WRK-03 deferral: full project-sheet parsing/admission and multi-record semantic batch materialization are out of scope for WRK-02. No multi-record graph command, hidden child request keys, parser, or batch workaround is shipped here. Each individual WRK-02 structural command performs one FND mutation/receipt within the supplied outer transaction; any future logical batch must respect the FND boundary instead of being simulated by WRK.
- The six-table FND composition remains the sole persistence composition: `store_metadata`, `identities`, `record_references`, `event_sequences`, `command_receipts`, and `events`. WRK adds no private store or schema.
- The supplied FND restart API requires the caller to provide the expected registered domain descriptor set/digest. The work module exposes `contribution()` for that admission input; it does not bypass FND admission.
- EDT-owned checkout materialisation, autosave, idle/manual finish, temporary-file cleanup, and partial file-open recovery remain unexecuted cross-owner proof. No dummy checkout, file deletion, dispatch, Git operation, deployment, candidate/decision/assessment, or readiness dispatcher was implemented.
- Persisted acceptance remains conditional on root release/integration of the supplied FND-03 candidate, per the parked brief. This worker receipt is implementation evidence, not root acceptance or product certification.

## Implementation source identity

- Pre-correction implementation commit: `c1dc2c9d4603ce4450202685c15ee90abfaa4d29`.
- Correction source/test/receipt commit and final tree are reported in the worker handoff below after validation.
- The receipt is an owned handoff artifact in the same worker branch; the final branch HEAD/tree are reported in the worker handoff below.
- No installed-wheel proof or root/product acceptance is claimed.
