# EDT-04 worker result — idle-close and recoverable cleanup

## Delivery identity

- Invoking root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20`
- Control root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery`
- Package: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2`
- Worker worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-edt04-worker`
- Branch: `edt-04-worker`
- Accepted baseline commit/tree: `5a28e1fee1811d77c0a6558311c77525c36ed069` / `640ac1a230d0535bde7ab23d172e2faf76b3f101`
- Final implementation commit/tree: `61bbedd1f682e2a7cd511b4081b1a89d4da16e6d` / `5c59ff7ece86b21a90c4e2bf274056b05479f09e`
- Final implementation worktree proof: `git status --short --branch` returned `## edt-04-worker` with no changes.
- Route/model/reasoning: normal / `gpt-5.6-luna` / high; no XHARD or Sol route.

## Launch and provenance

- Brief: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/edt-04-worker-brief-20260914.md`
- Brief SHA-256: `3d863519b5c458e0af7d959e27ea0372af5b56ecb71ee56cde6b4fc95c7e550e`
- Launch receipt: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/edt-04-worker-launch-receipt-20260914.json`, SHA-256 `94cebaefc135b518bcf19860d9ae9003a954591e7d780c21fef638e77754c33c`
- JSONL: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/edt-04-worker-jsonl-20260914.txt`, SHA-256 at handoff `acdca22d8ae98f64414806445d0e8a30a8eeb9bdd02f3889a50d2d5ff820da4c`
- Launch command: `/Users/hannahomalley/.local/bin/codex exec --skip-git-repo-check -m gpt-5.6-luna -c model_reasoning_effort=high -s danger-full-access --json -o /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/edt-04-worker-last.txt < /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/edt-04-worker-brief-20260914.md | tee /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/edt-04-worker-jsonl-20260914.txt`
- Process/session identity from manager receipt: CLI thread `01a09d39-19af-7721-9ebf-f234747e31ef`, functions session handle `56088`.
- Observed dispatch status: `in_progress` at receipt; the JSONL records the worker command and terminal completion results listed below.
- Source manifest: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`, SHA-256 `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.

## Implemented scope

- `src/herzchen/authoring/idle.py`: one-shot idle policy based on persisted/declared last content-edit time; reads and polling do not refresh it; writer quiescence/active/unknown fencing; shared EDT-03 semantic finish; exact untouched pending blank close without a fabricated revision; retryable cleanup status; additive content-edit timestamp declaration through the supplied session writer.
- `src/herzchen/authoring/cleanup.py`: descriptor-relative registered-file cleanup; root/parent identity checks; `O_NOFOLLOW` file opens; regular-file/type/size/SHA-256 checks immediately before deletion; unexpected-file, symlink, traversal, parent/root swap, open/unknown writer and partial-deletion fail-closed outcomes.
- `src/herzchen/authoring/__init__.py`: minimal exports.
- `tests/authoring/test_failure_matrix.py`: focused EDT-04 matrix with real temporary files and SQLite-backed session state.

No FND/DAT/WRK/PKG/OTT source, `sessions.py`, `snapshots.py`, `finish.py`, schema, host adapter, package metadata, extraction map, package seed, control ledger, or other owner worktree was edited.

## Reuse and boundary decisions

The applicable extraction-map entry is `EX-EDIT` at `plan/extraction-map.json:1293-1455` (manifest source map). Its decision is `extract_generalise`, with the stated reason that safe path/byte/CAS/transaction/receipt mechanics are reusable but the idle lifecycle, writer acknowledgement and registered cleanup are new EDT-owned behavior.

- Adapted the safe-path and descriptor-relative identity intent from Runtime `runtime_protocol/dirfd.py`, blob `4f936bebd4dae78c09c33603596431627e8409c6`, lines `129-172;185-210;241-299;398-424;492-560`. The new cleanup does not import Runtime or copy a Runtime store; it retains only the narrow no-follow, parent/root identity, regular-file, exact-read/hash and relative-descriptor approach.
- Adapted Runtime `runtime_protocol/cas.py`, blob `d0c3bf4b4d3d81176cfb87c10bf08133f9e2e12a`, lines `11-79`, as SHA-256 verification for registered bytes. Durable preservation remains through the supplied FND/EDT `Snapshot` boundary.
- Reused the accepted EDT-03 `SemanticFinishAdapter` and `AuthoringSessionService.finish`; manual/idle claim, validation, rejected-draft persistence, application recovery, actor release, receipt/event boundary and replay remain in the common owner. The accepted evidence is `work/edt-03-result.md:25-42`.
- Retained/adapted test intent from Runtime `tests/test_dirfd_publication.py`, blob `933d727cd496cd716d9c4db95d1a8c68bc615ed5`, lines `45-176;178-297`: parent replacement/symlink, concurrent-swap safety, pinned reads and cleanup safety. Runtime `tests/test_runtime_domains.py`, blob `8b5529ddd4e1accc239aa6c23000af54ed846646`, lines `42-77;221-300`, supplied concurrent replay/rollback/restart-replay intent.
- Astrid is lineage only. No Astrid loader, SDK, runtime import, product lifecycle or cutover was added; the manifest explicitly says its installed origin is unproven.

## Verification commands and observed exits

All candidate build/proof commands used `/opt/homebrew/bin/python3.11` (Python `3.11.16`). Installed proof commands unset both `PYTHONPATH` and `PYTHONHOME`.

1. Pre-edit `pwd; git status --short --branch; git rev-parse HEAD^{commit}; git rev-parse HEAD^{tree}` — exit `0`; exact accepted baseline confirmed.
2. `env -u PYTHONPATH -u PYTHONHOME /opt/homebrew/bin/python3.11 -m compileall -q src/herzchen/authoring` — exit `0`.
3. `env -u PYTHONHOME PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.11 -m pytest -q tests/authoring/test_failure_matrix.py tests/authoring/test_exclusivity.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py` — exit `0`; `26 passed in 0.30s`. This is source-checkout development proof only.
4. `env -u PYTHONPATH -u PYTHONHOME /opt/homebrew/bin/python3.11 -m pytest -q tests/authoring` before installation — exit `1`, expected `ModuleNotFoundError: No module named 'herzchen'`; source checkout is not installed-origin proof.
5. `env -u PYTHONPATH -u PYTHONHOME /opt/homebrew/bin/python3.11 -m pip wheel . --no-deps -w /tmp/herzchen-edt04-candidate-final.XGAgDS/dist` — exit `0`.
6. Final candidate wheel: `/tmp/herzchen-edt04-candidate-final.XGAgDS/dist/herzchen_contracts-0.1.0-py3-none-any.whl`; SHA-256 `78d1e6f5ef80f4b123cfb402466589616ecb314fc47438c53e82b610f9ba11ad`.
7. Disposable venv creation and installation with `/opt/homebrew/bin/python3.11 -m venv ...` and `pip install --no-deps pytest wheel` — exit `0`; pytest dependency correction `pip install pytest` — exit `0`.
8. Installed-origin command with `env -u PYTHONPATH -u PYTHONHOME`: exit `0`. `herzchen`, `idle`, and `cleanup` resolved from `/private/tmp/herzchen-edt04-candidate-final.XGAgDS/venv/lib/python3.11/site-packages`; site-packages origin was recorded in the terminal output.
9. Installed focused matrix, `env -u PYTHONPATH -u PYTHONHOME .../venv/bin/python -m pytest -q tests/authoring/test_failure_matrix.py` — exit `0`; `7 passed in 0.07s`.
10. Installed EDT-02/03 regressions, `... -m pytest -q tests/authoring/test_exclusivity.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py` — exit `0`; `19 passed in 0.09s`.
11. Fresh installed persisted-state probe, `env -u PYTHONPATH -u PYTHONHOME .../venv/bin/python` with a new SQLite file and real temporary checkout files — exit `0`; untouched blank => `pending_released`, edited blank => `finished`, both => cleanup `COMPLETE`, two `authoring.finish` and two `authoring.cleanup` events, two committed finish and cleanup receipts, restart read `ok`.
12. Final `git diff --check`, changed-path hashes and clean-worktree audit — exit `0` at implementation commit.

The first final-wheel test attempt exited `1` because `--no-deps` was accidentally applied to pytest, producing `ModuleNotFoundError: pluggy`; the venv was corrected and the exact installed tests then passed. It is retained as an environment setup observation, not code proof.

## Matrix evidence

- Idle basis: `test_idle_uses_last_content_edit_not_polling_and_untouched_blank_is_retained` and `test_declared_content_edit_time_is_persisted_and_polling_does_not_refresh_it` (`tests/authoring/test_failure_matrix.py:59-108`) prove controlled time, persisted declaration, no polling refresh, untouched blank close, durable release and only registered-file deletion.
- Edited blank: `tests/authoring/test_failure_matrix.py:110-134` proves ordinary changed content uses common finish, applies once, cleans the file, rejects the old token and reopens with a new token/turn.
- Rejected draft: `tests/authoring/test_failure_matrix.py:136-159` proves exact `malformed\\x00draft` bytes survive into the durable snapshot, diagnostics survive, adopted state is not applied, release occurs, and cleanup follows release.
- Writer/capture uncertainty: `tests/authoring/test_failure_matrix.py:161-191` proves active/unknown writer returns `writer_active` with bytes retained; capture failure returns `recovery_pending`, retains bytes, and does not falsely claim a clean close or delete.
- Cleanup safety: `tests/authoring/test_failure_matrix.py:193-218` proves unexpected files, symlinks and a parent/root swap are `UNSAFE` and preserved. `:220-231` proves one-file deletion followed by a second failure returns `deleted`/`remaining` and a retry can complete the remaining file.
- Shared manual/idle race and replay lineage: accepted EDT-03 `tests/authoring/test_finish.py:49-111` proves valid manual/idle race and one application; `:113-158` proves rejected/recovery/capture outcomes. Accepted EDT-02 `tests/authoring/test_exclusivity.py:237-275` proves exact replay, reopen/new turn and stale-token denial.
- Two-service scope race: accepted EDT-02 `tests/authoring/test_exclusivity.py:103-169` proves the shared FND reservation across service instances. A concurrent two-service *finish* probe against the unchanged EDT-03 port was not claimed as a pass: the loser can enter the baseline recovery path after the winner retires the token. Fixing that would require the explicitly prohibited `sessions.py` change; EDT-04 therefore documents the boundary rather than rewriting it.
- Blank persistence: the installed fresh probe used a new DB and real files, retained both durable authoring scopes/history identities, produced no fake task/revision/dispatch in the untouched pending path, and removed only `project.txt`.

## Changed-path SHA-256

These are the final implementation-commit file bytes:

```text
3aa87655cab06068c1724178834ffd3445be042ff68a08b38a893f3ebc305e60  src/herzchen/authoring/idle.py
f3aed208d4b90c67d35a7e8cfbad81d3d561207002b5a716c74bcdfb5da98dae  src/herzchen/authoring/cleanup.py
5e9d4f85fc0b1f53ce4fc5390f4d271a80c547e592cc66c85abfc509dcf35988  src/herzchen/authoring/__init__.py
81b318a2cca230494ab5568e636b58714adb3186cce62333828c607a8c580f05  tests/authoring/test_failure_matrix.py
```

## Explicit gaps and verdict

- EDT-05 remains open: no three-target project/document/pack handler wiring was added.
- EDT-06 remains open: no consumer handoff/acknowledgment protocol was added.
- Cross-service concurrent finish loser handling remains the accepted EDT-03 port boundary described above; no source outside EDT-04 ownership was changed.
- No product/Astrid cutover verdict is made. Runtime/Astrid source pins are lineage only, and installed Astrid/Runtime origin remains unproven.
- No upstream push/merge or control-ledger write was performed.

## Handoff pointers

- JSON handoff: `handoffs/EDT.json`
- Receipt: `work/edt-04-receipt.json`

## Correction supplement — cross-service finish loser reconciliation

This is an owner-authorized EDT-04 continuation. The original candidate,
launch receipt, JSONL, and original report sections above are retained
unchanged as lineage. The correction started from the exact recorded baseline
commit/tree `4d654b086a8da7cd0d8b5b36acf7ca4e49d1f0a3` /
`739ec55cdefb820e4806c6b75438628d3c467e39` and preserves implementation
parent `61bbedd1f682e2a7cd511b4081b1a89d4da16e6d` /
`5c59ff7ece86b21a90c4e2bf274056b05479f09e`.

The new correction commit is `4769c1153fd3177271b4d849cb7a3fceb450273b`
with tree `95a492ac07adbb33ab1f384d1b25b82d7485b06f`. It changes only
`src/herzchen/authoring/finish.py` and the focused
`tests/authoring/test_failure_matrix.py` regression. The adapter now uses the
supplied Store transaction around the existing common `AuthoringSessionService.finish`
boundary, allowing separate services to serialize on the shared durable writer
without an EDT lock, retry loop, second store, SQL, or receipt engine. It then
reconciles only a finished/released checkout with the same session/token/fence,
target/actor/base/pending semantics, shared `finish-<session>` claim, matching
packed snapshot digest, and committed durable `finish` receipt. A changed or
foreign/stale capability remains a recovery-safe non-success; genuine capture
and application failures have no committed finish receipt and remain
`recovery_pending`.

The focused regression is `tests/authoring/test_failure_matrix.py:138-232`.
It constructs two `AuthoringSessionService` and two `SemanticFinishAdapter`
instances over one supplied Store, gates both validations with a barrier, and
asserts one `finished` plus one `already_finished`, one handler application,
one finish receipt/event, coherent finished claim/state, exact replay as
`replayed`, changed-input non-success, and stale-token non-success. Existing
manual/idle, rejected-draft, capture/application failure, blank-project,
cleanup-safety, and EDT-02/03 tests remain in the source suite.

### Correction proof commands and exits

All proof used `/opt/homebrew/bin/python3.11` (Python `3.11.16`). Installed
proof unset both `PYTHONPATH` and `PYTHONHOME`.

1. `env -u PYTHONHOME PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.11 -m pytest -q tests/authoring/test_failure_matrix.py::FailureMatrixTests::test_cross_service_finish_loser_reconciles_durable_winner` — initial exit `1` (`finished` + `recovery_pending` before the post-recovery reconciliation adjustment); rerun after correction exit `0`, `1 passed`.
2. `env -u PYTHONHOME PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.11 -m pytest -q tests/authoring/test_failure_matrix.py tests/authoring/test_exclusivity.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py` — exit `0`, `27 passed`.
3. `/opt/homebrew/bin/python3.11 -m pip wheel . --no-deps --wheel-dir /tmp/herzchen-edt04-correction.55AJdU/dist` — exit `0`; new wheel `/tmp/herzchen-edt04-correction.55AJdU/dist/herzchen_contracts-0.1.0-py3-none-any.whl`, SHA-256 `fb39f36bd5ec2b35d22fccde16f497469eb8e9012366954f039cf9baf4d3dd3e`.
4. `/opt/homebrew/bin/python3.11 -m venv /tmp/herzchen-edt04-correction.55AJdU/venv` — exit `0`; pip installation of pytest and the wheel (`/tmp/herzchen-edt04-correction.55AJdU/venv/bin/python -m pip install pytest && ... -m pip install --no-deps <wheel>`) — exit `0`.
5. `env -u PYTHONPATH -u PYTHONHOME /tmp/herzchen-edt04-correction.55AJdU/venv/bin/python -c 'import herzchen, herzchen.authoring.finish, herzchen.authoring.sessions, sys; ...'` — exit `0`; origins were `/private/tmp/herzchen-edt04-correction.55AJdU/venv/lib/python3.11/site-packages/herzchen/__init__.py`, `/private/tmp/herzchen-edt04-correction.55AJdU/venv/lib/python3.11/site-packages/herzchen/authoring/finish.py`, and corresponding `sessions.py`; site-packages was `/private/tmp/herzchen-edt04-correction.55AJdU/venv/lib/python3.11/site-packages`.
6. `env -u PYTHONPATH -u PYTHONHOME /tmp/herzchen-edt04-correction.55AJdU/venv/bin/python -m pytest -q tests/authoring/test_failure_matrix.py tests/authoring/test_exclusivity.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py` — exit `0`, `27 passed` from installed package origins.
7. First fresh persisted-state probe using a nested document without its canonical parent — exit `1`, setup-only `ScopeResolutionError`; no code assertion ran and it is not counted as proof.
8. Corrected fresh persisted-state probe using a new SQLite file, new project scope, real checkout file, close/reopen, receipt/event readback, and exact replay — exit `0`; `first finished`, persisted state `finished`, receipt `finish committed 1`, one `authoring.finish` event, replay `replayed`.
9. Final `git diff --check`, changed-path hash, and clean-worktree audit — exit `0`.

### Correction hashes, retained evidence, and residual gaps

Correction changed-path SHA-256 values:

```text
0e450e9126dad0657161c080f5312830384f52b34d84c4383002a1edc659c8c7  src/herzchen/authoring/finish.py
e157cd8308c454c66bf285cd7044f4e8a2780f7c9e2cfb184264bce1c16ae267  tests/authoring/test_failure_matrix.py
```

The source manifest remains
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`
with SHA-256
`742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.
`EX-EDIT` remains `plan/extraction-map.json:1293-1455`; the retained Runtime
dirfd/CAS and test blobs are the exact lineage listed above. The correction
reuses EDT-03 `finish.py`/`sessions.py` claim, transaction, release, receipt,
event, and replay contracts and adds only EDT-owned adapter reconciliation;
`sessions.py`, FND, schema, package metadata, control artifacts, and other
owners remain untouched.

EDT-05 target-handler unification and EDT-06 consumer handoff remain open.
No product/Astrid cutover is claimed. No upstream push/merge or control-ledger
write occurred.
