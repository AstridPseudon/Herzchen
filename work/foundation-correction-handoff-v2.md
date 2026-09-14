# Foundation correction handoff v2

This is metadata-only packet preparation after sealed bounded correction `a9d9727`. It does not alter that frozen report, invoke review/gate/oracle, or claim acceptance.

## Current candidate and evidence

- Source: `7c15ae26909cd8a0da52e4a3231468d7459146f5` / tree `3b27fa3319b57ada95b4aadc62445834bfb4e7d4`.
- Evidence checkpoint: `075d8c99a3102414e65d3013a533b1d48a6d075c` / tree `0360a491e861828f27e7cb268a6f61b404590331`.
- Harness correction: `0bfd152c5399cf7dd9c94560d3ae2ccac5890009` / tree `3850370d055259bc302d7efd101696352fbe86eb`.
- Typed-rejection checker: `ca05a6ef76cdcb24a9d8523d09906653f9bd5bff` / tree `28c0251addaca79e05496995c381979c40e34b94`.
- Installed campaign: **248 passed, 0 skipped**, transcript `work/gf01-gf02-dat76-correction-installed-run.txt` (SHA-256 `344a1339d7532877b9ff8aa9538b7ab1ebaee8b5e73e83c99208f1268de04357`).
- Current C33: independent 76-descriptor inventory, direct full installed 76-row result, strict typed checker passes; current result `work/gf01-gf02-dat76-correction-harness-repair-full-installed-result.json` (SHA-256 `4a239bbda2bd8ab85ee61c05a85c9fd07d9b7e2fee73305b7fbf4c64b28e0e6a`). The earlier mixed result is retained as historical evidence.
- Wheel: SHA-256 `4da6dd9f56f705831f0dc8a282526de0c28031fca2331074b359803195db4f9b`; Python 3.11.16; `PYTHONPATH` and `PYTHONHOME` unset.
- Astrid: source `96e5664237eb35adeb4cad08bddd8cd6df0a2ae1` / tree `19f7539a266618a797559eedbda48e2752b30fa3`, exact local source installed with `--no-deps`, built Astrid wheel SHA `1303e51cb8364339413fe4727897c220cfd58ab14c9abf55a3fbb988acdfe5d0`; no consumer cutover claimed.
- Exact PKG04 fixture: `62503c6bf1e08e6399ed97bc4ee5aab7d3f3d96e` at `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-pkg04-worker`.

## Review03 disposition and allowance

- Three review calls are exhausted: `call-7c10e35b0b2648779ced07f05ff100b7`, `call-e07c463c653c46af80488f19c319281a`, `call-1b0dcc88310d402ca2bf94c8680ee459`. Calls used `3/3`; remaining `0`.
- Review03 named GF01 authority and C33 evidence gaps plus GF02 context composition; GF03 named retirement residual passed.
- No further review/gate call is requested or claimed here.

## GF01 / GF02 / GF03

- **GF01:** finite typed command-port boundary is present in the current source and affected installed campaign. The historical 77-port obligation is explicitly represented as 76 current ports after the accepted unsupported `work.v1|work.revise|work.project|work.parent-linked` removal at `8235d9a`. Whether that scope interpretation and finite-port semantics satisfy final authority remains an unresolved root judgment; this packet does not silently convert it into acceptance.
- **GF02:** all five logical context fields (`expected_revision`, `expected_version`, `edit_token`, `correlation`, `causation`) and original caller references are retained through the integrated lineage. Current kernel/work/assessment/authoring tests and current C33 replay evidence apply; standalone historical GF02 receipts remain provenance.
- **GF03:** Review03 passed the named retirement residual: cross-process flock, generation leases, authenticated fences, held guard through capture/cleanup, manifest/fence checks through unlink, restart reacquisition, and fail-closed unmanaged writers. Current authoring campaign provides regression applicability; Otto/Astrid host qualification remains later.

## C33 correction

- The prior five-row installed JSON and merged result are retained as historical artifacts because they mixed phases from separate runs. The current result is a single direct 76-descriptor installed campaign: `work/gf01-gf02-dat76-correction-harness-repair-full-installed-result.json` (SHA-256 `4a239bbda2bd8ab85ee61c05a85c9fd07d9b7e2fee73305b7fbf4c64b28e0e6a`). It contains 76 rows, explicit source `7c15ae26909cd8a0da52e4a3231468d7459146f5` / tree `3b27fa3319b57ada95b4aadc62445834bfb4e7d4`, wheel path/SHA `4da6dd9f56f705831f0dc8a282526de0c28031fca2331074b359803195db4f9b`, and 16 recorded installed module origins under the disposable venv site-packages.
- Exact full-run command and environment are preserved in `work/gf01-gf02-dat76-correction-harness-repair-full-installed-command.txt` (SHA-256 `a337e25926dee140115a3fb05621f585661729f86d88ad27bb5e8a4f59e7f26b`). The pytest transcript is `work/gf01-gf02-dat76-correction-harness-repair-full-installed-pytest.txt` (SHA-256 `46aa9bbc078c028a5363ad43e7ee5c2dafb0ceaf453534e8d9995d0dec9a92a2); exit `0`, output `77 passed in 4.49s`, with `PYTHONHOME` and `PYTHONPATH` unset and `PYTHONDONTWRITEBYTECODE=1`. The generated matrix is `work/gf01-gf02-dat76-correction-harness-repair-full-installed-matrix.json` (SHA-256 `3ad1a6d3902256171c6d18d97378cad844f08bb8ebf269c89c43b384c28f7bff)`; origins input is `work/gf01-gf02-dat76-correction-harness-repair-full-installed-origins.json` (SHA-256 `8b0b59544fbec07749c72edffe7a96f65c95c7e3d360ce854e121947ae93dd7f).
- The corrected checker script is `work/c33-persisted-port-strict-acceptance-corrected.py` (SHA-256 `dd11693400fd97e809f7ab31ce438152dc2632d42d82c28b49c8293cbc0b8533`, commit `ca05a6ef76cdcb24a9d8523d09906653f9bd5bff`, tree `28c0251addaca79e05496995c381979c40e34b94`). It accepts this direct full result with exit `0`; output `work/gf01-gf02-dat76-correction-harness-repair-full-installed-strict-check.txt` has SHA-256 `e5c6f2c26d9cf92e1977f6d47e2704497c490ed4bd604178bc05d733ef35fb0c` and says `C33 strict acceptance: 76 admitted descriptors, all passed`. The old mixed result and five-row raw run remain linked under historical fields in both packet JSON files.
## Criteria and scenario applicability

- `candidates/foundation.json` and `evidence/foundation-coverage.json` retain the full original C01–C17/C31/C33–C35/C38/C39 criteria list and the 49 original scenario records losslessly.
- `criteria_applicability` explicitly separates current installed evidence from retained historical references. Content/DAT rows absent from the final 248-test selection remain marked retained or mixed; no historical aggregate is claimed as a current rerun.
- Otto/Astrid consumer journeys, publication, cutover, and G-FINAL remain later-stage obligations. Gate state remains `pending`.

## Packet hashes

- Candidate packet SHA-256: `73ca9f8d3f2b4a00811c6dc8d52208b506bfc21a43ab1046dbfeb327ef952ded`.
- Coverage packet SHA-256: `aa6a6e6d8a3726ad4b2256035bad31b1c224133257eeea8a6d526d0b7f4c140b`.
- This handoff SHA-256 is recorded after writing: (computed by parent after commit).
