from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import runner  # noqa: E402


class RunnerContractTests(unittest.TestCase):
    def test_runner_wraps_query_result_into_openclaw_envelope(self) -> None:
        fake_result = {
            "ok": True,
            "intent": {
                "metric": "客座率",
                "filters": {"segment_from": "海口", "segment_to": "北京首都", "flight_date": ["2026-04-01"]},
            },
            "top_candidate": {
                "report_name": "未来航班客座率票价分析",
                "file_path": r"C:\mock\future.xlsx",
            },
            "used_live_refresh": True,
            "freshness_force_live": False,
            "metric_column": "现在客座率",
            "row_count_after_filter": 2,
            "answer_text": "未来两天海口-北京首都航段存在竞对弱势航班。",
        }
        with patch.object(runner, "execute_query", return_value=fake_result):
            result = runner.run_query("海口到北京首都未来两天客座率和票价")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["plan"]["report_name"], "未来航班客座率票价分析")
        self.assertEqual(result["analysis_result"]["matched_route"], "海口-北京首都")
        self.assertEqual(result["analysis_result"]["matched_dates"], ["2026-04-01"])

    def test_runner_keeps_failure_structured(self) -> None:
        fake_result = {"ok": False, "reason": "no_report_match", "intent": {"metric": None, "filters": {}}}
        with patch.object(runner, "execute_query", return_value=fake_result):
            result = runner.run_query("完全不存在的报表问题")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "no_report_match")
        self.assertEqual(result["next_action"], "refine_query")

    def test_runner_maps_route_mismatch_to_structured_reason_when_not_refreshed(self) -> None:
        fake_result = {
            "ok": False,
            "intent": {
                "metric": "客座率",
                "filters": {"segment_from": "海口", "segment_to": "北京首都", "analysis_mode": "competition_review"},
                "structured_intent": {
                    "metrics": ["客座率", "价格"],
                    "time": {"mode": "relative_future_range"},
                    "analysis": {"mode": "competition_review"},
                },
            },
            "top_candidate": {
                "report_name": "未来航班客座率票价分析",
                "file_path": r"C:\mock\future.xlsx",
            },
            "used_live_refresh": False,
            "freshness_force_live": False,
        }
        with patch.object(runner, "execute_query", return_value=fake_result), patch.object(
            runner,
            "build_source_meta",
            return_value={
                "ok": False,
                "source_type": "query_pipeline",
                "file_path": r"C:\mock\future.xlsx",
                "refreshed": False,
                "refresh_message": None,
                "last_modified": None,
                "schema_ok": True,
                "route_match_ok": False,
                "date_match_ok": True,
                "warnings": ["route_mismatch"],
            },
        ):
            result = runner.run_query("海口到北京首都未来两天客座率和票价")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "route_not_found_in_report")
        self.assertIn("当前报表", result["message"])


if __name__ == "__main__":
    unittest.main()
