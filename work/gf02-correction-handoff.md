# GF02 worker handoff

Candidate objective `GF02_EXACT_REPLAY_AND_RECOVERED_ACTOR` is implemented in the isolated `gf02-correction-worker` worktree and committed as one candidate. The original G-FOUNDATION `REWORK` history remains authoritative; this handoff is not gate acceptance.

Commit/tree, changed paths, exact checks, source/test lineage, frozen baseline failure receipt, wheel/install origins, before/action/fresh-after evidence, invocation metadata, and residual GF01/GF03 limits are in [gf02-correction-result.md](gf02-correction-result.md).

Handoff constraints:

- Consumer callers must use the canonical semantic digest boundary; compatibility `request_digest` arguments on GF02 operation/limit APIs are not trusted as identity.
- Unknown resolution requires `resolver=AuthenticatedActor(...)`; the resolution event actor and original operation actor are intentionally separate.
- Store/public writer ownership, extension admission, authoring retirement, consumer cutover, and product behavior remain outside this candidate.

Final artifact digests are supplied with the committed candidate because the handoff cannot embed its own post-write SHA-256.
