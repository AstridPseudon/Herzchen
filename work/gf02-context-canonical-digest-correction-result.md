# GF02 transaction-context canonical digest correction

Status: bounded source correction complete. This is not a review, oracle, gate,
consumer launch, or Store/DAT end-to-end closure.

## Custody and scope

- Route/model/reasoning: `normal / gpt-5.6-luna / high`.
- Base: `ce5dd4907e712f45caf29c238d5db8a5582e5228`, tree
  `6616e77efc4c4bca336f43ce3a79008c7dc9ce11`, branch
  `gf02-context-correction-worker`.
- Owned changes only: `src/herzchen/contracts/model.py`,
  `src/herzchen/kernel/operations.py`, `src/herzchen/kernel/limits.py`,
  `tests/kernel/test_context_digest_correction.py`, and this `work/` report
  plus JSONL receipt.
- `kernel/store.py`, DAT authoring/lifecycle modules, foundation packets/maps,
  control records, Otto/Astrid/Runtime, and upstream targets were not edited.

## Correction and exact adoption interface

`canonical_request_digest` now includes a deterministic
`transaction_context` object containing exactly:
`expected_revision`, `expected_version`, `edit_token`, `correlation_id`, and
`causation_id`. The preferred adoption interface is:

```python
canonical_request_digest(
    logical_request_key=context.logical_request_key,
    operation=operation,
    schema_revision=schema_revision,
    target=target,
    actor=context.actor,
    payload=final_envelope_payload,
    context=context,
)
```

Here `context` is the immutable `TransactionContext` that will be put in the
final `CommandEnvelope`; `final_envelope_payload` must be the exact JSON-safe
payload sent to the writer. The helper hashes no `request_digest`, current
identity, current version, current revision, or store-derived projection. The
legacy scalar keyword form remains available for adopters during migration and
must provide all five names explicitly. The output remains a lower-case
SHA-256 hex digest over the existing sorted/separator-free canonical JSON
format.

`OperationRequest` now carries all five context inputs, persists them in its
neutral identity payload, and puts them into every envelope/digest it builds.
`LimitService` public pool, reservation, and transition builders accept and
forward all five inputs. The owned operation/limit replay prechecks now call
strict `validate_replay` with no context-free legacy fallback. A
pre-correction receipt therefore cannot be admitted when any context input is
different (and cannot be safely replayed at all until its owner records the
complete context).

## Evidence separation

Fixture/helper evidence in `tests/kernel/test_context_digest_correction.py`:

- each of the five fields changes the digest;
- context and explicit-scalar helper forms agree;
- changing the supplied digest does not change identity;
- changing an external current identity projection does not change identity;
- the actual public `OperationRequest.envelope` and public `LimitService`
  builder envelopes carry all five fields and their digest equals the helper.
- five parameterized strict-replay cases reject each changed context field
  against a pre-correction receipt; five additional public `LimitService`
  cases prove the owned replay path rejects those same legacy receipts.

Product/replay evidence:

- follow-up correction command: `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/kernel/test_context_digest_correction.py`
  — exit 0, 14 passed;
- pre-correction compatibility check: `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/kernel/test_receipts_limits.py`
  — exit 1, 8 passed and 5 failed. The five failures are exact replay/reopen
  expectations against receipts whose frozen Store digest omits context; they
  now fail closed at strict `validate_replay` and are pending Store adoption.
- affected contract/kernel command: `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/contracts tests/kernel`
  — exit 1, 97 passed, 5 failed, 10 subtests. All five failures are the same
  frozen-Store pre-correction replay seam; no new unrelated failure appeared.
- previous focused command: `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/kernel/test_context_digest_correction.py tests/kernel/test_receipts_limits.py tests/contracts/test_contracts.py`
  — before this follow-up, exit 0, 41 passed, worker PID 77130,
  2026-09-14T08:20:15+02:00 to 08:20:16+02:00;
- affected command: `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests/contracts tests/kernel`
  — exit 0, 92 passed, 10 subtests, worker PID 77149, 2026-09-14T08:20:20+02:00 to
  08:20:21+02:00;
- prior full source smoke: `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest -q tests`
  — exit 0, 295 passed, 12 skipped, 80 subtests;
- installed focused command against the wheel’s site-packages — exit 0, 17
  passed. Disposable venv: `/private/tmp/gf02-context-correction-offline.LvGqxs/venv`,
  Python 3.11.16. Wheel:
  `/private/tmp/gf02-context-correction-offline.LvGqxs/wheel/herzchen_contracts-0.1.0-py3-none-any.whl`,
  SHA-256 `1ed268c6fe4152c3b142652336a5f812bc93b9028eaa9df1ec9ed9ae43d4376c`.
  Installed origins were the venv `site-packages/herzchen/...` paths for the
  package, contracts, kernel, operations, and limits modules; `PYTHONPATH` and
  `PYTHONHOME` were unset for the direct installed probe.

The earlier full source suite remains evidence for compatibility construction,
but its old exact-replay expectations are no longer a valid post-follow-up
result. The strict follow-up intentionally exposes the frozen Store seam; it is
not evidence of persisted five-field closure because Store still recomputes its
receipt digest without the context object.

## Exact pending FND/DAT call-site bindings

The base has six source helper callers. Owned callers are complete:

- `kernel/operations.py`: `OperationRequest` creates the final context and
  passes it to the helper for canonicalization and envelope construction.
- `kernel/limits.py`: each builder creates the final context and passes it to
  the helper before creating its envelope.

Pending owners must apply the exact interface above, without reading current
identity state into the digest:

- FND `src/herzchen/kernel/store.py:885`: pass `envelope.context` as
  `context`, the unchanged envelope operation/schema/target/actor, and the
  exact `envelope.payload`. Replace the context digest on the immutable
  envelope copy as today.
- DAT `src/herzchen/authoring/sessions.py:371-399`: build one context from
  the same actor/request id, expected revision/version, edit token, and
  correlation/causation metadata used by the final envelope; hash the exact
  final payload with that context, then place that digest/context in the
  envelope.
- DAT `src/herzchen/content/authoring.py:458-500`: use the command’s explicit
  expected revision/version and authoring metadata in one context; hash the
  exact document/revision replay payload. Do not substitute the current
  document projection for an expected field.
- Assessment `src/herzchen/domains/assessment/module.py:617-623`: create the
  context with its explicit expected revision/version and correlation/causation
  values (null when the command has none), then pass that context and the
  exact envelope payload to the helper.

For each pending Store/DAT path, the follow-up proof must create one committed
request, reopen a fresh reader/writer, then retry the same logical key with the
old supplied digest while changing, one at a time, expected revision, expected
version, edit token, correlation id, and causation id. Every retry must raise
`ReplayConflictError` before a durable delta; event, identity, receipt,
reference, and sequence counts must remain unchanged. An unchanged retry must
remain one-effect idempotent, and the old caller digest must never bypass the
conflict. This worker intentionally does not claim those persisted cases.

The follow-up specifically removes the unsafe legacy-receipt fallback from
`OperationManager` and `LimitService`. No Store/DAT source was changed.

## Commit custody limitation

The source checkout itself is writable, but its linked Git metadata resolves to
the parent worktree store outside the writable sandbox. The exact staging and
commit attempt failed before staging with `Unable to create .../index.lock:
Operation not permitted`. Therefore the final HEAD/tree remain the supplied
base until a manager with Git-metadata write access commits these owned paths;
the final response reports the resulting non-clean status explicitly.

## Final installed evidence refresh

This refresh rebuilt the current strict source after fallback removal without
changing source, Store, or DAT files.

- Wheel command: `/opt/homebrew/bin/python3.11 -m pip wheel --no-deps --no-build-isolation --wheel-dir /private/tmp/gf02-context-correction-refresh.CUM5VH/wheel .`
- Wheel: `/private/tmp/gf02-context-correction-refresh.CUM5VH/wheel/herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `1238d374319d731a874bc8e4b98bb09d47c9551520c84c8697a166c2b5397ee5`
- Fresh venv: `/private/tmp/gf02-context-correction-refresh.CUM5VH/venv`, Python 3.11.16,
  created with system pytest available; wheel installed with `--no-deps`.
- Direct probe command used `env -u PYTHONPATH -u PYTHONHOME`; all module origins
  were under `/private/tmp/gf02-context-correction-refresh.CUM5VH/venv/lib/python3.11/site-packages/`:
  `herzchen/__init__.py`, `herzchen/contracts/__init__.py`,
  `herzchen/kernel/__init__.py`, `herzchen/kernel/operations.py`, and
  `herzchen/kernel/limits.py`.
- Installed focused command:
  `env -u PYTHONPATH -u PYTHONHOME /private/tmp/gf02-context-correction-refresh.CUM5VH/venv/bin/python -m pytest -q tests/kernel/test_context_digest_correction.py`
  — exit 0, 14 passed.
- Installed affected command:
  `env -u PYTHONPATH -u PYTHONHOME /private/tmp/gf02-context-correction-refresh.CUM5VH/venv/bin/python -m pytest -q tests/contracts tests/kernel`
  — 97 passed, 5 failed, 10 subtests; the five failures are the known
  frozen-Store pre-correction replay seam and are recorded separately. This
  refresh makes no Store/DAT persisted-closure claim.
