from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from data.schemas import get_report_schema, validate_schema_columns  # noqa: E402
from planning.planner import build_query_plan  # noqa: E402


class PlannerSchemaTests(unittest.TestCase):
    def test_report_schema_registry_contains_future_flight_schema(self) -> None:
        schema = get_report_schema("未来航班客座率票价分析")
        self.assertIsNotNone(schema)
        self.assertEqual(schema["schema_name"], "future_flight_competition_v1")

    def test_schema_validation_flags_missing_identity_columns(self) -> None:
        schema = get_report_schema("未来航班客座率票价分析")
        result = validate_schema_columns(["价格", "竞航价格"], schema)
        self.assertFalse(result["schema_ok"])
        self.assertIn("航班号", result["missing_identity_cols"])

    def test_planner_requires_live_refresh_when_route_mismatch(self) -> None:
        intent = {
            "metric": "客座率",
            "metrics": ["客座率", "价格"],
            "filters": {"segment_from": "海口", "segment_to": "北京首都", "analysis_mode": "competition_review"},
            "structured_intent": {
                "metrics": ["客座率", "价格"],
                "time": {"mode": "relative_future_range"},
                "analysis": {"mode": "competition_review"},
            },
        }
        local_probe = {
            "file_exists": True,
            "schema_ok": True,
            "route_match_ok": False,
            "date_match_ok": True,
        }
        plan = build_query_plan(intent, local_probe=local_probe)
        self.assertEqual(plan["report_family"], "future_flight_competition")
        self.assertTrue(plan["require_live_refresh"])
        self.assertIn("refresh:route_mismatch", plan["rationale"])


if __name__ == "__main__":
    unittest.main()
