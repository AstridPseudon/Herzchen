# DAT-06 worker result

This is the completed DAT-06 worker evidence handoff, limited to the accepted
public APIs and the three owned paths. It is not a root acceptance or gate
verdict. The probe proves neutral task, shot-shaped, document, and assignment-
shaped contract behavior; it does not prove an Astrid adapter.

## Lineage and source pins

- Accepted base: commit `e9f91f196d5130965069c6110e3f2d60098c3952`, tree
  `a735253153056ae80b755005b64ee78d4322f275`.
- Evidence commit: `f9b4b85e016d5968d51e4ee8a2096b4b37f422ce`, tree
  `cf25ac59f06b666fcc03912eab75bb1b0dbe1f9b`.
- DAT-05 source pin: commit `3597187aaaebb627ed818f5dd3ab1f165eb15097`, tree
  `b405bdd3c229ee5d8fed04b8be5c45a86b71a64d`.
- FND typed-identity source pin: commit
  `59043551e6fb4a19d7130d5aa47cf75a732e0a45`, tree
  `39bb3ac322855f3e6552813b3ce87c6834d40917`.
- Refreshed source manifest SHA-256:
  `742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a`.
- Schema pins are machine-readable in `handoffs/DAT.json`: FND revision and
  fingerprint, content `dat-content.v1`, extensions `dat.extensions.v1`, work
  `work.v1`.

## Evidence and behavior

The generated handoff contains 15 committed events and 15 receipt operations.
It records before/action/fresh-after snapshots for the task, neutral
`shot.fixture`, neutral `work.assignment`, document revisions, associations,
and the context packet. Rejection cases are six no-delta failures:

- `wrong_owner`: `OwnerRequiredError`.
- `schema_typo`: `SchemaValidationError`.
- `managed_namespace`, `protected_primary`, `protected_provenance`, and
  `protected_acceptance`: `ManagedFieldError`.

The proof also records namespace-preserving reads and query results, sibling
field preservation, current versus pinned document revisions, detach-with-
history, backlink scope separation, same-key replay returning the original
receipt, changed-input replay as `ReplayConflictError`, stale write as
`VersionConflictError`, and fresh reads/replay after close-and-reopen.
S-ELEGANCE-CONTEXT and S-ELEGANCE-DEFINITION inputs were executed through
`ContextPacketService` and `ExtensionCommandService`; no elegance engine or
review panel was added. Reuse entries are `EX-CONTENT` and `EX-METADATA`.

## Exact verification commands

All source checks below used
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python`.

```text
PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/conformance/test_dat_handoff.py
exit 0; 1 passed in 0.10s

PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python tests/conformance/test_dat_handoff.py --write-handoff --path handoffs/DAT.json
exit 0; handoff generated, 137896 bytes

PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pytest -q tests/conformance/test_dat_handoff.py tests/extensions/test_namespaces.py tests/content/test_document_authoring_contract.py tests/content/test_documents.py tests/content/test_context_visibility.py tests/work/test_identity_graph.py tests/conformance/test_fixtures.py tests/conformance/test_matrix.py tests/conformance/test_rehearsal.py
exit 0; 63 passed, 70 subtests passed in 0.21s

PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m compileall -q src tests/conformance/test_dat_handoff.py
exit 0

PYTHONPATH=src /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -c "import herzchen, herzchen.extensions, herzchen.content, herzchen.domains.work"
exit 0; all four imports resolved from this checkout's src/

git diff --cached --check
exit 0
owned-path audit
exit 0; staged paths were exactly handoffs/DAT.json and tests/conformance/test_dat_handoff.py
```

The initial unqualified installed test remains separately reported as the
known ambient-package result:

```text
pytest -q tests/conformance/test_dat_handoff.py
exit 2; ambient installed herzchen lacked herzchen.extensions,
herzchen.content, and herzchen.domains
```

## Installed-origin evidence

The package setup permitted a disposable wheel build. `python -m build
--wheel --no-isolation` exited 1 because the `build` module was unavailable;
the bounded fallback below exited 0:

```text
/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int-02/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/dat06-candidate.9vnmqg/wheel .
exit 0; herzchen_contracts-0.1.0-py3-none-any.whl
SHA-256 674418ac14061932663581220fbc6d87a342f7a71b8e5692ba262e528fb47e85
```

In the disposable installed environment, with `env -u PYTHONPATH`, Python
`3.12.14` imported `herzchen`, `herzchen.extensions`,
`herzchen.content`, and `herzchen.domains.work` from
`/tmp/dat06-candidate.9vnmqg/venv/lib/python3.12/site-packages`. The bounded
installed test command was attempted and exited 1 because that disposable
venv had no `pytest` module. This is import-origin proof only; no source test
result is relabeled as installed evidence.

The exact bounded installed-test attempt was:

```text
env -u PYTHONPATH /tmp/dat06-candidate.9vnmqg/venv/bin/python -m pytest -q tests/conformance/test_dat_handoff.py
exit 1; No module named pytest
```

## Changed files and boundaries

At the evidence commit, SHA-256 hashes were:

- `tests/conformance/test_dat_handoff.py`:
  `573929e37cdc975c19405e2b82eeded962d3deee1b7e35a92ccdb9eb8d988281`.
- `handoffs/DAT.json`:
  `32efc243f7cb44a8e39933c08fa81df1fe7bc909242203ceee191e2e7d6ce8b8`.

The worker added no persistence, domain tables, private SQL writer, DDL,
event engine, or product/Astrid adapter. `shot.fixture` and
`work.assignment` are explicitly synthetic neutral identities. Actual Astrid
binding remains deferred behind G-OTTO; third-specialist resources remain
deferred. Publication and license review were not performed by this worker.
No push was made.
