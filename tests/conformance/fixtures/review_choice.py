"""Review routing inputs; alternatives are not stacked review stages."""

from __future__ import annotations

from .common import envelope


def build_review_choice_cases() -> dict[str, dict]:
    normal = {
        "choice_id": "review-choice-normal",
        "role": "reviewer_normal",
        "model": "gpt-5.6-luna",
        "reasoning": "xhigh",
        "stage": "selected_leaf",
        "accounting_scope": "existing-allowance",
        "review_sequence": ["reviewer_normal"],
        "extra_stage": False,
    }
    xhard = {
        "choice_id": "review-choice-xhard",
        "role": "reviewer_xhard",
        "model": "gpt-5.6-sol",
        "reasoning": "high",
        "stage": "selected_leaf",
        "accounting_scope": "existing-allowance",
        "review_sequence": ["reviewer_xhard"],
        "extra_stage": False,
    }
    rejected_stack = {
        "choice_id": "review-choice-invalid-stack",
        "role": "reviewer_normal",
        "model": "gpt-5.6-luna",
        "reasoning": "xhigh",
        "review_sequence": ["reviewer_normal", "reviewer_xhard"],
        "extra_stage": True,
        "rejection_reason": "a selected alternative cannot become an automatic second panel",
    }
    return {
        "normal": envelope("review_choice", normal, "review-choice-normal"),
        "xhard": envelope("review_choice", xhard, "review-choice-xhard"),
        "negative": envelope("review_choice", rejected_stack, "review-choice-negative"),
    }
