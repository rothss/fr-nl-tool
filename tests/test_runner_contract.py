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
    def test_runner_prefers_local_pipeline_before_legacy_executor(self) -> None:
        intent = {
            "metric": "客座率",
            "filters": {"segment_from": "海口", "segment_to": "北京首都", "analysis_mode": "competition_review"},
            "structured_intent": {
                "metrics": ["客座率", "价格"],
                "time": {"mode": "explicit_range"},
                "analysis": {"mode": "competition_review"},
            },
        }
        top_candidate = {
            "report_name": "未来航班客座率票价分析",
            "file_path": r"C:\mock\future.xlsx",
        }
        plan = {
            "report_family": "future_flight_competition",
            "report_name": "未来航班客座率票价分析",
            "report_path": r"C:\mock\future.xlsx",
            "require_live_refresh": False,
            "analysis_engine": "future_flight_competition",
            "fallback_plans": [],
            "rationale": [],
        }
        source_meta = {
            "ok": True,
            "source_type": "local_file",
            "file_path": r"C:\mock\future.xlsx",
            "refreshed": False,
            "refresh_message": None,
            "last_modified": None,
            "schema_ok": True,
            "route_match_ok": True,
            "date_match_ok": True,
            "warnings": [],
        }
        local_payload = {
            "ok": True,
            "intent": intent,
            "plan": plan,
            "source_meta": source_meta,
            "analysis_result": {
                "ok": True,
                "analysis_engine": "future_flight_competition",
                "matched_route": "海口-北京首都",
                "matched_dates": [],
                "issues": [],
                "advice": [],
                "summary": "本地分析摘要",
            },
            "answer_text": "本地分析答案",
        }
        with (
            patch.object(runner, "parse_query", return_value=intent),
            patch.object(runner, "resolve_top_candidate", return_value=top_candidate),
            patch.object(runner, "build_initial_plan", return_value=(plan, None)),
            patch.object(runner, "acquire_source", return_value=source_meta),
            patch.object(runner, "try_local_pipeline", return_value=local_payload),
            patch.object(runner, "execute_query", side_effect=AssertionError("legacy executor should not run")),
        ):
            result = runner.run_query("海口到北京首都的客座率和票价，和竞争对手比有什么问题")
        self.assertTrue(result["ok"])
        self.assertEqual(result["answer_text"], "本地分析答案")
        self.assertEqual(result["analysis_result"]["analysis_engine"], "future_flight_competition")

    def test_runner_wraps_query_result_into_openclaw_envelope(self) -> None:
        intent = {
            "metric": "客座率",
            "filters": {"segment_from": "海口", "segment_to": "北京首都", "flight_date": ["2026-04-01"]},
        }
        fake_result = {
            "ok": True,
            "intent": intent,
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
        with (
            patch.object(runner, "parse_query", return_value=intent),
            patch.object(runner, "resolve_top_candidate", return_value=fake_result["top_candidate"]),
            patch.object(
                runner,
                "build_initial_plan",
                return_value=(
                    {
                        "report_family": "future_flight_competition",
                        "report_name": "未来航班客座率票价分析",
                        "report_path": r"C:\mock\future.xlsx",
                        "require_live_refresh": True,
                        "analysis_engine": "future_flight_competition",
                        "fallback_plans": [],
                        "rationale": [],
                    },
                    None,
                ),
            ),
            patch.object(
                runner,
                "acquire_source",
                return_value={
                    "ok": False,
                    "source_type": "query_pipeline",
                    "file_path": r"C:\mock\future.xlsx",
                    "refreshed": False,
                    "refresh_message": "unsupported_structured_refresh",
                    "last_modified": None,
                    "schema_ok": True,
                    "route_match_ok": True,
                    "date_match_ok": True,
                    "warnings": ["unsupported_structured_refresh"],
                },
            ),
            patch.object(runner, "execute_query", return_value=fake_result),
        ):
            result = runner.run_query("海口到北京首都未来两天客座率和票价")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["plan"]["report_name"], "未来航班客座率票价分析")
        self.assertEqual(result["analysis_result"]["matched_route"], "海口-北京首都")
        self.assertEqual(result["analysis_result"]["matched_dates"], ["2026-04-01"])

    def test_runner_uses_refreshed_source_without_legacy_executor(self) -> None:
        intent = {
            "metric": "客座率",
            "filters": {"segment_from": "海口", "segment_to": "北京首都", "analysis_mode": "competition_review", "flight_date": ["2026-04-01"]},
            "structured_intent": {
                "metrics": ["客座率", "价格"],
                "time": {"mode": "relative_future_range"},
                "analysis": {"mode": "competition_review"},
            },
        }
        top_candidate = {"report_name": "未来航班客座率票价分析", "file_path": r"C:\mock\future.xlsx"}
        plan = {
            "report_family": "future_flight_competition",
            "report_name": "未来航班客座率票价分析",
            "report_path": r"C:\mock\future.xlsx",
            "require_live_refresh": True,
            "analysis_engine": "future_flight_competition",
            "fallback_plans": [],
            "rationale": ["refresh:future_query"],
        }
        source_meta = {
            "ok": True,
            "source_type": "live_refresh",
            "file_path": r"C:\mock\future.xlsx",
            "refreshed": True,
            "refresh_message": None,
            "last_modified": None,
            "schema_ok": True,
            "route_match_ok": True,
            "date_match_ok": True,
            "warnings": [],
        }
        local_payload = {
            "ok": True,
            "intent": intent,
            "plan": plan,
            "source_meta": source_meta,
            "analysis_result": {
                "ok": True,
                "analysis_engine": "future_flight_competition",
                "matched_route": "海口-北京首都",
                "matched_dates": ["2026-04-01"],
                "issues": [],
                "advice": [],
                "summary": "刷新后分析摘要",
            },
            "answer_text": "刷新后分析答案",
        }
        with (
            patch.object(runner, "parse_query", return_value=intent),
            patch.object(runner, "resolve_top_candidate", return_value=top_candidate),
            patch.object(runner, "build_initial_plan", return_value=(plan, None)),
            patch.object(runner, "acquire_source", return_value=source_meta),
            patch.object(runner, "try_local_pipeline", return_value=local_payload),
            patch.object(runner, "execute_query", side_effect=AssertionError("legacy executor should not run")),
        ):
            result = runner.run_query("海口到北京首都未来两天客座率和票价")
        self.assertTrue(result["ok"])
        self.assertEqual(result["answer_text"], "刷新后分析答案")

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
