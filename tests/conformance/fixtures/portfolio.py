"""Disposable two-project portfolio rehearsal specification."""

from __future__ import annotations

from pathlib import Path

from .common import HarnessWorkspace, envelope, stable_digest


def build_disposable_portfolio(workspace: HarnessWorkspace | None = None) -> dict:
    owned_workspace = workspace or HarnessWorkspace("int02-portfolio-")
    root = owned_workspace.root
    projects = [
        {"id": "rehearsal-alpha", "name": "Disposable Alpha", "repository": "repo-alpha"},
        {"id": "rehearsal-beta", "name": "Disposable Beta", "repository": "repo-beta"},
    ]
    for project in projects:
        project_root = root / project["repository"]
        project_root.mkdir(parents=True, exist_ok=True)
        (project_root / "README.fixture").write_text("INT-02 harness repository; not a product checkout.\n")
    payload = {
        "portfolio_id": "disposable-portfolio-v1",
        "root": str(root),
        "projects": projects,
        "repositories": ["repo-alpha", "repo-beta"],
        "local_promotion_target": "disposable-remote",
        "control_ledger_target": None,
        "operations": [
            "manager-selects-next-action",
            "shared-handoff",
            "failed-result-and-correction",
            "candidate-bound-decision",
            "restart-and-reconcile-attention",
        ],
        "expected_isolation": {"live_control_db_touched": False, "product_commands_invoked": False},
    }
    return envelope(
        "disposable_portfolio_rehearsal",
        {**payload, "spec_digest": stable_digest({k: v for k, v in payload.items() if k != "root"})},
        "disposable-portfolio-v1",
    )
