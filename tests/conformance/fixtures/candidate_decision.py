"""Candidate-bound decision and evidence-reuse inputs."""

from __future__ import annotations

from .common import envelope, stable_digest


def build_candidate_decision_cases() -> dict[str, dict]:
    candidate_a = {
        "candidate_id": "candidate-A",
        "artifact": "artifact-a",
        "source_revision": "source-a",
        "spec_revision": "spec-1",
        "consumed_inputs": ["input-1"],
    }
    candidate_b = {
        "candidate_id": "candidate-B",
        "artifact": "artifact-b",
        "source_revision": "source-b",
        "spec_revision": "spec-1",
        "consumed_inputs": ["input-2"],
    }
    decision = {
        "decision_id": "decision-001",
        "candidate_id": "candidate-A",
        "author": "resp-rehearsal-manager",
        "authority": "mandate-bounded-rehearsal",
        "rationale": "candidate A matches the pinned question",
        "return_condition": "changed consumed input",
        "verdict": "selected",
    }
    return {
        "positive": envelope(
            "candidate_decision",
            {"candidate": candidate_a, "decision": decision, "candidate_digest": stable_digest(candidate_a)},
            "candidate-decision-positive",
        ),
        "negative": envelope(
            "candidate_decision",
            {
                "candidate": candidate_b,
                "old_decision": decision,
                "unrelated_annotation": {"key": "does-not-invalidate"},
                "rejection_reason": "candidate-A decision cannot certify candidate-B after consumed input changed",
            },
            "candidate-decision-negative",
        ),
    }
