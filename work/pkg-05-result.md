# PKG-05 worker result

This is a worker implementation report. It does not claim PKG-05 acceptance,
publication, INT-03 completion, or a gate verdict. Root/manager validation and
acceptance remain outstanding.

## Fresh launch and custody receipt

- Requested and observed route: `worker_normal / gpt-5.6-luna / high`
- Launcher: `/Users/hannahomalley/.local/bin/codex`, observed `codex-cli 0.150.1`
- Worker session/thread: `01a09d21-f42c-7a63-9b94-1ac1411e89c4` / `01a09d21-f42c-7a63-9b94-1ac1411e89c4`
- Local shell receipt: PID `82590`, captured `2026-09-13T23:49:34Z`
- Separate launcher JSONL path: not exposed by this API worker; native tool receipts are the output reference.
- No silent model substitution, new provider credential, remote, upstream, Otto path, control DB, shared extraction map, or read-only source checkout was written.

The authorized integrated base was rechecked clean before work:

- Base commit/tree: `e9f91f196d5130965069c6110e3f2d60098c3952` /
  `a735253153056ae80b755005b64ee78d4322f275`
- Worker branch: `pkg-05-worker`
- PKG-04 dependency commit/tree: `62503c6bf1e08e6399ed97bc4ee5aab7d3f3d96e` /
  `e6dc75c4d2c0bf9a54dae1048224f69186604de3`
- Candidate implementation commit/tree: `19f3d632454aad353fb11ed77364ab2915bd42f1` /
  `83b978fbf39ad442affd94ce4e379efb2184f370`
- The result-report commit is a later named-path report commit; the candidate
  implementation identity above is the exact source candidate handed to the manager.

## Delivered boundary

Owned paths only:

- `src/herzchen/packs/authoring.py`
- `tests/packs/test_authoring.py`
- `handoffs/PKG.json`
- `work/pkg-05-result.md`

The public reader lazily imports Astrid's supported
`astrid.core.pack.discovery.discover_canonical_pack_metadata` and
`astrid.core.pack.loader.load_pack_manifest` APIs. It selects exactly one
`source_kind="managed"` record, requires its explicit manifest-ID binding and
manifest/tree/inventory provenance, then reads resource handles and SHA-256
digests from the admitted canonical entry. It does not use a construction-only
expected-ID shortcut.

The authoring handler uses the supplied `herzchen.kernel.Store` and
`Store.mutate(..., transaction=...)` boundary. It stores content bytes as
base64 snapshots, retains unknown sibling resources, emits content-only event
effects, and resolves old pinned revisions from those retained snapshots while
fresh reads return the current adopted revision. It does not create a private
SQLite connection, table, schema, DDL path, event engine, queue, subprocess,
provider/model invocation, dependency install, permission grant, or execution
state transition.

Execution pins/profile descriptions are separate from resource content. The
Megado description exposes finite `normal` and `xhard` choices, one compulsory
stage, no counter reset, and the independent `LATER-01` new-specialist recipe.
The blank work starter remains schema-v2, resource-only, sparse, and independent
of Megado.

## Contract and source lineage

- Refreshed source manifest:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`
- Source manifest SHA-256:
  `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`
- Astrid read-only source: commit `96e5664237eb35adeb4cad08bddd8cd6df0a2ae1`,
  tree `19f7539a266618a797559eedbda48e2752b30fa3`
- Runtime read-only source: commit `afccb430e2a983c968b6a8a96fd630ba3a6262fc`,
  tree `be89db2f02231aeef212bdb266d12c51778f32ae`
- poms-skills read-only source: commit `d849898cd0c191cffc5ababbb5ea7d2c188e8ed0`,
  tree `9644eb21632a98a51af7051ceeb294f851a7c70f`
- Shared extraction row: `EX-PACKS` in
  `work/package/otto_herzchen_delivery_v11_2/plan/extraction-map.json`
- FND contract: `fnd-02.v1.1`, digest
  `28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264`
- FND schema: `fnd-03.v1`, fingerprint
  `367b22e1a345e13539ce6cef0d302d507bebe36e73cda68010c4f037e8c1ca5c`
- Authoring contract revision: `pkg-05.managed-pack.v1`

The accepted PKG-04 managed-source mapping is preserved: `megado`,
`scene-production -> scene_production`, and `work-starters -> work_starters`
are bound by explicit managed inventory records. The observed fixture source
tree digest is `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
with inventory identity
`21f6272fb3b4303c51d386f0e726c7c605841549b8750367376a0d6088973cbf`. This is
recorded as the source-setup subpath fixture's observed field, not promoted to
a standalone repository-tree claim. An unbound extra-root scan still does not
discover the two hyphenated directories.

The exact pack/resource manifest and digest inventory, compatibility aliases,
historical rejection cases, execution pins, skill export proof, and unresolved
publication/license facts are in `handoffs/PKG.json`.

## Skill/export and lesson-transfer proof

The maintained native Megado skill and file-mode export are byte-identical:

- Native active skill: `packs/megado/skill`
- File-mode export:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/skill-export/megado`
- Tree digest: `ef3bd97aeb88e227c6d21e34248954d34ea531b603642c681f9e72bead821e40`
- `references/improvement-loop.md` digest:
  `dde7f6913a0775199c71174c8ee65c36e29720fa4f8895754cf7121c91523078`
- 12 offline relative links resolved; no cadence or rights grant was installed.

The transfer fixture links originating evidence to the adopted skill/resource
identity and a retained link-regression example. It proves transfer mechanics
only, not universal benefit, mass upgrade, or publication.

## Verification receipts

Disposable candidate environment:

- Venv: `/tmp/herzchen-pkg05-candidate.7zo9W7`
- Python: `3.11.16`
- pytest: `9.1.1`
- Wheel:
  `/tmp/herzchen-pkg05-final-wheel.N2vUn3/herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA-256:
  `27448373d6abe744edb7adcf9c34766a301e3a40ade0ebd805efa9377718e527`
- Astrid was installed from the pinned local source checkout with `--no-deps`
  solely to exercise its public loader; Herzchen was installed from the
  candidate wheel. All commands used `env -u PYTHONPATH`.
- Installed origins were candidate `site-packages` for `astrid`, `herzchen`,
  `herzchen.packs.authoring`, and `herzchen.packs.templates`. Static pack roots
  were checkout-only and are not claimed as installed product resources.

Focused installed command:

```text
env -u PYTHONPATH /tmp/herzchen-pkg05-candidate.7zo9W7/bin/python -m pytest -q tests/packs/test_authoring.py
13 passed in 1.25s (exit 0)
```

Affected pack/contract command:

```text
env -u PYTHONPATH /tmp/herzchen-pkg05-candidate.7zo9W7/bin/python -m pytest -q \
  tests/packs/test_authoring.py tests/packs/test_protocol_resources.py \
  tests/packs/test_task_templates.py tests/packs/test_composition.py \
  tests/work/test_identity_graph.py tests/kernel/test_transactions.py \
  tests/kernel/test_receipts_limits.py tests/content/test_documents.py \
  tests/content/test_context_visibility.py tests/extensions/test_namespaces.py \
  tests/contracts/test_contracts.py tests/authoring/test_exclusivity.py \
  tests/conformance/test_fixtures.py tests/conformance/test_matrix.py \
  tests/conformance/test_rehearsal.py
156 passed, 70 subtests passed in 1.45s (exit 0)
```

The final candidate worktree was clean after generated build/egg-info/bytecode
outputs were removed. Only the four named PKG-05 paths were committed. The
manager must perform its own handoff validation and root decides acceptance;
this worker result makes no publication or gate claim.

## Unresolved output

- No safe poms-skills, Astrid, or Runtime publication fork/target was bound;
  no upstream write was attempted.
- No license notice or rights grant was inferred beyond the pinned source
  provenance.
- Candidate installed-origin evidence is not production Otto/Astrid installed
  product evidence and does not prove G-OTTO or INT-03.
