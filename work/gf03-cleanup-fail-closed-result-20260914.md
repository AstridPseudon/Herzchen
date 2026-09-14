# GF03 cleanup fail-closed correction result

Objective: `GF03_WRITER_RETIREMENT_FINAL_BYTES`

This is a continuation supplement. The prior worker result remains at
`work/gf03-authoring-worker-result.md`; it is not rewritten.

## Correction identity

- Parent evidence commit: `e0ae45bd65401c129c06e1085343033efce9bab1`
- Parent evidence tree: `049e2212abcfd3a3c779f33e979b7bf6732a1175`
- Correction commit: `fcb4805636d6a8cb93fd8fd818579809c0a9675f`
- Correction tree: `171bef1b63ad670327e8b85d44098ac3da575d45`
- Commit message: `Close GF03 cleanup fail-closed boundary`

The correction is limited to the authoring cleanup/lifecycle boundary and
narrowly affected authoring consumer tests. No kernel, GF01, private writer,
scheduler, control-root, packet, or original-review files were changed.

## Correction outcome

- `cleanup_registered_files` now treats an absent, raising, unknown, or active
  writer probe as `CleanupStatus.UNSAFE` before any deletion.
- Every nonempty public cleanup request now requires both exact captured
  `sha256` and `size`; bare paths and partial metadata raise the established
  `CleanupIdentityError` before current bytes can become a baseline.
- Manual and idle lifecycle cleanup always passes a writer probe. The shared
  path continues to convert the persisted retirement manifest to exact
  path/digest/size entries; without a host writer hook, the probe reports
  unknown and cleanup remains unsafe.
- Direct public tests cover absent callback, unknown callback, active callback,
  raising callback, bare/partial metadata, and exact-manifest positive cleanup.
  All negative cases assert that bytes remain intact.
- Existing manual and idle late-write/barrier recovery, unknown-writer, and
  fresh-capture recovery tests remain present and pass.

## Source verification

Interpreter:

`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`

Focused source command (explicit `PYTHONPATH`):

```text
PYTHONPATH="$PWD/src" /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/authoring/test_gf03_retirement.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py tests/authoring/test_failure_matrix.py tests/authoring/test_handoff.py tests/authoring/test_three_targets.py tests/packs/test_task_templates.py
59 passed, 1 skipped in 0.61s
```

Affected source consumer command:

```text
PYTHONPATH="$PWD/src" /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/authoring tests/content/test_document_authoring_contract.py tests/packs/test_task_templates.py
77 passed, 1 skipped in 0.50s
```

The source skip is the existing installed-process gate.

## Disposable installed verification

Wheel built from correction commit `fcb4805636d6a8cb93fd8fd818579809c0a9675f`
with `/opt/homebrew/bin/python3.11`, installed into disposable venv
`/private/tmp/gf03-venv-38bmnx`:

- Wheel: `/private/tmp/gf03-wheel-VLGQnB/herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA256: `8ff73d59abd9bbfd9e3716f0d502f64ae05055cc08af58dfaecc22cdb9bbb6a9`
- Python: `3.11.16 (main, Aug 12 2026, 23:03:19) [Clang 17.0.0 (clang-1700.6.4.2)]`
- pytest: `9.1.1`
- pip: `26.2.1`
- `PYTHONPATH`: unset
- `PYTHONHOME`: unset
- Environment descriptor SHA256: `4db1dcc9d50109985c57406a5a08ac668c04eeba7d7578c61e12b4da23cadcd2`

Installed focused command:

```text
env -u PYTHONPATH -u PYTHONHOME /private/tmp/gf03-venv-38bmnx/bin/python -m pytest -q tests/authoring/test_gf03_retirement.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py tests/authoring/test_failure_matrix.py tests/authoring/test_handoff.py
29 passed in 0.44s
```

Installed affected consumer command:

```text
env -u PYTHONPATH -u PYTHONHOME /private/tmp/gf03-venv-38bmnx/bin/python -m pytest -q tests/authoring tests/content/test_document_authoring_contract.py tests/packs/test_task_templates.py
78 passed in 0.77s
```

The installed run includes the fresh-process handoff proof because the
package resolves from `site-packages`.

Installed origins, all under the disposable venv site-packages directory:

```text
herzchen=/private/tmp/gf03-venv-38bmnx/lib/python3.11/site-packages/herzchen/__init__.py
cleanup=/private/tmp/gf03-venv-38bmnx/lib/python3.11/site-packages/herzchen/authoring/cleanup.py
finish=/private/tmp/gf03-venv-38bmnx/lib/python3.11/site-packages/herzchen/authoring/finish.py
idle=/private/tmp/gf03-venv-38bmnx/lib/python3.11/site-packages/herzchen/authoring/idle.py
integration=/private/tmp/gf03-venv-38bmnx/lib/python3.11/site-packages/herzchen/authoring/integration.py
sessions=/private/tmp/gf03-venv-38bmnx/lib/python3.11/site-packages/herzchen/authoring/sessions.py
snapshots=/private/tmp/gf03-venv-38bmnx/lib/python3.11/site-packages/herzchen/authoring/snapshots.py
```

## Exact source and test hashes

```text
8fb15610f35d52b55689d094de43e8c6a5bb31eb4793259e320eff3c708bba8b  src/herzchen/authoring/cleanup.py
8d48e8718229e846673660d3f3038a27cb6093166cd648c6c41816d9b3498cb2  src/herzchen/authoring/idle.py
0af5319be6c78a03ba14f34864ca7a137a24c1938dd5ec07aea8f2c0726e98b8  src/herzchen/authoring/integration.py
d44fabcd8977171da0653f04a2f2f2fb666072a8ad3dc3ce43885c71e0a608c5  tests/authoring/test_gf03_retirement.py
934524a72a247d878db67bf47826a056c0b6279feeb54eff12c0000779c9dae9  tests/authoring/test_failure_matrix.py
a8b46d65d9e21d205e153abb4d61cd1e4ba4e6c9490d0390312673b836161e14  tests/authoring/test_handoff.py
0dc70d4ea76062698844f9db4cb9591dc9a7b417c22f9db45e70a421d1325003  tests/authoring/test_three_targets.py
```

`git diff --check` passed before the correction commit. Generated bytecode,
build output, and egg-info are removed from the continuation checkout after
verification. Root retains final acceptance; this file makes no product or
gate verdict.
