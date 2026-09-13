# PKG-03 atomicity correction result

## Scope and sealed evidence

- Worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-pkg03-worker`
- Accepted candidate base: commit `fbafff22ecfe01c984e2fb68fbcaec0d9324c4a1`, tree `cd40c763a0d4fc51370516b061af907061af2636`.
- Sealed `work/pkg-03-result.md` was preserved byte-for-byte and is unchanged.
- `work/pkg-03-launch-receipt-20260914.json` was not present at the requested path when checked; no replacement or edit was made.
- Only the two allowed source/test files and this new correction report are changed.
- No control database, integration worktree, shared extraction map, upstream, product module outside the allowed paths, or sealed report was changed.

## Route and execution identity

- Requested route: `/Users/hannahomalley/.local/bin/codex`, model `gpt-5.6-luna`, reasoning `high`.
- Observed route: model `gpt-5.6-luna`, reasoning `high`; no model or route substitution observed.
- Observed CLI: `/Users/hannahomalley/.local/bin/codex`, `codex-cli 0.150.1`.
- The command runner exposed shell process IDs, but no separate Codex session ID or pytest child PID. Validation shells had parent PID `70516`; the observed shell PIDs are recorded below.
- First successful validation timestamp: `2026-09-13T23:04:25.052906000Z`.
- Last full-suite validation ended: `2026-09-13T23:06:51.197603000Z`.

## Correction

`TemplateEngine.instantiate` now orders the graph before any write and enters one outer `Store.transaction()` around optional project creation and every public `WorkGraph.create` command. Existing public commands still call `Store.transaction()`, which becomes a nested savepoint under the outer transaction. A later-node exception therefore rolls back the project, earlier nodes, retained references, events, and receipts together.

The project-seed owner gate was also corrected so a valid non-blank template containing a project seed can exercise the optional new-project path. Topological, parameter, kind, alias, namespace, review, external-reference, and local-reference checks remain before the outer transaction and before writes.

The new public-API regression test injects a failure on the second task command, verifies zero records/events/receipts, restores `WorkGraph.create`, repeats the same logical request, and verifies three coherent records and three events. An exact replay returns the same references without adding records or events.

## Disposable venv / installed proof

- Disposable root: `/private/tmp/pkg03-atomicity-correction.iV202j`.
- Python: `Python 3.12.14`.
- Venv interpreter: `/private/tmp/pkg03-atomicity-correction.iV202j/venv312/bin/python`.
- pip: `pip 26.2.1` from `/private/tmp/pkg03-atomicity-correction.iV202j/venv312/lib/python3.12/site-packages/pip`.
- pytest: `pytest 9.1.1`.
- `PYTHONPATH` observed as `None`; all commands used `env -u PYTHONPATH`.
- Installed distribution: `herzchen-contracts 0.1.0`.
- Installed origins:
  - `herzchen`: `/private/tmp/pkg03-atomicity-correction.iV202j/venv312/lib/python3.12/site-packages/herzchen/__init__.py`
  - `herzchen.packs.templates`: `/private/tmp/pkg03-atomicity-correction.iV202j/venv312/lib/python3.12/site-packages/herzchen/packs/templates.py`
- Candidate wheel: `/private/tmp/pkg03-atomicity-correction.iV202j/wheel-proof/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `80307494d802a00ffb7d5500244a62966bb45557be029735abc5e3bff3f661f5`.
- Source SHA-256 after correction:
  - `fc6c12bc79d49507ea383bc71c1b5b1cd95de6a71c3e2624c080f1e320704c60  src/herzchen/packs/templates.py`
  - `a9556fe66807a3b0dd836b123c7bc46e1c2398a2626705a8ae5466ef9734e6a3  tests/packs/test_task_templates.py`

The first disposable attempt used system Python 3.9.6 with setuptools 58.0.4 and produced an empty `UNKNOWN-0.0.0` wheel; it was discarded and not used as installed proof. The valid proof above used the 3.12.14 disposable venv.

Disposable venv setup command:

```sh
candidate_root=/private/tmp/pkg03-atomicity-correction.iV202j
base_python=/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int03-wrk02/bin/python
"$base_python" -m venv "$candidate_root/venv312"
env -u PYTHONPATH "$candidate_root/venv312/bin/python" -m pip install --quiet --upgrade pip setuptools wheel pytest
```

## Exact build, install, and validation commands

All commands below ran from the worktree and used no `PYTHONPATH`.

1. Build command, shell PID `71618`, parent PID `70516`, started `2026-09-13T23:06:34.552081000Z`, ended `2026-09-13T23:06:35.133648000Z`, exit `0`:

   ```sh
   candidate_root=/private/tmp/pkg03-atomicity-correction.iV202j
   proof_wheel_dir="$candidate_root/wheel-proof"
   mkdir -p "$proof_wheel_dir"
   env -u PYTHONPATH "$candidate_root/venv312/bin/python" -m pip wheel --no-deps --no-build-isolation --wheel-dir "$proof_wheel_dir" .
   ```

2. Install command, shell PID `71640`, parent PID `70516`, started `2026-09-13T23:06:44.355466000Z`, ended `2026-09-13T23:06:44.632622000Z`, exit `0`:

   ```sh
   candidate_root=/private/tmp/pkg03-atomicity-correction.iV202j
   wheel="$candidate_root/wheel-proof/herzchen_contracts-0.1.0-py3-none-any.whl"
   env -u PYTHONPATH "$candidate_root/venv312/bin/python" -m pip install --quiet --force-reinstall "$wheel"
   ```

3. Focused suite, shell PID `71232`, parent PID `70516`, started `2026-09-13T23:04:25.052906000Z`, ended `2026-09-13T23:04:25.285412000Z`, exit `0` — `8 passed`:

   ```sh
   env -u PYTHONPATH /private/tmp/pkg03-atomicity-correction.iV202j/venv312/bin/python -m pytest -q tests/packs/test_task_templates.py
   ```

4. Injected rollback test, shell PID `71244`, parent PID `70516`, started `2026-09-13T23:04:30.981032000Z`, ended `2026-09-13T23:04:31.146421000Z`, exit `0` — `1 passed, 7 deselected`:

   ```sh
   env -u PYTHONPATH /private/tmp/pkg03-atomicity-correction.iV202j/venv312/bin/python -m pytest -q tests/packs/test_task_templates.py -k 'rolls_back_later_node_failure_and_replays_once'
   ```

5. Integrated work/content/contracts/kernel suites, shell PID `71272`, parent PID `70516`, started `2026-09-13T23:04:37.712190000Z`, ended `2026-09-13T23:04:38.051150000Z`, exit `0` — `63 passed`:

   ```sh
   env -u PYTHONPATH /private/tmp/pkg03-atomicity-correction.iV202j/venv312/bin/python -m pytest -q tests/work tests/content tests/contracts tests/kernel
   ```

6. Affected packs plus integrated suites, shell PID `71303`, parent PID `70516`, started `2026-09-13T23:04:43.769228000Z`, ended `2026-09-13T23:04:44.167785000Z`, exit `0` — `82 passed`:

   ```sh
   env -u PYTHONPATH /private/tmp/pkg03-atomicity-correction.iV202j/venv312/bin/python -m pytest -q tests/packs tests/work tests/content tests/contracts tests/kernel
   ```

7. Full suite against the installed candidate wheel, shell PID `71668`, parent PID `70516`, started `2026-09-13T23:06:50.565178000Z`, ended `2026-09-13T23:06:51.197603000Z`, exit `0` — `99 passed, 70 subtests passed`:

   ```sh
   env -u PYTHONPATH /private/tmp/pkg03-atomicity-correction.iV202j/venv312/bin/python -m pytest -q
   ```

8. Final hygiene check, observed exit `0`:

   ```sh
   git diff --check
   ```

Build metadata and bytecode were removed after validation: `build/`, `src/herzchen_contracts.egg-info/`, all generated `__pycache__/` directories, and generated `.pyc`/`.pyo` files in the worktree.

## Exact unified source/test diff

Captured with `git diff --no-ext-diff -- src/herzchen/packs/templates.py tests/packs/test_task_templates.py`:

```diff
diff --git a/src/herzchen/packs/templates.py b/src/herzchen/packs/templates.py
index 05fa091..6be1a3f 100644
--- a/src/herzchen/packs/templates.py
+++ b/src/herzchen/packs/templates.py
@@ -651,7 +651,7 @@ class TemplateEngine:
         project_seed = seed.get("project")
         if project_seed is not None and not isinstance(project_seed, Mapping):
             raise TemplateValidationError("seed project must be an object")
-        if owner_target is None and resource.id != BLANK_TEMPLATE_ID:
+        if owner_target is None and resource.id != BLANK_TEMPLATE_ID and project_seed is None:
             raise TemplateReferenceError("template instantiation requires an existing project owner")
         if owner_target is not None:
             owner_record = self.graph.get(owner_target)
@@ -662,6 +662,7 @@ class TemplateEngine:
         if resource.id == BLANK_TEMPLATE_ID and nodes:
             raise TemplateValidationError("blank project must contain zero work nodes")
         self._validate_seed_references(seed, nodes, owner_record, name_set)
+        ordered = self._ordered_nodes(nodes, edges)
         request = _request_key(logical_request_key, resource, rendered)

         # All checks above are intentionally before the first public WRK
@@ -670,53 +671,53 @@ class TemplateEngine:
         receipts: list[Any] = []
         local_refs: dict[str, ResourceRef] = {}
         records: list[WorkRecord] = []
-        if owner_record is None:
-            title = project_seed.get("title") if project_seed else None
-            outcome = project_seed.get("outcome", "") if project_seed else ""
-            metadata = dict(project_seed.get("fields", {})) if project_seed else {}
-            metadata["template_origin"] = _origin(resource)
-            owner_record = self.graph.create_project(title=title, outcome=outcome, metadata=metadata,
-                                                     logical_request_key=request + ":project", actor=actor)
-            receipts.append(self.store.get_receipt(request + ":project"))
-        if resource.id == BLANK_TEMPLATE_ID:
-            return TemplateResult(owner_record, (), {"project": owner_record.ref}, tuple(receipts), rendered, False)
-
-        ordered = self._ordered_nodes(nodes, edges)
-        for node in ordered:
-            name = _local_name(node)
-            kind = node.get("kind")
-            if isinstance(kind, str):
-                kind = kind.removeprefix("work.")
-            try:
-                work_kind = WorkKind(kind)
-            except (TypeError, ValueError) as exc:
-                raise TemplateValidationError(f"unsupported template work kind: {kind!r}") from exc
-            parent = self._resolve_seed_ref(node.get("parent", node.get("parent_ref")), local_refs, owner_record)
-            if parent is None:
-                parent = owner_record
-            dependencies = tuple(self._resolve_seed_ref(ref, local_refs, owner_record, required=True) for ref in node.get("dependencies", node.get("depends_on", [])))
-            fields = dict(node.get("fields", {}))
-            if not isinstance(node.get("fields", {}), Mapping):
-                raise TemplateValidationError(f"fields for {name!r} must be an object")
-            fields.update({key: deepcopy(value) for key, value in node.items() if key in {"namespace", "key", "instructions", "description", "criteria", "documents", "profile_ref", "allowance_ref"}})
-            default_namespace = TASK_NAMESPACE if work_kind is WorkKind.TASK else CRITERION_NAMESPACE if work_kind is WorkKind.CRITERION else "work"
-            namespace = node.get("namespace", namespaces.get(work_kind.value, namespaces.get(work_kind.value + "s", default_namespace)))
-            fields["namespace"] = _text(namespace, "node namespace")
-            fields["key"] = node.get("key", name)
-            choice = _review_choice(node.get("review_choice", node.get("review")))
-            if choice is not None:
-                fields["review_choice"] = choice
-            fields["template_origin"] = dict(_origin(resource), local_id=name)
-            for field in ("profile_ref", "allowance_ref"):
-                if field in node:
-                    fields[field] = _ref_dict(_ref(node[field], field))
-            kwargs = {"title": node.get("title", node.get("name", name)), "name": node.get("name", node.get("title", name)),
-                      "alias": node.get("alias", name), "aliases": tuple(node.get("aliases", ())), "parent": parent,
-                      "dependencies": dependencies, "fields": fields, "logical_request_key": request + ":" + name, "actor": actor}
-            record = self.graph.create(work_kind, project=owner_record, **kwargs)
-            local_refs[name] = record.ref
-            records.append(record)
-            receipts.append(self.store.get_receipt(request + ":" + name))
+        with self.store.transaction():
+            if owner_record is None:
+                title = project_seed.get("title") if project_seed else None
+                outcome = project_seed.get("outcome", "") if project_seed else ""
+                metadata = dict(project_seed.get("fields", {})) if project_seed else {}
+                metadata["template_origin"] = _origin(resource)
+                owner_record = self.graph.create_project(title=title, outcome=outcome, metadata=metadata,
+                                                         logical_request_key=request + ":project", actor=actor)
+                receipts.append(self.store.get_receipt(request + ":project"))
+            if resource.id == BLANK_TEMPLATE_ID:
+                return TemplateResult(owner_record, (), {"project": owner_record.ref}, tuple(receipts), rendered, False)
+
+            for node in ordered:
+                name = _local_name(node)
+                kind = node.get("kind")
+                if isinstance(kind, str):
+                    kind = kind.removeprefix("work.")
+                try:
+                    work_kind = WorkKind(kind)
+                except (TypeError, ValueError) as exc:
+                    raise TemplateValidationError(f"unsupported template work kind: {kind!r}") from exc
+                parent = self._resolve_seed_ref(node.get("parent", node.get("parent_ref")), local_refs, owner_record)
+                if parent is None:
+                    parent = owner_record
+                dependencies = tuple(self._resolve_seed_ref(ref, local_refs, owner_record, required=True) for ref in node.get("dependencies", node.get("depends_on", [])))
+                fields = dict(node.get("fields", {}))
+                if not isinstance(node.get("fields", {}), Mapping):
+                    raise TemplateValidationError(f"fields for {name!r} must be an object")
+                fields.update({key: deepcopy(value) for key, value in node.items() if key in {"namespace", "key", "instructions", "description", "criteria", "documents", "profile_ref", "allowance_ref"}})
+                default_namespace = TASK_NAMESPACE if work_kind is WorkKind.TASK else CRITERION_NAMESPACE if work_kind is WorkKind.CRITERION else "work"
+                namespace = node.get("namespace", namespaces.get(work_kind.value, namespaces.get(work_kind.value + "s", default_namespace)))
+                fields["namespace"] = _text(namespace, "node namespace")
+                fields["key"] = node.get("key", name)
+                choice = _review_choice(node.get("review_choice", node.get("review")))
+                if choice is not None:
+                    fields["review_choice"] = choice
+                fields["template_origin"] = dict(_origin(resource), local_id=name)
+                for field in ("profile_ref", "allowance_ref"):
+                    if field in node:
+                        fields[field] = _ref_dict(_ref(node[field], field))
+                kwargs = {"title": node.get("title", node.get("name", name)), "name": node.get("name", node.get("title", name)),
+                          "alias": node.get("alias", name), "aliases": tuple(node.get("aliases", ())), "parent": parent,
+                          "dependencies": dependencies, "fields": fields, "logical_request_key": request + ":" + name, "actor": actor}
+                record = self.graph.create(work_kind, project=owner_record, **kwargs)
+                local_refs[name] = record.ref
+                records.append(record)
+                receipts.append(self.store.get_receipt(request + ":" + name))
         return TemplateResult(owner_record, tuple(records), local_refs, tuple(receipts), rendered, False)

diff --git a/tests/packs/test_task_templates.py b/tests/packs/test_task_templates.py
index 354fe94..ae61639 100644
--- a/tests/packs/test_task_templates.py
+++ b/tests/packs/test_task_templates.py
@@ -106,6 +106,56 @@ def test_bundle_is_literal_idempotent_and_retains_origin_namespaces_and_review(h
     assert graph.get(task.ref).title == "literal {{title}}"


+def test_bundle_rolls_back_later_node_failure_and_replays_once(harness, monkeypatch):
+    store, graph, engine, _ = harness
+    template = work_template(
+        "atomic-bundle",
+        revision="atomic-1",
+        seed={
+            "project": {"title": "Atomic project", "outcome": "Complete atomically"},
+            "tasks": [
+                {"local_id": "first", "title": "First task"},
+                {"local_id": "second", "title": "Second task"},
+            ],
+        },
+    )
+
+    original_create = graph.create
+    calls = 0
+
+    def fail_on_second_node(kind, **kwargs):
+        nonlocal calls
+        calls += 1
+        if calls == 2:
+            raise RuntimeError("injected later-node failure")
+        return original_create(kind, **kwargs)
+
+    monkeypatch.setattr(graph, "create", fail_on_second_node)
+    with pytest.raises(RuntimeError, match="injected later-node failure"):
+        engine.instantiate(template, logical_request_key="atomic-request")
+
+    assert graph.list() == ()
+    assert store.list_events() == ()
+    assert store.get_receipt("atomic-request:project") is None
+    assert store.get_receipt("atomic-request:first") is None
+    assert store.get_receipt("atomic-request:second") is None
+
+    monkeypatch.setattr(graph, "create", original_create)
+    result = engine.instantiate(template, logical_request_key="atomic-request")
+    assert [record.title for record in result.records] == ["First task", "Second task"]
+    assert len(graph.list()) == 3
+    assert len(store.list_events()) == 3
+    assert all(store.get_receipt(key) is not None for key in (
+        "atomic-request:project", "atomic-request:first", "atomic-request:second",
+    ))
+
+    replay = engine.instantiate(template, logical_request_key="atomic-request")
+    assert [record.ref for record in replay.records] == [record.ref for record in result.records]
+    assert replay.project.ref == result.project.ref
+    assert len(graph.list()) == 3
+    assert len(store.list_events()) == 3
+

 def test_all_invalid_seed_fail_before_any_work_record_is_written(harness):
     store, graph, engine, _ = harness
     project = engine.instantiate("work.blank_project", logical_request_key="owner").project
```

This correction report does not claim manager acceptance, root acceptance, or integration acceptance.
