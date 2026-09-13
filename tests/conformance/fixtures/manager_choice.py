"""Manager-choice inputs: readiness/attention never becomes business action."""

from __future__ import annotations

from .common import envelope


def build_manager_choice_cases() -> dict[str, dict]:
    selected = {
        "decision_id": "manager-choice-001",
        "source_event": "evt-prerequisite-accepted",
        "available_actions": ["implement-rehearsal-change", "hold-for-owner"],
        "selected_action": "implement-rehearsal-change",
        "justification": "the manager selected the bounded change after reading current evidence",
        "automatic_dispatch": False,
    }
    attention_only = {
        "decision_id": "manager-choice-002",
        "source_event": "evt-prerequisite-accepted",
        "available_actions": ["implement-rehearsal-change", "hold-for-owner"],
        "selected_action": None,
        "attention_status": "ready_for_manager",
        "automatic_dispatch": False,
        "rejection_reason": "prerequisite completion creates attention, not an implicit business choice",
    }
    return {
        "positive": envelope("manager_choice", selected, "manager-choice-positive"),
        "negative": envelope("manager_choice", attention_only, "manager-choice-negative"),
    }
