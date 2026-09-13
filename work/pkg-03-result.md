# PKG-03 worker receipt

## Request and execution identity

- Requested assignment: `PKG-03 executable worker brief`, one bounded `worker_normal` launch.
- Requested model/reasoning: `gpt-5.6-luna`, high reasoning.
- Observed model/reasoning: `gpt-5.6-luna`, high reasoning (no substitution observed).
- CLI/session/process: Codex API session using `/bin/zsh -lc` `exec_command`; no external agent, launcher, worker, or hidden model process was invoked. The shell process IDs were not exposed by the command runner.
- Worktree: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-pkg03-worker`.
- Start: `2026-09-13T22:38:21.075455Z` (worker session log start).
- End: `2026-09-13T22:53:40.683226Z` (UTC evidence capture).

## Source and dependency pins

- Source base: commit `9ba4719c58c6aab0e358ffc6ba84b18f8bf207ff`, tree `8e34882d6ff2a0a9578abf3bb14690be4eb031d5`.
- FND-03 accepted dependency: commit `98430201ff196313df0ac69a701851225c8c31a7`, tree `ddd9eaab56df1b8321443021db8283e4a75910cd`.
- DAT-02 accepted dependency: commit `a8611a9b9b8cd9ad36c2816c4d1cb2e24e8ded97`, tree `83698bddf0709bb08743192060d380083bd82c21`.
- WRK-02 accepted integration: commit `9ba4719c...`, tree `8e34882d...`.
- PKG-02 accepted dependency: commit `83f696dfdd077cb75a90fdb40dbeefd726be62d7`, tree `7836569cecf99be2ac29e18c6b6ec3a11dcea35b`.
- Candidate venv: `/private/tmp/pkg03-candidate-final2.RjmPwV`.
- Candidate versions: Python `3.12.14`, pip `25.0.1`, pytest `9.1.1`, `herzchen-contracts 0.1.0`.
- Installed origins: `herzchen` and `herzchen.packs.templates` both resolved from `/private/tmp/pkg03-candidate-final2.RjmPwV/lib/python3.12/site-packages/`; installed proof used no `PYTHONPATH` or `__path__` injection.

## Exclusive changes

- `src/herzchen/packs/templates.py` — resource-only `WorkTemplate`/`WorkProtocol`, safe parameter/local expansion, common blank projection/field definitions, preflight graph/reference validation, stable origin metadata, public WRK instantiation, explicit protocol adoption, resume, and clone helpers.
- `tests/packs/test_task_templates.py` — 7 focused tests using a real FND SQLite `Store`, real `Transaction`-backed `WorkGraph`, fresh reads, receipts, and events.
- `work/pkg-03-result.md` — this receipt.
- SHA-256: `78a4a276b1aa5892c5707d68bd0a1bb5c5523c7974fa0d41151651a7d0b98737  src/herzchen/packs/templates.py`; `544a351eeb45db38e7d686fb0fd72c7a0c4d2b31a6e3bbedcd91a852e0e4c5a0  tests/packs/test_task_templates.py`.

## Implemented and observed behavior

- Built-in `work.blank_project` renders one pending project, zero tasks, empty outcome, no protocol, and no manager/budget/dispatch side effects; title default is the literal `Untitled project`.
- `$param` accepts only a declared scalar parameter and `$local` accepts only an explicit seed-local reference. Ordinary strings, including template-looking prose, remain literal; no code, shell, import, network, or secret lookup is evaluated.
- Full expanded seeds are prevalidated for parameter shape/defaults, typed local/external references, aliases, namespaces, review choice metadata, profile/allowance existence, and parent/dependency cycles before the first WRK write.
- Task, criterion, task-bundle, and bounded-effort creation delegates to public `WorkGraph` commands and the supplied FND writer. Stable IDs/request keys and per-node `template_origin` preserve source resource ID/revision/local ID. Repeated exact requests replay existing FND receipts without new events.
- Task and criterion namespace/key values are retained independently, including colliding visible keys. `normal` and `xhard` choices are explicit metadata; multi-review/extra-stage requests are rejected.
- Profile/allowance references are read/resolved and retained as metadata; no allowance grant or model/credential permission is created. Template protocol mention does not adopt it. Adoption is a separate explicit operation. Resume is a fresh read; clone removes live/evidence/consumed-state facts.

## Exact validation commands and results

1. `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY' ... compile(open('src/herzchen/packs/templates.py').read(), 'templates.py', 'exec') ... PY` — passed. This source-only check was not used as installed proof.
2. Candidate wheel build: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/.venvs/int03-wrk02/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir "$wheel_dir" .` — passed.
3. Installed focused proof: `"$candidate_venv/bin/python" -m pip install --no-deps --force-reinstall "$wheel_dir"/*.whl && "$candidate_venv/bin/python" -m pytest -q tests/packs/test_task_templates.py` — `7 passed in 0.07s`.
4. Installed affected proof: `"$candidate_venv/bin/python" -m pytest -q tests/packs/test_task_templates.py tests/packs/test_composition.py tests/work/test_identity_graph.py tests/kernel/test_transactions.py tests/content/test_documents.py tests/contracts/test_contracts.py` — `81 passed in 0.28s`.
5. Installed complete proof: `"$candidate_venv/bin/python" -m pytest -q` — `98 passed, 70 subtests passed in 0.33s`.
6. `git diff --check` — passed.
7. Final source/base capture: `git rev-parse HEAD` = `9ba4719c58c6aab0e358ffc6ba84b18f8bf207ff`; `git rev-parse HEAD^{tree}` = `8e34882d6ff2a0a9578abf3bb14690be4eb031d5`.

## Fixture versus product boundary

The tests exercise the actual shared Store/Transaction and public WRK operations. The two `profile`/`allowance` identities in one test are pre-existing FND identities created through the public FND mutation port as controlled external-reference fixtures; they are not a profile service, allowance ledger, or grant path. No launcher, host invoke/resume, worker, DDL, migration, private writer, product database, or hidden agent call was used.

This receipt does not claim PKG-03 manager acceptance or root completion. The supplied WRK surface has no public multi-record batch command, so invalid seeds are atomically rejected by complete preflight and valid bundles use public per-record WRK commands inside the existing FND boundary. Full DAT document creation/association batching, reader breadth, PKG-04/05 packaging/publication, and INT-03 gate evidence remain outside this bounded worker. Final worktree status is intentionally not clean: the only untracked paths are the three owned deliverables listed above (the two source/test paths and this receipt).
