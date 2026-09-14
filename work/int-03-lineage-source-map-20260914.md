# INT-03 final integration lineage mapping

The final integration line started from `2c6c586b4fada18e9115f5f249b7735dc25fbd48`
(tree `8a28fa21060624dc54302175091b1f1b03af86ab`). The original accepted
source commit IDs are not ancestors of that line because the equivalent patches
were integrated under local commits; patch identity and actual file content were
checked.

| accepted source | integration commit | stable patch id | actual integrated proof |
|---|---|---|---|
| `cec510615fa7a3c619a0c7e73d4d5a4dae851748` | `0556fea` | `f04e2de89298dd3a137e4d6c9dc5ac38734665c9` for both | `src/herzchen/authoring/finish.py` reconciliation around `authorize_mutation`; `src/herzchen/kernel/store.py` RLock around public reads; `tests/kernel/test_transactions.py::StoreTests::test_concurrent_public_reads_serialize_with_store_transaction` |
| `77bd75e4b4047d3ca32550f299d2b9cf2305dbfa` | `32692de` | `b74a9fc49d6868de57400c7778fe0001de96f1f8` for both | full `tests/authoring/test_handoff.py` including deterministic idle/timer, durable cleanup recovery, and fresh consumer-process/restart readback |

The final candidate now additionally contains metadata-only probe repair commit
`323c3c6a3ed2151d26cb4a3f31593214a497a97f`, tree
`17d10ad2dcdbfabdac6c138d08f826be835fcbad`. It removes three dangling
criterion-map references and preserves the historical probe receipt.

Validation on the integrated tree before the metadata-only commit:

```
env -u PYTHONHOME PYTHONPATH=src work/.venvs/int-02/bin/python -m pytest -q \
  tests/kernel/test_transactions.py tests/authoring/test_handoff.py
```

Result: `20 passed, 1 skipped in 0.36s`. The metadata-only repair does not
alter source or tests; rerun is unnecessary for that change.

The final integrated line contains the cec510/EDT06 behavior by equivalent patch
and actual function/test content, even though the original source hashes are not
ancestor commits. No gate or INT-03 completion is claimed.

