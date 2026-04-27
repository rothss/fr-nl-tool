from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from parse_query_intent import parse_structured_query  # noqa: E402


class LLMIntentMergeTests(unittest.TestCase):
    def test_llm_candidate_can_fill_missing_analysis_mode(self) -> None:
        llm_candidate = {
            "analysis": {
                "mode": "competition_review",
                "compare_target": "competitor",
                "question_type": "diagnosis",
            },
            "parser_trace": ["llm:analysis"],
        }
        with patch("parse_query_intent.maybe_parse_with_local_llm", return_value=llm_candidate):
            actual = parse_structured_query(
                "海口到北京首都未来两天的客座率和票价对比情况",
                today=date(2026, 4, 1),
            )
        self.assertEqual(actual["analysis"]["mode"], "competition_review")
        self.assertIn("llm:slot_fill", actual["parser_trace"])

    def test_llm_candidate_does_not_override_existing_high_confidence_route(self) -> None:
        llm_candidate = {
            "route": {
                "origin_norm": "博鳌",
                "destination_norm": "北京首都",
            }
        }
        with patch("parse_query_intent.maybe_parse_with_local_llm", return_value=llm_candidate):
            actual = parse_structured_query(
                "海口到北京首都未来两天的客座率和票价，和竞争对手比有什么问题",
                today=date(2026, 4, 1),
            )
        self.assertEqual(actual["route"]["origin_norm"], "海口")
        self.assertEqual(actual["route"]["destination_norm"], "北京首都")


if __name__ == "__main__":
    unittest.main()
