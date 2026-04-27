from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from adapters.openclaw_contract import to_openclaw_result  # noqa: E402


CASE_FILE = Path(__file__).with_name("e2e_cases.json")


class E2EContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))

    def test_cases_map_to_expected_openclaw_contract(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["name"]):
                result = to_openclaw_result(case["payload"])
                for key, expected in (case["expected"] or {}).items():
                    self.assertEqual(result.get(key), expected)


if __name__ == "__main__":
    unittest.main()
