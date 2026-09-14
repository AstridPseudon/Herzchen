# GF03 residual XHARD correction result

Objective: close the residual cross-process compare/unlink race and make an
authenticated, complete retirement handoff mandatory for cleanup completion.

## Accepted input and scope

- Accepted base commit: `ce5dd4907e712f45caf29c238d5db8a5582e5228`
- Accepted base tree: `6616e77efc4c4bca336f43ce3a79008c7dc9ce11`
- Review input: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/g-foundation-review-02-result.md`
- Verified review SHA256: `7b3d73468d5a1f562490d33589ff34c88243d6ce80066a95bf3b949a2e012896`
- Reviewed packet: `29ee7330796ced3581c910644aa35fb15f4b596b`
- Reviewed packet tree: `f4692efe6fc98e2664b9b06c225cfc7ea3c4e84e`
- Scope: GF03 only. No kernel Store, shared contract, GF01 authority,
  GF02 request-digest, scheduler, workflow DSL, or private SQLite writer change
  was made.

## Implementation identity

- Implementation commit: `7358569d4be8beed8d91cb72b63f5ef65786065e`
- Implementation tree: `0ca9b3ebe9244014dbbc6cdb9140e5765e579256`
- Commit message: `Close GF03 writer retirement race`

Changed files in that commit:

- `src/herzchen/authoring/__init__.py`
- `src/herzchen/authoring/cleanup.py`
- `src/herzchen/authoring/finish.py`
- `src/herzchen/authoring/idle.py`
- `src/herzchen/authoring/integration.py`
- `src/herzchen/authoring/sessions.py`
- `src/herzchen/authoring/writer_lease.py`
- `tests/authoring/test_exclusivity.py`
- `tests/authoring/test_failure_matrix.py`
- `tests/authoring/test_finish.py`
- `tests/authoring/test_gf03_retirement.py`
- `tests/authoring/test_handoff.py`
- `tests/authoring/test_three_targets.py`
- `tests/packs/test_task_templates.py`

## Established invariant

`FileWriterLeaseAuthority` is a host-keyed, authoring-local capability. It
uses a stable external lock file and POSIX `flock`: managed writes acquire a
shared lock and retirement acquires an exclusive lock. The lifecycle holds
that exclusive lease continuously across final capture, capture-barrier
verification, the existing FND finish/retirement transaction, durable fence
validation, the final descriptor-relative compare, unlink, and the durable
cleanup outcome.

The authenticated lock state advances a generation when retirement begins.
`GuardedWriterDescriptor` records its opening generation and reacquires the
shared lock for every write. A descriptor opened before retirement therefore
cannot write while the exclusive lease is held and remains revoked after that
lease is released. A no-op object or boolean callback is rejected as a lease.

The HMAC-authenticated durable fence binds all of the following:

- fence format, authority and key ID;
- exact owner identity and exhaustive managed-writer identity set/digest;
- session ID, token and session fence;
- canonical checkout path plus device/inode identity;
- exclusive lease ID and generation;
- canonical retirement-manifest digest and entry count;
- final snapshot digest; and
- issuance and expiry times.

Before physical cleanup, the complete canonical path/size/SHA256 manifest is
checked against the durable snapshot identity, stored bytes and digest, then
authenticated against the currently held lease. Physical cleanup additionally
requires its exact entries to match the manifest authorized on that held
capability. `AuthoringSessionService.cleanup(..., COMPLETE)` downgrades to
`UNSAFE` unless all of those checks succeed. Missing, malformed, partial,
mismatched, stale or unauthenticated state cannot record `COMPLETE`.

On restart, cleanup acquires a new exclusive generation, authenticates the
prior durable fence with the same host authority, binds the handoff to the new
lease through the existing `authoring.cleanup.refresh` FND command, revalidates
it, and only then compares/unlinks. Lock acquisition failure, lock-state
authentication failure, stale prior proof, or a changed authority preserves
the checkout and returns `UNSAFE`. `fresh_capture=True` remains the explicit
late-write/stale-fence recovery route and commits the new exact bytes before
cleanup.

`unmanaged_writers=True` is now admitted on session/lifecycle open and is part
of the canonical open request. It prevents physical deletion and durable
completion even when a valid managed-writer lease exists.

## Exact retained and new GF03 cases

All nine pre-existing tests in `tests/authoring/test_gf03_retirement.py` were
retained by name and continue to run:

- `test_manual_late_write_is_recovery_and_fresh_retry_durably_preserves_it`
- `test_idle_late_write_uses_same_recovery_barrier_and_keeps_file`
- `test_exact_manifest_rejects_in_place_late_write_during_cleanup`
- `test_public_cleanup_without_writer_callback_blocks_exact_deletion`
- `test_public_cleanup_with_unknown_writer_state_blocks_deletion`
- `test_public_cleanup_with_active_or_raising_writer_state_blocks_deletion`
- `test_public_cleanup_rejects_bare_or_partial_metadata_even_when_writer_quiescent`
- `test_public_cleanup_deletes_only_exact_manifest_with_quiescent_writer`
- `test_unchanged_manual_and_idle_finish_still_persist_and_clean`

The positive public-cleanup case now authenticates the exact manifest on a
real held lease; boolean quiescence remains only a supplemental probe.

New cases proving the residual invariant are:

- `test_public_cleanup_with_held_but_unbound_guard_preserves_file`
- `test_boolean_or_noop_object_cannot_impersonate_a_held_lease`
- `test_invalid_durable_retirement_handoffs_never_complete_or_delete`, with
  separate absent-manifest, absent-fence, partial-manifest, partial-fence,
  mismatched-fence and unauthenticated-fence nodes
- `test_authentic_but_stale_fence_preserves_checkout`
- `test_declared_unknown_or_unmanaged_writer_forces_unsafe_cleanup`
- `test_restart_reacquisition_failure_is_explicit_and_preserves_bytes`
- `test_restart_reestablishes_same_authenticated_authority_before_unlink`
- `test_cross_process_already_open_managed_descriptor_is_blocked_at_unlink_boundary`

The last test starts a real subprocess, opens the checkout descriptor before
retirement, and asks it to write from the deterministic `before_unlink` hook,
after the final compare. The subprocess receives `WriterLeaseUnavailable`
while the exclusive lease is held and `WriterLeaseRevokedError` on its retry
after retirement. The checkout file is deleted only because the attempted
late write was prevented; the original exact bytes are verified in the
durable FND snapshot. The existing manual/idle raw late-write barriers still
prove the recovery branch: changed bytes remain on disk until a fresh durable
capture succeeds.

Existing GF01 handler-registration and GF02 canonical-request behavior were
not edited. The full source suite, including their tests, passed.

## Source validation

Interpreter and test tool:

- Python: `3.12.14`
- Interpreter: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`
- pytest: `9.1.1`
- `PYTHONDONTWRITEBYTECODE=1`
- Source import: explicit `PYTHONPATH=$PWD/src`

Focused command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/authoring/test_gf03_retirement.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py tests/authoring/test_failure_matrix.py tests/authoring/test_exclusivity.py tests/authoring/test_handoff.py tests/authoring/test_three_targets.py tests/packs/test_task_templates.py
82 passed, 1 skipped in 0.96s
```

The one source skip is the existing installed-process gate. It passes in the
installed-wheel run below.

Full source command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q
304 passed, 12 skipped, 80 subtests passed in 2.60s
```

The full run's conformance probe rewrites its historical generated work files
as part of the test, so those two files were restored to the accepted base
after validation. No historical result or reviewed packet is in the
implementation commit.

`git diff --check` passed before the implementation commit.

## Disposable installed-wheel validation

The wheel was built from implementation commit
`7358569d4be8beed8d91cb72b63f5ef65786065e` with Python `3.11.16` and:

```text
/opt/homebrew/bin/python3.11 -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/gf03-wheel.W3WWNh
```

- Wheel: `/tmp/gf03-wheel.W3WWNh/herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA256: `5ff5c1adcb7e192834cab6f4e6837ce90fa2cc252cdcef1ecf4c974295cedf9c`
- Disposable venv: `/tmp/gf03-venv.9sakCd`
- Installed Python: `3.11.16 (main, Aug 12 2026, 23:03:19) [Clang 17.0.0 (clang-1700.6.4.2)]`
- Installed pytest: `9.1.1`
- `PYTHONPATH`: unset
- `PYTHONHOME`: unset

Installed focused command:

```text
env -u PYTHONPATH -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 /tmp/gf03-venv.9sakCd/bin/python -m pytest -q tests/authoring/test_gf03_retirement.py tests/authoring/test_finish.py tests/authoring/test_snapshots.py tests/authoring/test_failure_matrix.py tests/authoring/test_exclusivity.py tests/authoring/test_handoff.py tests/authoring/test_three_targets.py tests/packs/test_task_templates.py
83 passed in 1.11s
```

Recorded installed origins:

```text
herzchen=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/__init__.py
cleanup=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/authoring/cleanup.py
finish=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/authoring/finish.py
idle=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/authoring/idle.py
integration=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/authoring/integration.py
sessions=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/authoring/sessions.py
snapshots=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/authoring/snapshots.py
writer_lease=/private/tmp/gf03-venv.9sakCd/lib/python3.11/site-packages/herzchen/authoring/writer_lease.py
```

Build output and egg-info created in the checkout were removed after the wheel
was hashed and installed. The checkout was clean before adding this result.

## Remaining host dependency and limitations

The host must provision and protect a stable secret of at least 32 bytes, an
owner-only lock directory, the exhaustive exact managed-writer identity set,
and one authenticated writer identity for retirement. Every managed checkout
writer must use `GuardedWriterDescriptor` for every write. Any writer that
cannot be brought under that capability must be declared through
`unmanaged_writers=True`; cleanup then remains `UNSAFE`. Recreating the same
authority configuration is required for restart recovery.

The concrete exclusion uses POSIX `fcntl.flock` and therefore requires a
filesystem whose lock implementation coordinates all participating processes;
Windows is not supported by this implementation. A stale authentic fence does
not authorize default cleanup; the caller must perform a fresh guarded capture.

Those are host-integration dependencies, not unimplemented fallback paths.
Within the authenticated managed-writer boundary, no boolean callback,
single-thread assertion, or last-compare-only check is treated as ownership
proof.
