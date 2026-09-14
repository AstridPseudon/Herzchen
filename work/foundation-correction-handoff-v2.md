# Foundation correction handoff v2

This is metadata-only packet preparation after sealed bounded correction `a9d9727`. It does not alter that frozen report, invoke review/gate/oracle, or claim acceptance.

## Current candidate and evidence

- Source: `7c15ae26909cd8a0da52e4a3231468d7459146f5` / tree `3b27fa3319b57ada95b4aadc62445834bfb4e7d4`.
- Evidence checkpoint: `075d8c99a3102414e65d3013a533b1d48a6d075c` / tree `0360a491e861828f27e7cb268a6f61b404590331`.
- Harness correction: `0bfd152c5399cf7dd9c94560d3ae2ccac5890009` / tree `3850370d055259bc302d7efd101696352fbe86eb`.
- Typed-rejection checker: `ca05a6ef76cdcb24a9d8523d09906653f9bd5bff` / tree `28c0251addaca79e05496995c381979c40e34b94`.
- Installed campaign: **248 passed, 0 skipped**, transcript `work/gf01-gf02-dat76-correction-installed-run.txt` (SHA-256 `344a1339d7532877b9ff8aa9538b7ab1ebaee8b5e73e83c99208f1268de04357`).
- Current C33: independent 76-descriptor inventory, 76-row result, strict typed checker passes; merged result `work/gf01-gf02-dat76-correction-harness-repaired-result.json` (SHA-256 `356c444612b74b4c3bf0ee8ac9706fc970abbd7511f2d398c47b833d9923ce5a`).
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

- The old evidence had five synthetic `RejectedWithoutException` labels despite successful exact replays/recovery returns. The corrected harness now submits a same-key changed logical request with typed `InvalidSessionError` or `ReplayConflictError` and verifies unchanged counts/events for `actor.release`, `finish.claim`, `finish.recovery`, `finish`, and `release`.
- The raw installed five-row result is `work/gf01-gf02-dat76-correction-harness-repair-installed-result.json` (SHA-256 `940e3460e3d785b65fcc98ba5c2240f5b9bda9ae06a247139eb7529e2f679ec1`), with transcript `work/gf01-gf02-dat76-correction-harness-repair-installed.txt` (SHA-256 `ae0f0fa0c72a74b3507128a9def99d944c7eb80a39185559575d7353d03e420e). It was produced by:
  `env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 C33_RUN_ID=harness-repair-installed-20260914 C33_RESULT_PATH=/private/tmp/c33-harness-repair-installed.eyIxXY/result.json C33_MATRIX_PATH=/private/tmp/c33-harness-repair-installed.eyIxXY/matrix.json /private/tmp/herzchen-correction-delivery.gA7Nsm/venv/bin/python -m pytest -q -ra tests/conformance/test_c33_persisted_port_conformance.py -k 'dc2ced1157ed or 857bfa7ba9e7 or 93c383e03e9e or 2962a59f53a9 or be47b08ec0ae'`
  with exit `0`, output `5 passed, 72 deselected in 0.28s`, Python 3.11.16, both `PYTHONHOME` and `PYTHONPATH` unset, and wheel SHA-256 `4da6dd9f56f705831f0dc8a282526de0c28031fca2331074b359803195db4f9b`. The raw source result is `work/gf01-gf02-dat76-correction-harness-repair-source-result.json` (SHA-256 `6c59e486d90c828d43a0b17c2e726a3c808589d5bc56516315b46aa53e62053b`) with transcript `work/gf01-gf02-dat76-correction-harness-repair-source.txt` (SHA-256 `e7f9342ec5b026e182045de3df14e92c494c297bab484fecfcfd862cf05ba272), exit `0`, output `77 passed in 4.07s`.
- The corrected checker script is `work/c33-persisted-port-strict-acceptance-corrected.py` (SHA-256 `dd11693400fd97e809f7ab31ce438152dc2632d42d82c28b49c8293cbc0b8533`, commit `ca05a6ef76cdcb24a9d8523d09906653f9bd5bff`, tree `28c0251addaca79e05496995c381979c40e34b94`). Running it on the old result `work/gf01-gf02-dat76-correction-c33-result.json` exited `1` with exactly five synthetic-row failures; running it on merged result `work/gf01-gf02-dat76-correction-harness-repaired-result.json` exited `0` with `76 admitted descriptors, all passed`. The old/new checker output files are `work/gf01-gf02-dat76-correction-harness-repair-strict-check-corrected-old.txt` (SHA-256 `511d60603771f72055aad93c5572e7941cecf0a3a93202da26241c0852641cbe) and `work/gf01-gf02-dat76-correction-harness-repair-strict-check-corrected-new.txt` (SHA-256 `e5c6f2c26d9cf92e1977f6d47e2704497c490ed4bd604178bc05d733ef35fb0c). The product wheel and source remain unchanged by this harness correction.

## Criteria and scenario applicability

- `candidates/foundation.json` and `evidence/foundation-coverage.json` retain the full original C01–C17/C31/C33–C35/C38/C39 criteria list and the 49 original scenario records losslessly.
- `criteria_applicability` explicitly separates current installed evidence from retained historical references. Content/DAT rows absent from the final 248-test selection remain marked retained or mixed; no historical aggregate is claimed as a current rerun.
- Otto/Astrid consumer journeys, publication, cutover, and G-FINAL remain later-stage obligations. Gate state remains `pending`.

## Packet hashes

- Candidate packet SHA-256: `6ef1da40d94456a2061f04e6e22101f77ae40ef778ce4cb009116c48353a39b5`.
- Coverage packet SHA-256: `bfccf267fcc9fc17d20576323ece20828407caf83b73388acf25266d2830e7ac`.
- This handoff SHA-256 is recorded after writing: (computed by parent after commit).
