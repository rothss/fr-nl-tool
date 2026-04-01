from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from parse_query_intent import parse_query  # noqa: E402


CASE_FILE = Path(__file__).with_name("query_intent_cases.json")


def _assert_subset(testcase: unittest.TestCase, actual: object, expected: object, path: str = "root") -> None:
    if isinstance(expected, dict):
      testcase.assertIsInstance(actual, dict, f"{path} should be dict")
      actual_dict = actual if isinstance(actual, dict) else {}
      for key, exp_value in expected.items():
          testcase.assertIn(key, actual_dict, f"missing key at {path}.{key}")
          _assert_subset(testcase, actual_dict[key], exp_value, f"{path}.{key}")
      return
    if expected == "__non_empty__":
      testcase.assertTrue(actual not in (None, "", [], {}), f"{path} should be non-empty")
      return
    testcase.assertEqual(actual, expected, f"unexpected value at {path}")


class QueryIntentRegressionTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))

    def test_cases_are_well_formed(self) -> None:
        self.assertGreater(len(self.cases), 0)
        for case in self.cases:
            self.assertIn("name", case)
            self.assertIn("query", case)
            self.assertIn("expected", case)

    def test_regression_cases(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["name"]):
                actual = parse_query(case["query"])
                _assert_subset(self, actual, case["expected"])


if __name__ == "__main__":
    unittest.main()
