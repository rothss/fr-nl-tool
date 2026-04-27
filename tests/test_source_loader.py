from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from data.source_loader import acquire_source, should_block_on_preflight  # noqa: E402


class SourceLoaderTests(unittest.TestCase):
    def test_acquire_source_marks_live_refresh(self) -> None:
        plan = {"report_path": r"C:\mock\future.xlsx", "report_name": "未来航班客座率票价分析"}
        intent = {"filters": {}}
        query_result = {
            "ok": True,
            "used_live_refresh": True,
            "top_candidate": {"file_path": r"C:\mock\future.xlsx", "report_name": "未来航班客座率票价分析"},
        }
        actual = acquire_source(plan, intent, query_result)
        self.assertEqual(actual["source_type"], "live_refresh")
        self.assertTrue(actual["refreshed"])

    def test_acquire_source_attempts_structured_refresh_when_required(self) -> None:
        plan = {
            "report_family": "future_flight_competition",
            "report_path": r"C:\mock\future.xlsx",
            "report_name": "未来航班客座率票价分析",
            "require_live_refresh": True,
        }
        intent = {"filters": {"segment_from": "海口", "segment_to": "北京首都", "flight_date": ["2026-04-01"]}}
        query_result = {
            "ok": False,
            "used_live_refresh": False,
            "top_candidate": {"file_path": r"C:\mock\future.xlsx", "report_name": "未来航班客座率票价分析"},
        }
        with (
            patch("data.source_loader.probe_local_file_against_intent", side_effect=[
                {"file_exists": True, "schema_ok": True, "route_match_ok": False, "date_match_ok": True, "warnings": ["route_mismatch"]},
                {"file_exists": True, "schema_ok": True, "route_match_ok": True, "date_match_ok": True, "warnings": []},
            ]),
            patch("data.source_loader.run_fast_future_kzl_export", return_value=(True, "ok")),
        ):
            actual = acquire_source(plan, intent, query_result)
        self.assertEqual(actual["source_type"], "live_refresh")
        self.assertTrue(actual["refreshed"])
        self.assertTrue(actual["route_match_ok"])

    def test_preflight_blocks_route_mismatch_before_refresh(self) -> None:
        plan = {"report_family": "future_flight_competition"}
        source_meta = {"schema_ok": True, "route_match_ok": False, "date_match_ok": True, "refreshed": False}
        blocked, reason, message = should_block_on_preflight(plan, source_meta)
        self.assertTrue(blocked)
        self.assertEqual(reason, "route_not_found_in_report")
        self.assertIn("航段", message)


if __name__ == "__main__":
    unittest.main()
