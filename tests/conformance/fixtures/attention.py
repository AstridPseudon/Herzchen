"""Durable attention, cursor, duplicate and restart inputs."""

from __future__ import annotations

from .common import envelope


def build_attention_recovery() -> dict:
    payload = {
        "stream_id": "attention-rehearsal",
        "events": [
            {"event_id": "evt-010", "sequence": 10, "kind": "result_ready", "handled": False},
            {"event_id": "evt-011", "sequence": 11, "kind": "owner_revisit", "handled": False},
        ],
        "consumer": {"id": "manager-client", "cursor_before": 9, "cursor_after_restart": 9},
        "hints": [
            {"event_id": "evt-011", "sequence": 11, "delivery": "duplicate"},
            {"event_id": "evt-009", "sequence": 9, "delivery": "out_of_order"},
        ],
        "expected": {
            "ordered_reread": ["evt-010", "evt-011"],
            "business_dispatches": 0,
            "unhandled_preserved": True,
            "restart_keeps_cursor": True,
        },
    }
    return envelope("attention_wait_restart", payload, "attention-recovery-v1")
