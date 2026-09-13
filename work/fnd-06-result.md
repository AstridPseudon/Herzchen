# FND-06 packaged-kernel and reduced-composition result

Status: candidate-ready handoff. This is bounded candidate evidence, not a product, Runtime/Astrid, AST, or live-controller verdict.

## Exact candidate and custody

- Worker: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd06-worker`, branch `fnd-06-worker`.
- Supplied base: `e9f91f196d5130965069c6110e3f2d60098c3952` / tree `a735253153056ae80b755005b64ee78d4322f275`.
- Required preflight: `211571555e2ab798faad0f3c5644ea477d1dd5f2` / tree `d7c3821c68ebc1a73ab358b8366ff22f71aecc3f`; clean.
- Candidate source commit/tree used for the final wheel: `9e15ad908c4a9773ce27e7ff8e03e3dfca274c9b` / `db08184a5bf81a74c1970db7ac741f97cc192cda`; clean at source handoff.
- Handoff: [`handoffs/FND.json`](../handoffs/FND.json). Receipt: [`work/fnd-06-receipt.json`](fnd-06-receipt.json).

No merge or push was made. No canonical ledger, package seed, extraction map, Runtime/Astrid checkout, or other owner worktree was changed.

## Lineage and source manifest

The refreshed manifest is `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/source-set-int01-refresh-20260913.json`, SHA-256 `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.

The accepted typed revision baseline is source `59043551e6fb4a19d7130d5aa47cf75a732e0a45` / tree `39bb3ac322855f3e6552813b3ce87c6834d40917`; current blobs are `src/herzchen/kernel/store.py` `0c133689d8f20fc24005b1ee5fa531a57f0e7eca` and [`tests/kernel/test_identity_revisions.py`](../tests/kernel/test_identity_revisions.py) `be3627efacb723a8bcb14c009ef6b633ecee719a`. It was not duplicated or rewritten.

FND-05 original source `13f23ec6b00bfd7ecb2b6534ded49029b1c94a23` and corrected source `8258aafc8fa95e23ce7ff50303c01583c9f8e605` / tree `273695de8c2091e268d85eaa77cfd85a66cf0db4` are retained through current cherry-pick `2115715`. The corrected supplement remains separate at `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-fnd05-correction-worker/work/fnd-05-correction-result.md`, SHA-256 `2c3e5b143965f259b36a22b38b60e974105824c12b64b4f790d37bc13818b47b`; its original installed supplement is not silently reused as proof for the corrected candidate.

This result cites the single extraction map `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/plan/extraction-map.json` (SHA-256 `3ec83c6ff9b6e5ab415827b3bb38412a80349745ace2b442c0f7379c74fb59a3`), entries `EX-STORE`, `EX-OPS`, and `EX-EVENTS`. Those entries remain proposed discovery lineage, not consumer-cutover or installed-origin evidence. Runtime lineage is commit/tree `afccb430e2a983c968b6a8a96fd630ba3a6262fc` / `be89db2f02231aeef212bdb266d12c51778f32ae`; Astrid lineage is `96e5664237eb35adeb4cad08bddd8cd6df0a2ae1` / `19f7539a266618a797559eedbda48e2752b30fa3`.

## Candidate package and installed proof

Built from a temporary source copy with repository-root `work/`, `tests/`, and `handoffs/` omitted. Final artifact:

- Distribution: `herzchen-contracts==0.1.0`; `Requires-Dist`: none.
- Python: `3.11.16`; venv `/private/tmp/herzchen-fnd06-candidate-final2.JMsgxP/venv311`.
- Wheel: `/private/tmp/herzchen-fnd06-candidate-final2.JMsgxP/wheels/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `4ac45490195be909ada4e9f1bdce87b9e098dd2b9526b70c622302495651dbc3`.
- Installed tests used `env -u PYTHONPATH -u PYTHONHOME`; checkout `src/` was not importable. Wheel contained 34 files and no root `work/` or `assessment/` files.
- Observed installed origins were under `/private/tmp/herzchen-fnd06-candidate-final2.JMsgxP/venv311/lib/python3.11/site-packages/` for `herzchen`, `herzchen.contracts`, kernel schema/store/operations/limits/recovery, adapters host/receipt, and `herzchen.domains.work` when that optional composition was explicitly tested.

Fresh subprocess import observation imported `herzchen.kernel` and `herzchen.adapters` and loaded no optional modules: `herzchen.domains.work`, `herzchen.domains.megado`, `herzchen.domains.god`, `herzchen.domains.shot`, `herzchen.runtime`, `herzchen.astrid`, or `herzchen.otto`. Their specs were absent except packaged `herzchen.domains.work`, which was not imported in the reduced run. Package metadata and runtime module specs/import observation, not source-string search alone, supplied this dependency proof. The added exact assertion is [`tests/kernel/test_reduced_composition.py`](../tests/kernel/test_reduced_composition.py), SHA-256 `5f11a45e807e542a9bfb4d9dd4b9c65860a135fab0805d12c8489793dad38a20`; the minimal package marker is `src/herzchen/domains/__init__.py`, SHA-256 `a6d310139109be639186fde21a94d4f84ac8d1af538b7301ba4f1c504da2efeb`.

Installed schema/readback proof recorded:

- schema revision `fnd-03.v1`; schema fingerprint `367b22e1a345e13539ce6cef0d302d507bebe36e73cda68010c4f037e8c1ca5c`;
- composition `store_metadata, identities, record_references, event_sequences, command_receipts, events`; composition digest `bff6fc666dc6bdf41973b68606b13765c5581a04e8cfa7f20785fb3bb07f1713`;
- contract revision/digest `fnd-02.v1.1` / `28ee051bef55163e79be8acf17513eccd258769f9cebcb5a2608bdb8bd300264`;
- fresh and reopened identity revision `rev-1`, version `1`; committed receipt and one event share the transaction ID; receipt/event IDs and references agree; coherence was `True`.

## Installed commands and results

All commands and timestamps are reproduced in `handoffs/FND.json`.

- Focused installed kernel: identity revisions, transactions, receipts/limits, corrected recovery, and reduced import test — exit `0`; `47 passed, 10 subtests` at `2026-09-14T01:49:45+02:00`–`01:49:46+02:00`.
- Installed `kernel+documents`: `tests/content/test_documents.py`, `test_document_authoring_contract.py`, `test_context_visibility.py` — exit `0`; `31 passed`.
- Installed `kernel+work`: `tests/work/test_identity_graph.py` — exit `0`; `6 passed`.
- Installed common conformance: `tests/conformance/test_fixtures.py`, `test_matrix.py`, `test_rehearsal.py` — exit `0`; `17 passed, 70 subtests`.
- Installed schema/history proof — exit `0`; metadata, fresh reads, receipt/event transaction binding, reference history and reopen replay coherent.
- Source-only sanity: `PYTHONPATH=src ... pytest -q tests/kernel/test_reduced_composition.py` — exit `0`; `1 passed`; this does not replace the installed proof above.
- `git diff --check` — exit `0`.

The default macOS Python 3.9.6/setuptools 58 attempt produced a superseded `UNKNOWN-0.0.0` wheel and no pytest module in its venv; it is recorded separately as an environment/tooling failure in the handoff and is not candidate evidence.

## Limits

Unmanaged host writers, external exactly-once boundaries, optional-domain adapter ownership, and all live Runtime/Astrid/AST/controller execution remain outside this handoff. The common conformance matrix is installed and run, but its own fixture/product status remains respected. No product migration, scheduler, shot-specific behavior, or installed Runtime/Astrid origin is claimed.
