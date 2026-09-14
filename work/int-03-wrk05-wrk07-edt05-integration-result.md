# INT-03 versioned integration checkpoint: WRK-05 + WRK-07 + EDT-05

Status: dependency-baseline preparation only. This checkpoint does not claim INT-03 completion, G-FOUNDATION, a gate verdict, product qualification, review/oracle approval, or publication. The sealed INT-03 API-probe evidence from `07044ba` is preserved byte-for-byte and was not rerun or rewritten.

## Integrated source set

- API-probe baseline: `07044ba553f7dc648c89edd37f65032346cdf727`, tree `a4f9757ee7eb280079dd081fa82fef5004bdb190`.
- WRK-07 accepted source: `5c8d89ba997998b0b6c420d2d4827c18ec476697`, tree `bb916b3d1bf523447047f55f0ea7ce41f998dc9d`.
- WRK-05 accepted source: `6efdda1cb73fd4ca3438fd83189a69eb40d42c2b`, tree `34f7df82876d6bfa52554c1085a6bd597f25d75a`.
- EDT-05 candidate source integrated for dependency proof: `023de7472e15c8b64356dc1d2b3a400071502462`, tree `c449148badec5670358499411920dacce6fdb3b4`. Root acceptance remains separate.
- Integration checkout: `Herzchen-int03-wrk05-wrk07-edt05-integration`.
- Current checkpoint before this report commit: `e9f58d2fa7f0c2e15caec95f191a1394118f2ed6`, tree `139e026e79a02fee7ef76e2c62599fb5e7dda038`.

The API evidence files are unchanged from `07044ba`: `work/int-03-api-probe-evidence.json`, `work/int-03-api-probe-result.md`, `tests/conformance/test_int03_public_api_probes.py`, and `validation/int03-area-links.json`.

## Installed proof

Candidate wheel was built from the integrated source with `/opt/homebrew/bin/python3.11` and installed into disposable environment `/tmp/herzchen-int03-next.9YUIBp/venv`. Wheel SHA-256:

`12ba40985af69fcf3e2c63651d207f6c3436103f4fcad6f5095d16519e9b88c6`

With both `PYTHONPATH` and `PYTHONHOME` unset, the installed origins were:

- `herzchen`: `/private/tmp/herzchen-int03-next.9YUIBp/venv/lib/python3.11/site-packages/herzchen/__init__.py`
- `herzchen.domains.work.decisions`: `/private/tmp/herzchen-int03-next.9YUIBp/venv/lib/python3.11/site-packages/herzchen/domains/work/decisions.py`
- `herzchen.domains.work.sheet`: `/private/tmp/herzchen-int03-next.9YUIBp/venv/lib/python3.11/site-packages/herzchen/domains/work/sheet.py`
- `herzchen.authoring.integration`: `/private/tmp/herzchen-int03-next.9YUIBp/venv/lib/python3.11/site-packages/herzchen/authoring/integration.py`

Focused combined installed command:

```text
env -u PYTHONPATH -u PYTHONHOME /tmp/herzchen-int03-next.9YUIBp/venv/bin/python -m pytest -q -rs \
  tests/work/test_candidates_decisions_waiting.py \
  tests/work/test_sheet_batches.py \
  tests/authoring/test_three_targets.py \
  tests/authoring/test_exclusivity.py \
  tests/authoring/test_finish.py \
  tests/authoring/test_snapshots.py \
  tests/authoring/test_failure_matrix.py \
  tests/content/test_document_authoring_contract.py \
  tests/packs/test_authoring.py
```

Result: **64 passed, 11 skipped** in 0.50s. The 11 skips are optional Astrid-loader/source-setup checks because Astrid is not installed in this disposable Herzchen-only environment; no Herzchen test failed.

The previously reported WRK-05 source-checkout race (`FailureMatrixTests.test_cross_service_finish_loser_reconciles_durable_winner`, observed around `Store._identity_from_row`) was exercised through the integrated installed candidate three times:

- run 1: 8 passed
- run 2: 8 passed
- run 3: 8 passed

This is concrete combined-candidate behavior evidence; FND owner correction/acceptance remains a separate responsibility.

## Scope and remaining work

No product/control/package-seed/source-manifest/upstream write was made. Generated wheel/build/cache files were moved to disposable `/tmp` paths. EDT-05 remains a root acceptance dependency, and EDT-06/WRK-06 plus later consumer/API revalidation remain pending. The sealed API probe may be rerun only after the final settled candidate as directed by root.
