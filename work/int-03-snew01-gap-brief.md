# INT-03 S-NEW-01 atomic initial-spec gap brief

Owner route: normal Luna/high implementation worker under WRK/PKG/EDT composition ownership. No review/oracle call. Start from tested INT-03 candidate `c7156360ab601533a38710b8957887e582db669e` / tree `f547137f5804c0d8958d68d08633b35698aa2e43` in a separate worker checkout.

The direct installed probe `work/int-03-c38-foundation-probe-20260914.json` closes C38 create/query/edit/document/revisit/admission and no-dispatch behavior. It also identifies the remaining S-NEW-01 gap: `TemplateEngine.instantiate("work.blank_project")` executes `src/herzchen/packs/templates.py::TemplateEngine.instantiate`, where the early blank return occurs immediately after the WRK project receipt and before the DAT document loop. `src/herzchen/packs/templates.py::_blank_seed` currently has `documents: []`. `AuthoringSessionService.create_and_open` in `src/herzchen/authoring/sessions.py` only persists an authoring scope/snapshot after its caller-created project; it does not create an initial-spec DAT identity/ref/receipt.

Implement the smallest supported public composition that makes the shipped/default blank project atomically return:

1. one pending zero-task project identity and WRK creation receipt;
2. one initial-spec DAT document identity plus empty initial revision/ref and DAT receipt, linked to the project where the normal public contract requires a project document association;
3. a fresh read of the project/template revision and initial spec before optional open, with no manager, gate, budget, allowance, accepted result, active session, or dispatch;
4. same request replay returning the same project/spec refs and receipts without duplicate identities/events; changed arguments rejecting with no partial rows;
5. ordinary authoring open with the initial empty content, untouched idle close retaining project/spec/revisions and removing only registered checkout files, with no fabricated task or content revision;
6. later edit/attach remains ordinary public `ProjectSheet`/DAT behavior, and explicit admission remains separate.

Preserve the shipped template schema/version and stable request-derived IDs. Do not add a private SQLite writer or test-only setup. Update only owner paths plus focused tests under `tests/packs/`, `tests/authoring/`, or the shared conformance fixture path. Run the focused blank-template/authoring matrix and installed wheel proof with `env -u PYTHONPATH -u PYTHONHOME`; report exact source commit/tree, wheel digest, refs, event/receipt counts, replay/invalid/close results, and installed origins.

Acceptance blocker is the exact pre-open atomic initial-spec ref/receipt proof; C39 manager-host action remains later scope. Do not mark a gate or acceptance verdict.

## Closure receipt

Root accepted the bounded correction as S-NEW-01 source `acd9ae3666574add8b9289d368a9b9f6f74b694b`, tree `793c435567261ad077f093ac4a7f5ba30bcd05a7`. The dynamic blank composition is integrated in INT-03 commits `becafe9`, `d5e4892`, and `046b9ac`; the final installed affected campaign is recorded at `work/int-03-snew01-installed-affected-run-20260914.txt` with 154 passed and zero skips. This brief is retained as the historical gap specification, not an open blocker.
