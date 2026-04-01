from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analysis.airline_yoy import analyze_airline_yoy, render_airline_yoy_answer  # noqa: E402
from planning.router import route_report_family  # noqa: E402


class AirlineYoyTests(unittest.TestCase):
    def test_router_prefers_adjusted_profit_overview(self) -> None:
        routed = route_report_family(
            {
                "metric": "净利润同比",
                "metrics": ["净利润同比"],
                "raw_query": "2月份的不含发动机大修和飞机退租的净利润，哪个航司提升最大",
                "filters": {
                    "report_variant": "adjusted_profit_overview",
                    "compare_scope": "airline_yoy",
                    "extreme": "best",
                },
                "structured_intent": {"metrics": ["净利润同比"], "analysis": {"mode": None}, "time": {"mode": None}},
            }
        )
        self.assertEqual(routed[0]["report_name"], "航空集团收入利润概览（调整后）")

    def test_analyze_airline_yoy_best_case(self) -> None:
        result = analyze_airline_yoy(
            {
                "metric": "净利润同比",
                "raw_query": "这个月的各航司净利润的同比，谁表现最好",
                "filters": {"extreme": "best", "date_start": "2026-03-01", "date_end": "2026-03-31"},
            },
            {
                "rows": [
                    {"航司": "首都航空", "净利润同比": "658.26%", "排名": "1"},
                    {"航司": "福州航空", "净利润同比": "18.26%", "排名": "10"},
                ]
            },
            {"file_path": r"C:\mock\profit.xlsx", "report_name": "航空集团经营提升分析"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["analysis_engine"], "airline_yoy")
        self.assertIn("首都航空", result["summary"])

    def test_render_airline_yoy_answer(self) -> None:
        text = render_airline_yoy_answer(
            {
                "ok": True,
                "result_row": {"airline": "福州航空", "yoy": 18.26, "rank": 10, "total": 10, "yoy_col": "净利润同比"},
            },
            {"filters": {"extreme": "worst", "date_start": "2026-03-01", "date_end": "2026-03-31"}},
            {"report_name": "航空集团经营提升分析", "file_path": r"C:\mock\profit.xlsx"},
        )
        self.assertIn("表现最差: 福州航空", text)
        self.assertIn("同比: 18.26%", text)


if __name__ == "__main__":
    unittest.main()
