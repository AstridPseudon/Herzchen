# INT-03 bounded foundation public API probes

Status: `gate_state: pending`. This is candidate-installed public Herzchen API evidence only; it is not INT-03 acceptance, G-FOUNDATION, G-OTTO, product qualification, review/oracle, or publication.

Candidate commit/tree: `4a310a0e81d96417fdd38ecc3984656064275e59` / `d512e1a7e263d8be71a399887ee4301cbdcae31d`.
Wheel SHA-256: `76d4365b1d1aa92ef484686aebc4f65bc43162cfbd2fa0c52f3e9dbe6158b26f`. Python/pytest: `Python 3.11.16` / `pytest 9.1.1`.
Environment proof: `PYTHONPATH` and `PYTHONHOME` were unset; module origins are recorded in the JSON evidence.

## Probe inventory

- `INT03-FND-001` — `Store.create/open + Store.transaction/mutate/get_record/get_identity/get_receipt/list_events`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-CURSOR-001` — `EventCursorReader.page/catch_up`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-LIMIT-001` — `LimitService.reserve/mark_uncertain/settle/release`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-PKG-001` — `packs.composition.compose + WorkGraph.register`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-DAT-001` — `ContentCommandHandler builders/execute/read + ContextPacketService.create_packet/read_packet/compare_supplied_inputs`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-DAT-003` — `ExtensionCommandService.describe/read/query/set`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-PKG-002` — `TemplateEngine.instantiate/adopt_protocol`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-PKG-003` — `public pack loader/read_managed_pack + ManagedPackAuthoringHandler.author/read`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-WRK-001` — `WorkGraph.register/create_project/create_task/get/list + ProjectBatches.apply_project_sheet/create_pending_project + assignment/readiness public records`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-REOPEN-001` — `Store.close/open fresh-process aggregate read`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.
- `INT03-LINK-001` — `additive int03-area-links seed-field mechanical comparison`: receipt/event identity captured; fresh read, replay/rejection, and restart observations are in the JSON.

## Criteria status

The installed assertions and focused probe IDs supporting C02/C03/C04/C05/C06/C10/C11/C12/C13/C14/C15/C16/C17/C31/C33/C34/C35 are listed in the JSON. All remain `pending`: this lane records bounded evidence and does not convert installed assertions into a gate verdict.

C35 foundation evidence is public Herzchen API evidence. Future Otto/AST consumer journeys are later INT-04/INT-05/INT-07/G-OTTO/G-FINAL obligations, not prerequisites silently pulled into this foundation run.

WRK04 source identity is recorded without an installed WRK04 assessment claim. The accepted EDT04 receipt is reused without duplicating its real two-service finish race. EDT05/EDT06 remain pending unless supplied by an accepted dependency.

No package seed, `validation/scenarios.json`, `validation/area-contracts.json`, control DB, source manifest, extraction map, upstream, `src/`, or another owner's product path was edited.
