# Combined GF01/GF02/DAT76 integration result

Date: 2026-09-14 (Europe/Berlin)

Status: **bounded incompatibility; current C33 result is 75/76 and the strict
checker exits 1.** This worker does not claim INT03 or G-FOUNDATION completion,
gate acceptance, review/oracle authority, consumer cutover, or upstream
publication.

## Custody, source checkpoints, and inputs

- Sole writer checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-int-final-combined-xhard-worker`.
- Requested route: `gpt-5.6-sol`, high reasoning (`xhard`). The runtime does not expose an independent backend-model attestation.
- GF01/P01 source checkpoint: `8235d9aacbe7357e8f72cec8342eca77aab0cb58`, tree `c69702a8b42420159dbcdb4b0d572c0e8f9dfffa`.
- Integrated source checkpoint after the GF02 and DAT equivalent applications: `74c8cb56b0e530985384535ebeac7e8f1864427d`, tree `834dab82c220aaa4c9a3c11a851af8ec60c6cb0e`.
- Final campaign source HEAD: `98ff41e3cd662d96a0f71c8c64ddb61d44bda052`, tree `2ed55b5907c1d7e6870ec5f562a728b37e8e30ac`.
- `git status --porcelain=v1` immediately before the final archive/build had no output (exit 0). The final delivery commit and clean status are necessarily recorded after this report is committed because a report cannot contain its own commit hash.
- Generated input manifest SHA-256: `2bb4bdfe58041555b950492c6af2c19c24d8472288adb5f833907663e15aa520`.
- Adopted P01 amendment SHA-256: `d5e6f6ee114913a31f8fce4fed7a1f835f089e0859ccd5ce7941e9f094951503`.
- Read-only current extraction-map SHA-256: `bea51be5e6721e20a21e6befc0cd75dd340af103f722f0d154a671721520e413`.

The manifest records every full GF01, GF02, and DAT commit/tree and its
equivalent mapping. GF02 manager custody `768b765abeb3b53eeb67c8a124f48ad121bdcc76`
resolved to the required tree `33ad8844fd54a7a6898d1b12780c887034906297`;
its report explicitly retains that the v3 worker final was absent after the
authorized fence. DAT `9028f0f08af1844e29fba5fa4b14aa65793d161e`
resolved to `2d553b6c4c6ff653fca902741962953a66b3a11c` and was applied only as
test/evidence lineage. The historical 77-row matrix remains separate at
`work/c33-persisted-port-matrix-77-historical-20260914.json` (SHA-256
`4c5cb78ec497c58300bbc8d68e5c7571c563194717fc65bd7f3f4d00d8fcf766`).

## Conflict resolutions

The equivalent cherry-picks produced only accepted-contract overlaps:

- `ef13cfe`: `src/herzchen/domains/work/batches.py` — retained GF01's private typed `work_handler` command facade and admitted public operations while moving same-key replay ahead of current-projection/stale-base validation and retaining the full request context.
- `f620cd3`: `src/herzchen/authoring/sessions.py`, `src/herzchen/domains/assessment/module.py`, `src/herzchen/domains/work/assignments.py`, `src/herzchen/domains/work/batches.py`, `src/herzchen/domains/work/module.py`, and `src/herzchen/packs/authoring.py` — transplanted GF02 logical request payload, replay, result-payload, and context semantics onto GF01's sealed `self.__writer` command ports. No weak-map/private raw Store bypass was restored.
- `3582d9d`: authoring sessions and assessment — retained GF01 typed ports while adding cleanup replay payloads and correction/result replay composition.
- `768b765`: authoring sessions and assessment — retained GF01's accepted public `reject_finish` contract, returned the actual recovery receipt, normalized only derived assessment projections, and preserved explicit caller `ResourceRef` revision pins.

One imported GF02 test asserted that a fresh derived `Finding` projection was a
caller pin, contradicting the sealed manager report. The integrated test now
proves both accepted contracts: exact replay after a derived projection advances,
and `ReplayConflictError` with zero durable delta when the caller explicitly
passes the changed pinned `ResourceRef`. The DAT `finish.recovery` lookup was
changed only on the test side to include the actual
`request_id:capture-failure` locator. Production never fabricates a caller-key
success receipt.

## Wheel and installed origins

- Build source: disposable `git archive` of final campaign HEAD `98ff41e3cd662d96a0f71c8c64ddb61d44bda052`.
- Wheel: `/private/tmp/gf01-gf02-dat76-wheel-final.5mXRTN/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `8a2af12051568f244ca4e6f1d3d3dcc0b8730b28af52698e31f2195d7c868ae0`; size `218488` bytes.
- Disposable environment: `/private/tmp/gf01-gf02-dat76-venv-final.UXOPMx`; Python `3.11.16`.
- Both `PYTHONHOME` and `PYTHONPATH` were absent. Every recorded Herzchen origin is below `/private/tmp/gf01-gf02-dat76-venv-final.UXOPMx/lib/python3.11/site-packages/herzchen/`; see the hashed module-origin artifact.
- Independent installed contribution export: exactly 76 unique persisted mutation descriptors; catalog digest `4e452c740ff35e04b6527629ddf976b6fc6eba145b91e3768bac6de662685162`.

## Commands and exits

Input/custody verification:

```text
git status --short --branch && git rev-parse HEAD^{commit} HEAD^{tree}
exit 0 — clean at 8235d9a / c69702a

git fetch /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-c33-conformance-worker 9028f0f08af1844e29fba5fa4b14aa65793d161e
exit 0

git rev-parse <each required input>^{commit} <each required input>^{tree}; git merge-base --is-ancestor ...
exit 0 after the DAT fetch — all required objects, exact trees, and lineages verified

shasum -a 256 /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/periodic01-adopted-process-amendment-20260914.md
exit 0 — d5e6f6ee114913a31f8fce4fed7a1f835f089e0859ccd5ce7941e9f094951503

shasum -a 256 /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/plan/extraction-map.json
exit 0 — bea51be5e6721e20a21e6befc0cd75dd340af103f722f0d154a671721520e413
```

Equivalent applications:

```text
git cherry-pick -n ef13cfed36f8d43925a28e8312bf0235379b1488
exit 1 — resolved batches.py as recorded above

git cherry-pick -n ff5d85cc09ace8731845e8c7fb54d63bfd07e081 && git cherry-pick -n f620cd36d8f9267935e7b4ae7aa1f950a4b1db2d
exit 1 — ff5d85c applied; resolved the six f620cd3 paths recorded above

git cherry-pick -n 3582d9d129369c14be17ccc7e822001719ecfe6c
exit 1 — resolved sessions.py and assessment/module.py

git cherry-pick -n 768b765abeb3b53eeb67c8a124f48ad121bdcc76
exit 1 — resolved sessions.py and assessment/module.py

git cherry-pick -n 73b71d25b31091f581ff7fe40fbcc6f59764adda && git cherry-pick -n 254c1e9e715e625cf5448291e80b36cacc75c538 && git cherry-pick -n 9e27291551e28baae8c31d2d8fae91c2312430d0 && git cherry-pick -n 9028f0f08af1844e29fba5fa4b14aa65793d161e
exit 0 — DAT test/evidence only
```

Focused semantic checks after the conflict resolutions exited 0: `44 passed`,
`26 passed`, the authoritative five-test GF02 manager selection `5 passed`, and
the corrected explicit-pin/derived-projection case `1 passed`.

Final build/install command used `env -u PYTHONHOME -u PYTHONPATH`, a disposable
`git archive`, `pip wheel --no-deps --no-build-isolation`, a new venv, and
`pip install --no-deps`; exit 0.

The single final heavy installed pytest process invoked these affected paths in
one command:

```text
env -u PYTHONHOME -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \
  C33_RUN_ID=gf01-gf02-dat76-combined-final-installed-20260914 \
  C33_SOURCE_COMMIT=98ff41e3cd662d96a0f71c8c64ddb61d44bda052 \
  C33_SOURCE_TREE=2ed55b5907c1d7e6870ec5f562a728b37e8e30ac \
  C33_WHEEL_SHA256=8a2af12051568f244ca4e6f1d3d3dcc0b8730b28af52698e31f2195d7c868ae0 \
  /private/tmp/gf01-gf02-dat76-venv-final.UXOPMx/bin/python -m pytest -q -ra \
  tests/kernel/test_context_digest_correction.py tests/kernel/test_public_command_capabilities.py \
  tests/kernel/test_public_mutation_admission.py tests/kernel/test_receipts_limits.py \
  tests/extensions/test_definition_admission.py tests/extensions/test_namespaces.py \
  tests/work/test_batches.py tests/work/test_assignments.py tests/work/test_identity_graph.py \
  tests/work/test_gf02_c33_replay_closure.py tests/assessment/test_accounting.py \
  tests/authoring tests/packs/test_authoring.py tests/conformance/test_c33_persisted_port_conformance.py
exit 0 — 236 passed, 11 skipped
```

The 11 skips are only optional Astrid imports in `tests/packs/test_authoring.py`;
there are no skipped C33 rows. The current C33 result is not inferred from that
aggregate exit. Its independent strict command was:

```text
env -u PYTHONHOME -u PYTHONPATH /private/tmp/gf01-gf02-dat76-venv-final.UXOPMx/bin/python /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/c33-persisted-port-strict-acceptance.py --inventory work/gf01-gf02-dat76-combined-descriptor-inventory.json --matrix work/gf01-gf02-dat76-combined-final-c33-matrix.json --result work/gf01-gf02-dat76-combined-final-c33-result.json
exit 1 — 75 passed rows, 1 unresolved row
```

## Exact bounded incompatibility

- Row: `mutation-port:edt-02.authoring.v1|finish.recovery|authoring-scope|authoring.finish.recovery`.
- Phase: `exact_replay`.
- First action: valid. A failing capture produces durable
  `c33:C33-93c383e03e9e:capture-failure`, operation `finish.recovery`, with its
  exact event lineage. No receipt exists under the caller key, as required.
- Replay: the same public `AuthoringSessionService.finish` call observes the
  checkout already released by the first recovery and raises
  `InvalidSessionError: authoring session is no longer open` before it can
  resolve the recovery receipt.
- Root cause: the accepted GF02 source returns the real recovery receipt but
  does not define exact public `finish` retry ordering after capture recovery.
  Reordering session validation against recovery replay would be a new product
  semantic change, not a conflict-only integration resolution. It was not made.

The final 76-row matrix therefore remains a failed current campaign. Historical
70/1, five-test, 77-row, and attempt-01 counts are not added to it.

## Evidence SHA-256

- Input manifest: `2bb4bdfe58041555b950492c6af2c19c24d8472288adb5f833907663e15aa520`
- Attempt-01 C33 matrix: `cf7a322fb84cc4100f005999ae4b5adb9ce20e17bd279fe0c24be5fd3f86b6ff`
- Attempt-01 C33 result: `ebed4aa63d3f052bb4299febede31ca8fab1e9ef297daa96469f6176ba7c214e`
- Attempt-01 installed JUnit: `dd4f5198c6de3c86cd6e2202415899fc66d6dc7d6cb77dcb2eba6985f7e0bb9a`
- Independent final descriptor inventory: `e34f195365ddacf78971a10fe1ce9fd2f16a5cda062c1c3fe32ba9aabcdd00b4`
- Final C33 matrix: `1ac6456534cedafe63cf24e3c964487c1aa5821bf592239c2f28b835d0b85086`
- Final C33 result: `7af887f0b01eaf8703681c1526efc1c1fb37b6f7781c667954d963144a0dacd3`
- Final installed JUnit: `a033ce604f5a009a620dcf3ae6a579c2041da3c6c9b8bfba0531535a4bf6fe2f`
- Final installed module origins: `af3f377fd93494c01718517859c4c0a1eff4a18630c948a7d79e9a9f204a9d7c`
- Final strict-check transcript: `5f089987717545947d8f88df0199309e6eb41ff35a70eab85fe5f080702a3fe8`
- Worker receipt: `e00545ebf82625367db2bd4bd88753aa714de28dae300ecbcb4ee3b946418ba4`
- Candidate wheel: `8a2af12051568f244ca4e6f1d3d3dcc0b8730b28af52698e31f2195d7c868ae0`

The SHA of this result is recorded after writing and committing it; embedding a
file's own cryptographic digest inside itself is not possible.
