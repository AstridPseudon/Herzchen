# DAT-02 worker receipt

## Status

Bounded DAT-02 implementation complete in this worker checkout. The content
domain is wired to the supplied FND-03 Store API and does not claim the final
root-integrated DAT-02 acceptance until the FND-03 working implementation is
committed and released by the manager.

## Frozen inputs and lineage

- Worker baseline: HEAD `5a283db00e8c5943f2080bf019f9483ada8eb821`, tree `261ba0353eb495cb0d82f0b8c2bb9755d70b4ce1`.
- Source manifest: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json` (the requested `/can-x20/local/` path was absent); SHA-256 `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.
- Accepted discovery: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/dat-01-result.md`.
- Package brief/catalog: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/dat-wrk-next-briefs.md`, `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/plan/catalog.json:542-569`, and DAT criteria `C05`/`C34` in `projects/DAT/implementation-criteria.md`.
- Extraction lineage: `plan/extraction-map.json:151-197`, `architecture/SHARED-CONTRACTS.md` document/revision and transaction sections, and DAT-01's Runtime/Astrid references. Runtime test lineage retained conceptually from `tests/test_runtime_domains.py` and `tests/test_shot_candidate_promotion.py`; no Runtime/Astrid files were copied or changed.
- FND-02 contract: sibling `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-worker/src/herzchen/contracts/model.py`, revision `fnd-02.v1.1`, digest `28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264`.

## Concrete FND-03 seam used

The sibling FND-03 worktree supplied:

- `src/herzchen/kernel/schema.py`: admitted composition contains only FND tables; no DAT table or migration was added.
- `src/herzchen/kernel/store.py`: `Store.transaction()`, `Store.mutate(...)`, `Store.put_identity(...)`, and `Store.get_identity(...)`.

At inspection, those FND-03 kernel files were untracked in the sibling
worktree (`git status --short` showed `?? src/herzchen/kernel/` and
`?? tests/kernel/`); sibling HEAD remained `5a283db...`. The integration test
therefore used the actual supplied Store source with an ephemeral database,
while preserving this dependency as a manager/root-release condition.

## Owned implementation

Only the permitted DAT paths were changed:

- `src/herzchen/content/model.py` — stable document identity, independent visibility/access/maintainer/authoring scope, imported/pinned source references, immutable revision payload shape/digest, deterministic per-document revision identities, association identity, and FND domain contribution.
- `src/herzchen/content/commands.py` — envelope builders and FND-03 Store transaction adapter. Document heads, revision identities, and active/unlinked association identities are mutated through the supplied FND transaction; FND emits receipts/events.
- `src/herzchen/content/__init__.py` — public exports.
- `tests/content/test_documents.py` — pure boundary cases plus integration tests against the sibling FND-03 Store.

No private SQLite owner/store, schema migration, event engine, receipt store,
test-only persistence implementation, Runtime/Astrid authority, checkout
materializer, cleanup owner, candidate/decision acceptance path, dispatch, or
readiness inference was added.

## Commands and evidence

```text
PYTHONPATH=src python3 -B -m unittest discover -s tests/content -p 'test_*.py'
Ran 16 tests; OK (5 skipped: FND-03 absent from PYTHONPATH)

HERZCHEN_FND03_SRC=/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-worker/src PYTHONPATH=src python3 -B -m unittest discover -s tests/content -p 'test_*.py'
Ran 16 tests; OK

PYTHONPATH=src python3 -B -m unittest discover -s tests -p 'test_*.py'
Ran 24 tests; OK

python3 -m compileall -q src tests
git diff --check
```

The FND-03 integration tests use fresh `get_identity` reads after each command
and verify these persisted deltas: one document/revision identity; two
project plus five task associations resolving to the same document; unlink
marks only its association inactive while the document, revision and other
links remain readable; append moves current navigation while the pinned old
revision remains unchanged; create replay returns the exact receipt without a
second event; changed-digest replay and stale expected revision produce no
receipt or partial head mutation; and an auxiliary revision-row failure rolls
back the head, event, and receipt. The integrated link scenario ends with
nine FND events (create, seven links, unlink).

## Files and hashes before commit

```text
c7359affab656ea7f5a47fff517d3309d5394adfb619090698fa749202e6e8c2  src/herzchen/content/__init__.py
052b076cd47cc6aaf1420a2fd04a9a4eabf2885685640a1d77c63975e640a778  src/herzchen/content/model.py
de81e6ce7ea4ffeb833fef8451a34bd116d38491c8218eabf8d1c5582047abd4  src/herzchen/content/commands.py
776df86748a47e883e8b9646f413abb5867dd6a27d42e8e314403c0fdbf800e4  tests/content/test_documents.py
```

## Commit

- Implementation commit: `7d7a523ee7f39cdb37380001d3aa5199609f9879`
- Implementation tree: `24f9dfbd5e225eb4fd4651593a06066f3c3b0ce7`
- The final receipt text is a follow-up commit so this receipt does not contain a self-referential commit hash.
- Receipt: `work/dat-02-result.md`
