from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from render.failure_renderer import infer_next_action, render_failure_message  # noqa: E402


class FailureRendererTests(unittest.TestCase):
    def test_route_mismatch_message(self) -> None:
        self.assertIn("航段", render_failure_message("route_not_found_in_report"))

    def test_live_refresh_failed_message_carries_error(self) -> None:
        msg = render_failure_message("live_refresh_failed", {"live_refresh_error": "auth_required"})
        self.assertIn("实时刷新失败", msg)
        self.assertIn("auth_required", msg)

    def test_next_action_for_route_mismatch(self) -> None:
        self.assertEqual(infer_next_action("route_not_found_in_report"), "trigger_live_refresh")


if __name__ == "__main__":
    unittest.main()
