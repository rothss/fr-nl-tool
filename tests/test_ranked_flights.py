from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analysis.ranked_flights import analyze_first_flight_bottom10, render_first_flight_bottom10_answer  # noqa: E402
from planning.router import route_report_family  # noqa: E402


class RankedFlightsTests(unittest.TestCase):
    def test_router_prefers_ranked_flights_for_first_flight_bottom10(self) -> None:
        routed = route_report_family(
            {
                "metric": None,
                "metrics": [],
                "filters": {"rank_scope": "后十", "first_flight": True},
                "structured_intent": {"metrics": [], "analysis": {"mode": None}, "time": {"mode": None}},
            }
        )
        self.assertEqual(routed[0]["report_name"], "集团前十后十航班")

    def test_analyze_first_flight_bottom10(self) -> None:
        result = analyze_first_flight_bottom10(
            {},
            {
                "rows": [
                    {"公司_2": "CompanyB", "往返航班号_2": "JD1234", "机型_2": "桂林-海口"},
                    {"公司_2": "CompanyB", "往返航班号_2": "JD5678", "机型_2": "海口-长沙"},
                ]
            },
            {"file_path": r"C:\mock\ranked.xlsx", "report_name": "集团前十后十航班"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["first_flight_routes"], ["桂林-海口", "海口-长沙"])

    def test_render_first_flight_bottom10_answer(self) -> None:
        text = render_first_flight_bottom10_answer(
            {"first_flight_routes": ["桂林-海口", "海口-长沙"]},
            {"report_name": "集团前十后十航班", "file_path": r"C:\mock\ranked.xlsx"},
        )
        self.assertIn("后十首航航班共 2 条", text)
        self.assertIn("桂林-海口", text)


if __name__ == "__main__":
    unittest.main()
