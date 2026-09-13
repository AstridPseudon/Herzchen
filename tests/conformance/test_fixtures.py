"""Shape and discriminating-case checks for the source-independent fixtures."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from fixtures.attention import build_attention_recovery
from fixtures.candidate_decision import build_candidate_decision_cases
from fixtures.common import HARNESS_MARKER, HarnessWorkspace, stable_digest
from fixtures.definition_catalog import AREA_TASKS, build_definition_catalog
from fixtures.manager_choice import build_manager_choice_cases
from fixtures.operating_context import build_operating_context_cases
from fixtures.portfolio import build_disposable_portfolio
from fixtures.review_choice import build_review_choice_cases


class FixtureShapeTests(unittest.TestCase):
    def assert_harness_envelope(self, fixture: dict) -> None:
        self.assertEqual(fixture["fixture_schema"], "int-02-fixture/v1")
        self.assertEqual(fixture["harness"], HARNESS_MARKER)
        self.assertFalse(fixture["harness"]["product_state"])
        self.assertFalse(fixture["harness"]["live_control_target"])

    def test_all_builders_are_marked_harness_inputs(self):
        builders = [
            *build_operating_context_cases().values(),
            *build_manager_choice_cases().values(),
            *build_review_choice_cases().values(),
            *build_candidate_decision_cases().values(),
            build_definition_catalog(),
            build_attention_recovery(),
        ]
        for fixture in builders:
            with self.subTest(fixture=fixture["fixture_id"]):
                self.assert_harness_envelope(fixture)

    def test_context_positive_and_negative_are_observably_different(self):
        cases = build_operating_context_cases()
        self.assertTrue(cases["positive"]["payload"]["mandate"])
        self.assertIsNone(cases["negative"]["payload"]["mandate"])
        self.assertNotEqual(cases["positive"]["payload"]["context_revision"], cases["negative"]["payload"]["context_revision"])

    def test_definition_is_read_only_and_preserves_unknown_conditional_pending(self):
        payload = build_definition_catalog()["payload"]
        self.assertTrue(payload["definition"]["read_only"])
        catalog = payload["catalog"]
        self.assertTrue(catalog["read_only"])
        self.assertTrue(catalog["preserve_unknown_conditional_pending"])
        self.assertEqual(set(AREA_TASKS), {area["area"] for area in catalog["owner_areas"]})
        for area in catalog["owner_areas"]:
            self.assertIn("unknown_fields", area)
            self.assertIn("conditional_nodes", area)
            self.assertIn("pending_nodes", area)

    def test_manager_choice_does_not_collapse_into_ready_flag(self):
        cases = build_manager_choice_cases()
        self.assertEqual(cases["positive"]["payload"]["selected_action"], "implement-rehearsal-change")
        self.assertIsNone(cases["negative"]["payload"]["selected_action"])
        self.assertFalse(cases["negative"]["payload"]["automatic_dispatch"])
        self.assertIn("not an implicit business choice", cases["negative"]["payload"]["rejection_reason"])

    def test_review_choice_alternatives_and_invalid_stack_are_distinct(self):
        cases = build_review_choice_cases()
        self.assertEqual((cases["normal"]["payload"]["model"], cases["normal"]["payload"]["reasoning"]), ("gpt-5.6-luna", "xhigh"))
        self.assertEqual((cases["xhard"]["payload"]["model"], cases["xhard"]["payload"]["reasoning"]), ("gpt-5.6-sol", "high"))
        self.assertTrue(cases["negative"]["payload"]["extra_stage"])
        self.assertEqual(len(cases["negative"]["payload"]["review_sequence"]), 2)

    def test_candidate_input_change_invalidates_only_affected_decision(self):
        cases = build_candidate_decision_cases()
        self.assertEqual(cases["positive"]["payload"]["decision"]["candidate_id"], "candidate-A")
        self.assertEqual(cases["negative"]["payload"]["candidate"]["candidate_id"], "candidate-B")
        self.assertEqual(cases["negative"]["payload"]["unrelated_annotation"]["key"], "does-not-invalidate")

    def test_attention_recovery_orders_events_and_does_not_dispatch(self):
        payload = build_attention_recovery()["payload"]
        self.assertEqual(payload["expected"]["ordered_reread"], ["evt-010", "evt-011"])
        self.assertEqual(payload["expected"]["business_dispatches"], 0)
        self.assertTrue(payload["expected"]["unhandled_preserved"])

    def test_digest_is_deterministic(self):
        first = build_definition_catalog()["payload"]["catalog_digest"]
        second = build_definition_catalog()["payload"]["catalog_digest"]
        self.assertEqual(first, second)
        self.assertEqual(stable_digest({"b": 2, "a": 1}), stable_digest({"a": 1, "b": 2}))

    def test_portfolio_is_temporary_and_disposable(self):
        with HarnessWorkspace("int02-test-") as workspace:
            rehearsal = build_disposable_portfolio(workspace)
            self.assert_harness_envelope(rehearsal)
            payload = rehearsal["payload"]
            self.assertIsNone(payload["control_ledger_target"])
            self.assertFalse(payload["expected_isolation"]["live_control_db_touched"])
            self.assertEqual({p["id"] for p in payload["projects"]}, {"rehearsal-alpha", "rehearsal-beta"})
            self.assertTrue((workspace.root / "repo-alpha" / "README.fixture").exists())
        self.assertFalse(workspace.root.exists())


if __name__ == "__main__":
    unittest.main()
