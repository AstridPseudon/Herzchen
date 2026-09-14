"""Typed, protocol-neutral assessment records.

The records in this module are projections over FND identities.  They are
deliberately small: protocol packs supply the meaning of ``protocol`` and the
shape of ``protocol_result``/``guidance`` while the durable identity and
revision vocabulary remains shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from herzchen.contracts import AuthenticatedActor, CommandReceipt, ResourceRef


class AssessmentError(ValueError):
    """Base error for assessment validation and authority failures."""


class AssessmentNotFoundError(AssessmentError):
    """A requested assessment record is not present."""


class StaleAssessmentError(AssessmentError):
    """A typed current/pinned reference no longer denotes current state."""


class AssessmentAuthorityError(AssessmentError):
    """The actor or authority is not allowed to perform the operation."""


class AssessmentStateError(AssessmentError):
    """The requested assessment transition is not valid."""


class Verdict(str, Enum):
    PASS = "PASS"
    REWORK = "REWORK"
    UNKNOWN = "UNKNOWN"


class Disposition(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    DEFER = "defer"
    ACCEPT_WITH_RISK = "accept-with-risk"


@dataclass(frozen=True)
class AssessmentScope:
    ref: ResourceRef
    parent_obligation_ref: ResourceRef
    protocol: str
    criterion_refs: Tuple[ResourceRef, ...]
    review_required: bool
    allow_no_review: bool
    designated_approver: Optional[str]
    authority: Optional[str]
    policy: Mapping[str, Any]
    version: int
    payload: Mapping[str, Any]

    @property
    def revision(self) -> Optional[str]:
        return self.ref.revision


@dataclass(frozen=True)
class InputPacket:
    ref: ResourceRef
    scope_ref: ResourceRef
    consumed_refs: Tuple[ResourceRef, ...]
    packet: Mapping[str, Any]
    version: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Invocation:
    ref: ResourceRef
    operation_ref: ResourceRef
    reservation_ref: ResourceRef
    route: str
    role: str
    state: str
    declared_units: int
    actual_units: int
    result: Mapping[str, Any]
    version: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Finding:
    ref: ResourceRef
    result_ref: ResourceRef
    parent_obligation_ref: ResourceRef
    summary: str
    severity: str
    subjective: bool
    status: str
    correction_ref: Optional[ResourceRef]
    evidence_refs: Tuple[ResourceRef, ...]
    version: int
    payload: Mapping[str, Any]

    @property
    def resolved(self) -> bool:
        return self.status == "closed"


@dataclass(frozen=True)
class AssessmentResult:
    ref: ResourceRef
    scope_ref: ResourceRef
    parent_obligation_ref: ResourceRef
    criterion_ref: ResourceRef
    candidate_ref: ResourceRef
    input_packet_ref: ResourceRef
    verdict: Verdict
    guidance: Mapping[str, Any]
    protocol_result: Mapping[str, Any]
    invocation: Invocation
    findings: Tuple[Finding, ...]
    correction_refs: Tuple[ResourceRef, ...]
    version: int
    payload: Mapping[str, Any]
    receipt: Optional[CommandReceipt] = None

    @property
    def status(self) -> Verdict:
        return self.verdict

    @property
    def accepted(self) -> bool:
        return bool(self.payload.get("accepted", False))


@dataclass(frozen=True)
class CandidateSelection:
    ref: ResourceRef
    scope_ref: ResourceRef
    candidate_ref: ResourceRef
    criterion_ref: ResourceRef
    rationale: str
    author: str
    version: int
    payload: Mapping[str, Any]
    receipt: Optional[CommandReceipt] = None


@dataclass(frozen=True)
class Correction:
    ref: ResourceRef
    result_ref: ResourceRef
    parent_obligation_ref: ResourceRef
    finding_refs: Tuple[ResourceRef, ...]
    instruction: str
    status: str
    version: int
    payload: Mapping[str, Any]
    receipt: Optional[CommandReceipt] = None


@dataclass(frozen=True)
class Decision:
    ref: ResourceRef
    parent_obligation_ref: ResourceRef
    result_ref: Optional[ResourceRef]
    candidate_ref: ResourceRef
    criterion_ref: ResourceRef
    author: str
    authority: str
    rationale: str
    disposition: str
    evidence_refs: Tuple[ResourceRef, ...]
    return_condition: Optional[str]
    version: int
    payload: Mapping[str, Any]
    receipt: Optional[CommandReceipt] = None


__all__ = [
    "AssessmentAuthorityError", "AssessmentError", "AssessmentNotFoundError",
    "AssessmentResult", "AssessmentScope", "AssessmentStateError",
    "CandidateSelection", "Correction", "Decision", "Disposition", "Finding",
    "InputPacket", "Invocation", "StaleAssessmentError", "Verdict",
]
