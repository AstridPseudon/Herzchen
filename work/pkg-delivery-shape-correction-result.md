# PKG shipped delivery seed-shape correction

## Scope and source

- Worker: `Herzchen-pkg-delivery-shape-correction-worker`
- Source base commit: `2c6c586b4fada18e9115f5f249b7735dc25fbd48`
- Source base tree: `8a28fa21060624dc54302175091b1f1b03af86ab`
- Immutable input: `packs/megado/templates/delivery.json`, loaded from its real bytes in the focused tests.
- Changed paths: `src/herzchen/packs/templates.py`, `tests/packs/test_task_templates.py`, this report.

## Route receipt

The requested route was launched with this exact successful command:

```text
/Users/hannahomalley/.local/bin/codex -m gpt-5.6-luna -c reasoning_effort=high --dangerously-bypass-approvals-and-sandbox exec -C /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-pkg-delivery-shape-correction-worker --json -o /tmp/pkg-delivery-shape-correction-last-message.txt "Implement the bounded PKG shipped delivery seed-shape correction requested by the user. Work only in this checkout. Inspect the actual packs/megado/templates/delivery.json and existing TemplateEngine/public typed work-command contracts. Reproduce the current direct-instantiation baseline first and preserve evidence. Implement the narrowest generic data-driven correction in PKG-owned code, with no catalog/project/stage hardcoding, no private writer/SQL, using existing transaction boundary. Add focused tests under tests/packs that load the real resource bytes and cover positive path, idempotency/conflict, atomic invalidity, and compatibility. Build/test as appropriate, but do not edit owner files outside the allowed PKG source/tests/report and do not commit generated artifacts. Leave source/tests/report changes in the working tree for review. Summarize exact changes and verification."
```

- JSONL: `/tmp/pkg-delivery-shape-correction.jsonl` (44 lines, retained).
- PTY/session: `exec_command` session `52996`.
- Codex thread: `01a09d88-a3ea-7700-b5c1-5b558d60878d`.
- Observed route: requested `gpt-5.6-luna`, `reasoning_effort=high`; the JSONL ends with `turn.completed` and no fallback model was used.
- A preliminary syntax probe using `codex exec ... -a never` was rejected by this CLI before launch; the successful command above uses the supported top-level approval flag and is the only implementation route.

## Baseline and correction

Baseline was reproduced against the real delivery resource before the source correction: direct public `TemplateEngine.instantiate()` with an existing project returned the project result with zero child work records. The old `_node_list()` only discovered `nodes` and plural buckets, so `seed.work` and its `seed.links` were invisible.

The corrected public path now:

- validates and expands generic `seed.work` entries while retaining existing plural/node/bundle shapes;
- admits effort/task/criterion titles, substituted outcomes, custom metadata, parent refs, local IDs, namespaces, keys, status, and document payloads into the public WRK `fields` mapping;
- validates local work identities and endpoints, rejects unsupported link relations, retains `from`/`to`/`relation` link payloads, and maps the supported relations into the existing typed dependency graph;
- validates document definitions and document links before mutation, retains linked document payloads and link bindings in public fields, and resolves typed external refs through existing store APIs;
- keeps all writes in the existing `TemplateEngine` transaction around `WorkGraph.create()`/`create_project()` and FND receipts/events.

No private writer, SQL write path, catalog ID check, project/stage special case, upstream write, or non-PKG owner file was introduced.

## Exact source/test functions changed

- `src/herzchen/packs/templates.py`
  - `_node_list()` — generic `seed.work`/link validation and dependency projection.
  - `_seed_work_fields()` — public field admission for shipped work data.
  - `TemplateEngine.instantiate()` — applies admitted seed fields through existing WRK commands.
  - `TemplateEngine._validate_seed_references()` — invokes document contract validation before writes.
  - `TemplateEngine._document_seed_values()` — validates and prepares local document/document-link payloads.
- `tests/packs/test_task_templates.py`
  - real-resource loaders and durable-count helper;
  - `test_shipped_delivery_seed_work_is_expanded_from_real_resource()`;
  - `test_shipped_delivery_is_idempotent_and_conflicts_on_changed_parameters()`;
  - parametrized `test_invalid_shipped_shape_writes_nothing()`;
  - existing plural-shape compatibility test retained.

## Behavioral proof

The positive test asserts the existing project plus effort, two tasks, and criterion; all four `TemplateResult.local_refs`; parent graph; dependency graph; substituted title/outcome/proof; `custom.megado.execution_class`; namespaces/keys; `planning_only` status; linked document content; document-link binding; both resource links; committed receipts and event IDs.

The replay test asserts identical project/record refs and local refs, unchanged identities/references/receipts/events/event-sequence counts, and the existing `ReplayConflictError` with unchanged state for same-key changed parameters.

The invalidity matrix covers malformed `work`, missing and duplicate local IDs, unknown work-link endpoints, unsupported relation shape, unknown document endpoint, and pinned document links without a revision. Each failure is asserted to leave identities, references, receipts, events, event sequences, and public graph state unchanged.

## Installed-wheel verification

Disposable proof root: `/private/tmp/pkg-delivery-shape-correction-test.svGJan`.

Python 3.12.14 was used from `/private/tmp/pkg03-candidate-final2.RjmPwV/bin/python`; the proof venv was created at `/private/tmp/pkg-delivery-shape-correction-test.svGJan/venv312`. `PYTHONPATH` and `PYTHONHOME` were unset for build, install, import, and test commands.

Build/install/proof command:

```sh
proof_root=$(mktemp -d /private/tmp/pkg-delivery-shape-correction-test.XXXXXX)
base_python=/private/tmp/pkg03-candidate-final2.RjmPwV/bin/python
"$base_python" -m venv "$proof_root/venv312"
env -u PYTHONPATH -u PYTHONHOME "$proof_root/venv312/bin/python" -m pip install --quiet --upgrade pip setuptools wheel pytest
env -u PYTHONPATH -u PYTHONHOME "$proof_root/venv312/bin/python" -m pip wheel --no-deps --no-build-isolation --wheel-dir "$proof_root/wheel" .
wheel=$(find "$proof_root/wheel" -maxdepth 1 -name '*.whl' -print -quit)
env -u PYTHONPATH -u PYTHONHOME "$proof_root/venv312/bin/python" -m pip install --quiet --force-reinstall "$wheel"
env -u PYTHONPATH -u PYTHONHOME "$proof_root/venv312/bin/python" -m pytest -q tests/packs/test_task_templates.py
```

- Focused result: `18 passed`.
- Wheel: `/private/tmp/pkg-delivery-shape-correction-test.svGJan/wheel/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `ade59ee58466b625bf6b44e93256bfda3007e53f2d5024382eecb396fdc00fe2`.
- Installed `herzchen` origin: `/private/tmp/pkg-delivery-shape-correction-test.svGJan/venv312/lib/python3.12/site-packages/herzchen/__init__.py`.
- Installed `herzchen.packs.templates` origin: `/private/tmp/pkg-delivery-shape-correction-test.svGJan/venv312/lib/python3.12/site-packages/herzchen/packs/templates.py`.
- Compatibility command/result: `env -u PYTHONPATH -u PYTHONHOME /private/tmp/pkg-delivery-shape-correction-test.svGJan/venv312/bin/python -m pytest -q tests/packs tests/work tests/content tests/contracts tests/kernel` — `181 passed, 11 skipped, 10 subtests passed`.
- `git diff --check`: passed.

No broad/full-suite run was used for acceptance.

## Mapping and limitations

- Work `kind` selects the existing `WorkKind` command; `parent` and link-derived dependencies resolve through local refs and become normal WRK graph fields.
- `title`, `outcome`, `custom`, `namespace`, `key`, and other admitted neutral work data are retained under the public record `fields`; `template_origin.local_id` and `TemplateResult.local_refs` retain local identity.
- `requires` and `covers` are retained as inspectable local `links` fields and also projected to the existing dependency command because that is the available typed WRK relation.
- Local document definitions linked by `document_links` are retained under the subject work record's public `fields.documents`; normalized link payloads remain under `fields.document_links` with `current`/`pinned` binding validation.
- `status` is retained as the seed status field (`planning_only`); the WRK lifecycle remains its existing pending lifecycle. No automatic review, dispatch, allowance, or DAT document creation is performed.
- The template layer does not own DAT document creation. A seed that needs durable DAT document identities must supply an existing typed document ref and satisfy the existing store contract; the adapter rejects malformed/unresolved refs before mutation. The shipped resource uses local planning document payloads, which are preserved in public fields.

## Final ownership/hygiene receipt

- Allowed paths only: PKG source, focused PKG test, and this PKG report.
- No catalog hardcoding; no private writer; no SQL write path; no upstream write; no FND/DAT/WRK/EDT/OTT/control/seed/manifest/contract/shared-map owner-file change.
- Generated wheel, build metadata, venv, caches, and bytecode are outside the worker checkout and were not left as tracked or working-tree artifacts.
- Final source/test/report commit and tree are recorded after the allowed-path commit; the checkout is clean at handoff.
