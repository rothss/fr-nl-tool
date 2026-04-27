from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from profiles import (  # noqa: E402
    get_profile_analysis_binding,
    get_profile_analysis_engine_name,
    get_profile_report_name,
)


class ProfileBindingsTests(unittest.TestCase):
    def test_profile_report_names_cover_known_families(self) -> None:
        self.assertEqual(
            get_profile_report_name("future_flight_competition"),
            "未来航班客座率票价分析",
        )
        self.assertEqual(
            get_profile_report_name("adjusted_profit_overview"),
            "集团收入利润概览（调整后）",
        )

    def test_profile_analysis_engine_names_cover_known_families(self) -> None:
        self.assertEqual(
            get_profile_analysis_engine_name("ranked_flights"),
            "ranked_flights",
        )
        self.assertEqual(
            get_profile_analysis_engine_name("airline_yoy"),
            "airline_yoy",
        )

    def test_profile_analysis_binding_resolves_renderer_pair(self) -> None:
        binding = get_profile_analysis_binding(
            "未来航班客座率票价分析",
            analysis_mode="competition_review",
        )
        self.assertIsNotNone(binding)
        engine, renderer = binding
        self.assertEqual(
            getattr(engine, "__name__", ""), "analyze_future_flight_competition"
        )
        self.assertEqual(
            getattr(renderer, "__name__", ""), "render_future_competition_review"
        )


if __name__ == "__main__":
    unittest.main()
