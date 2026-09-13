# EDT-03 worker result

Status: complete

## Handoff identity

- Branch: `edt-03-worker`
- Worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-edt03-worker`
- Accepted base commit: `182e36818eeac4595200a6f5d464e07efcb94ea9`
- Accepted base tree: `0d78ae4cf5fe2889de356bf079891897a240d7ba`
- Implementation commit: `6eeb3b7da6920e0871acb0036da92b0ebb2f9841`
- Implementation tree: `0720353cf741e6893911f269f30bf6eb8119e126`
- Source manifest: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`
- Source manifest SHA-256: `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`

Initial verification before editing:

```text
pwd: /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-edt03-worker
git status --short --branch: ## edt-03-worker
git rev-parse HEAD^{commit}: 182e36818eeac4595200a6f5d464e07efcb94ea9
git rev-parse HEAD^{tree}: 0d78ae4cf5fe2889de356bf079891897a240d7ba
```

## Implemented scope

- `src/herzchen/authoring/snapshots.py`: deterministic whole-tree capture for a registered relative-file set; absolute/`..`/symlink/path-escape, missing, unregistered, unsettled, and stat-change rejection; exact per-file bytes, manifest, tree digest, packed durable payload, draft autosave/no-op, and restart read through the supplied session writer.
- `src/herzchen/authoring/finish.py`: typed target-neutral validation/apply hooks; stable capture and preflight outside the short transaction; valid semantic application through `AuthoringSessionService.finish`; rejected draft diagnostics and recovery-pending application/capture failure outcomes; shared manual/idle claim and request replay behavior.
- `src/herzchen/authoring/__init__.py`: minimal exports.
- `tests/authoring/test_snapshots.py`: exact multi-file bytes/manifest, invalid paths, missing/unregistered files, symlink escape, unsettled writes, no-op autosave, restart read.
- `tests/authoring/test_finish.py`: valid application once, exact replay, concurrent manual/idle race, validation rollback/rejected draft, application failure, capture failure.

No edits were made to `sessions.py`, FND/DAT/WRK/PKG/OTT source, accepted worktrees, schema tables, host adapters, or cleanup/idle-close wiring.

## Reuse, adaptation, and new decisions

- Runtime `runtime_protocol/dirfd.py`, blob `4f936bebd4dae78c09c33603596431627e8409c6`, observations at lines 129–172, 185–210, 241–299, 398–424, and 492–560: adapted the narrow lexical-relative path, symlink, stable identity/stat, exact-read/hash safety intent. Descriptor-relative physical cleanup was not copied; `remove_tree_at` remains an EDT-04 concern.
- Runtime `runtime_protocol/cas.py`, blob `d0c3bf4b4d3d81176cfb87c10bf08133f9e2e12a`, lines 11–79: adapted exact SHA-256/content-addressed mechanics into the immutable packed snapshot payload. Persistence remains through `Snapshot` and the supplied writer, not a private CAS.
- Runtime `runtime_protocol/service.py`, blob `2a62a312f2e9e81adc9fbefe050904d917c42e8d`, lines 189–205, 756–844, and 2674–3135: retained as a source observation only. No second transaction, event, receipt, staging, or publication engine was copied; `AuthoringSessionService.finish` owns the common boundary and replay.
- Astrid `astrid/core/foundation/atomic_io.py`, blob `bc07c6f341f69028343ab0a26cd6566b27cb6948`, lines 37–156, and test blob `00220d8107b400a0494687bbff36ffa29a6a8dd7`, lines 46–235: retained the narrow exact-byte/target-preservation lesson only. No Astrid authoring lifecycle or durable semantic behavior was imported.
- Accepted EDT-02 `sessions.py` and `test_exclusivity.py`: retained `Snapshot`, `autosave`, `_capture`, `finish`, `read_snapshot`, `FinishClaim`, release/cleanup, and injected-writer semantics. New tests preserve the existing exact-snapshot/replay assertions and add only adapters around them.
- Accepted FND Store/transaction/receipt/event contract in `store.py` and `contracts/model.py`: used `Store.transaction()` and the session service; no private SQL is required by the new tests.

## Verification

Command and exit code:

```text
python3 -m compileall -q src tests                                  exit 0
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v exit 0
```

Final bounded test count: 68 tests, all passed.

Changed-path SHA-256 values at implementation commit:

```text
ad3bd1e4d3873ae08c54d7250317ae700d0225a4b055817bb47d8ae343e3edd2  src/herzchen/authoring/__init__.py
b408707a94b611d4a2aed73a1da7767d4477178d4aab3ddc601f14abcc51862b  src/herzchen/authoring/finish.py
c195fe8daf9509acdb5512935904efaca8f58adf12ad0f42f24bd22cfc8ad963  src/herzchen/authoring/snapshots.py
f71c0779773ab99ee0e2ce6c280eea30cbaad505bf079ce21325ed4f6c2f2107  tests/authoring/test_finish.py
0f32dc5125993aef8f7b869235cba28cfecfdc754a22199e7bf5877bae2dbd48  tests/authoring/test_snapshots.py
```

## Installed-origin receipt

The candidate is not installed as a wheel or editable distribution in the worker interpreter:

```text
python3 -c 'import sys; print(sys.executable); import herzchen'       exit 1
  /Library/Developer/CommandLineTools/usr/bin/python3
  ModuleNotFoundError: No module named 'herzchen'
python3 -m pip show herzchen-contracts                              exit 1
  WARNING: Package(s) not found: herzchen-contracts
python3 -m pip list --format=freeze | rg -i 'herzchen|astrid|runtime' exit 1
```

Direct source import evidence, with `PYTHONPATH=src`, succeeds:

```text
PYTHONPATH=src python3 -c 'import herzchen, herzchen.authoring.snapshots, herzchen.authoring.finish; ...' exit 0
interpreter: /Library/Developer/CommandLineTools/usr/bin/python3
herzchen.__file__: /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-edt03-worker/src/herzchen/__init__.py
snapshots.__file__: .../src/herzchen/authoring/snapshots.py
finish.__file__: .../src/herzchen/authoring/finish.py
```

Therefore Herzchen source-import evidence is recorded, but no wheel/hash or direct-install metadata is claimed. Astrid and Runtime installed origin was not observed and remains unproven.

## Bounded gaps

- EDT-04: no descriptor-relative deletion proof, idle-close/cleanup race, or physical checkout removal was implemented.
- EDT-05: no three-target wiring or product handler registration was implemented; handlers remain injected and target-neutral.
- EDT-06: no handoff protocol or consumer acknowledgment wiring was implemented.
- Handler-owned alias/revision mappings must be written by the injected `apply(snapshot, checkout, tx, writer, ...)` hook within the supplied transaction; the adapter does not invent product vocabulary or a second receipt engine.

## Receipt pointer

The detailed command/source-origin receipt is `work/edt-03-receipts/edt-03-receipt.md`.
