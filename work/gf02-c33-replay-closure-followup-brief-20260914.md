# GF02/C33 persisted replay closure follow-up

Resume the same worker session on this checkout at normal `gpt-5.6-luna` with
explicit `model_reasoning_effort=high`. This is a bounded continuation from
the sealed GF02 implementation commit `ef13cfed36f8d43925a28e8312bf0235379b1488`
and evidence commit `ff5d85cc09ace8731845e8c7fb54d63bfd07e081`; do not rewrite
those commits or the frozen reviewed packet.

## Scope

Close only reproduced persisted exact-retry semantics that share the GF02
complete-context cause. Use public service paths and the admitted Store. The
required bounded cases are:

1. `WorkGraph.revise` for all six work kinds and its
   `work.revised`, `work.parent-linked`, `work.state-changed`, and
   `work.dependency-linked` mutation paths: after a successful first action,
   an exact retry returns the original receipt/result and creates no new
   identity, event, association, reference, revision, or receipt; changed
   caller preconditions must still conflict without effects.
2. `ProjectBatches` `work.project.activate`: valid first action and exact
   retry with the same logical request key; preserve caller expected revision
   and reject changed preconditions without receipt-derived override.
3. `AssessmentModule` `assessment.finding.close`: valid first action and
   exact retry; changed caller preconditions conflict with no delta.
4. `ResponsibilityAssignments.reassign`: same valid-first-action/exact-retry
   and changed-precondition checks if the public API exposes the reproduced
   path.
5. `ManagedPackAuthoringHandler` `pack.content.author`: same checks if the
   public API exposes the reproduced path.
6. Authoring `actor.release` and `release`: exercise valid first action then
   exact retry; preserve `InvalidSession` for unsupported/stale first actions
   and do not convert an invalid first action into a successful replay.

Use the corrected DAT/C33 evidence available under the root package only to
classify reproduced first-action/exact-retry cases. Do not assume every matrix
row is a product defect, and do not add broad matrix coverage in this lane.

## Ownership and constraints

- Owned implementation paths are the affected service/domain modules and
  focused tests only. Do not edit FND Store, contracts/model, command-port
  adapters, or the separate C33 conformance checkout.
- Preserve caller supplied logical context and explicit preconditions through
  request/envelope/event/reopen. Never rebuild caller context from current
  projection or use a receipt's derived context to override changed caller
  preconditions.
- Coordinate overlaps with the FND typed-port worker by preserving the
  existing public handler/mutate/transaction interface; record any semantic
  assumptions and exact diffs in the result.
- No new review, oracle, gate, upstream, or control call. Do not claim the
  wider C33 matrix is complete.

## Proof and delivery

Add focused regression tests that independently prove exact replay/no delta
and changed-precondition conflict for each reproduced path. Run source and
installed-wheel focused tests in a disposable Python 3.11/3.12 environment
with `PYTHONPATH` and `PYTHONHOME` unset for installed-origin checks. Capture
the exact commands, PIDs/timestamps, module origins, counts, and result in
`work/gf02-c33-replay-closure-result.md` and a JSONL receipt. Keep changes
unstaged if Git metadata is inaccessible; the manager will commit named paths.
