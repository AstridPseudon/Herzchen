# DAT-05 worker result

## Identity and scope

- Worker checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-dat05-worker`
- Branch: `dat-05-worker`
- Parent checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-int03-dat04-integration`
- Parent commit/tree: `a31cd678d286a93e0cfcf9490c6f8a45acc48f7` / `7dbd0c0d0709dc0127233f6778942ab66a2eabb1`
- Worker baseline commit/tree: `a31cd678d286a93e0cfcf9490c6f8a45acc48f7` / `7dbd0c0d0709dc0127233f6778942ab66a2eabb1`
- The worker changes were committed for handoff after validation. No upstream push, package edit, catalog edit, control-root edit, or product verdict was made.
- Owned-path audit at handoff: only `src/herzchen/content/authoring.py`, `tests/content/test_document_authoring_contract.py`, and `work/dat-05-result.md` are changed/untracked. Generated `__pycache__` directories were removed after verification.

## Source lineage and APIs used

The new handler is local DAT-05 source at `src/herzchen/content/authoring.py`. It composes, without replacing:

- accepted DAT content model/commands/packets and extensions from the DAT-04 parent tree;
- `herzchen.content.commands.ContentCommandHandler` for document, immutable revision, link, and unlink envelopes;
- the supplied FND-03 `herzchen.kernel.store.Store` transaction, `mutate`, `put_identity`, `get_identity`, receipts, events, and fresh reads;
- the accepted EDT `herzchen.authoring.sessions.AuthoringSessionService` for scope resolution, actor/scope exclusivity, capability checks, snapshots, finish claims, recovery, and cleanup.

No SQL/DDL, private SQLite connection, shadow content store, private event engine, second writer, second reservation ledger, product import, prose evaluator, Astrid adapter, or Runtime adapter was added. Direct document apply and project-sheet apply call the same `_apply_parsed` path. Content summaries and exact schema errors are returned through both direct and on-disk front ends.

## Implemented contract

- Private documents with an owning `authoring_scope` resolve to that project scope; shared and standalone documents resolve to their own document scope without a fake project.
- An occupied parent scope masks the direct child checkout while fresh content reads continue. Actor, session, token, fence, base, and canonical-scope checks precede mutation; wrong-scope shared edits are rejected.
- New document, initial immutable revision, and multiple associations run through one outer FND owner transaction. The association rows share one document identity. Unlink emits an FND mutation with document/revision preservation.
- Direct semantic drafts and on-disk finish use the same JSON-only interpreter, schema validator, scope/capability check, and content apply path. No prose is interpreted as code.
- Replay with the same request key and exact payload returns the original receipts without adding rows; changed payload under the key raises the FND replay conflict. Stale base/session/token failures do not mutate content.
- Finish captures raw files into the EDT/FND snapshot path. Valid on-disk content is freshly read through the supplied snapshot API before the host cleanup hook is called. Cleanup/persistence failure leaves the temporary file retryable; durable content and snapshots are not deleted. Malformed drafts retain the exact raw rejected/recovery snapshot and schema error and perform no document/link mutation.
- Pinned revision reads and unrelated execution/materialisation identities are outside the authoring cleanup path and remain readable after cleanup.

## Test evidence — source checkout

All source tests below used the required interpreter:
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`.

1. Focused contract suite:

   `PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m unittest -v tests.content.test_document_authoring_contract`

   Exit `0`; `Ran 8 tests`; `OK`.

   Covers private/shared/standalone scopes and fresh current refs; occupied parent and same-actor conflict; copied token/session and wrong-scope denial with reads continuing; atomic new document/revision/two-link batch; unlink preservation; injected mid-batch rollback with no document/revision/link receipt/event; direct/on-disk validator parity; fresh persistence before cleanup; malformed draft recovery; identical replay and changed-key conflict; stale base; pinned reads; and no private writer/product import.

2. Applicable full source suite:

   `PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests`

   Exit `0`; `132 passed, 70 subtests passed in 0.49s`.

3. Compile check:

   `PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m compileall -q src`

   Exit `0`.

4. Source import check:

   `PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -c 'import herzchen.content.authoring as m; print(m.__file__); print(m.DocumentAuthoringHandler.__name__)'`

   Exit `0`; imported from the worker checkout and printed `DocumentAuthoringHandler`.

## Installed-origin separation and gaps

The same interpreter without `PYTHONPATH` resolves `herzchen` to:
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/lib/python3.12/site-packages/herzchen/__init__.py`, and `find_spec("herzchen.content.authoring")` returned `None`. This is the accepted pre-DAT-05 installed origin. The worker therefore claims source-checkout evidence only; INT/root must build/install the worker composition and establish any installed DAT-05 proof.

The accepted EDT public finish API records an apply/validation exception as a durable recovery-pending snapshot rather than exposing a separate public `REJECTED` transition for handler validation errors. DAT-05 preserves the exact schema error and raw snapshot, leaves files for retry, and performs no partial content mutation; it does not add a second reservation writer to manufacture that state. EDT-04 descriptor-relative races, idle-policy expansion, Astrid/Runtime adapters, and installed integration remain outside this worker.

## Immutable source handoff

- `src/herzchen/content/authoring.py` SHA256: `bb1f9dd8c1019562eb6b0f2cd5ca3fbcf2341703b3e619785cc5625a6038a5e7`
- `tests/content/test_document_authoring_contract.py` SHA256: `de5a2acd7cb67b7fe23f8b57e11985a06a001c7214d4f1972aac06caabf4cd89`
- The manager handoff commit/tree and final receipt SHA256 are recorded in the accountable-manager handoff message because the commit identity necessarily changes when this receipt changes.
