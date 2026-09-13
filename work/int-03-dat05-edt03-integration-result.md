# INT-03 DAT05 + EDT03 installed integration checkpoint

This is a bounded integration checkpoint, not an INT-03 task or gate verdict. It combines the submitted DAT-05 and EDT-03 source increments with the latest accepted common foundation and the accepted typed identity port and PKG-04 resources. No upstream or control-root writes were made.

## Source set

- Integration base: `c0c1ec742ddd8777dbabd0ce12923bd409e89a26`, tree `868de7edf69414c74df960881b1c740d19253d61`.
- Accepted typed FND identity revision source: `59043551e6fb4a19d7130d5aa47cf75a732e0a45`, tree `39bb3ac322855f3e6552813b3ce87c6834d40917`.
- Accepted PKG-04 source: `62503c6bf1e08e6399ed97bc4ee5aab7d3f3d96e`, tree `e6dc75c4d2c0bf9a54dae1048224f69186604de3`.
- DAT-05 submitted source: `3597187aaaebb627ed818f5dd3ab1f165eb15097`, tree `b405bdd3c229ee5d8fed04b8be5c45a86b71a64d`.
- EDT-03 implementation source: `6eeb3b7da6920e0871acb0036da92b0ebb2f9841`, tree `0720353cf741e6893911f269f30bf6eb8119e126`.
- EDT-03 receipt/result source: `06ef49474d00640c3ae989ea9b056884b4193bfd`, tree `c14f062def0b41f2dae8580319cf9e3dadfdad04`.

The isolated integration branch is `int-03-dat05-edt03-integration`. Because EDT-03's submitted receipt commit is a child of its implementation commit, both were included. Resulting pre-report checkpoint was `fd9f29eeb4f9a2b48db530241d1bd1c787dc982c`, tree `b8e86eca19ce509df6271fa58effcfe84662cb30`; the final report commit follows below.

## Installed proof

Candidate environment: `/tmp/herzchen-int03-dat05-edt03.DFOeUf`

- Python `3.12.14`; pytest `9.1.1`.
- Wheel: `/tmp/herzchen-int03-dat05-edt03-wheel.nJEaQu/herzchen_contracts-0.1.0-py3-none-any.whl`.
- Wheel SHA-256: `058e06689e69df6d1692e1fc40b3949720e3eddc72d31006f6a431ff5a3c4ec9`.
- Installed origins with `env -u PYTHONPATH`: `herzchen`, `herzchen.authoring.snapshots`, `herzchen.authoring.finish`, and `herzchen.content.authoring` all resolved from the candidate's `site-packages`.

Command:

```text
env -u PYTHONPATH /tmp/herzchen-int03-dat05-edt03.DFOeUf/bin/python -m pytest -q tests/authoring/test_snapshots.py tests/authoring/test_finish.py tests/content/test_document_authoring_contract.py tests/kernel/test_identity_revisions.py tests/content/test_documents.py tests/content/test_context_visibility.py tests/authoring/test_exclusivity.py tests/kernel/test_transactions.py tests/kernel/test_receipts_limits.py tests/packs/test_protocol_resources.py tests/packs/test_task_templates.py tests/packs/test_composition.py tests/work/test_identity_graph.py tests/contracts/test_contracts.py tests/extensions/test_namespaces.py tests/conformance/test_fixtures.py tests/conformance/test_matrix.py tests/conformance/test_rehearsal.py
168 passed, 80 subtests passed in 0.69s
```

The command used one candidate wheel and no `PYTHONPATH` injection. It covers DAT document authoring and replay/rollback, EDT snapshot capture/finish/manual-idle race/recovery, FND typed identity revision, and the accepted common kernel/content/work/pack/conformance suites.

## State

Generated build, egg-info, and `__pycache__` artifacts were removed with bounded path cleanup after testing. The integration worktree was clean before this report was written; no source owner paths were edited directly by the manager. Remaining INT-03 obligations (FND06/DAT06/PKG05/WRK06/EDT06 and the G-FOUNDATION packet) are not claimed complete.
