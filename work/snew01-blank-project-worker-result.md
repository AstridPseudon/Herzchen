# SNEW01 blank-project corrective result

## Scope correction

The shipped blank resource and `_blank_seed` are restored to the declared
baseline: `documents: []` and `document_links: []` in the JSON resource, and
`documents: []` with no document-link seed in `_blank_seed`. The static seed is
not the source of the initial specification.

`TemplateEngine` now composes the blank initial DAT document and its current
`project.documents/specification` association dynamically from the shared
`render_blank_project(rendered.parameters)` projection. The canonical content
contains the rendered project and zero tasks plus:

```text
metadata.template_ref       pack/work.blank_project/pkg-03.v1
metadata.template_revision  pkg-03.v1
metadata.projection_schema  pending-project-sheet/v1
```

The composition uses the supplied FND transaction and existing DAT document
and link commands before any optional checkout materialization. No SQL,
private writer, second receipt engine, schema owner, controller/control,
Runtime, Astrid, or generic `{}` content was added.

## Corrective source/tests

Changed source/test paths in the corrective working tree:

```text
packs/work-starters/templates/blank-project.json  (restored baseline)
src/herzchen/packs/templates.py
tests/packs/test_authoring.py                     (restored sparse assertion)
tests/packs/test_protocol_resources.py            (restored sparse assertion)
tests/packs/test_task_templates.py
```

The linked-worktree sandbox prevented the worker from writing Git metadata;
the owning manager recorded the validated source, tests, and this handoff
after the worker completed. The final commit and tree are bound in the
manager completion supplement because embedding a commit hash in its own
committed payload would be self-referential.

## Focused validation

Source command, using the required interpreter:

```text
PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/packs tests/authoring tests/content tests/work/test_batches.py tests/work/test_sheet_batches.py tests/work/test_identity_graph.py tests/conformance/test_dat_handoff.py tests/conformance/test_int03_public_api_probes.py
142 passed, 12 skipped
```

Fresh-store evidence from the source composition:

```text
project_ref       evidence/work.project/project-4555c284bfd698c4d43528e56ec6@rev-1
spec_document_ref evidence/dat.content.document/template-81166781c31433c7f86b2ba9cbdeeccd
association_ref   evidence/document-association/link-3c2fb9c50d540a3b4532a05c5385f2ea
receipts          3
events            3
durable counts    identities=5, record_references=7, command_receipts=3,
                  events=3, event_sequences=3
```

Fresh supported reads show one pending zero-task project, one initial DAT
document, an empty-parent initial revision, and one active association. The
project has no manager, budget, gate, worker, protocol, execution, or dispatch
readiness. The initial content is the shared projection with provenance.
Same-input replay returns the same project/spec/association refs and receipts
with event count unchanged at 3. Changed title raises `ReplayConflictError`.
Invalid title, actor occupancy, materializer failure/recovery, and untouched
close are covered by the focused tests. Untouched close retains durable
project/spec/revision/association state, releases the reservation, removes
only the registered checkout file, and creates no task or content revision.

## Disposable wheel

The supplied wheel was checked with `PYTHONPATH` and `PYTHONHOME` unset. Its
digest is:

```text
e42e31ef3fc0990f024d9e8ab9c78df519c8625ca8570b96e26d052b47c32f39
```

It was built before the final static-seed restoration and consequently gave
`142 passed, 11 skipped, 1 failed` on the exact matrix (the sparse-seed
assertion). It is not claimed as a passing corrective artifact.

The final wheel built from the restored working tree is:

```text
/private/tmp/herzchen-snew01-final-wheel.fQhR3e/herzchen_contracts-0.1.0-py3-none-any.whl
sha256 aaf946d925d76cdf0ad4c35f6d3cd1a7b7179b43795d0feff61d9b2a73382c66
```

Installed origins in the disposable venv:

```text
/private/tmp/herzchen-snew01-wheel.NwXHBp/venv/lib/python3.12/site-packages/herzchen/__init__.py
/private/tmp/herzchen-snew01-wheel.NwXHBp/venv/lib/python3.12/site-packages/herzchen/packs/templates.py
/private/tmp/herzchen-snew01-wheel.NwXHBp/venv/lib/python3.12/site-packages/herzchen/domains/work/sheet.py
```

With `env -u PYTHONPATH -u PYTHONHOME`, the exact focused matrix returned:

```text
143 passed, 11 skipped
```

## Boundary

This result covers only the corrected PKG `TemplateEngine` blank composition
and focused proof. Controller/Runtime/Astrid exposure and G-FOUNDATION remain
outside this bounded change. No full-product acceptance is claimed.
