"""Adapter-only evidence envelope; FND HostReceipt remains unchanged."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping, Optional
import json

RECEIPT_ENVELOPE_REVISION = "ott-02.adapter-receipt.v1"

@dataclass(frozen=True)
class AdapterReceiptEnvelope:
    owner: str
    logical_agent_id: str
    physical_session_id: Optional[str]
    source: str
    worktree: str
    input_packet_digest: str
    requested_model: str
    requested_reasoning: str
    requested_profile: str
    observed_model: Optional[str]
    observed_reasoning: Optional[str]
    observed_profile: Optional[str]
    launcher: str
    runner: Optional[str]
    process_id: Optional[str]
    started_at: str
    ended_at: Optional[str]
    exit_status: Optional[int]
    status: str
    stdout_ref: Optional[str]
    native_receipt_ref: Optional[str]
    delivery_state: str
    cursor: Optional[str]
    timeout: Optional[str]
    cancel: Optional[str]
    reconciliation: Optional[str]
    unsupported_error: Optional[str]
    result_ref: Optional[str]
    fnd_receipt: Mapping[str, Any]
    envelope_revision: str = RECEIPT_ENVELOPE_REVISION
    command: Optional[tuple[str, ...]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
