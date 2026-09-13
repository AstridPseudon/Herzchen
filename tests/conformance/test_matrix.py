"""Validation of the INT-02 matrix and explicit product-proof boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MATRIX = json.loads((ROOT / "validation/scenarios.json").read_text())
BINDINGS = json.loads((ROOT / "validation/area-command-bindings.json").read_text())

REQUIRED_FIELDS = {
    "id", "owner", "produced_by", "criteria", "consumer_contract",
    "command_action_binding", "required_input_source_refs", "positive_cases",
    "negative_cases", "proof_class", "expected_observable_effect",
    "before_read", "action", "fresh_after_read", "fresh_read_expectation",
    "persisted_expectations",
    "restart_recovery_expectation", "fixture_vs_product_status",
}
REQUIRED_PERSISTED_FIELDS = {"state_delta", "event_receipt", "replay"}
AREAS = {"FND", "DAT", "PKG", "WRK", "EDT", "OTT", "AST", "INT"}


class MatrixTests(unittest.TestCase):
    def test_matrix_is_versioned_and_unexecuted(self):
        self.assertEqual(MATRIX["schema"], "int-02-conformance-matrix/v1")
        self.assertRegex(MATRIX["matrix_version"], r"^\d{4}-\d{2}-\d{2}\.\d+$")
        self.assertEqual(MATRIX["status"], "planned_not_executed")
        self.assertIn("schema_only", MATRIX["proof_classes"])

    def test_every_retained_scenario_has_direct_conformance_fields(self):
        scenarios = MATRIX["scenarios"]
        ids = [scenario["id"] for scenario in scenarios]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(MATRIX["coverage"]["retained_existing_scenario_ids"]))
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                self.assertTrue(REQUIRED_FIELDS <= set(scenario))
                self.assertTrue(REQUIRED_PERSISTED_FIELDS <= set(scenario["persisted_expectations"]))
                self.assertEqual(scenario["proof_class"], "harness_fixture")
                self.assertEqual(scenario["fixture_vs_product_status"]["fixture"], "planned")
                self.assertEqual(scenario["fixture_vs_product_status"]["installed_product"], "pending")
                self.assertNotEqual(scenario["positive_cases"], scenario["negative_cases"])

    def test_required_discriminating_scenarios_are_present(self):
        scenarios = {scenario["id"]: scenario for scenario in MATRIX["scenarios"]}
        for scenario_id in ("S-ELEGANCE-CONTEXT", "S-ELEGANCE-DEFINITION", "S-MANAGER-CHOICE", "S-REVIEW-CHOICE"):
            self.assertIn(scenario_id, scenarios)
            scenario = scenarios[scenario_id]
            self.assertGreaterEqual(len(scenario["positive_cases"]), 2)
            self.assertGreaterEqual(len(scenario["negative_cases"]), 2)
            self.assertIn("fresh", scenario["fresh_read_expectation"].lower())
            self.assertIn("reject", json.dumps(scenario["negative_cases"]).lower())

    def test_all_owner_areas_are_represented_by_bindings(self):
        bindings = BINDINGS["bindings"]
        self.assertEqual(len(bindings), 10)
        self.assertEqual({row["owner"] for row in bindings}, AREAS)
        self.assertEqual({row["area"] for row in bindings}, {"kernel", "metadata_docs", "packs_templates", "work_assessment", "authoring", "agent_host", "otto_product", "astrid_adoption", "third_specialist", "integration_release"})
        for row in bindings:
            with self.subTest(area=row["area"]):
                self.assertTrue(row["command"].startswith("fixture-only:"))
                self.assertIsNone(row["public_command"])
                self.assertIn("pending", row["missing_binding_status"])
                self.assertEqual(row["product_status"], "pending")
                self.assertTrue(row["fixture_path"].startswith("tests/conformance/fixtures/"))
                self.assertTrue(row["criteria"])

    def test_exact_source_pins_are_used_without_product_claims(self):
        expected = {
            "astrid": ("96e5664237eb35adeb4cad08bddd8cd6df0a2ae1", "19f7539a266618a797559eedbda48e2752b30fa3"),
            "runtime": ("afccb430e2a983c968b6a8a96fd630ba3a6262fc", "be89db2f02231aeef212bdb266d12c51778f32ae"),
            "poms-skills": ("d849898cd0c191cffc5ababbb5ea7d2c188e8ed0", "9644eb21632a98a51af7051ceeb294f851a7c70f"),
        }
        lineage = {item["id"]: item for item in MATRIX["lineage"]["source_inputs"]}
        for source_id, (commit, tree) in expected.items():
            self.assertEqual((lineage[source_id]["commit"], lineage[source_id]["tree"]), (commit, tree))
        self.assertNotIn("PASS", json.dumps(MATRIX["fixture_inventory"]))
        self.assertNotIn("product_state", json.dumps(MATRIX["scenarios"]))

    def test_catalog_and_rehearsal_are_explicitly_read_only_or_disposable(self):
        catalog = MATRIX["whole_catalog_representation"]
        rehearsal = MATRIX["disposable_portfolio_rehearsal"]
        self.assertTrue(catalog["read_only"])
        self.assertEqual(set(catalog["owner_areas"]), AREAS)
        self.assertTrue(rehearsal["isolation"]["temporary_directory"])
        self.assertFalse(rehearsal["isolation"]["live_control_db"])
        self.assertIn("pending", rehearsal["product_status"])


if __name__ == "__main__":
    unittest.main()
