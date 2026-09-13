# DAT-03 worker result — namespaced metadata and extension definitions

## Route and frozen inputs

- Task: `DAT-03`, “Implement namespaced metadata and extension definitions”.
- Requested route/model/reasoning: `normal` / `gpt-5.6 Luna` / `high`.
- Worker branch: `dat-03-worker`.
- Base before this worker: HEAD `6d4c6e67867d61e44190117525072f01b3ca0504`, tree `9773d270e703c3392f823f250b6a37de5863c478`.
- Source manifest: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`.
- Source manifest SHA-256: `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.
- DAT-01 contract: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/contracts/extension-inventory.md`.
- Criteria/catalog source: `work/package/otto_herzchen_delivery_v11_2/projects/DAT/implementation-criteria.md`, `projects/DAT/tasklist.md`, and `catalog.json` DAT-03 entry.

## Source-backed composition and lineage

The implementation uses the accepted in-tree FND/DAT composition.  The
read/write boundary is FND's six-table `Store`; no DAT table, SQL, migration,
private connection, shadow writer, event engine, or product authority was
added.

Consumed source hashes:

```text
src/herzchen/contracts/model.py       968a1c732a3ff50c27a8d219d8461d2660f2dd047c072bb17967bc14192e827c
src/herzchen/kernel/schema.py         bb4932f4a023a4a0c3ea8893ae1185f6347b870e9136c236c0b2c8247b8a32bc
src/herzchen/kernel/store.py          d14b47f37c93e08026af90e8dde87a9ea84f0a187d3c1a79df376bbc6f8d7817
src/herzchen/content/model.py         052b076cd47cc6aaf1420a2fd04a9a4eabf2885685640a1d77c63975e640a778
src/herzchen/content/commands.py      de81e6ce7ea4ffeb833fef8451a34bd116d38491c8218eabf8d1c5582047abd4
```

FND lineage is the read-only accepted source at
`local/repos/Herzchen-fnd03-worker`, commit
`98430201ff196313df0ac69a701851225c8c31a7`, tree
`ddd9eaab56df1b8321443021db8283e4a75910cd`.  DAT-02 is consumed from the
accepted integrated base; its source-level origin is the supplied worker
commit `a8611a9b9b8cd9ad36c2816c4d1cb2e24e8ded97`.  No FND worktree, control
root, Runtime, Astrid, or DAT-02 source was modified.

## Owned implementation

Only the requested DAT-03 paths are owned by this result:

- `src/herzchen/extensions/model.py` — immutable extension definitions,
  document-role definitions, collision-checked catalog, pinned schema refs,
  dependency-free JSON-schema-like validation, and typed DAT contribution.
- `src/herzchen/extensions/commands.py` — canonical FND-backed
  `describe/help`, fresh `read/query`, and CAS/replay-safe `set/remove`.
- `src/herzchen/extensions/__init__.py` — public extension surface.
- `tests/extensions/test_namespaces.py` — eight integration tests against the
  supplied FND `Store`, not a fake store.
- `work/dat-03-result.md` — this receipt.

## Definition and namespace contract

The single `DEFAULT_CATALOG` feeds descriptions/help, editable namespace
shape, schema validation, and supported query fields.  Standard schema refs
are pinned `ResourceRef("herzchen", "dat.extensions.schema", <definition-id>,
"1")` values.

| definition/role | namespace or role | class/meaning |
|---|---|---|
| `dat.extensions.annotation.open.v1` | `annotation.open` | Open annotation; arbitrary JSON field values are retained and cannot grant authority. |
| `dat.extensions.protocol.choice.v1` | `protocol.choice` | Owner-declared choice with `accept/reject/hold` schema; writes require owner `dat.protocol-owner`. |
| `dat.extensions.managed.state.v1` | `managed.state` | Read-only managed identity/ownership/version/archive/promotion/provenance/receipt/event/head/acceptance boundary. |
| `candidate-manifest` | typed document role | Candidate inputs/outputs/criteria/provenance descriptor. |
| `decision-manifest` | typed document role | Subject/authority/criteria/evidence/disposition/rationale/reconsideration descriptor. |

Metadata is stored as the one canonical FND identity payload member
`payload["metadata"][namespace]`.  A set reads the fresh identity, merges only
the named namespace, and sends the preserved complete payload through FND
`mutate` with both expected version and expected revision.  Remove only drops
the named open namespace or requested open fields.  Unknown sibling namespaces
and every unrelated managed payload member survive.

Annotation writes reject protected identity, ownership, version, archive,
promotion/primary, provenance, acceptance, permission, receipt, event, and
head-like field names.  Managed namespace writes and protocol writes without
the registered owner are rejected before the writer.  Protocol values are
validated after the namespace merge, so strict misspellings reject without a
delta.  Read/query/describe/help are explicit read-only operations.

## Exact FND interface and incompatibility

The service uses the supplied FND interface as follows:

- `registered_domains()` and `register_domain(DomainContribution)` admit the
  typed `dat.extensions` contribution.
- `transaction()` scopes one FND-owned transaction.
- `get_identity(ResourceRef)` supplies every fresh read and the pre-CAS
  current payload/version/revision.
- `mutate(CommandEnvelope, event_type, result_ref, before_refs, after_refs,
  effects, no_op, transaction)` performs the one state delta, durable receipt,
  and common event.  `put_identity(...)` is used only by the real FND fixture
  setup to admit a subject identity; the extension service does not bypass
  `mutate` for public state changes.
- `list_events()` is used by the integration assertions for event/no-event
  evidence.

Narrow FND incompatibility: `mutate` accepts a complete identity payload, not
a namespace delta, and `get_identity` exposes the current identity row rather
than historical payload versions.  DAT-03 handles this without private
persistence: it performs a fresh read/merge and relies on FND expected
version/revision CAS; current pinned reads reject a non-current pin, while a
stale pinned write reaches FND and fails its CAS.  No last-writer-wins or
historical shadow mechanism was added.

The contribution is `dat.extensions` version `1`, schema revision
`dat.extensions.v1`, with resource `dat.extensions.metadata`, document role
types `dat.extensions.candidate-manifest` and
`dat.extensions.decision-manifest`, the three namespaces above, the five
declared operations, and changed/removed event types.  Its composition binds
to `fnd-03.six-table-composition` and `dat.content.document-roles`.

## Verification evidence

Exact required focused command:

```text
PYTHONPATH="/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-dat03-worker/src:/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-worker/src" /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/extensions/test_namespaces.py
8 passed in 0.07s
```

Additional verification:

```text
PYTHONPATH="/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-dat03-worker/src:/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd03-worker/src" /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests
93 passed, 70 subtests passed in 0.27s

python3 -m compileall -q src
exit 0

git diff --check
exit 0
```

Observed negative and replay evidence from the focused suite:

- unknown protocol field `choic` raises `SchemaValidationError`; the FND
  identity and event count are unchanged;
- managed namespace and annotation attempts for `identity`, `version`,
  `primary`, `provenance`, and `acceptance` raise `ManagedFieldError` with no
  state/event delta;
- protocol owner `caller` raises `OwnerRequiredError`, while the registered
  owner succeeds only with the declared choice schema;
- same logical key and digest returns the exact prior FND receipt with no new
  event; changed digest raises `ReplayConflictError` with no delta;
- stale expected version/revision raises FND `VersionConflictError` with no
  partial payload or event delta;
- after close/open, a fresh read returns the persisted namespace and identical
  schema reference; a non-current pinned read is rejected.

## Installed-origin status

This is source/test evidence only.  No wheel, package installation, or
integrated installed artifact was observed in this worker, so this result does
not claim installed origin, product acceptance, Astrid integration, or final
INT proof.  Root/INT owns final installed proof.

## Result hashes

Implementation/test hashes before commit:

```text
src/herzchen/extensions/model.py       c5c2838a6078b4f1dd677298c120687b1f1ed5297e48cb406883a1de77b5c929
src/herzchen/extensions/commands.py    fe7eb35576c458ceef97c88e6fa2bcc54761f751ad1da9dd6e8fb89b188c4207
src/herzchen/extensions/__init__.py    ff85d3dee6d08cfe27ee4e94051d62cf595077affc29778c73523525393657ab
tests/extensions/test_namespaces.py     52a9f0bcb4d9082549809f3387f551926105a679362f593e150356eec7ff2559
```

The final commit/tree and receipt SHA-256 are recorded below after commit.
