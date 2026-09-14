# SNEW01 blank-project worker result

## Scope and implementation

Implemented the narrow PKG/WRK public composition for
`TemplateEngine.instantiate("work.blank_project")`.

- The built-in blank seed now declares one owned DAT document with role
  `initial-specification`, an empty pending project specification, and one
  current `project.documents/specification` association.
- The existing project-local identity is made available to the existing DAT
  link resolver.
- The blank early return was removed. Existing `WorkGraph`,
  `ContentCommandHandler`, `Store.transaction`, `Store.mutate`,
  `put_identity`, `put_reference`, and fresh-read paths now compose the WRK,
  DAT document/revision, and association commands in the one outer FND
  transaction.
- No controller, Runtime/Astrid code, SQL/schema owner, private writer,
  second receipt engine, manager, gate, budget, allowance, task, dispatch, or
  admission behavior was added.

Implementation commit/tree:

```text
87dde21be00c9a76c2227429d6793c881eea126f
98b06980fc58db6d8b29abdbe66d9359080de2da
```

Changed files:

```text
src/herzchen/packs/templates.py
packs/work-starters/templates/blank-project.json
tests/packs/test_task_templates.py
tests/packs/test_protocol_resources.py
tests/packs/test_authoring.py
```

## Source validation

Interpreter:
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`

Command:

```text
PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/packs tests/authoring tests/content tests/work/test_batches.py tests/work/test_sheet_batches.py tests/work/test_identity_graph.py tests/conformance/test_dat_handoff.py tests/conformance/test_int03_public_api_probes.py
```

Result: `142 passed, 12 skipped`.

Additional source checks:

```text
git diff --check                         exit 0
PYTHONPATH=src ... python -m compileall -q src/herzchen tests/packs/test_task_templates.py   exit 0
```

## Durable blank evidence

The fresh-store/reopen probe produced:

```text
project_ref          {"authority":"snew01-evidence","id":"project-36672d5b9f72414cea1b48e3f603","kind":"work.project","revision":"rev-1"}
spec_document_ref    {"authority":"snew01-evidence","id":"template-f8df8bf101d2c4202130420358c3fa8f","kind":"dat.content.document","revision":null}
association_ref      {"authority":"snew01-evidence","id":"link-fdee2b3b5ed61cbdc2f33051b7d1e1b1","kind":"document-association","revision":null}
initial_revision_ref rev-ac82774ab7b68c6ef00435b7f997d5de
```

The initial document read is role `initial-specification`, its revision is
`initial: true` with no parent, and its content has the supplied title,
empty outcome/instructions, empty acceptance/custom/documents/tasks, and no
execution metadata. The fresh project read is pending with zero tasks,
`protocol`, `manager`, `gate`, `budget`, `worker`, `execution`, and
`external_action` unset, and dispatch false. The association is active and
current-bound to the document.

The creation returned three committed receipts and three events:

```text
evidence-blank:project
evidence-blank:document:initial-specification
evidence-blank:link:project:project.documents:specification
```

Replaying the same request and title returned the same project/spec/link refs
and receipt values; receipt count stayed `3` and event count stayed `3`.
Reusing the request with a changed title raised `ReplayConflictError` before
mutation. Invalid empty title validation left the fresh store with no project,
receipt, or event. Closing and reopening the database through `Store.open` and
fresh WRK/DAT reads retained all three durable identities and the initial
revision.

## Authoring and negative-path evidence

The new focused untouched-close test opens the created pending project through
`AuthoringSessionService.open` with the exact initial DAT content, then uses
the existing `SemanticFinishAdapter`/`IdleCloseService` path. It reports
`closed_cleaned`, removes the registered checkout file, releases the actor
reservation, retains the project/spec/active association, keeps the project
revision unchanged, and creates no task or content revision.

Existing focused authoring tests, run in the matrix above, provide the other
required negative paths:

- `ExclusivityTests.test_create_and_open_does_not_create_when_actor_is_occupied`:
  actor occupancy returns before the creator callback (`called == []`).
- `ExclusivityTests.test_materialization_failure_saves_project_and_releases`:
  materialization returns `saved_project_edit_not_opened`, preserves the
  project reference and durable scope payload, and leaves the scope available
  for recovery.
- Existing authoring failure/conformance tests cover rejected/capture failure,
  registered-file cleanup, replay, stale tokens, and unexpected-file safety.
- Existing PKG template tests cover atomic later-node/DAT failure rollback,
  replay, changed-parameter conflict, and invalid seed preflight.

The normal `ProjectSheet`/WRK/DAT edit and document-attach path remains
separate and continues to use its existing public batch composition. Explicit
admission remains separate; this worker claims no G-FOUNDATION or full-product
acceptance.

## Installed wheel validation

Disposable wheel build used `pip wheel . --no-deps --no-build-isolation`.

```text
Wheel: herzchen_contracts-0.1.0-py3-none-any.whl
SHA-256: e7021249f7e346785f8da47a7fb99da492a349db739e36a7cab441bd07f0c26b
```

Installed origins, with `env -u PYTHONPATH -u PYTHONHOME`, were:

```text
/tmp/herzchen-snew01-wheel.NwXHBp/venv/lib/python3.12/site-packages/herzchen/__init__.py
/tmp/herzchen-snew01-wheel.NwXHBp/venv/lib/python3.12/site-packages/herzchen/packs/templates.py
/tmp/herzchen-snew01-wheel.NwXHBp/venv/lib/python3.12/site-packages/herzchen/domains/work/sheet.py
```

Exact focused matrix command:

```text
env -u PYTHONPATH -u PYTHONHOME /tmp/herzchen-snew01-wheel.NwXHBp/venv/bin/python -m pytest -q tests/packs tests/authoring tests/content tests/work/test_batches.py tests/work/test_sheet_batches.py tests/work/test_identity_graph.py tests/conformance/test_dat_handoff.py tests/conformance/test_int03_public_api_probes.py
```

Result: `143 passed, 11 skipped`. The one-count difference from source is an
environment-dependent optional skip; the same test paths were used. The
candidate wheel itself was the installed module origin. Generated build,
wheel, cache, and temporary checkout artifacts are not in the worker tree.

## Remaining owner boundary

No concrete gap remains in the requested PKG `TemplateEngine` blank path.
Host/controller exposure of create-and-open and all G-FOUNDATION/product-level
acceptance remain outside this bounded worker change and require their owning
integration paths.
