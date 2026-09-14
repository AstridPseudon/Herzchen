# GF02/C33 persisted replay closure result

Date: 2026-09-14
Worker base: `ff5d85cc09ace8731845e8c7fb54d63bfd07e081`
HEAD tree at start/final audit: `a6f030b399a747524dc356e632e90b02a1647083`
Implementation parent: `ef13cfed36f8d43925a28e8312bf0235379b1488`

## Outcome

PASS for the bounded reproduced persisted exact-retry closure. Changes are
left unstaged for the manager; no commit was rewritten, and no review, oracle,
gate, upstream, control, Store, contract, command-port, or C33-conformance
checkout was changed.

The service/domain paths now compose a stable caller-intent request payload
with a separate derived identity payload. Same-key replay is presented to the
admitted Store using the original receipt target and precondition before the
current projection is read. The original receipt/result snapshot is returned;
changed request/precondition inputs reach Store replay validation and produce a
conflict before any durable delta.

## Implementation and tests

Implementation files:

- `src/herzchen/domains/work/module.py`: `WorkGraph.revise`, parent/dependency
  linking, and readiness state mutation replay/result closure for all six
  `WorkKind` values.
- `src/herzchen/domains/work/batches.py`: `work.project.activate` stable
  request composition, original-base replay, and optional backward-compatible
  `base_revision` precondition.
- `src/herzchen/domains/assessment/module.py`:
  `assessment.finding.close` replay before stale finding validation.
- `src/herzchen/domains/work/assignments.py`: `reassign` replay and original
  assignment result snapshot.
- `src/herzchen/packs/authoring.py`: `pack.content.author` stable request and
  original content snapshot replay.
- `src/herzchen/authoring/sessions.py`: `release` and its persisted
  `actor.release` composition, with capability validation retained before an
  exact replay.

Focused regression file:

- `tests/work/test_gf02_c33_replay_closure.py` — 9 collected tests covering:
  six work kinds; `work.revised`; parameterized
  `work.parent-linked`, `work.dependency-linked`, and `work.state-changed`;
  project activation; finding close; assignment reassign; managed-pack
  authoring; and authoring release/actor release. Each reproduced case proves
  exact receipt/result replay and changed-input/precondition conflict with
  unchanged `(identities, references, receipts, events)` counts. Authoring
  release also reopens the Store and repeats the exact request.

The supplied public handler/mutate/transaction interface remains intact.
`identity_payload` continues to be passed through the existing handler port;
no private writer or SQL path was added. The one interface addition is the
optional `base_revision` keyword on `ProjectBatches.activate_project`, which
defaults to prior behavior. FND typed-port work can merge these service-level
changes without adapter changes. The semantic assumption is that a pinned
caller object/reference is part of the logical precondition; a changed pin,
generation, base revision, or caller argument therefore conflicts even when a
same-key receipt exists.

## Evidence

Source-origin command, PID 2154, started
`2026-09-14T08:14:54.670704000Z`, ended
`2026-09-14T08:14:56.678678000Z`, exit 0:

```text
env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.11 -m pytest -q tests/kernel tests/work tests/assessment/test_accounting.py tests/authoring/test_finish.py tests/authoring/test_exclusivity.py tests/packs/test_authoring.py
153 passed, 11 skipped, 10 subtests passed in 1.71s
```

Installed-origin command, PID 2220, started
`2026-09-14T08:15:07.887332000Z`, ended
`2026-09-14T08:15:09.924257000Z`, exit 0:

```text
env -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 PYTHONPATH='' /private/tmp/gf02-c33-venv.JwF7u1/bin/python -m pytest -q tests/kernel tests/work tests/assessment/test_accounting.py tests/authoring/test_finish.py tests/authoring/test_exclusivity.py tests/packs/test_authoring.py
153 passed, 11 skipped, 10 subtests passed in 1.75s
```

Installed module origins were under
`/private/tmp/gf02-c33-venv.JwF7u1/lib/python3.11/site-packages/herzchen/`;
the wheel was built from this worker tree as
`/tmp/gf02-c33-wheel-20260914/herzchen_contracts-0.1.0-py3-none-any.whl`.
Python `3.11.16` was used. `/opt/homebrew/bin/python3.12` was unavailable on
this host and is recorded as unavailable, not waived or substituted.

The corrected DAT/C33 root-package evidence was used read-only to classify the
bounded reproduced cases. This result does not claim the wider C33 matrix is
complete.

## Working-tree custody

The six implementation files and focused test are intentionally unstaged.
The supplied follow-up brief and launch receipt remain unedited. No push or
merge was performed. `git diff --check` passed and the final audit found no
generated `__pycache__` directories in `src` or `tests`.
