# GF01/GF02 replay semantic correction result

Date: 2026-09-14 (Europe/Berlin)

This is a correction candidate and evidence handoff. It does not claim gate
acceptance, consumer cutover, or product behavior.

## Custody and lineage

- GF01 checkpoint: `c9a797882ee128dfd6aabf63df0610251db9db0c`, tree
  `db71b18fdb5fddaf6a88938b251b745db399b18e`.
- Accepted GF02 source lineage: `3950476ede81d03bc746d656634b9df7cd31fc4d`.
- Integration cherry-pick baseline: `f7712bd8a52df29619c582fbdc67deb7927f9738`,
  tree `33182f521d274b5720704086d7bac51d557fd66e`.
- Prior Store integration checkpoint: `b480890086d92c968deeff25fffa6c145828c551`,
  tree `007e8b7aa91cd92b3dc342948ff7bff3e90f712f`.
- The worktree was verified at exactly `b480890` / `007e8b7` before this
  correction. Generated `__pycache__` directories were the only initial
  untracked paths and were cleaned.
- Worker route/session evidence: GF01 implementation continuation on
  `gpt-5.6-sol`, high reasoning, branch `gf01-correction-worker`. The runtime
  exposes no separate CLI/session receipt identifier.
- Supplied baseline-failure receipt remains unchanged: raw-output SHA-256
  `77a1d929aa3fa0b293ffcd7db94be81dd8acd3e138fb6b7ee10ab572208e7ab4`;
  report SHA-256
  `10403df1841719be50e290dffa1e40097a6c3edc030fd5f4429a81313917dc`.

## Changed source and test lineage

- `src/herzchen/kernel/operations.py` (SHA-256
  `cd326b6f2b87116249efe5b821669462f9398831a987d9cb6627cae9cd947c52`):
  `OperationRequest.envelope` now derives its context digest from the exact
  payload carried by the envelope using the sole helper imported from
  `herzchen.contracts.canonical_request_digest`. `_transition` constructs the
  recovered original-operation identity and full outcome payload once, then
  uses the same envelope for the pre-Store replay check and Store mutation.
- `tests/kernel/test_receipts_limits.py` (SHA-256
  `cf7e62897203848ba7dcd3d7094b450a2229e606b90555d25ef9797528f7279e`):
  adds `test_outcome_replay_binds_full_semantics_before_any_delta`, covering
  exact idempotent replay and changed result, state, target, original
  operation, and resolver actor with reused caller digests. Every conflict is
  checked against unchanged identity/event/receipt/reference/sequence counts
  through `ConsumerStore.snapshot_counts()`.
- Canonical helper definition remains solely in
  `src/herzchen/contracts/model.py`; no local digest helper was introduced.
- No LimitService source, Store admission, extension, DAT, WRK, PKG, EDT,
  control, map, or prior result file was edited.

The outcome event continues to use `transition_actor` (the authenticated
resolver for explicit resolution), while the reconstructed stored operation
request retains the original request actor. Store still independently
canonicalizes the same public envelope and ignores any caller digest.

## Source proof

Verified interpreter:
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`

An initial command omitted `PYTHONPATH=src` and resolved the interpreter's old
installed package. It exited 2 during collection (four import errors); no tests
ran. This is not substantive source evidence.

Correct source command (exit 0):

```text
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/kernel/test_receipts_limits.py tests/kernel/test_public_mutation_admission.py tests/extensions/test_definition_admission.py tests/extensions/test_namespaces.py
.....................................                                    [100%]
37 passed in 0.21s
```

This covers the accepted GF02 receipt/LimitService suite plus GF01 admission,
definition-digest, altered-catalog, owner-spoofing, and extension namespace
paths. `git diff --check` exited 0.

The affected legacy conformance probe was also run alone (exit 1):

```text
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .../int-02/bin/python -m pytest -q tests/conformance/test_int03_public_api_probes.py
1 failed in 0.11s
```

Its first direct `Store.mutate` uses the unregistered combination
`probe.record.create` / `probe.record` / `probe.record.created` /
`int03.probe.v1`, which correctly raises `MutationAdmissionError`. Updating
that probe to register an explicit handler capability is a downstream test
obligation; admitting arbitrary probe names would weaken GF01.

## Candidate-installed proof

Build command (exit 0):

```text
env PYTHONDONTWRITEBYTECODE=1 .../int-02/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /private/tmp/gf01-gf02-replay-wheel.T3J5ez .
```

- Wheel: `/private/tmp/gf01-gf02-replay-wheel.T3J5ez/herzchen_contracts-0.1.0-py3-none-any.whl`
- Size: 192759 bytes
- SHA-256: `39a69a863a4dfc1f46bf52664a5b4bc9104c860f080c3675b2468f0610d92be0`
- Disposable venv: `/private/tmp/gf01-gf02-replay-installed.5l1jJB`
- Install exited 0 with `--no-deps`.

With `PYTHONHOME` and `PYTHONPATH` unset, an isolated origin probe reported
both as null and resolved every checked module under candidate site-packages:

```text
herzchen   /private/tmp/gf01-gf02-replay-installed.5l1jJB/lib/python3.12/site-packages/herzchen/__init__.py
contracts  /private/tmp/gf01-gf02-replay-installed.5l1jJB/lib/python3.12/site-packages/herzchen/contracts/__init__.py
kernel     /private/tmp/gf01-gf02-replay-installed.5l1jJB/lib/python3.12/site-packages/herzchen/kernel/__init__.py
operations /private/tmp/gf01-gf02-replay-installed.5l1jJB/lib/python3.12/site-packages/herzchen/kernel/operations.py
store      /private/tmp/gf01-gf02-replay-installed.5l1jJB/lib/python3.12/site-packages/herzchen/kernel/store.py
limits     /private/tmp/gf01-gf02-replay-installed.5l1jJB/lib/python3.12/site-packages/herzchen/kernel/limits.py
```

Installed test command used `python -I`, appended only the verified
interpreter's pytest site-packages after candidate site-packages, and passed
the same four absolute test paths (exit 0):

```text
.....................................                                    [100%]
37 passed in 0.20s
```

The tests are external source files, but all `herzchen` imports were proven to
originate from the disposable candidate installation.

## Bounded downstream obligations

- `tests/work/test_identity_graph.py`: three existing tests construct
  `WorkGraph` without `graph.register()`, so `work.create` is unregistered; a
  fourth registers the graph but uses actor authority `test` against owner
  `wrk` without an explicit handler/actor binding. These are downstream WRK
  composition/actor-binding omissions and were not altered.
- `tests/conformance/test_int03_public_api_probes.py:328`: the direct raw Store
  probe must migrate to an explicitly registered capability or supported
  consumer composition.

No broad admission fallback, same-name exception, actor/owner equivalence, or
special replay bypass was added.

## Commit custody

The substantive files and this result are ready, but the execution sandbox
cannot create the linked worktree Git metadata lock at
`.../Herzchen/.git/worktrees/Herzchen-gf01-correction-worker/index.lock`.
The attempted `git add`/commit exited 128 with `Operation not permitted`.
Manager must commit these three paths and then append the resulting commit and
tree (and copy this tracked result to the requested canonical external work
location if required):

```text
/usr/bin/git add src/herzchen/kernel/operations.py tests/kernel/test_receipts_limits.py work/gf01-gf02-replay-correction-result.md
/usr/bin/git commit -m "Align operation outcome replay semantics"
/usr/bin/git rev-parse HEAD HEAD^{tree}
```
