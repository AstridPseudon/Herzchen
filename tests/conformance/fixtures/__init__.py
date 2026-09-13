"""Deterministic, stdlib-only INT-02 harness inputs.

These builders produce disposable descriptions and filesystem fixtures. They
are never product state and deliberately do not import a product module.
"""

from .attention import build_attention_recovery
from .candidate_decision import build_candidate_decision_cases
from .definition_catalog import build_definition_catalog
from .manager_choice import build_manager_choice_cases
from .operating_context import build_operating_context_cases
from .portfolio import build_disposable_portfolio
from .review_choice import build_review_choice_cases

__all__ = [
    "build_attention_recovery",
    "build_candidate_decision_cases",
    "build_definition_catalog",
    "build_disposable_portfolio",
    "build_manager_choice_cases",
    "build_operating_context_cases",
    "build_review_choice_cases",
]
