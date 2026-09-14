# INT-03 dependency integration checkpoint: PKG05 + FND06 + DAT06

Status: accepted-source integration evidence only. This is a dependency checkpoint for downstream owner work; it is not INT-03 completion, G-FOUNDATION, a gate verdict, or a publication claim.

## Integrated source set

- Clean base: `5a28e1fee1811d77c0a6558311c77525c36ed069`, tree `640ac1a230d0535bde7ab23d172e2faf76b3f101` (WRK03 installed checkpoint plus the FND06 namespace marker already present).
- Isolated worktree: `local/repos/Herzchen-int03-pkg05-fnd06-dat06-integration`, branch `int-03-pkg05-fnd06-dat06-integration`.

Accepted worker source lineages were integrated by cherry-pick without rewriting their source manifests or handoff files:

- FND06 full corrected recovery/handoff: source `ac568c3` (FND05 recovery), `2115715` (corrected recovery proof), `da7aed1` (FND06 handoff). The `9e15ad9` FND06 namespace marker was already in the base as `4ec4d40`; its cherry-pick was empty and skipped. Integrated commits are `734cb28`, `03ac504`, and `b3fe3fb`.
- DAT06 handoff: source `f9b4b85` (public API conformance/handoff) and `2f4dd05` (worker result). Integrated commits are `6cadbd7` and `7e91167`.
- PKG05 full accepted lineage through the neutral-boundary/provenance correction: source `19f3d63`, `2de637d`, `bb34312`, `7e33aca`, `d8a9bf1`, `d649f57`. Integrated commits are `7db36de`, `7233248`, `61eca11`, `cce05b9`, `d041c01`, and `7437dc3`.

The accepted handoff artifacts remain at `handoffs/FND.json`, `handoffs/DAT.json`, and `handoffs/PKG.json`; worker result reports remain under `work/`.

## Candidate installed proof

A disposable candidate environment was created at `/tmp/herzchen-int03-pkg05-fnd06-dat06-candidate.pwUzWY` with `/opt/homebrew/bin/python3.11` (Python 3.11.16), pytest 9.1.1, and build tooling. The integrated Herzchen wheel was built and installed without dependencies:

- Wheel: `/tmp/herzchen-int03-pkg05-fnd06-dat06-candidate.pwUzWY/wheels/herzchen_contracts-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `45577a69514bae214aa51e77b306b6bd9152280386e28f80da6f2a206d7000c9`

To exercise PKG05's explicit Astrid default adapter in the same installed candidate, Astrid was built from the pinned read-only source `96e5664237eb35adeb4cad08bddd8cd6df0a2ae1` / tree `19f7539a266618a797559eedbda48e2752b30fa3` in a temporary source copy and installed with no product-source mutation:

- Astrid wheel SHA-256: `1da76f252f96e7db84c31a387704e8a6ecdf22333098528139b3db83c8fda67a`
- Minimal validation dependencies installed into this disposable environment: PyYAML, jsonschema, and referencing.

All test commands used `env -u PYTHONPATH -u PYTHONHOME`. Imports resolved from candidate `site-packages` for `astrid`, `herzchen`, `herzchen.kernel`, `herzchen.packs.authoring`, `herzchen.domains.work`, `herzchen.content`, and `herzchen.extensions`. The complete command/output is preserved at `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/int-03-pkg05-fnd06-dat06-installed-run.txt`.

The affected installed suite covered:

- FND recovery, identity revisions, transactions, receipts/limits, and reduced composition;
- WRK assignments, batches, and identity graph;
- DAT06 handoff, fixtures, matrix, and rehearsal conformance;
- PKG05 authoring, protocol resources, templates, and composition;
- document authoring/context, extensions, contracts, and authoring exclusivity.

Result: **198 passed, 80 subtests passed in 1.79s**. No skips or failures occurred with the pinned Astrid adapter installed. The PKG05 neutral path and Astrid default path therefore both ran in the same candidate, while the neutral test continued to block Astrid/Otto/Runtime imports and verify exact resource-digest rejection.

## Final checkpoint

Pre-report integrated HEAD was `7437dc3dec566b947ef086b61b92e5485f153fa5`, tree `5a7f78fb741b6d316ca554b1998e76321101381b`. This report is the only new path to commit after the test run. The checkout was clean after removing generated build, egg-info, and Python bytecode artifacts. No control DB, source manifest, extraction map, upstream remote, or other owner worktree was changed.
