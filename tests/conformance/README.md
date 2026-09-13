# INT-02 conformance harness

This directory contains deterministic, stdlib-only inputs for the INT-02
conformance matrix.  Fixture output is labelled `harness_input`; it is not
product state, installed-product evidence, fresh-agent evidence, or media
evidence.  No fixture targets the canonical control ledger and no test imports
product-private code.

`validation/scenarios.json` retains the package's 49 planned scenario IDs and
adds direct before/action/fresh-after, persisted state, event/receipt, replay,
rejection, and restart expectations.  `validation/area-command-bindings.json`
has one row per planned owner/area.  Product commands are intentionally null
and marked pending until the owning product supplies a real public entrypoint.

The fixture builders adapt the behavior/spec intent of these package inputs:

- `validation/test_control_trial.py`
- `validation/test_execution_clarity.py`
- `validation/test_execution_learning.py`
- `validation/test_lineage.py`
- `validation/test_v11_operating.py`
- `validation/area-contracts.json`

Those are lineage/spec evidence only.  They are not copied private SQL and
they do not establish a product pass in this empty INT-02 repository.
