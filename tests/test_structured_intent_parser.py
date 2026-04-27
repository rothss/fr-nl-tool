from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from parse_query_intent import parse_structured_query  # noqa: E402


class StructuredIntentParserTests(unittest.TestCase):
    def test_future_two_days_competition_query(self) -> None:
        actual = parse_structured_query(
            "海口到北京首都未来两天的客座率和票价，和竞争对手比有什么问题",
            today=date(2026, 4, 1),
        )
        self.assertEqual(actual["time"]["mode"], "relative_future_range")
        self.assertEqual(actual["time"]["start_date"], "2026-04-01")
        self.assertEqual(actual["time"]["end_date"], "2026-04-02")
        self.assertEqual(actual["route"]["origin_norm"], "海口")
        self.assertEqual(actual["route"]["destination_norm"], "北京首都")
        self.assertIn("客座率", actual["metrics"])
        self.assertIn("价格", actual["metrics"])
        self.assertEqual(actual["analysis"]["mode"], "competition_review")

    def test_airport_aliases_are_normalized(self) -> None:
        actual = parse_structured_query(
            "美兰到首都未来两天的客座率和票价",
            today=date(2026, 4, 1),
        )
        self.assertEqual(actual["route"]["origin_norm"], "海口")
        self.assertEqual(actual["route"]["destination_norm"], "北京首都")
        self.assertEqual(actual["route"]["origin_code"], "AP1")
        self.assertEqual(actual["route"]["destination_code"], "PEK")


if __name__ == "__main__":
    unittest.main()
