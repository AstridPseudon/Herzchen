# GF03 authoring worker result

Objective: `GF03_WRITER_RETIREMENT_FINAL_BYTES`

## Baseline and implementation

- Baseline commit: `046b9acfdc9ba541faff65ff3713961890684303`
- Baseline tree: `047a43ba687f45c298139b595756dac84ab729da`
- Implementation commit: `faf13ba4d5fe54aa7f0347fed74e5789570ee321`
- Implementation tree: `db0870c30dd525c748d24ebdd1b261f96eb8a796`

Only the requested authoring sources and focused test were changed:

- `src/herzchen/authoring/cleanup.py`
- `src/herzchen/authoring/finish.py`
- `src/herzchen/authoring/idle.py`
- `src/herzchen/authoring/integration.py`
- `src/herzchen/authoring/sessions.py`
- `src/herzchen/authoring/snapshots.py`
- `tests/authoring/test_gf03_retirement.py`

## Design outcome

Manual and idle finish now accept a deterministic `capture_barrier`. The
shared finish boundary performs the host quiescence/writer check, captures a
stable tree, invokes the barrier, rechecks the fence, and verifies the exact
capture manifest before handler application, durable claim retirement, or
cleanup. A changed manifest enters durable `recovery_pending`/released state;
the old finish is not committed and the changed file is not deleted.

The durable finish/recovery payload carries `retirement_manifest` plus a
`retirement_fence` binding session, token, fence, and manifest digest. The
lifecycle and idle cleanup paths convert that exact manifest to path/digest/
size entries. Cleanup rechecks digest and size as well as identity immediately
before unlink, so an in-place late write cannot become a just-in-time baseline.
Unknown writer responses remain unsafe. `fresh_capture=True` is an explicit
retry path: it requires a new stable capture/fence, persists the late bytes as
the new final snapshot, and only then permits deletion.

## Late-write evidence

`tests/authoring/test_gf03_retirement.py` proves:

- manual late write after capture returns `recovery_pending`, leaves the late
  bytes on disk, rejects cleanup against the old manifest, and succeeds only
  after a fresh durable capture;
- idle finish exercises the same barrier and retry path;
- a late in-place write injected during cleanup yields durable `UNSAFE` and
  leaves the late bytes intact;
- unknown writer state blocks deletion;
- unchanged manual and idle finishes still persist completion and clean files.

## Test commands and results

The specified interpreter was used:

```text
/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python
```

Without a source path, collection reported `ModuleNotFoundError` because this
isolated checkout is not installed in that environment. The following are
functional source-checkout runs using that interpreter and an explicit
`PYTHONPATH`; they are not installed-package proof:

```text
PYTHONPATH="$PWD/src" .../int-02/bin/python -m pytest -q tests/authoring/test_gf03_retirement.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py tests/authoring/test_failure_matrix.py tests/authoring/test_handoff.py
24 passed, 1 skipped

PYTHONPATH="$PWD/src" .../int-02/bin/python -m pytest -q tests/authoring
40 passed, 1 skipped

PYTHONPATH="$PWD/src" .../int-02/bin/python -m pytest -q tests/authoring tests/content/test_document_authoring_contract.py tests/packs/test_authoring.py
53 passed, 12 skipped

PYTHONPATH="$PWD/src" .../int-02/bin/python -m pytest -q
264 passed, 12 skipped, 80 subtests passed
```

The skips are existing environment/install-gated tests, including the fresh
process installed-wheel proof. `git diff --check` passed. No product/control
files, packet evidence, or the original foundation review were modified.

## Bounded residual issue

The correction preserves the existing compatibility behavior for direct
cleanup callers that provide bare paths. Shared lifecycle retirement always
uses the exact durable manifest. No GF01-owned port change was required.
