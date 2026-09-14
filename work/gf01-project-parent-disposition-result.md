# GF01 project-parent descriptor disposition

Date: 2026-09-14

## Ownership and route

This is a bounded FND owner correction following the accepted GF01 Review03 authority-boundary candidate. Root authorized a manager-local edit because the correction is one descriptor binding plus focused inventory/invariant coverage. No new review or gate call was requested.

- Manager root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20`
- Source checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-review03-correction-worker`
- Correction base: `d4f2c61ab441d36b56870d75e9329abf2449d06c` / `b9ccc0a7042e9be3952a73e681d03b0979b3673d`
- Source manifest: `.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`, SHA `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`

## Root cause and minimal disposition

The `herzchen.work` descriptor previously emitted one mutation-port row for every `WorkKind` and each structural event. That included the historical row:

`work.v1|work.revise|work.project|work.parent-linked`

`WorkGraph._validate_parent` rejects a project child with the existing hierarchy invariant (`projects cannot have a parent`). Existing `work.link-parent` remains valid for non-project work records, so no replacement project operation exists or is needed. The correction removes only the unsupported project-parent descriptor binding. It leaves the operation/event vocabulary, `WorkGraph.link_parent`, and project-root invariant unchanged.

Historical 77-port provenance is preserved in the prior GF01 correction result and DAT scratch. The authoritative persisted FND inventory is now 76 ports: `herzchen.work` changes from 30 to 29 and the total from 77 to 76. This is a source/inventory correction only; it is not a 77-port closure, gate, cutover, or product-origin claim. DAT must adapt its owned parameterized matrix to the authoritative 76-port descriptor set.

## Source and tests

Changed paths:

- `src/herzchen/domains/work/module.py`: excludes only the project + `work.parent-linked` mutation-port binding.
- `tests/kernel/test_persisted_mutator_inventory.py`: expects `herzchen.work=29`, total `76`, and asserts the removed key is absent from the persisted descriptor.
- `tests/work/test_identity_graph.py`: proves a project-parent link raises `InvalidParentError("projects cannot have a parent")`, leaves the event count unchanged, and leaves the project root parentless.

Executed with the verified interpreter and source checkout:

`env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-review03-correction-worker/src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/kernel/test_persisted_mutator_inventory.py tests/work/test_identity_graph.py tests/work/test_batches.py tests/work/test_sheet_batches.py`

Result: `24 passed, 0 failed`.

No installed-wheel campaign was run for this one-binding correction. The previously accepted candidate-installed proof remains attributed to commit `880e6d293bd7389c4992cb81bd503385bf654c33`; this source correction requires downstream integration and refreshed installed proof there.

## Handoff

INT/DAT must carry the descriptor removal into their integrated candidate and update any owned exact-port matrix to 76. They must preserve the project-root invariant, the historical old-row mapping, and the no-delta negative proof. No package seed, canonical extraction map, upstream source, or unrelated worktree was modified.
