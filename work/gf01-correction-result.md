# GF01 correction result — public mutation capability and admission

Status: one GF01 candidate prepared for the enclosing worker commit. This is
correction evidence only. The original G-FOUNDATION verdict remains **REWORK**;
this result does not accept G-FOUNDATION, qualify G-OTTO, claim consumer
cutover, or establish Runtime/Astrid production origin or product behavior.

## Custody, route, and frozen evidence

- Exclusive worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-correction-worker`; branch `gf01-correction-worker`.
- Required preflight was clean at commit `046b9acfdc9ba541faff65ff3713961890684303`, tree `047a43ba687f45c298139b595756dac84ab729da`.
- Review result SHA-256: `889da6e3f4751d396b88153d8da584552d9535c1df23939de0d75faf63766fcd`.
- Failed baseline raw output SHA-256: `77a1d929aa3fa0b293ffcd7db94be81dd8acd3e138fb6b7ee10ab572208e7ab4`.
- Failed baseline report SHA-256 observed from the authoritative file: `10403df1841719be50e290dffa1e40097a6c3edc030fd5f442a29a81313917dc`. The direct dispatch text omitted two hexadecimal characters near `...5f442a29...`; the adopted brief and file agree with the value recorded here.
- Canonical extraction map was read only at SHA-256 `e273cb7b7e9c26f83a8e1002753c835863333b77e9bfce5b5a3909b1801dbbd5`.
- Launch receipt SHA-256: `2cb654912e206d5832feec33306911d1cde23ee3d626590003157ae9c6c41ad4`. It records CLI `/Users/hannahomalley/.local/bin/codex`, CLI version `0.150.1`, requested XHARD route `gpt-5.6-sol` / high reasoning, thread `01a09e0f-7301-75a0-b364-5520738e28f8`, and supervised session handle `41381`. The receipt does not independently attest the observed backend model, so none is inferred.
- No subagent, oracle, external model, upstream write, control/map/package edit, or frozen-checkout edit was used.

The supplied failed baseline is retained unchanged: direct `put_identity` and
`revise_identity` produced state without receipt/events, `append_event`
produced an event without a command receipt, a non-owner could supply
`owner="dat.protocol-owner"`, and a same-name altered catalog was admitted.

## Corrected boundary

`Store` is now the sealed host/owner capability: it can only be constructed by
its admitted `create`/`open` operations, and it remains the one holder of the
SQLite connection, transaction, bootstrap identity/reference methods, event
append, domain registration, and mutation engine. `Store.consumer()` returns
a concrete non-proxying `ConsumerStore` with read methods only. The installed
ordinary surface has no path/connection/SQL transaction, `put_identity`,
`revise_identity`, `append_event`, `mutate`, `put_reference`, or
`register_domain` attribute. This is a capability split, not an `__all__` or
documentation-only rename.

Before opening a transaction, `Store.mutate` now resolves the exact operation,
target resource kind, event type, and schema revision against a persisted
`DomainContribution`, then checks the authenticated actor against the
contribution owner or explicit `actor-authority:`/`actor-id:` binding. An
ambiguous, undeclared, wrong-schema, or non-owner combination raises
`MutationAdmissionError` before identity/reference/event/receipt/sequence
allocation. Neutral operations/limits/recovery use a finite kernel-owned port
table; arbitrary names are not admitted.

The DAT extension contribution binds its handler, admitted actor authority,
finite mutation resource ports, and SHA-256 of the complete typed
`DefinitionCatalog`. The digest covers every definition and role, including
namespace, definition/version identity, schema and pinned schema reference,
resource/document applicability, owner, classification, writability, help,
validation shape, and query fields; the persisted contribution separately
binds its version, owner, resource/document/namespace types, operations, and
event declarations. Service
construction verifies the supplied catalog against the installed definition
and the persisted contribution; each read/describe/query/mutation rechecks
that the catalog has not changed after admission. Protocol mutation binds
`TransactionContext.actor` to the definition owner and treats the legacy
`owner` argument only as an exact admitted-owner assertion, never as
authorization.

The extension adapter still performs a fresh read and namespace-only merge,
preserves every sibling and unrelated payload member, and passes the supplied
transaction to the one Store mutation boundary. No raw SQL, second store,
private event/receipt engine, new DDL, optional-domain inward import, or FK was
introduced.

## Changed consumers and tests

Production consumer change is limited to
`herzchen.extensions.ExtensionCommandService` and its exported catalog
surface. Existing kernel tests that directly exercise the owner capability
were given explicit fixture domain declarations where they call `mutate`:
`test_transactions`, `test_identity_revisions`, and `test_recovery`.
`test_namespaces` now supplies the admitted DAT actor authority. No DAT
content/authoring, WRK, PKG, EDT, OTT, GF02, Runtime, or Astrid implementation
was edited.

New named proofs are:

- `tests/kernel/test_public_mutation_admission.py`: ordinary consumer surface,
  sealed owner construction, non-owner actor rejection, independent negative
  operation/resource/event/schema cases with exact no-delta assertions,
  valid receipt/event/state linkage, and the existing
  `ManagedPackAuthoringHandler` through an explicit PKG declaration.
- `tests/extensions/test_definition_admission.py`: caller-owner spoof
  rejection with all five durable counts unchanged; same-namespace altered
  schema/owner/classification/writability rejection before service use; valid
  DAT open/protocol writes, sibling preservation, receipt/event linkage, and
  reopen/fresh read.
- `work/gf01-installed-proof.py`: isolated installed-wheel origin and
  before/action/fresh-after JSON probe.

## Source proof

All successful commands used Python `3.11.16`, `PYTHONHOME` unset, and source
commands explicitly used `PYTHONPATH=src`:

```text
python -m pytest -q tests/kernel tests/extensions
exit 0 — 71 passed, 10 subtests passed

python -m pytest -q tests/conformance -k 'not test_dat06_public_api_conformance and not test_int03_installed_public_api_probes'
exit 0 — 17 passed, 2 deselected, 70 subtests passed

python -m compileall -q src/herzchen tests/kernel tests/extensions work/gf01-installed-proof.py
exit 0

git diff --check
exit 0
```

The two excluded conformance cases were also run, not hidden. Full
`tests/conformance` exited `1`: `2 failed, 17 passed, 70 subtests passed`.
The whole repository suite exited `1`: `83 failed, 164 passed, 12 skipped, 27
errors, 80 subtests passed`. These failures are the expected exposed public-port
coordination described below; GF01 did not weaken admission to preserve
undeclared writes.

## Fresh installed-wheel proof

- Wheel: `/tmp/gf01-wheel-sealed.scc0lu/herzchen_contracts-0.1.0-py3-none-any.whl`.
- SHA-256: `cd6985113d3b24c4af23617a847a9d08d295fe65913d4d0a3513a7dbc6efd431`; size `191831` bytes.
- Fresh venv: `/tmp/gf01-venv-sealed.Msdm5z`; Python `3.11.16`; installed distribution `herzchen-contracts==0.1.0`.
- Proof and installed tests used `-I` with `PYTHONPATH` and `PYTHONHOME` unset.
- Installed origins were `/private/tmp/gf01-venv-sealed.Msdm5z/lib/python3.11/site-packages/herzchen/kernel/store.py`, `.../herzchen/extensions/model.py`, and `.../herzchen/extensions/commands.py`.
- Installed kernel+extension suite: exit `0`, `71 passed, 10 subtests passed`.
- Installed unaffected conformance set: exit `0`, `17 passed, 2 deselected, 70 subtests passed`.

The isolated JSON probe exited `0`. It observed all ordinary-writer attributes
absent; non-owner `OwnerRequiredError` with identical before/after counts;
four altered catalogs rejected with `ExtensionError`; unregistered mutation
rejected with identical before/after counts; one valid committed receipt and
one linked event; preserved sibling metadata; and a fresh reopened value.
Fresh durable counts after the one valid mutation were identities `2`,
record references `4`, events `1`, command receipts `1`, and event sequences
`1`.

## Exact lineage

The canonical map entries remain read-only planning/source lineage, not
installed product origin or cutover evidence:

- `EX-STORE`: Runtime `afccb430e2a983c968b6a8a96fd630ba3a6262fc` /
  tree `be89db2f02231aeef212bdb266d12c51778f32ae`,
  `runtime_protocol/store.py` blob
  `4c2b4caf9e68e818f5814dfee893d2579f0206f7` lines 90–175, plus retained
  `tests/test_runtime_domains.py` blob
  `8b5529ddd4e1accc239aa6c23000af54ed846646` atomicity/receipt tests.
- `EX-EVENTS`: the same Runtime store blob lines 1110–1179 and service blob
  `2a62a312f2e9e81adc9fbefe050904d917c42e8d` lines 756–844, with the same
  runtime-domain tests and `tests/test_cursor_pagination.py` blob
  `c11c9c214ec6cbda65295b9eefba55fe66814161`.
- `EX-METADATA`: Runtime service blob
  `2a62a312f2e9e81adc9fbefe050904d917c42e8d` lines
  1039–1060, 1097–1124, 1775–1839, with retained unknown-sibling and managed
  promotion requirements. DAT-03 originally landed as commit
  `b7cf631949bda1bcb9927984a3a750ebc470348d`, tree
  `10e1ace0592180c11616c8945ffd4ceace589fac`; DAT-02 source lineage is
  `a8611a9b9b8cd9ad36c2816c4d1cb2e24e8ded97`.

This correction adapts those one-writer, atomic receipt/event, namespace
preservation, and managed-field assertions. It does not relabel Runtime or
Astrid as an installed dependency.

## File identities before the enclosing commit

```text
src/herzchen/kernel/store.py                    fd783b8f7b2cf762a7efb74aaf8ad1d097c47f97eb353febd6ea86f5c9e14a1a
src/herzchen/kernel/__init__.py                 3eeedc26370c676d4c5dcd928685fba9081538817a3708cd1c97b15d6b7e9b72
src/herzchen/extensions/model.py                55699878ac4f71c4fce28bb9c485c65f048454a85751244c843f6d8b9cdbae2d
src/herzchen/extensions/commands.py             ae108ff30717d5e97fd8853b385b43d71f199949b46b4d03ec08a34b42f864cf
src/herzchen/extensions/__init__.py             1941b5e7dd564fc3e1328a0aae9f1f8fc8153713f8681cce0ac0a5d55c6aae54
tests/kernel/test_public_mutation_admission.py   ce0c102acc128f974770b1364b602d580e948c7131525f87b6dbf9fb44c4eea2
tests/extensions/test_definition_admission.py   d3cdc90b9256b5add1f8ee4212a4a82269ba14e0a0162898ce9f6f7db6554d18
tests/kernel/test_transactions.py               ea6a291659d9a8bc948bb8e05923ca46562c0d8b11d42072c2607f121481f88d
tests/kernel/test_identity_revisions.py         ec8c51bda6c5c7b44a46c3c0bd8c4255fa5943d231465c93ba473c44622d9b85
tests/kernel/test_recovery.py                   e0ca223e827344dc3c376a27117b08775dec6baf9aa061a6a5547e8a802f35f6
tests/extensions/test_namespaces.py             7b1ebf68dae9d4ffa234e03bb02104e556e05bbc26b8dd744d907f0520cb9b4b
work/gf01-installed-proof.py                    ce261adb3be6b9bd39c9eb532461ac4032b7ae6871e78e1d3ef1ce0e2e82147c
```

## Required downstream public-port coordination

The corrected boundary deliberately exposes previously implicit authority:

1. `tests/conformance/test_dat_handoff.py` uses one DAT actor for WRK commands.
   WRK must supply a WRK-owner-bound actor/handler declaration, while DAT
   extension commands retain the DAT-bound actor. Its `shot.fixture` and
   `work.assignment` setup also uses owner-only `put_identity`; DAT-06 must
   replace those with admitted fixture/domain commands before its own
   conformance claim.
2. `tests/conformance/test_int03_public_api_probes.py` starts with arbitrary
   `probe.record.*` mutation names and later directly seeds extension state.
   INT-03 must register a typed probe contribution with an actor binding and
   create seed state through that handler, or stop claiming those writes as
   the ordinary public API.
3. Existing DAT content, WRK/assessment, EDT authoring, and PKG template test
   fixtures contain additional call sites that omit domain registration,
   declare incomplete resource/operation/event sets, or reuse actors across
   owners. Their owners must publish exact handler/actor/resource bindings.
   This worker did not edit them and did not broaden the kernel to arbitrary
   names.

The enclosing Git commit/tree and final clean-worktree state are necessarily
reported by the worker after this tracked result is committed; embedding a
commit's own identity in its contents would be self-referential.
