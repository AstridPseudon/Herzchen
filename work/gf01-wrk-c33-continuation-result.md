# GF01 / WRK admission and C33 continuation result

Status: implementation and source/installed verification complete; final Git commit is blocked solely by the worker sandbox's inability to create the linked-worktree index lock. This is not a gate acceptance or consumer-cutover claim.

## Custody and lineage

- Worker route/session: `gpt-5.6-sol`, high reasoning, GF01 XHARD implementation worker.
- Worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-correction-worker`
- Accepted starting commit: `7298363f70aa4dc39cbe374083275ec377d9b2a5`
- Accepted starting tree: `23e35ba9cd2a618226ac79635b82614200203aff`
- Prior Store integration parent: `b480890086d92c968deeff25fffa6c145828c551`
- Accepted GF02 source lineage: `3950476ede81d03bc746d656634b9df7cd31fc4d`
- Prior replay result SHA-256: `7145c7986b61757b98c3c08bb5febe84c47d9c58ceb6b991349b7815b911b9e4`
- DAT inspection SHA-256: `1af96685a702193fbc0c4bb07b5fb8b98f82b4c844b095114ec1de75a7ba211a`
- Pre-result source/test patch SHA-256: `5361c12e2915d97e768e9fbcd08c6bb8d238c1edd3d79d6b897862ded56a44e6`

The supplied GF01/GF02 baseline and its result history were not rewritten. No control, package-seed, source-manifest, extraction-map, or GF03 branch was edited.

## Public composition and admission result

`src/herzchen/kernel/store.py` adds a sealed `DomainHandler` capability. `Store.register_domain_handler()` atomically persists an exact nonempty sequence of typed `DomainContribution` values and issues the Store-bound capability; `Store.domain_handler()` issues only for descriptors exactly equal to the persisted definitions. Construction is sealed by an internal token, and Store admission additionally verifies capability object issuance, Store identity, and admitted domain identity. A bare owner string, actor-name/prefix equivalence, a handler from another Store, or direct `Store.mutate` against a `handler-required` contribution is rejected before mutation.

`Store._admit_mutation()` evaluates exact persisted `mutation-port:<schema>|<operation>|<resource>|<event>` bindings. There is no wildcard or automatic mutation registration. `ConsumerStore` remains the supported ordinary-consumer surface and exposes no connection, transaction, SQL, identity writer, event writer, or mutation method. Trusted handlers reuse the one Store transaction/identity/reference/receipt/event writer.

The WRK aggregate registration path is `herzchen.domains.work.contributions()` -> `register_work(store)` -> `Store.register_domain_handler(...)`. `WorkGraph.register()` performs this composition; other supported WRK adapters acquire the already-registered aggregate handler. Durable request/event actors remain the supplied authenticated DAT/PKG/EDT/test actors and are not rewritten to `wrk`.

Exact WRK contributions and emitted ports:

- `herzchen.work.structural`, `work.v1`: `work.create/work.created`; `work.revise` with `work.revised`, `work.parent-linked`, `work.dependency-linked`, or `work.state-changed`, for declared structural work kinds.
- `herzchen.work.assignments`, `work.assignment.v1`: assignment create/reassign/dispatch and result/report append ports.
- `herzchen.work.batches`, `work.batch.v1`: project-sheet apply/create, project create/activate, readiness observe, project-report append, amendment link, and authoring reconcile ports.
- `herzchen.work.sheet`, emitted `work.batch.v1`: route-pin/route-pinned against `wrk.assignment`.
- Existing decisions and assessment contributions are handler-capability compatible.

The former duplicate event identity is resolved deliberately: assignment reports retain `work.report.append` / `work.report.appended`; batch project reports use `work.project-report.append` / `work.project-report.appended`. A focused negative proves that registering another descriptor with `work.report.appended` is rejected by unchanged `DomainRegistry` event uniqueness.

Public callers corrected: `WorkGraph`, `ResponsibilityAssignments`, `ProjectBatches`, `ProjectSheet`, `DecisionService`, assessment, content commands, extension commands, managed-pack authoring, DAT handoff, PKG task-template composition, and EDT three-target authoring composition. The finite EDT lifecycle now has its own exact `herzchen.authoring.sessions` descriptor and sealed handler registration. Its replay precheck uses the single `herzchen.contracts.canonical_request_digest`; logical command payload is separated from the persisted managed identity payload so exact finish replay remains idempotent and changed semantics remain conflicts.

The full-suite continuation also adds the real `herzchen.content.packets` descriptor for `dat.context.attention.create` / `dat.context.attention.created`. `ContextPacketService` acquires a combined sealed content/packet handler. Content document writes now present the full logical `{document, revision}` payload to Store replay identity while supplying the derived head row separately as the managed identity payload. Thus reused keys with changed content conflict at Store before the immutable revision row, while exact document-authoring replay uses the same canonical helper and envelope semantics.

## C33 public probe

`tests/conformance/test_int03_public_api_probes.py` no longer registers or mutates a synthetic `probe.*` descriptor. It composes a real `WorkGraph`, registers the WRK aggregate, creates and revises a project through public commands, verifies receipt/event identity, closes and freshly reopens the Store, reads through the public cursor, verifies exact replay, and verifies changed-input rejection. The managed-pack subpath registers its real typed authoring descriptor. Probe-generated tracked evidence was restored to the accepted baseline after each run and is not part of this correction.

## Negative and provenance proof

`tests/kernel/test_public_mutation_admission.py` proves no-delta rejection for an unregistered operation, resource, event, or schema; non-owner spoofing; missing capability; a bare `"wrk"` value; a foreign-Store capability; and an exact-port mismatch. It proves caller-digest replacement and payload/target/operation/actor replay conflicts with unchanged identity/event/receipt/reference/sequence counts. It also proves that a DAT-authenticated actor remains the durable WRK event actor when the valid WRK handler admits the command. Duplicate descriptor and shared event identity registration are rejected.

The DAT handoff and EDT three-target tests exercise foreign authenticated actors through WRK/content/pack handlers. No actor prefix heuristic, owner-string substitution, wildcard Store rule, direct test-only registration, second Store, SQLite writer, DDL, inward optional-domain import, or optional-domain FK was introduced.

## Source proof

Interpreter: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`.

The complete affected suites were run serially (one pytest process at a time) as:

`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 <interpreter> -m pytest -q -rs <suite>`

Exit status for every invocation: `0`. Results:

- `tests/authoring`: 35 passed, 1 intentional skip
- `tests/content`: 31 passed
- `tests/assessment`: 9 passed
- `tests/extensions`: 15 passed
- `tests/work`: 33 passed
- `tests/packs`: 52 passed, 11 intentional skips
- `tests/conformance`: 19 passed, 70 subtests passed
- `tests/kernel/test_public_mutation_admission.py tests/kernel/test_receipts_limits.py`: 24 passed

Total: 218 passed, 70 subtests passed, 12 skipped, 0 failed. The source-only authoring skip is `tests/authoring/test_handoff.py:205`, whose fresh-process proof is intentionally reserved for the disposable installed wheel. The 11 pack skips require unavailable optional Astrid loader/source-setup modules; exact locations and reasons were emitted by `pytest -rs`. `git diff --check` exited `0`.

## Candidate wheel and installed proof

- Build command: `<interpreter> -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/gf01-wrk-full-wheel.Z0Stkd .`
- Build exit: `0`
- Wheel: `herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `9da1a4c4c5fa19130c5fb6a4817e362950a2f687226cf9ecd53277d31879071d`
- Disposable environment: `/tmp/gf01-wrk-full-installed.qOJY4D/venv`
- Install command: `env -u PYTHONPATH -u PYTHONHOME <candidate-python> -m pip install --no-deps <wheel>`
- Install exit: `0`

Origin proof under `python -I`, with `PYTHONPATH` and `PYTHONHOME` unset, resolved all checked modules beneath `/tmp/gf01-wrk-full-installed.qOJY4D/venv/lib/python3.12/site-packages/`: `herzchen`, `herzchen.kernel.store`, `herzchen.domains.work.module`, `herzchen.authoring.sessions`, `herzchen.content.commands`, `herzchen.content.packets`, `herzchen.content.authoring`, `herzchen.domains.assessment.module`, `herzchen.extensions.commands`, and `herzchen.packs.authoring`.

Installed tests used candidate `python -I`; only the verified interpreter's pytest site-packages was appended after candidate site-packages. The same complete affected suites were run separately. Every exit status was `0`: 219 passed, 70 subtests passed, 11 optional-Astrid skips, 0 failed. The installed run executes the fresh-process authoring proof, accounting for its one additional pass. This is installed-origin proof, not a source-checkout import claim.

Build-generated `build/`, `src/herzchen_contracts.egg-info/`, bytecode caches, and probe-generated accepted evidence changes were removed/restored after proof.

## Changed lineage

Source: `src/herzchen/kernel/{store.py,__init__.py}`; `src/herzchen/domains/work/{module.py,__init__.py,assignments.py,batches.py,sheet.py,decisions.py}`; `src/herzchen/domains/assessment/module.py`; `src/herzchen/content/{model.py,commands.py,packets.py,authoring.py}`; `src/herzchen/extensions/{model.py,commands.py}`; `src/herzchen/packs/authoring.py`; `src/herzchen/authoring/{sessions.py,finish.py,idle.py}`.

Tests: `tests/kernel/test_public_mutation_admission.py`; `tests/work/{test_identity_graph.py,test_candidates_decisions_waiting.py,test_wrk06_handoff.py}`; `tests/conformance/{test_dat_handoff.py,test_int03_public_api_probes.py}`; `tests/packs/test_task_templates.py`; `tests/assessment/test_accounting.py`; `tests/content/{test_context_visibility.py,test_document_authoring_contract.py,test_documents.py}`; `tests/authoring/{test_exclusivity.py,test_failure_matrix.py,test_finish.py,test_handoff.py,test_snapshots.py,test_three_targets.py}`.

## Bounded operational obligation

The implementation worktree cannot write the linked-worktree Git metadata at `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen/.git/worktrees/Herzchen-gf01-correction-worker/`. Exact attempted command:

Final attempt: `/usr/bin/git add src tests work/gf01-wrk-c33-continuation-result.md && /usr/bin/git commit -m "Complete typed public admission across affected consumers"`

It exited `128` before staging: `fatal: Unable to create .../index.lock: Operation not permitted`. Therefore no truthful follow-up commit/tree can be reported by this sandbox. A manager holding parent-repository metadata custody must stage the listed paths plus this result, commit once on `gf01-correction-worker`, copy this result to `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-wrk-c33-continuation-result.md`, and record the resulting commit/tree and external result digest. There is no identified source compatibility gap in the requested test matrix.
