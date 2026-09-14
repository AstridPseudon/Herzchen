# GF01/GF02/DAT76 bounded authoring correction result

Date: 2026-09-14 (Europe/Berlin)

Status: **complete for the requested bounded correction.** The final installed
campaign passed 248 tests with zero skips. The independent current C33
inventory, matrix, result, and strict checker agree on exactly 76 admitted
rows, all 76 passed.

No review, oracle, gate, upstream publication, consumer cutover, INT03
completion, or G-FOUNDATION completion was invoked or claimed.

## Execution identity and custody

- Checkout:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-int-final-correction-xhard-worker`.
- Session ID / thread ID: `01a09fe3-10a9-77e2-af39-7e36f904a986`.
- Runtime-facing model identity: Codex based on GPT-5. The exact backend model
  identifier was not exposed in `CODEX_MODEL`; it is not inferred here.
- Reasoning setting: not exposed in `CODEX_REASONING_EFFORT`; it is not
  inferred here.
- Starting commit/tree:
  `6019553fade710b3392437382916c1a716edf217` /
  `16e130334ca6313a6eb238f9084c332416879d2c`.
- `git status --short` at start had no output.
- Corrected product/test source commit/tree:
  `7c15ae26909cd8a0da52e4a3231468d7459146f5` /
  `3b27fa3319b57ada95b4aadc62445834bfb4e7d4`.
- Evidence/manifest checkpoint commit/tree:
  `075d8c99a3102414e65d3013a533b1d48a6d075c` /
  `0360a491e861828f27e7cb268a6f61b404590331`.
- `git status --porcelain=v1` immediately after the evidence checkpoint commit
  had no output. This report is the only subsequent file added before its own
  delivery commit; final clean status is necessarily verified after that
  commit and recorded in the external factual receipt.

## Production correction

`AuthoringSessionService.finish` now resolves `K:capture-failure` before it
requires an open checkout when no receipt exists at `K`. Initial capture
failure persists the original public finish binding inside the recovery
mutation: logical request key and canonical finish digest, admitted finish
target, target scope, authenticated actor, EDT owner, and session identity.

An exact public `finish(K)` retry does not invoke capture and does not mutate.
It validates all of the following before returning the existing recovery
result:

- the actual `K:capture-failure` receipt is a committed `finish.recovery`
  receipt for the bound authoring scope;
- its canonical recovery digest covers the original finish binding, failure,
  and snapshot digest;
- the referenced event lineage has the same actor, operation, owner, and
  source-request binding;
- the persisted checkout matches the original session capability and is in
  released/recovery-pending state;
- the durable snapshot reference, bytes, manifest, and digest agree.

The initial failure and exact retry return equal `FinishResult` values and the
same real suffixed receipt. No receipt is written at `K`, no success receipt is
aliased, and no success is fabricated. A changed mode or actor conflicts via
`ReplayConflictError` with zero durable delta. A same-key change only to the
capture value returns the already-bound recovery result with zero durable
delta, because capture is deliberately not part of the logical finish digest
and is not reinvoked.

Focused authoring coverage proves full result equality, one capture call,
released-handle state, persisted digest/target/target-scope/actor/owner
bindings, changed-mode and changed-actor conflicts, and unchanged identity,
reference, receipt, and event counts. The C33 recovery row uses the public
`AuthoringSessionService.finish` retry and records the actual
`c33:C33-93c383e03e9e:capture-failure` receipt.

## Manifest repair and retained history

`work/gf01-gf02-dat76-combined-input-manifest.json` is valid JSON and contains
22 unique verified commit rows. It now includes the complete requested GF01
Review03 sequence and mappings:

| Commit | Exact tree | Mapping |
|---|---|---|
| `e0b84e6490b86b3474d60e927b396b4774ab152c` | `9d99264520013a2003c4fdebec7540613ba4b222` | already reachable from `integration_base` |
| `4addb44942f8517650c252c26ca85da6d28328ef` | `a227edcc8646c7ee9876f58da3c39ca202673442` | already reachable from `integration_base` |
| `880e6d293bd7389c4992cb81bd503385bf654c33` | `6ac8cb09b2bc4359c9ab6e5b5c084c4ccf08367f` | already reachable from `integration_base` |
| `d4f2c61ab441d36b56870d75e9329abf2449d06c` | `b9ccc0a7042e9be3952a73e681d03b0979b3673d` | already reachable from `integration_base` |
| `8235d9aacbe7357e8f72cec8342eca77aab0cb58` | `c69702a8b42420159dbcdb4b0d572c0e8f9dfffa` | `integration_base` |

Mechanical checks resolved every input as a commit, matched every recorded
tree, and proved all five rows ancestral to the GF01 integration base. The
manifest retains historical attempt source `1fe71f8b115abd1b413690a6e954a7afe591f21c`
/ tree `a2f500b0354339826b25f6cff220f68a40d91513`, and separately retains the
quarantined evidence checkpoint `6019553fade710b3392437382916c1a716edf217`
/ tree `16e130334ca6313a6eb238f9084c332416879d2c` as 75 passed of 76 current
rows with one unresolved row. Those old artifacts were not overwritten or
counted in the corrected campaign.

Historical 6019553 evidence remains byte-identical:

| Artifact | SHA-256 |
|---|---|
| `work/gf01-gf02-dat76-combined-final-c33-matrix.json` | `1ac6456534cedafe63cf24e3c964487c1aa5821bf592239c2f28b835d0b85086` |
| `work/gf01-gf02-dat76-combined-final-c33-result.json` | `7af887f0b01eaf8703681c1526efc1c1fb37b6f7781c667954d963144a0dacd3` |
| `work/gf01-gf02-dat76-combined-final-installed-junit.xml` | `a033ce604f5a009a620dcf3ae6a579c2041da3c6c9b8bfba0531535a4bf6fe2f` |
| `work/gf01-gf02-dat76-combined-final-strict-check.txt` | `5f089987717545947d8f88df0199309e6eb41ff35a70eab85fe5f080702a3fe8` |
| `work/gf01-gf02-dat76-combined-result.md` | `abec1b13b276cbc33b291cf3f0dcec4c5b49e89e69688f1fe00b6794bf8e3c5c` |
| `work/gf01-gf02-dat76-combined-worker-receipt-20260914.jsonl` | `e00545ebf82625367db2bd4bd88753aa714de28dae300ecbcb4ee3b946418ba4` |

## Wheel, Astrid, and installed origins

- Fresh wheel built from a `git archive` of source commit `7c15ae2`:
  `/private/tmp/herzchen-correction-delivery.gA7Nsm/dist/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256:
  `4da6dd9f56f705831f0dc8a282526de0c28031fca2331074b359803195db4f9b`.
- Disposable venv:
  `/private/tmp/herzchen-correction-delivery.gA7Nsm/venv`.
- Python / pytest: `3.11.16` / `9.1.1`.
- `PYTHONHOME` and `PYTHONPATH` were absent for installation, origin capture,
  focused tests, final campaign, and strict checking.
- Pinned Astrid source:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/sources/Astrid-96e5664237eb`.
- Astrid origin: `https://github.com/peteromallet/Astrid.git`.
- Astrid commit/tree:
  `96e5664237eb35adeb4cad08bddd8cd6df0a2ae1` /
  `19f7539a266618a797559eedbda48e2752b30fa3`.
- Astrid source status was clean. It was installed directly from that path with
  `pip install --no-deps`; installed `direct_url.json` records the same path.
- All recorded Herzchen and Astrid module origins are below the disposable
  venv's `site-packages`; none resolves to either source checkout.

## Commands and results

Source-focused correction run:

```text
env -u PYTHONHOME PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  C33_RUN_ID=correction-source-focused-2 \
  C33_RESULT_PATH=<disposable>/result.json \
  C33_MATRIX_PATH=<disposable>/matrix.json \
  /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python \
  -m pytest -q tests/authoring/test_finish.py \
  tests/conformance/test_c33_persisted_port_conformance.py
exit 0 — 85 passed; generated result contained 76/76 passed rows and exact
action/replay recovery-result equality.
```

Fresh build and installs:

```text
git archive 7c15ae26909cd8a0da52e4a3231468d7459146f5 | tar -x -C <source>
env -u PYTHONHOME -u PYTHONPATH /opt/homebrew/bin/python3.11 \
  -m pip wheel --no-deps --wheel-dir <dist> <source>
env -u PYTHONHOME -u PYTHONPATH /opt/homebrew/bin/python3.11 -m venv <venv>
env -u PYTHONHOME -u PYTHONPATH <venv>/bin/python -m pip install \
  pytest==9.1.1 PyYAML==6.0.3 jsonschema==4.25.1
env -u PYTHONHOME -u PYTHONPATH <venv>/bin/python -m pip install --no-deps \
  <dist>/herzchen_contracts-0.1.0-py3-none-any.whl
env -u PYTHONHOME -u PYTHONPATH <venv>/bin/python -m pip install --no-deps \
  /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/sources/Astrid-96e5664237eb
exit 0 for every command.
```

Installed focused run:

```text
env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \
  <venv>/bin/python -m pytest -q -ra \
  tests/authoring/test_finish.py::FinishTests::test_direct_capture_failure_returns_actual_recovery_receipt \
  tests/authoring/test_finish.py::FinishTests::test_direct_capture_failure_exact_public_retry_returns_bound_recovery_without_mutation \
  'tests/conformance/test_c33_persisted_port_conformance.py::test_persisted_port_public_handler_conformance[C33-93c383e03e9e]'
exit 0 — 3 passed, zero skipped.
```

One coherent final installed campaign:

```text
env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 TMPDIR=/private/tmp \
  C33_RUN_ID=gf01-gf02-dat76-correction-final-installed-20260914 \
  C33_SOURCE_COMMIT=7c15ae26909cd8a0da52e4a3231468d7459146f5 \
  C33_SOURCE_TREE=3b27fa3319b57ada95b4aadc62445834bfb4e7d4 \
  C33_WHEEL_SHA256=4da6dd9f56f705831f0dc8a282526de0c28031fca2331074b359803195db4f9b \
  <venv>/bin/python -m pytest -q -ra --junitxml=<correction-junit> \
  tests/kernel/test_context_digest_correction.py \
  tests/kernel/test_public_command_capabilities.py \
  tests/kernel/test_public_mutation_admission.py \
  tests/kernel/test_receipts_limits.py \
  tests/extensions/test_definition_admission.py tests/extensions/test_namespaces.py \
  tests/work/test_batches.py tests/work/test_assignments.py \
  tests/work/test_identity_graph.py tests/work/test_gf02_c33_replay_closure.py \
  tests/assessment/test_accounting.py tests/authoring \
  tests/packs/test_authoring.py \
  tests/conformance/test_c33_persisted_port_conformance.py
exit 0 — 248 passed, zero failed/errors/skipped. All applicable Astrid tests ran.
```

Independent strict checker:

```text
env -u PYTHONHOME -u PYTHONPATH <venv>/bin/python \
  /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/c33-persisted-port-strict-acceptance.py \
  --inventory work/gf01-gf02-dat76-correction-descriptor-inventory.json \
  --matrix work/gf01-gf02-dat76-correction-c33-matrix.json \
  --result work/gf01-gf02-dat76-correction-c33-result.json
exit 0 — C33 strict acceptance: 76 admitted descriptors, all passed.
```

The final mechanical verifier also exited 0 after checking JSON syntax, all Git
object types and exact trees, 22-row manifest uniqueness, five-row GF01
ancestry, the exact 76-row inventory/matrix/result bijection, 76 passed status
values, full action/replay recovery-result equality, replay and changed-request
zero deltas, one capture call, installed module origins, unset Python path/home,
and the exact clean Astrid pin.

A preliminary non-final aggregate invocation was run from an archived test root
before the final source was frozen. It produced 242 passes and six fixture
setup errors because `tests/packs/test_authoring.py` intentionally resolves a
sibling `Herzchen-pkg04-worker` relative to the checkout; that sibling does not
exist beside an isolated `/private/tmp` archive. The authoritative final command
above ran the same installed packages from this replacement checkout, resolved
the required pinned sibling at commit `62503c6bf1e08e6399ed97bc4ee5aab7d3f3d96e`,
and passed with zero skips. This is not an unresolved product issue.

## Corrected evidence SHA-256

| Artifact | SHA-256 |
|---|---|
| `src/herzchen/authoring/sessions.py` | `2bee1bc7d86cb28611dc8e53f1c0795a4b02756d9ffadf6df65f19263f6c2669` |
| `tests/authoring/test_finish.py` | `2e50fda96915ae8d2e4bdca440069d456a923017790c0563655f7e7e0238fc18` |
| `tests/conformance/test_c33_persisted_port_conformance.py` | `a0f44906adc74027299faca5055b3d855f3643ebc71b84da8e367418968e2414` |
| `work/gf01-gf02-dat76-combined-input-manifest.json` | `927b02bc8459b83202cdffb765dc66c42100ffa0aef8fc6d88f056b42b5361b6` |
| `work/gf01-gf02-dat76-correction-descriptor-inventory.json` | `eadcdaf81ef0e83158a5c9cc34756f4f8472792f2c60a53529551bb3e77e88ab` |
| `work/gf01-gf02-dat76-correction-c33-matrix.json` | `3ad1a6d3902256171c6d18d97378cad844f08bb8ebf269c89c43b384c28f7bff` |
| `work/gf01-gf02-dat76-correction-c33-result.json` | `6a0059ea424a849b0e62cf4fd9c00c461f9e47670e0602717f4f7f932dda09cc` |
| `work/gf01-gf02-dat76-correction-installed-junit.xml` | `c2e2d3053b00fed8d88b657bf9ada4adf5a621611a3d654f353cd249fc03d09e` |
| `work/gf01-gf02-dat76-correction-module-origins.json` | `8b0b59544fbec07749c72edffe7a96f65c95c7e3d360ce854e121947ae93dd7f` |
| `work/gf01-gf02-dat76-correction-focused-installed.txt` | `77d92cd56cd64a1a5b65adac4e344cc7fd9699faace17014c0a319c92f46082d` |
| `work/gf01-gf02-dat76-correction-installed-run.txt` | `344a1339d7532877b9ff8aa9538b7ab1ebaee8b5e73e83c99208f1268de04357` |
| `work/gf01-gf02-dat76-correction-strict-check.txt` | `e5c6f2c26d9cf92e1977f6d47e2704497c490ed4bd604178bc05d733ef35fb0c` |
| `work/gf01-gf02-dat76-correction-wheel-sha256.txt` | `d6e971d33b14acd0f09e0c28966b4090be6d6b52101facd890832547d396f48d` |
| Candidate wheel | `4da6dd9f56f705831f0dc8a282526de0c28031fca2331074b359803195db4f9b` |

## Unresolved issues

None within the requested bounded correction and verification scope.
