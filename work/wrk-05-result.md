# WRK-05 worker result

## Delivery

Implemented the typed `ProjectSheet` adapter in `src/herzchen/domains/work/sheet.py` and focused proof in `tests/work/test_sheet_batches.py`.

The adapter delegates plan/task/document mutations to the accepted
`ProjectBatches.apply_project_sheet` path. It adds the sheet definitions and
fresh authored/observed view, selected task/document export, decision/candidate
and actionable wait context, protected-field validation, dependency-safe local
alias ordering, current-versus-pinned DAT binding normalization, explicit
assignment route pinning, authority/exact-base policy amendments, passive
`adopt-existing-effort`, and distinct pending template instantiation.

No FND/DAT/EDT/PKG/upstream source, package/control file, extraction map, or
existing work/assessment/decision file was modified. No public Otto, Astrid, or
Runtime live use is claimed.

## Scope and lineage

- Dispatch HEAD/tree: `37292c6c855e1712ad619b05244eba683f24e836` /
  `3d1aa21a8c04e658e7730227f61cd2a86f51bf45`.
- Accepted common: `5617d8b7aae1e5dd6ac2b270489b4ad1cbd324fa` /
  `272193e21c64628191d91f846ec936f341208b94`.
- Accepted WRK-04: `bb25ec35d3fd17fe1c63ec623e75d68e9f410a78`.
- Accepted WRK-07: `5c8d89ba997998b0b6c420d2d4827c18ec476697`.
- EDT-04 lineage consumed read-only: `61bbedd1f682e2a7cd511b4081b1a89d4da16e6d`,
  `4769c1153fd3177271b4d849cb7a3fceb450273b`.
- Canonical control-root map:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/plan/extraction-map.json`, SHA-256
  `55da00d1d99ff60426f66b555c5728c8cd4f57641dbabe247ad115adf1787db6`.
- Immutable historical seed map:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/plan/extraction-map.json`, SHA-256
  `c08d94ea32f394596578a3c908e35dc037c1297194d3d5994945a88093101c59`.

Reusable accepted source inputs were retained/adapted from:

- `src/herzchen/domains/work/batches.py` — `10c50feae4e0a2d49b2b0caaa990d0af753cca323abb4f4b1fc3e6ac404e35a8`.
- `src/herzchen/domains/work/module.py` — `4e13c4b6f04ea98096a1c24392cfbf5b61372859b19a9fdb51284a0b01b736d2`.
- `src/herzchen/domains/work/decisions.py` — `9aeeb8a6e4a7f692b3e9a2d2317696431ca874a618cae5ec889dab39d14e42a8`.
- `src/herzchen/domains/work/assignments.py` — `e0071b940e4be36515975e8df3420840fb0196959a312d855d3e8851c27c3514`.
- `src/herzchen/content/commands.py` — `de81e6ce7ea4ffeb833fef8451a34bd116d38491c8218eabf8d1c5582047abd4`.
- `src/herzchen/content/model.py` — `052b076cd47cc6aaf1420a2fd04a9a4eabf2885685640a1d77c63975e640a778`.

Retained/adapted test assertions cover batches, identity graph, assignments,
candidate/decision/waiting, assessment accounting, DAT documents/authoring/
visibility, authoring failure matrix, and conformance. Existing test hashes
remain available from the source checkout; the new focused test hash is listed
below.

## Verification

Source checkout checks used the required interpreter and `PYTHONPATH=src`:

1. `PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/work/test_sheet_batches.py` — exit 0, **10 passed**.
2. Same interpreter, focused plus listed affected files — exit 0, **79 passed** before the final template/current-binding additions.
3. `PYTHONPATH=src ... pytest -q tests/work tests/assessment tests/content tests/authoring tests/conformance` on the final tree — exit 1, **116 passed, 70 subtests passed, 1 failure**. The sole failure is the pre-existing EDT-04 `FailureMatrixTests.test_cross_service_finish_loser_reconciles_durable_winner`; it races in `authoring/finish.py` before the second thread reads a committed identity and raises from `Store._identity_from_row`. WRK-05 files are not imported by that test and no EDT file was changed.
4. Initial required source command without `PYTHONPATH` — exit 2 during collection with 8 `ModuleNotFoundError`s; this confirms checkout imports require the explicitly documented `PYTHONPATH=src`.
5. `PYTHONPATH=src ... python -m compileall -q src/herzchen/domains/work/sheet.py` — exit 0.

Installed candidate was built with `/opt/homebrew/bin/python3.11`, installed in
`/tmp/herzchen-wrk05-final.DQGjPP/venv`, and tested serially with
`env -u PYTHONPATH -u PYTHONHOME`:

1. `.../venv/bin/python -m pytest -q tests/work/test_sheet_batches.py` — exit 0, **10 passed**.
2. `.../venv/bin/python -m pytest -q tests/work tests/assessment tests/content tests/authoring tests/conformance` — exit 0, **117 passed, 70 subtests passed**.

Final wheel: `herzchen_contracts-0.1.0-py3-none-any.whl`, SHA-256
`08c1b6c85e7900408d22a6999d1b5a4b62109dca39a845cb1ed051f7981b4d60`.

Installed origins:

- package: `/private/tmp/herzchen-wrk05-final.DQGjPP/venv/lib/python3.11/site-packages/herzchen/__init__.py`
- WRK-05 module: `/private/tmp/herzchen-wrk05-final.DQGjPP/venv/lib/python3.11/site-packages/herzchen/domains/work/sheet.py`
- site-packages: `/private/tmp/herzchen-wrk05-final.DQGjPP/venv/lib/python3.11/site-packages`

## Final file hashes

- `src/herzchen/domains/work/sheet.py` — SHA-256
  `90b8aa251ac32111c388a571010e3ae28198ff62f86cf31ca69c488ab40a51e2`.
- `tests/work/test_sheet_batches.py` — SHA-256
  `541a197ff5f4361b754dc773fbd6241d530f7fd93deb0e635c4788e9e071b87b`.

## Commit custody

The final handoff reports the commit/tree and committed blob IDs captured after
the last commit. The final commit contains only the three WRK-05 paths; local
build and `__pycache__` outputs are unstaged working-tree artifacts.
