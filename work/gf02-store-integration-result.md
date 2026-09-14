# GF02/GF01 transaction-context integration checkpoint

Date: 2026-09-14 (Europe/Berlin)

Status: bounded pre-GF03 integration checkpoint. This evidence does not claim GF03 completion, a final installed campaign, or a gate decision.

## Checkout and custody

- Checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf02-store-integration`
- Branch: `gf02-store-integration`
- Starting source: `ce5dd4907e712f45caf29c238d5db8a5582e5228`; tree `6616e77efc4c4bca336f43ce3a79008c7dc9ce11`
- Accepted GF01 custody source: `d040ef212f6c57fdb963530124ac79795241d8ce`; tree `d253707effa7bc69147406e67d26f2a5b664c597`. Its cherry-pick is local commit `17d5bda`; the resulting tree is byte-identical to the accepted GF01 tree.
- GF02 custody source: `e8e3c3651d16986bc9bed38ca3b4ee79907340fc`; tree `529489c1946e09ea82d4b6ba949cf981f6754e56`. Its cherry-pick required a narrow `limits.py` conflict resolution to retain GF01 `_COMMAND_PORTS` boundaries while carrying GF02 context fields; the combined GF02 commit is `56f6208`.
- Final mechanical integration commit: `d2dc937ba07954d2015d50305efc5859b577471a`; tree `d5cf838300f90d7a0bbb203184d2460e4ac45bac`.
- Working tree: clean after the evidence commit.

## Integration changes

The Store now recomputes the canonical request digest with `envelope.context`. Authoring sessions, DAT document/link/unlink operations, and assessment envelopes construct the same explicit transaction context before hashing. Exact replay therefore retains all five context inputs instead of silently recomputing from current identity state. The public mutation admission assertion now uses the original envelope context when deriving its expected digest.

The five GF02 context-recomputation failures were corrected without xfail or waiver. The content create path keeps `expected_revision=None` for a new identity and uses the admitted base revision only for an append.

## Validation

Command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.11 -m pytest -q tests/authoring tests/content tests/assessment tests/kernel/test_public_mutation_admission.py tests/kernel/test_receipts_limits.py tests/kernel/test_context_digest_correction.py
```

Result: `122 passed, 1 skipped in 1.07s`.

`git diff --check` and Python 3.11 source compilation passed before commit. No source path injection beyond the checkout's explicit test `PYTHONPATH=src` was used in this source validation. The full built-artifact campaign remains held until the accepted GF03 handoff is available.

