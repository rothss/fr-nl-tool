from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from data.extractor_registry import describe_analysis_binding, get_analysis_renderer  # noqa: E402


class ExtractorRegistryTests(unittest.TestCase):
    def test_future_competition_renderer_binding_exists(self) -> None:
        renderer = get_analysis_renderer("未来航班客座率票价分析", analysis_mode="competition_review")
        self.assertIsNotNone(renderer)
        self.assertEqual(getattr(renderer, "__name__", ""), "render_future_competition_review")

    def test_binding_description_for_unknown_case(self) -> None:
        info = describe_analysis_binding("未知报表", analysis_mode="competition_review")
        self.assertFalse(info["bound"])
        self.assertIsNone(info["renderer_name"])


if __name__ == "__main__":
    unittest.main()
