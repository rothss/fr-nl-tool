from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from adapters.openclaw_contract import to_openclaw_result  # noqa: E402


class OpenClawContractTests(unittest.TestCase):
    def test_success_payload_maps_to_completed_stage(self) -> None:
        payload = {
            "ok": True,
            "intent": {"metric": "客座率"},
            "plan": {"report_name": "未来航班客座率票价分析"},
            "source_meta": {"ok": True},
            "analysis_result": {"ok": True},
            "answer_text": "ok",
        }
        result = to_openclaw_result(payload)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "completed")
        self.assertIsNone(result["reason_code"])
        self.assertEqual(result["answer_text"], "ok")

    def test_failure_payload_maps_reason_and_next_action(self) -> None:
        payload = {"ok": False, "reason": "no_report_match"}
        result = to_openclaw_result(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "planning")
        self.assertEqual(result["reason_code"], "no_report_match")
        self.assertEqual(result["next_action"], "refine_query")


if __name__ == "__main__":
    unittest.main()

