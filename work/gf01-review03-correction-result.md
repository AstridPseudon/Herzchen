# GF01 Review03 bounded authority correction result

Date: 2026-09-14

## Custody and route

- Route: XHARD implementation.
- Model: `gpt-5.6-sol`.
- Model reasoning effort: `high`.
- Invoking project root: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20`.
- Exclusive worker checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-review03-correction-worker`.
- Branch: `gf01-review03-correction`.
- Base commit/tree: `6c9bf746c5ef4509f0071603f7a3b59e908370a0` / `0e95a070db51eccb120d3797b56c837a9c93c4a1`.
- Final candidate implementation commit/tree: `e0b84e6490b86b3474d60e927b396b4774ab152c` / `9d99264520013a2003c4fdebec7540613ba4b222`.
- Frozen reviewed candidate retained unchanged: `994d234b349c35a9de58f296fc8f542bc210dc7c` / `229ab9cf87d318424fd0ff3c05e97fced3cd5519`.
- Post-handoff-commit worktree result: clean (`git status --short` produced no output).

## Input custody

The supplied historical inputs were verified before implementation and were not edited:

- `work/g-foundation-review-03-result.md`: `16d9392d62623f752bc0e06e1159ee802d52260887694ea164456185530d132c`.
- `work/gf01-review03-root-cause-diagnosis-20260914.md`: `21a9cf21e352bf64891a8e41077ea544d08c6d7d698f8d39fced12407be33e98`.
- `.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`: `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.

The package seed, control contracts, canonical extraction map, upstream source, frozen review packet, and other worktrees were not modified.

## Correction design and supported boundary

Trusted composition still acquires the sole `Store` owner and exact `DomainHandler` values. `Store.issue_command_port` and `DomainHandler.issue_command_port` now issue an authenticated `DomainCommandPort` for a finite domain adapter contract. Each ordinary command is a facade retaining only that port and, where reads are supported, a concrete `ConsumerStore`.

The formerly public command implementation is now a module-private engine. Its broad owner exists only inside the engine retained in the port's slot; it is not present in command `vars`, port `vars`, a module-global map, or a supported factory result. The port publishes only the exact non-private domain endpoints discovered from that engine, binds calls against each endpoint's exact Python signature, and delegates to the existing typed domain validation before the owner mutation path. Its supported surface has no `connection`, generic `mutate`, unrestricted `transaction`, `put_identity`, `revise_identity`, `put_reference`, domain registration, or equivalent writer escape.

All `_COMMAND_PORTS` and `_KERNEL_PORTS` weak registries were removed. `vars(command)` contains only the narrow port and optional reader; `DomainCommandPort` has no instance dictionary, and its `dir` surface is limited to `domain_id`, `endpoints`, `reader`, and exact public domain methods. Counterfeit construction is sealed by an owner-only construction token. Passing a port as an owner, passing a wrong-domain handler to WRK, or using a port after owner closure fails without durable mutation.

Multi-row work/content/authoring behavior remains inside the typed domain engine and uses the one supplied owner transaction. No generic transaction was added to the port. The sole FND writer, logical transaction, receipt table, event stream authority, and replay engine are unchanged. The lightweight facade constructor is in `src/herzchen/command_ports.py` so importing resource-only pack/template modules does not import SQLite; actual construction lazily resolves and calls the trusted Store issuer.

Same-process access through Python private-slot/closure introspection is outside the supported adversary model, as directed. The supported command object, port, reader, module containers, aliases, and factories expose only the finite command/read contract.

## 77/77 mutator inventory and effect proof

`tests/kernel/gf01_mutator_inventory.py` is the common bijective artifact. `MUTATOR_INVENTORY` contains exactly 77 unique rows keyed by the full persisted mutation port (`schema|operation|resource|event`). Every row identifies:

- the exact supported command entry point;
- the primitive persisted delta for that admitted port fixture: `+1 identities`, `+2 record_references` (unpinned target and pinned result), `+1 events`, `+1 command_receipts`, and `+1 event_sequences`;
- receipt/event linkage and one receipt transaction identity;
- exact replay after an independent identity revision advances durable state;
- changed target, payload, actor, expected version, expected revision, edit token, correlation, and causation conflicts with no delta;
- unregistered operation, schema/descriptor, resource/target, and event/port rejection before mutation;
- forced transaction rollback with no identity, reference, event, receipt, or sequence delta;
- fresh identity, receipt, event, and reference reads after close/reopen, followed by exact replay with no delta.

Aggregate rows explicitly name child effects. These cover authoring actor/draft/final snapshot identities and references; project-sheet task revisions, dependencies, document heads/revisions, and associations; optional authoring reservation identity/reference; assessment operation/reservation/invocation/finding identities and links; correction-result linkage; and content revision identities/references.

Executable evidence is `tests/kernel/test_persisted_mutator_conformance.py`:

- `test_inventory_is_bijective_complete_and_declares_aggregate_children` proves exact descriptor-to-row equality, 77 unique keys, supported entry points, delta schema, and required aggregate child coverage.
- `test_each_persisted_mutation_port_effect_replay_rejection_rollback_and_restart` is parameterized once for each of the 77 keys and performs every effect/replay/rejection/rollback/restart observation above.
- `tests/kernel/test_public_command_capabilities.py` proves ordinary construction/module/alias state retains only `DomainCommandPort`/`ConsumerStore`, former registries are absent, and counterfeit, wrong-owner, wrong-domain, and stale-owner paths fail closed.
- `tests/kernel/test_public_mutation_admission.py` supplies the admitted changed-operation conflict, foreign-handler rejection, exact actor provenance, descriptor/event/resource/schema admission, and no-delta checks.

The focused source 77/capability/GF02/GF03 window passed `152`, skipped `0`, failed `0`. The installed campaign passed `144`, skipped `0`, failed `0`; it includes all 77 parameterized rows. These are exact focused counts, not a claim inferred from a broad aggregate.

## Verification commands and results

Verified project interpreter: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`.

Final full source command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q
```

Result: `400 passed`, `80 subtests passed`, `12 skipped`, `0 failed` in `3.37s`.

Final focused source command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/kernel/test_public_command_capabilities.py tests/kernel/test_persisted_mutator_inventory.py tests/kernel/test_persisted_mutator_conformance.py tests/kernel/test_context_digest_correction.py tests/authoring/test_gf03_retirement.py tests/work/test_sheet_batches.py tests/packs/test_task_templates.py
```

Result: `152 passed`, `0 skipped`, `0 failed` in `1.33s`.

Disposable installed candidate construction used a git archive of exact commit `e0b84e6490b86b3474d60e927b396b4774ab152c`:

```text
git archive --format=tar --output=/tmp/gf01-review03-wheel.aXuNBh/candidate.tar e0b84e6490b86b3474d60e927b396b4774ab152c
tar -xf /tmp/gf01-review03-wheel.aXuNBh/candidate.tar -C /tmp/gf01-review03-wheel.aXuNBh/source
env -u PYTHONPATH -u PYTHONHOME /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/gf01-review03-wheel.aXuNBh/wheelhouse /tmp/gf01-review03-wheel.aXuNBh/source
env -u PYTHONPATH -u PYTHONHOME /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m venv --system-site-packages /tmp/gf01-review03-wheel.aXuNBh/venv
env -u PYTHONPATH -u PYTHONHOME /tmp/gf01-review03-wheel.aXuNBh/venv/bin/python -m pip install pytest /tmp/gf01-review03-wheel.aXuNBh/wheelhouse/herzchen_contracts-0.1.0-py3-none-any.whl
```

Wheel: `/tmp/gf01-review03-wheel.aXuNBh/wheelhouse/herzchen_contracts-0.1.0-py3-none-any.whl`; SHA-256 `c8472e7c2a66b9d89056e3bf75ebb7b5857f0204cc3026fb6d44039409c4c13b`.

The final installed launcher used `env -u PYTHONPATH -u PYTHONHOME`, the disposable venv interpreter, asserted package origins, and invoked pytest on:

```text
tests/kernel/test_public_command_capabilities.py
tests/kernel/test_public_mutation_admission.py
tests/kernel/test_persisted_mutator_inventory.py
tests/kernel/test_persisted_mutator_conformance.py
tests/kernel/test_context_digest_correction.py
tests/work/test_batches.py
tests/work/test_sheet_batches.py
tests/authoring/test_gf03_retirement.py
```

Actual installed origins:

```text
/private/tmp/gf01-review03-wheel.aXuNBh/venv/lib/python3.12/site-packages/herzchen/__init__.py
/private/tmp/gf01-review03-wheel.aXuNBh/venv/lib/python3.12/site-packages/herzchen/command_ports.py
/private/tmp/gf01-review03-wheel.aXuNBh/venv/lib/python3.12/site-packages/herzchen/kernel/store.py
```

Installed result: `144 passed`, `0 skipped`, `0 failed` in `1.57s`.

Two superseded diagnostic windows are retained here for transparency: the first full source run was `399 passed`, `80 subtests passed`, `12 skipped`, `1 failed` and exposed the template import/SQLite regression, which was corrected by the lightweight facade module; the first target-directory installed attempt was `143 passed`, `0 skipped`, `1 failed` because its temporary parent-only `sys.path` was not inherited by a GF03 subprocess. The authoritative venv-installed rerun above passed the identical focused selection `144/144`, including that subprocess case.

## Changed source/test paths and SHA-256

| Path | SHA-256 |
|---|---|
| `src/herzchen/authoring/sessions.py` | `36d4f5ec4e93277e7e5a0e274372c39b37f445353d90341f33eea941e07bc81c` |
| `src/herzchen/command_ports.py` | `9de7800a04e4e5d1df83f9f389ebd4557a5308b7f4e98127bf8a40b500ad528c` |
| `src/herzchen/content/authoring.py` | `9f71c2e0d91f5b106327a02b7ac0189328c8d3eeac958ea5321ff742806a287e` |
| `src/herzchen/content/commands.py` | `2eb741e609e5aaa0ff883901064937077c50350a90e21831d79d8259b1e2ebca` |
| `src/herzchen/content/packets.py` | `7fb6b531dbcbb74e0e7e9ff12e5136295c270f3f45256180c641a1d7700b3234` |
| `src/herzchen/domains/assessment/module.py` | `e953f62b8ee49b831bda0979223a4d29dcd3309e5fd11f006eb9dcd0a281d24c` |
| `src/herzchen/domains/work/assignments.py` | `ba50e3c3285aa0f839ac87beb00eaae0c1e2a65cf7ba556ed3c6bc0bfb4b6acc` |
| `src/herzchen/domains/work/batches.py` | `debf51a595dfcb119ace9ee561f35d598cda686f0c9d3a296dbc1f7bf312333b` |
| `src/herzchen/domains/work/decisions.py` | `f3a0d07d565a038e2ec5ad3a0000373146669b551a9c757f03e525e25fb1f453` |
| `src/herzchen/domains/work/module.py` | `88d5df79cc95213db67db0cc3c437822b741b9e9782e787716c3f51c8dcd465e` |
| `src/herzchen/domains/work/sheet.py` | `d711687775ad21297bd2fff9af1c26cc789ff76c5e9219a9e452d9aaed9ea67c` |
| `src/herzchen/extensions/commands.py` | `56e8761c1ae3cad06975652b8214c65872ae39681efd0c536041b6927a5ae9aa` |
| `src/herzchen/kernel/__init__.py` | `1a3eb637cd8e2180482fa03e92c5c78ad794ed01b49a41293aba33f83c72c342` |
| `src/herzchen/kernel/limits.py` | `5910380b74f1a65fa547f8f06efc9b37a7b172f325e0e3300d6324344e939c2e` |
| `src/herzchen/kernel/operations.py` | `f2098c9eb10a4c7262cf34cb7cbb790a3db66ad17dc61c248d1f85f6f910bb05` |
| `src/herzchen/kernel/store.py` | `cefd6a9ab5d10b6c1db30b770b1459a0fbb1c1d1476df902af945729e9cacf23` |
| `src/herzchen/packs/authoring.py` | `c4e03213504a928517e88821c22dd2759fa358d20f2560236e6b0101d8216ce0` |
| `src/herzchen/packs/templates.py` | `aa8c6dcd737673dc1ffab3c6de538e761bf32b2444e77e3b0a2163170ac91be2` |
| `tests/kernel/gf01_mutator_inventory.py` | `094fb7d7f70b6a2ef15c36080baba1a4a4c6edeef32100866db98dfc15945c0d` |
| `tests/kernel/test_persisted_mutator_conformance.py` | `487f09810ae76eff04a1bc84728f4a319907494633fd1a738d2d2b356e0aa01c` |
| `tests/kernel/test_public_command_capabilities.py` | `40a98329f8a02efbbef749cf05d935d6bf96ccbca6e86512861c1dd99fba6d02` |

## INT overlap and handoff

The correction touches `src/herzchen/kernel/operations.py` and `src/herzchen/domains/work/batches.py`, which overlap INT's GF02 context/replay integration area. Those files receive only the engine/facade owner-access conversion; the accepted GF02 canonical context, exact replay ordering, and project-sheet precondition semantics from base commit `6c9bf74` were not changed. INT should integrate candidate commit `e0b84e6`, preserve its own later semantic edits inside the private engine bodies if any, and rerun `tests/kernel/test_context_digest_correction.py`, `tests/work/test_batches.py`, and `tests/work/test_sheet_batches.py` from the installed candidate. Any constructor/writer-map conflict must resolve in favor of `DomainCommandPort` issuance with no restored broad registry.

`src/herzchen/authoring/sessions.py` overlaps GF03 only at command owner access. Retirement lease, fence, handoff, and cleanup semantics were not changed; the full source and installed `test_gf03_retirement.py` cases are green.

## Scope statement

This is a GF01 bounded authority correction and evidence handoff only. It makes no gate, cutover, Runtime production-origin, Astrid production-origin, G-OTTO, G-FINAL, publication, or host-qualification claim. It adds no process isolation, platform-security dependency, second SQLite writer, second receipt/event engine, or speculative framework.
