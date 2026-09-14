# EDT-06 result — authoring service and recovery evidence

Status: worker evidence complete. This is not a gate verdict and does not
claim product/Astrid/Runtime cutover or remote-host support.

## Identity and immutable inputs

- Invoking root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20`
- Control root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery`
- Worker: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-edt06-worker`
- Branch: `edt-06-worker`
- Baseline commit/tree: `dfc323203843e0b58cc0790485cb6e7b825d6c02` /
  `efe0ae1ed39643042ec2f87b00ca537f08ea6a28`
- Accepted EDT-05 implementation commit/tree:
  `023de7472e15c8b64356dc1d2b3a400071502462` /
  `c449148badec5670358499411920dacce6fdb3b4`
- Source manifest:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`
- Manifest SHA-256:
  `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`
- Executable evidence commit/tree:
  `77bd75e4b4047d3ca32550f299d2b9cf2305dbfa` /
  `61f2f9a6141a38c4ac3706f8842838993ec930df`

The accepted EDT-05 implementation was retained. EDT-06 added only
`tests/authoring/test_handoff.py`; no source implementation, package seed,
control root, manifest, upstream, or FND-07 file was changed.

## Platform and installed provenance

Primary platform was macOS 15.6.1 arm64, Darwin kernel 24.6.0. The host
interpreter was `/opt/homebrew/bin/python3.11`, Python 3.11.16 built with
Clang 17.0.0. Packaging used `setuptools.build_meta` with
`setuptools>=68`; the disposable test environment used pip 26.2.1 and
pytest 9.1.1.

Exact build commands:

```text
/opt/homebrew/bin/python3.11 -m venv /tmp/herzchen-edt06-final-EGvLDv/venv
/tmp/herzchen-edt06-final-EGvLDv/venv/bin/python -m pip install --quiet pytest
/tmp/herzchen-edt06-final-EGvLDv/venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/herzchen-edt06-final-EGvLDv/wheels .
/tmp/herzchen-edt06-final-EGvLDv/venv/bin/python -m pip install --quiet /tmp/herzchen-edt06-final-EGvLDv/wheels/herzchen_contracts-0.1.0-py3-none-any.whl
```

Wheel build and hash:

```text
exit 0
130892bee07f23212be0d4adf64b0caf9deb51472a832dc5b7b99fcec8cce051  /tmp/herzchen-edt06-final-EGvLDv/wheels/herzchen_contracts-0.1.0-py3-none-any.whl
```

The installed site-packages root was
`/private/tmp/herzchen-edt06-final-EGvLDv/venv/lib/python3.11/site-packages`.
`env -u PYTHONPATH -u PYTHONHOME` was used for the provenance probe and
installed suite; both variables printed as unset. `herzchen`,
`herzchen.authoring.integration`, `cleanup`, `idle`, `snapshots`, `sessions`,
`herzchen.content.authoring`, `herzchen.domains.work.batches`,
`herzchen.packs.authoring`, and `herzchen.kernel.store` all resolved below
that site-packages root.

## Commands and exits

```text
/opt/homebrew/bin/python3.11 -m compileall -q src tests
exit 0

PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.11 -m pytest -q
exit 0; 212 passed, 12 skipped, 80 subtests passed in 1.29s

PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.11 -m pytest -q tests/authoring/test_handoff.py tests/authoring/test_three_targets.py tests/authoring/test_failure_matrix.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py
exit 0; 25 passed, 1 skipped in 0.33s

env -u PYTHONPATH -u PYTHONHOME /private/tmp/herzchen-edt06-final-EGvLDv/venv/bin/python -m pytest -q tests/authoring/test_handoff.py tests/authoring/test_three_targets.py tests/authoring/test_exclusivity.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py tests/authoring/test_failure_matrix.py tests/content/test_document_authoring_contract.py tests/content/test_documents.py tests/work/test_batches.py tests/work/test_identity_graph.py tests/packs/test_authoring.py tests/packs/test_composition.py
exit 0; 88 passed, 11 skipped in 0.61s

git diff --check
exit 0
```

## Observed handoff and lifecycle proof

`tests/authoring/test_handoff.py` exercises the accepted
`AuthoringLifecycle`, `SemanticFinishAdapter`, `IdleCloseService`,
`DurableSnapshotAdapter`, `cleanup_registered_files`, `AuthoringSessionService`,
and `Store` surfaces. EDT-05’s real DAT, WRK, and PKG owner tests remained in
the installed affected run and passed.

A direct installed probe used two fresh processes against one real temporary
database and checkout:

- Writer PID 2333 used `/tmp/herzchen-edt06-probe-9qv6R3/handoff.sqlite` and
  `/tmp/herzchen-edt06-probe-9qv6R3/checkout`, finished with `state=finished`,
  committed receipt, and complete cleanup. The registered checkout file was
  absent afterward.
- Reader PID 2334 reopened the same database, returned `available`, read
  `state=finished` and `cleanup=complete`, and read exact snapshot bytes
  `exact probe bytes`.
- Both processes reported the same snapshot ref and receipt event ID
  `event-0fd6321fd127f342b8560992a2ac904c`. The linked event after-ref was
  `edt06-probe/authoring-scope/probe-target@rev-3`; the exact final snapshot
  digest was
  `2d382b76664419fd6154992aec98fa92c4f68d1c5389f427e7ff60c722a2e4e2`.
- The process test also closes/reopens after recovery and confirms durable
  snapshot readback. A separate unsaved-buffer assertion confirms that only
  persisted opening bytes are recoverable; an unsubmitted memory-only edit is
  not claimed recoverable.

Idle evidence used no model for waiting. A deterministic clock case with
`last_content_edit=100.0`, `now=105.0`, and a ten-second threshold returned
`not_idle` with `idle_seconds=5.0`. A short actual `threading.Timer(0.05)`
called `IdleCloseService` using real time and returned `closed_cleaned`, with
only the registered draft file deleted.

## Recovery and physical filesystem evidence

The direct recovery probe used:
`/tmp/herzchen-edt06-recovery-b9Zuki/recovery.sqlite` and
`/tmp/herzchen-edt06-recovery-b9Zuki/checkout`.

- A failed cleanup returned `unsafe`, persisted `cleanup_outcome=unsafe`, and
  left `registered.tmp` bytes intact.
- Adding `unmanaged-execution-materialisation.tmp` made the retry return
  `unsafe`; both registered and unmanaged files remained.
- Removing only the unmanaged file allowed a later registered-only retry to
  return `complete` and remove `registered.tmp`.
- `../outside.bin` raised `CleanupPathError`. A
  `pinned-execution.bin` symlink returned `unsafe`, remained a symlink, and
  its outside target retained `outside bytes`.
- Existing EDT-05/EDT-04 tests additionally cover malformed/rejected exact
  snapshots, no success receipt on rejection, symlink/parent replacement,
  partial deletion, token/fence fencing, ownership release, and retained PKG
  execution pins.

## Acceptance coverage and gaps

Evidence addresses the requested C07, C08, C09, C33, and C35 surfaces through
durable state, owner application, receipt/event links, process handoff,
deterministic and actual timer fixtures, physical cleanup, recovery, and
restart readback. It is not an acceptance claim or gate verdict.

Open limitations:

- Astrid/Runtime production adoption, product-private imports, publication,
  execution, manager/scheduler/readiness decisions, and remote-host support
  are not claimed.
- Remote finalisation remains explicitly unsupported pending an acknowledgement
  protocol.
- The separately running FND-07 race-correction scratch lane remains an open
  integration dependency; no correction was supplied to this lane and no
  FND-07 file was changed here.
