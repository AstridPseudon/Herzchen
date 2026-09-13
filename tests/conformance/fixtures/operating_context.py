"""Operating-context inputs for the resolved-brief continuity contract."""

from __future__ import annotations

from .common import envelope


def build_operating_context_cases() -> dict[str, dict]:
    positive = {
        "context_revision": "ctx-001",
        "responsibility": {"id": "resp-rehearsal-manager", "owner": "OTT"},
        "mandate": {"id": "mandate-bounded-rehearsal", "scope": "disposable-portfolio"},
        "profile": {"id": "manager-normal", "model": "gpt-5.6-luna", "reasoning": "high"},
        "current_inputs": ["task-rehearsal-01", "definition-v1"],
        "attention": {"event_id": "evt-attention-001", "cursor": 11, "unhandled": True},
        "omissions": [],
    }
    negative = {
        "context_revision": "ctx-000-stale",
        "responsibility": {"id": "resp-rehearsal-manager", "owner": "OTT"},
        "mandate": None,
        "profile": {"id": "manager-normal", "model": "gpt-5.6-luna", "reasoning": "high"},
        "current_inputs": ["task-rehearsal-01"],
        "attention": {"event_id": "evt-attention-001", "cursor": 9, "unhandled": True},
        "omissions": ["missing mandate", "stale cursor requires reread"],
        "rejection_reason": "stale or incomplete context cannot authorize a bounded action",
    }
    return {
        "positive": envelope("operating_context", positive, "operating-context-positive"),
        "negative": envelope("operating_context", negative, "operating-context-negative"),
    }
