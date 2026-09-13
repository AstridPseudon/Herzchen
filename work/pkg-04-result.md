# PKG-04 worker result

This is a worker implementation report. It does not claim PKG-04 acceptance,
PKG-05 publication, INT-03 completion, or a gate verdict.

## Fresh launch receipt

- Captured before implementation: `2026-09-13T23:18:20Z`
- Route: `worker_normal / gpt-5.6-luna / high`
- Launcher: `/Users/hannahomalley/.local/bin/codex` (`codex-cli 0.150.1`)
- Sole-writer root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-pkg04-worker`
- Starting worker commit/tree: `c0c1ec742ddd8777dbabd0ce12923bd409e89a26` / `868de7edf69414c74df960881b1c740d19253d61`
- Common checkpoint recheck: same commit/tree, clean before implementation
- Source-derived manifest: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`
- Source manifest SHA-256: `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`
- Read-only pack source: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/packs`

## Scope and evidence

Implementation evidence will be added below after the resource copy and focused
tests. The source packs are treated as read-only inputs; no upstream, source
checkout, common integration worktree, control database, or extraction map is
modified.

## Implementation

- Delivered 25 resource files under the three allowed pack roots:
  - `packs/megado/` — 17 files, 15 manifest resources plus documentation
  - `packs/scene-production/` — 5 files, 3 manifest resources plus documentation
  - `packs/work-starters/` — 3 files, 1 manifest resource plus documentation
- Added `tests/packs/test_protocol_resources.py` with 11 focused tests.
- Added no product/runtime code, DDL, private tables/enums/counters, scheduler,
  allowance grant, agent invocation, or Fieldnote implementation.
- The delivered pack trees compare byte-for-byte with their read-only pinned
  source inputs under `work/package/otto_herzchen_delivery_v11_2/packs/`.

## Validation receipts

Focused checkout test:

```text
/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int03-common-dat04-pkg03/bin/python -m pytest -q tests/packs/test_protocol_resources.py
11 passed in 0.08s
```

Disposable installed candidate:

- Candidate venv: `/tmp/herzchen-pkg04-candidate.wkgBV1`
- Python: `3.12.14`
- pytest: `9.1.1`
- Installed Python origins, all from candidate `site-packages`:
  - `herzchen`: `/tmp/herzchen-pkg04-candidate.wkgBV1/lib/python3.12/site-packages/herzchen/__init__.py`
  - `herzchen.packs.templates`: `/tmp/herzchen-pkg04-candidate.wkgBV1/lib/python3.12/site-packages/herzchen/packs/templates.py`
  - `herzchen.content.packets`: `/tmp/herzchen-pkg04-candidate.wkgBV1/lib/python3.12/site-packages/herzchen/content/packets.py`
- Wheel: `/tmp/herzchen-pkg04-wheel.bz4uVo/herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `60b52124aa4449be389c781f3f7de77b3089e8c73a7dc6715beecee5d1b83211`
- Broad affected command:

```text
env -u PYTHONPATH /tmp/herzchen-pkg04-candidate.wkgBV1/bin/python -m pytest -q tests/packs/test_protocol_resources.py tests/packs/test_task_templates.py tests/packs/test_composition.py tests/work/test_identity_graph.py tests/kernel/test_transactions.py tests/kernel/test_receipts_limits.py tests/content/test_documents.py tests/content/test_context_visibility.py tests/extensions/test_namespaces.py tests/contracts/test_contracts.py tests/authoring/test_exclusivity.py tests/conformance/test_fixtures.py tests/conformance/test_matrix.py tests/conformance/test_rehearsal.py
143 passed, 70 subtests passed in 0.54s
```

The static pack roots were confirmed absent from candidate `site-packages`, so
they are reported as checkout resources, not installed package resources.

Read-only source-lineage validation used the Astrid source checkout's current
canonical validator with its supported `expected_pack_id` binding:

```text
canonical_valid=megado id=megado resources=16
canonical_valid=scene-production id=scene_production resources=4
canonical_valid=work-starters id=work_starters resources=2
canonical_rejects_database=... database contributions are forbidden ...
static_pack_roots=checkout_only
```

The resolved-resource counts include each pack's documentation resource. The
hyphenated delivery directories use the manifest IDs `scene_production` and
`work_starters`; direct folder-name-only validation would reject that layout,
while the current provenance-bound discovery path accepts the explicit IDs.

Megado active skill/export proof:

- Active skill SHA-256: `fc3ff4fa32b52c85a8f1684e077deb6359efec4695c17e7ce4105a9cc5901a28`
- The pack skill tree and read-only `skill-export/megado` tree match byte-for-byte,
  including all pinned references/templates; offline relative-link resolution passes.
- Upstream source remains provenance only; `upstream_written` is false.

## Source and test lineage

- Common base: commit `c0c1ec742ddd8777dbabd0ce12923bd409e89a26`, tree
  `868de7edf69414c74df960881b1c740d19253d61`.
- PKG-03 accepted source/correction: `fbafff22ecfe01c984e2fb68fbcaec0d9324c4a1` and
  `91cd0825ad396f1bd82a9c1c8aa32bab33bbf96c`.
- EX-PACKS extraction row retained from
  `work/package/otto_herzchen_delivery_v11_2/plan/extraction-map.json`.
- Astrid compatibility lineage was read-only source-checkout evidence from the
  pinned `validate.py`, `discovery.py`, `registry.py` and retained pack tests;
  it is not described as an installed Astrid origin.
- The refreshed full-source manifest remains pinned at SHA-256
  `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.

No remote, upstream, common integration worktree, control database, extraction
map, Otto path, or source checkout was written.
