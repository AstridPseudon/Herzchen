# GF01 Review03 bounded-authority correction — consolidated continuation result

Date: 2026-09-14

## Custody, route, and status

- Route: XHARD implementation.
- Model: gpt-5.6-sol.
- Model reasoning effort: high.
- Invoking manager root: /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20.
- Exclusive worker checkout: /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-review03-correction-worker.
- Branch: gf01-review03-correction.
- Required base commit/tree: 6c9bf746c5ef4509f0071603f7a3b59e908370a0 / 0e95a070db51eccb120d3797b56c837a9c93c4a1.
- Corrected implementation commit/tree: 880e6d293bd7389c4992cb81bd503385bf654c33 / 6ac8cb09b2bc4359c9ab6e5b5c084c4ccf08367f.
- Frozen reviewed candidate retained unchanged: 994d234b349c35a9de58f296fc8f542bc210dc7c / 229ab9cf87d318424fd0ff3c05e97fced3cd5519.
- Pre-amendment implementation e0b84e6490b86b3474d60e927b396b4774ab152c (tree 9d99264520013a2003c4fdebec7540613ba4b222) and handoff commit 4addb44942f8517650c252c26ca85da6d28328ef (tree a227edcc8646c7ee9876f58da3c39ca202673442) are superseded and are not accepted evidence.

This file records all four queued amendments as one consolidated continuation: DAT scope correction, private-facade hardening, lightweight pack import boundary retention, and corrected source/installed evidence.

## Immutable inputs

The following supplied historical inputs were verified and were not edited:

- work/g-foundation-review-03-result.md: 16d9392d62623f752bc0e06e1159ee802d52260887694ea164456185530d132c.
- work/gf01-review03-root-cause-diagnosis-20260914.md: 21a9cf21e352bf64891a8e41077ea544d08c6d7d698f8d39fced12407be33e98.
- .otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json: 742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a.

The package seed, control contracts, canonical extraction map, upstream source, frozen review packet, other worktrees, DAT checkout, and integration branches were not modified.

## Narrow-port construction and supported consumer boundary

Trusted composition owns the sole Store and exact DomainHandler capabilities. It constructs a domain engine and asks Store.issue_command_port or DomainHandler.issue_command_port to issue a DomainCommandPort over a finite set of public engine methods. An ordinary supported consumer receives only the command facade, its DomainCommandPort, and (where applicable) ConsumerStore reads.

The corrected facade enforces the boundary as follows:

- src/herzchen/command_ports.py discovers only engine methods whose names do not begin with an underscore. Private engine helpers are not copied onto the command class.
- CommandFacade.__getattr__ and CommandFacade.__setattr__ reject every private name and every finite writer-shaped forbidden name before engine dispatch.
- DomainCommandPort construction rejects private endpoint names as well as connection, transaction, mutate, direct identity/reference writers, event append, and domain-registration endpoints.
- The supported command and port surfaces contain no Store, DomainHandler, Transaction, generic execute/apply/mutate facility added by this correction, raw connection, or unrestricted transaction.
- vars(command), vars(module), former _COMMAND_PORTS/_KERNEL_PORTS paths, command aliases, and supported constructors expose only narrow ports/readers and finite domain collaborators. DomainCommandPort has no instance dictionary.
- Python closure/private-slot introspection is outside the supported adversary model, as directed.

The adapter repairs do not replace the closed bypass with another broad port:

- AuthoringSessionService exposes finite typed operations validate_session, record_content_edit, reject_finish, and record_finish_recovery. They accept a typed SessionHandle and exact operation inputs, revalidate current scope/token/fence/actor, and retain transaction/mutation ownership inside the private engine.
- The complete finish operation is serialized inside the common owner transaction. No transaction object is returned through the public facade.
- Semantic finish and idle adapters use those finite session operations and no longer call private session helpers.
- ProjectBatches uses WorkGraph.resolve, with WorkNotFoundError preserving its previous optional-resolution behavior.
- ProjectSheet constructs the fixed work.assignment.route-pin / work.batch.v1 envelope inside its trusted private engine, including canonical actor, target, payload, version, revision, and digest inputs. It no longer calls a private batch envelope helper.
- Multi-row work/content/authoring behavior still uses one FND writer, one logical owner transaction, and the existing receipt/event authority. No process isolation, second SQLite writer, second receipt/event engine, or speculative framework was added.

tests/kernel/test_public_command_capabilities.py now checks all representative private helper names and all writer-shaped names for get/set/class-forwarding/port discovery rejection with unchanged durable counts. It also proves counterfeit construction, private endpoint issuance, foreign/wrong-domain owner use, and stale closed-owner use fail closed. tests/kernel/test_public_mutation_admission.py and tests/kernel/test_context_digest_correction.py retain wrong operation, resource, schema, event/descriptor, target, payload, actor, expected version/revision, edit token, correlation, and causation rejection/no-delta evidence.

## DAT 77/77 ownership and exact open disposition

DAT owns the 77/77 parameterized persisted-mutator effect/replay/rejection conformance. This candidate removes and does not run:

- tests/kernel/gf01_mutator_inventory.py
- tests/kernel/test_persisted_mutator_conformance.py

Manager retained the removed pre-amendment files and output outside this candidate for root/DAT comparison only:

- /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review03-dat-duplicate-scratch-20260914/gf01_mutator_inventory.py — 094fb7d7f70b6a2ef15c36080baba1a4a4c6edeef32100866db98dfc15945c0d.
- /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review03-dat-duplicate-scratch-20260914/test_persisted_mutator_conformance.py — 487f09810ae76eff04a1bc84728f4a319907494633fd1a738d2d2b356e0aa01c.
- /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review03-dat-duplicate-scratch-20260914/worker-selected-output.jsonl — 569104152126f7ee9652058a6442ada2283caf05b3da343150882b58011ab5f4.
- /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/gf01-review03-dat-duplicate-scratch-20260914/MANIFEST.md — 8d31a2cf44b6b09adbae9187a5e5a827ba91a46b9bfc94c16862e574108ffab5.

Those artifacts are out-of-scope historical scratch, not candidate tests and not acceptance evidence. No 77 campaign was rerun in this continuation, and this worker makes no 77/77 conformance claim.

The manager/root scope amendment queued for this continuation is preserved verbatim in substance in the scratch manifest: DAT owns the 77/77 parameterized effect/replay/rejection conformance; FND must remove the duplicate candidate artifacts, exclude the historical 78-pass run from FND acceptance, and continue only with narrow capability and affected adapter/domain regressions. The follow-up instruction to preserve the two files plus exact command/output before deletion is recorded there separately. The JSONL's `item_55` retains the exact historical command, output (`78 passed in 0.56s`), and exit code; it was not rerun.

Exact owner-disposition gap: historical scratch counted work.v1|work.revise|work.project|work.parent-linked and mapped it to WorkGraph.link_parent. WorkGraph._validate_parent rejects a project child because projects cannot have a parent. This candidate does not weaken that hierarchy, invent an operation, or treat the row as supported merely to preserve a count. The existing descriptor remains unchanged; root/DAT/owning integration must disposition the mismatch in the authoritative inventory/descriptor process. If removal is selected there, the old row is the key above and the new authoritative inventory must omit it with the project-root invariant as the reason.

## Corrected source evidence

Verified project interpreter:

/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python

The one recorded affected source campaign used:

~~~text
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q \
  tests/kernel/test_public_command_capabilities.py \
  tests/kernel/test_public_mutation_admission.py \
  tests/kernel/test_context_digest_correction.py \
  tests/kernel/test_receipts_limits.py \
  tests/authoring/test_exclusivity.py \
  tests/authoring/test_failure_matrix.py \
  tests/authoring/test_finish.py \
  tests/authoring/test_gf03_retirement.py \
  tests/authoring/test_handoff.py \
  tests/authoring/test_snapshots.py \
  tests/authoring/test_three_targets.py \
  tests/content/test_context_visibility.py \
  tests/content/test_document_authoring_contract.py \
  tests/content/test_documents.py \
  tests/assessment/test_accounting.py \
  tests/extensions/test_definition_admission.py \
  tests/extensions/test_namespaces.py \
  tests/packs/test_authoring.py \
  tests/packs/test_composition.py \
  tests/packs/test_protocol_resources.py \
  tests/packs/test_task_templates.py \
  tests/work/test_assignments.py \
  tests/work/test_batches.py \
  tests/work/test_candidates_decisions_waiting.py \
  tests/work/test_identity_graph.py \
  tests/work/test_sheet_batches.py \
  tests/work/test_wrk06_handoff.py
~~~

Result: 239 passed, 12 skipped, 0 failed in 2.20s.

The selected import-boundary test starts a fresh child with sys.executable, imports herzchen.packs.composition and herzchen.packs.templates, and asserts sqlite3 is absent and no astrid, otto, or runtime-prefixed module is loaded. It passed in both recorded campaigns. The selection contains no DAT inventory or conformance test.

Pre-commit smoke checks (diagnostic only, not additional acceptance campaigns) were 16 passed and 42 passed after the two legacy private WorkGraph._resolve assertions were converted to the supported resolve/WorkNotFoundError contract.

## Exact corrected wheel and installed evidence

A git archive of exact implementation commit 880e6d293bd7389c4992cb81bd503385bf654c33 was built and installed:

~~~text
git archive --format=tar --output=/tmp/gf01-review03-corrected.8c0hOu/candidate.tar 880e6d293bd7389c4992cb81bd503385bf654c33
tar -xf /tmp/gf01-review03-corrected.8c0hOu/candidate.tar -C /tmp/gf01-review03-corrected.8c0hOu/source
env -u PYTHONPATH -u PYTHONHOME /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/gf01-review03-corrected.8c0hOu/wheelhouse /tmp/gf01-review03-corrected.8c0hOu/source
env -u PYTHONPATH -u PYTHONHOME /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m venv --system-site-packages /tmp/gf01-review03-corrected.8c0hOu/venv
env -u PYTHONPATH -u PYTHONHOME /tmp/gf01-review03-corrected.8c0hOu/venv/bin/python -m pip install --no-deps --force-reinstall /tmp/gf01-review03-corrected.8c0hOu/wheelhouse/herzchen_contracts-0.1.0-py3-none-any.whl
env -u PYTHONPATH -u PYTHONHOME /tmp/gf01-review03-corrected.8c0hOu/venv/bin/python -m pip install pytest
~~~

Wheel:

- /tmp/gf01-review03-corrected.8c0hOu/wheelhouse/herzchen_contracts-0.1.0-py3-none-any.whl
- SHA-256: f2dfc90cf1ee93eed38d9a68094026292e603b60477911ad75af6a1e75c72dfc.

The final installed launcher ran from /tmp/gf01-review03-corrected.8c0hOu/run, used env -u PYTHONPATH -u PYTHONHOME, invoked /tmp/gf01-review03-corrected.8c0hOu/venv/bin/python, disabled unrelated auto-loaded pytest plugins, and passed the same expanded test selection above by absolute worker-checkout paths. Child subprocesses inherited that sys.executable.

Before pytest, the launcher imported every selected Herzchen package family and asserted every loaded herzchen module origin was below:

/private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages

Selected actual origins were:

| Module | Installed origin |
|---|---|
| herzchen | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/__init__.py |
| herzchen.command_ports | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/command_ports.py |
| herzchen.kernel.store | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/kernel/store.py |
| herzchen.authoring.sessions | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/authoring/sessions.py |
| herzchen.content.authoring | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/content/authoring.py |
| herzchen.content.commands | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/content/commands.py |
| herzchen.content.packets | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/content/packets.py |
| herzchen.domains.assessment.module | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/domains/assessment/module.py |
| herzchen.domains.work.assignments | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/domains/work/assignments.py |
| herzchen.domains.work.batches | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/domains/work/batches.py |
| herzchen.domains.work.decisions | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/domains/work/decisions.py |
| herzchen.domains.work.module | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/domains/work/module.py |
| herzchen.domains.work.sheet | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/domains/work/sheet.py |
| herzchen.extensions.commands | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/extensions/commands.py |
| herzchen.kernel.limits | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/kernel/limits.py |
| herzchen.kernel.operations | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/kernel/operations.py |
| herzchen.packs.authoring | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/packs/authoring.py |
| herzchen.packs.composition | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/packs/composition.py |
| herzchen.packs.templates | /private/tmp/gf01-review03-corrected.8c0hOu/venv/lib/python3.12/site-packages/herzchen/packs/templates.py |

Installed result: 240 passed, 11 skipped, 0 failed in 2.48s.

Two launcher setup stops occurred before collection and ran zero candidate tests: first pytest was not installed in the nested venv; after installation, running from /tmp exposed an unrelated /private/tmp/tomllib.py shadow lacking the standard API. The final launcher used the clean run directory above. These setup stops are not counted as installed campaigns.

The source/installed skip counts are reported separately and are not used to claim optional Astrid or other product-origin coverage.

## Superseded evidence

The pre-amendment handoff reported a full source count of 400 passed plus 80 subtests and 12 skipped, a focused count of 152 passed, and an installed count of 144 passed. Those runs exercised the rejected e0b84e6 candidate, included the now-removed DAT campaign in focused/installed selections, and are superseded diagnostic history only. They are not final evidence for this correction.

## Changed source/test paths at corrected implementation commit

SHA-256 values are for the files in commit 880e6d293bd7389c4992cb81bd503385bf654c33.

| Path | SHA-256 |
|---|---|
| src/herzchen/authoring/finish.py | 13016c7fd66462750c803861447b9a8223af07c770bb65bc2ed0454ec867e245 |
| src/herzchen/authoring/idle.py | f091cae3ebb7439176e23ff72b95db20bba771c75c6b6ecb8be0790ff7939648 |
| src/herzchen/authoring/sessions.py | a7ed4578fe26383b74e29c0f423cb47fc89ebd1b88ad8adda8ec1f5ab17ceb19 |
| src/herzchen/command_ports.py | 4dcc701345b472fa33381e5b4b1922fd9e955181fc84a5c85e2279ea6a1474d9 |
| src/herzchen/content/authoring.py | 9f71c2e0d91f5b106327a02b7ac0189328c8d3eeac958ea5321ff742806a287e |
| src/herzchen/content/commands.py | 2eb741e609e5aaa0ff883901064937077c50350a90e21831d79d8259b1e2ebca |
| src/herzchen/content/packets.py | 7fb6b531dbcbb74e0e7e9ff12e5136295c270f3f45256180c641a1d7700b3234 |
| src/herzchen/domains/assessment/module.py | e953f62b8ee49b831bda0979223a4d29dcd3309e5fd11f006eb9dcd0a281d24c |
| src/herzchen/domains/work/assignments.py | ba50e3c3285aa0f839ac87beb00eaae0c1e2a65cf7ba556ed3c6bc0bfb4b6acc |
| src/herzchen/domains/work/batches.py | 9db1429a46ea01fa1552d076e3e01560db2fce1ebee158ae9d2b276fce8ad835 |
| src/herzchen/domains/work/decisions.py | f3a0d07d565a038e2ec5ad3a0000373146669b551a9c757f03e525e25fb1f453 |
| src/herzchen/domains/work/module.py | 88d5df79cc95213db67db0cc3c437822b741b9e9782e787716c3f51c8dcd465e |
| src/herzchen/domains/work/sheet.py | b0e4d8350e2d10c67c285a4b88a35cb82534325e2fc55afe37b6dad9bb7bc93c |
| src/herzchen/extensions/commands.py | 56e8761c1ae3cad06975652b8214c65872ae39681efd0c536041b6927a5ae9aa |
| src/herzchen/kernel/__init__.py | 1a3eb637cd8e2180482fa03e92c5c78ad794ed01b49a41293aba33f83c72c342 |
| src/herzchen/kernel/limits.py | 5910380b74f1a65fa547f8f06efc9b37a7b172f325e0e3300d6324344e939c2e |
| src/herzchen/kernel/operations.py | f2098c9eb10a4c7262cf34cb7cbb790a3db66ad17dc61c248d1f85f6f910bb05 |
| src/herzchen/kernel/store.py | 20c586bbcedf9e447794c90dd92d15fdbaabaaf0cc0c3d7c3957c36ec0c17b65 |
| src/herzchen/packs/authoring.py | c4e03213504a928517e88821c22dd2759fa358d20f2560236e6b0101d8216ce0 |
| src/herzchen/packs/templates.py | aa8c6dcd737673dc1ffab3c6de538e761bf32b2444e77e3b0a2163170ac91be2 |
| tests/kernel/test_public_command_capabilities.py | d92272d9ab12d4855affba19171275e601559eebecaac32819ffe3c4fdbb2eb3 |
| tests/work/test_batches.py | d3ba88f96881f23dd445c9ac1e394cfb36ac18b163e5793ad92d3026b5714d46 |
| tests/work/test_sheet_batches.py | 63ad2ca6df4f3b9100d0c38b33af60805e500815d353da306dee01c6dbd7524c |

The two removed DAT-owned test files are absent from the corrected candidate tree; their retained scratch hashes are listed in the DAT section rather than represented as candidate artifacts.

## INT overlap and precise handoff

The candidate differs from the base in src/herzchen/kernel/operations.py and src/herzchen/domains/work/batches.py, both within INT's GF02 operations/batches integration area.

INT must:

1. Preserve DomainCommandPort facade construction and never restore Store/DomainHandler registries or private-name forwarding.
2. Preserve GF02 canonical context and replay logic in operations.py.
3. Preserve the batches.py use of the public WorkGraph.resolve endpoint and rerun test_context_digest_correction.py, test_batches.py, and test_sheet_batches.py from the installed integration candidate.
4. Coordinate the unresolved work.v1|work.revise|work.project|work.parent-linked descriptor/inventory mismatch with DAT/root; do not weaken the project-root invariant or invent a command to satisfy a count.

Authoring finish/idle source was adjusted only because those existing adapters depended on the now-closed private facade path. GF03 retirement lease, immutable manifest/fence, cleanup, and replay semantics were retained; the selected source and installed GF03 tests are green.

## Claim boundary

This is a GF01 bounded-authority correction and handoff only. It makes no gate, cutover, Runtime production-origin, Astrid production-origin, G-OTTO, G-FINAL, publication, or host-qualification claim. DAT conformance and the open descriptor disposition remain external acceptance dependencies.
