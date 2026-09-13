"""Filesystem/concurrency-shaped rehearsal checks with no product state."""

from __future__ import annotations

import unittest

from fixtures.common import HarnessWorkspace
from fixtures.portfolio import build_disposable_portfolio


class RehearsalTests(unittest.TestCase):
    def test_rebuild_in_same_workspace_is_stable_and_isolated(self):
        with HarnessWorkspace("int02-rehearsal-") as workspace:
            first = build_disposable_portfolio(workspace)
            files_before = sorted(path.relative_to(workspace.root).as_posix() for path in workspace.files())
            second = build_disposable_portfolio(workspace)
            files_after = sorted(path.relative_to(workspace.root).as_posix() for path in workspace.files())
            self.assertEqual(first["fixture_id"], second["fixture_id"])
            self.assertEqual(files_before, files_after)
            self.assertNotIn("control.db", files_after)
            self.assertNotIn("source-set-int01-refresh", " ".join(files_after))

    def test_rehearsal_declares_operations_but_does_not_execute_them(self):
        with HarnessWorkspace("int02-rehearsal-") as workspace:
            payload = build_disposable_portfolio(workspace)["payload"]
            self.assertEqual(payload["operations"], [
                "manager-selects-next-action",
                "shared-handoff",
                "failed-result-and-correction",
                "candidate-bound-decision",
                "restart-and-reconcile-attention",
            ])
            self.assertFalse(payload["expected_isolation"]["product_commands_invoked"])


if __name__ == "__main__":
    unittest.main()
