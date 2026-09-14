# C33 persisted-port conformance correction handoff

Correction scope is test/evidence only. Historical commit `73b71d2` remains
the prior evidence record; this correction does not modify product
implementation, kernel, contracts, GF01, GF02, or GF03 paths.

## Binding and final hashes

- Source base commit: `6c9bf746c5ef4509f0071603f7a3b59e908370a0`
- Source base tree: `0e95a070db51eccb120d3797b56c837a9c93c4a1`
- Exact matrix: 77 unique accepted `mutation-port:` descriptors.
- Matrix SHA256: `4c5cb78ec497c58300bbc8d68e5c7571c563194717fc65bd7f3f4d00d8fcf766`
- Final result SHA256: `8d1fb0ce7d857f9780e59a280f40e7f62edd41b70f5a6663aba026cb40aff5e8`
- Final disposable wheel SHA256: `b16b1f9a61e412dc2eb549b6a69cace8d54555a26f3023855eabc1f9897b829f`

## Corrected evidence semantics

Fixture setup is now separated from the tested command. Every row captures
counts/events immediately before its first action; `fixture_setup.delta` covers
only public fixture admission, while `action.delta` is the command delta.
Every result records `first_action_valid` and a phase-tagged exception when a
row stops. Statuses are deliberately limited to:

- `passed`: first action, receipt/event/result, exact replay, changed-request
  zero delta, and close/reopen durability all verified;
- `fixture_incomplete`: the accepted descriptor cannot be exercised by the
  current public fixture/surface;
- `reproduced_owner_defect`: first action was valid, but a public lifecycle or
  replay/receipt phase reproduced an exact-base defect.

Assessment result and finding objects are refreshed through public
`get_result`/`get_finding` after setup before their tested action. The project
parent-linked row is `fixture_incomplete`, not an owner defect:

```text
descriptor: work.v1|work.revise|work.project|work.parent-linked
public surface: herzchen.domains.work.WorkGraph.link_parent
first-action exception: InvalidParentError: projects cannot have a parent
mismatch: the descriptor requires a project parent-linked mutation, but the
public surface rejects project parents and exposes no valid parent-clear path.
```

EDT release and actor.release exact-replay defects remain reproduced. The
cleanup.refresh fixture now retains and reestablishes its public retirement
lease: first action is valid and the exact replay reproduces
`ReplayConflictError`. Finish.recovery is labeled only after explicit receipt
lookup: its recovery event is present, but all public candidate receipt keys
have zero matches; the lookup candidates and event ID are in the result JSON.

DAT `metadata.remove` records the same logical key, `annotation.open` field
`seed` before/after metadata, action receipt/event, immediate one-command
delta, changed-field request (`missing`) with stale precondition, and changed
request zero delta.

## Final runs

Source inventory command:

```text
env -u PYTHONHOME TMPDIR=/private/tmp PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/kernel/test_persisted_mutator_inventory.py
```

Result: passed. Log SHA256:
`bee77e396a089e69cb8ac1d751d3c9bdea64861e9d7dc4ee2c7c6c5820b867d9`.

Source matrix command:

```text
env -u PYTHONHOME TMPDIR=/private/tmp PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 C33_RUN_ID=source-correction-final C33_SOURCE_COMMIT=6c9bf746c5ef4509f0071603f7a3b59e908370a0 C33_SOURCE_TREE=0e95a070db51eccb120d3797b56c837a9c93c4a1 /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/conformance/test_c33_persisted_port_conformance.py
```

Result: 78 passed at the pytest harness level (bijection plus 77 rows), with
row statuses `passed=49`, `reproduced_owner_defect=27`,
`fixture_incomplete=1`. Log SHA256:
`aa749e669366367bafbc10cae249fd2a0f6db973eaededa82f08e676ae02aa60`.

Installed proof used a fresh venv at
`/private/tmp/c33-correction-proof.dtnvhK`, with the wheel built from this
checkout and all handler module origins resolving under that venv's
`site-packages`. Its pytest command kept both import-path variables unset:

```text
env -u PYTHONPATH -u PYTHONHOME TMPDIR=/private/tmp C33_RUN_ID=installed-correction-final C33_SOURCE_COMMIT=6c9bf746c5ef4509f0071603f7a3b59e908370a0 C33_SOURCE_TREE=0e95a070db51eccb120d3797b56c837a9c93c4a1 C33_WHEEL_PATH=/private/tmp/c33-correction-proof.dtnvhK/wheel/herzchen_contracts-0.1.0-py3-none-any.whl C33_WHEEL_SHA256=b16b1f9a61e412dc2eb549b6a69cace8d54555a26f3023855eabc1f9897b829f C33_MODULE_ORIGINS_JSON='<recorded in result JSON>' /private/tmp/c33-correction-proof.dtnvhK/venv/bin/python -m pytest -q tests/conformance/test_c33_persisted_port_conformance.py
```

Result: 78 passed at the pytest harness level with the same row statuses:
`passed=49`, `reproduced_owner_defect=27`, `fixture_incomplete=1`. Log SHA256:
`766fbea6955661ef7d6146f99268ecfb853436b46fbd1b62f1814c5e7ab8ae7f`.

The prior deleted-macOS-TMPDIR correction remains recorded: all pytest/build
commands used `TMPDIR=/private/tmp`.

## Custody

The correction commit contains only the conformance test and C33 work evidence:

- `tests/conformance/test_c33_persisted_port_conformance.py`
- `work/c33-persisted-port-matrix-20260914.json`
- `work/c33-persisted-port-result-20260914.json`
- `work/c33-persisted-port-handoff-20260914.md`
- `work/c33-source-run-correction-20260914.txt`
- `work/c33-installed-run-correction-20260914.txt`
- `work/c33-inventory-run-correction-20260914.txt`
- `work/c33-correction-wheel-sha256-20260914.txt`

The disposable venv/wheel remain outside the checkout. The exact prior
`73b71d2` evidence is retained in git history.
