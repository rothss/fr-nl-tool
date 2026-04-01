from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analysis.future_flight_competition import render_future_competition_review  # noqa: E402


class FutureFlightCompetitionTests(unittest.TestCase):
    def test_render_competition_review_contains_findings(self) -> None:
        rows = [
            {
                "航班号": "HU1234",
                "航班日期": "2026-04-02 00:00:00",
                "时刻": "2026-04-02 11:00:00",
                "现在客座率": "71.8%",
                "本DCP阶段标准客座率目标": "86.2%",
                "与竞航客座率差": "-18.9",
                "与竞航价格差": "-150",
            }
        ]
        text = render_future_competition_review(
            rows,
            "未来航班客座率票价分析",
            r"C:\mock\future.xlsx",
            {"segment_from": "海口", "segment_to": "北京首都", "date_start": "2026-04-01", "date_end": "2026-04-02"},
        )
        self.assertIn("HU1234", text)
        self.assertIn("低于阶段目标", text)
        self.assertIn("客座率较竞航低", text)


if __name__ == "__main__":
    unittest.main()
