from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analysis.single_margin import analyze_single_margin, render_single_margin_answer  # noqa: E402
from planning.router import route_report_family  # noqa: E402


class SingleMarginTests(unittest.TestCase):
    def test_router_prefers_single_margin(self) -> None:
        routed = route_report_family(
            {
                "metric": "单机边际贡献",
                "metrics": ["单机边际贡献"],
                "filters": {},
                "structured_intent": {"metrics": ["单机边际贡献"], "analysis": {"mode": None}, "time": {"mode": None}},
            }
        )
        self.assertEqual(routed[0]["report_name"], "单机边际贡献")

    def test_analyze_single_margin(self) -> None:
        result = analyze_single_margin(
            {"metric": "单机边际贡献"},
            {"rows": [{"日期": "2026-04-01", "公司": "CompanyB", "机型": "宽体机", "单机边际贡献": 12.34}]},
            {"file_path": r"C:\mock\single_margin.xlsx", "report_name": "单机边际贡献"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["analysis_engine"], "single_margin")

    def test_render_single_margin_answer(self) -> None:
        text = render_single_margin_answer(
            {"ok": True, "rows": [{"日期": "2026-04-01", "公司": "CompanyB", "机型": "宽体机", "单机边际贡献": 12.34}]},
            {"metric": "单机边际贡献"},
            {"report_name": "单机边际贡献", "file_path": r"C:\mock\single_margin.xlsx"},
        )
        self.assertIn("单机边际贡献=12.34", text)


if __name__ == "__main__":
    unittest.main()
