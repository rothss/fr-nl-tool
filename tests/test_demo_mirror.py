from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from create_demo_mirror import create_demo_mirror  # noqa: E402
from profiles.opm_example import profile_metadata  # noqa: E402
import runner  # noqa: E402


class DemoMirrorTests(unittest.TestCase):
    def test_profile_metadata_exposes_demo_queries(self) -> None:
        meta = profile_metadata()
        self.assertEqual(meta["profile_id"], "opm_example")
        self.assertGreaterEqual(len(meta["demo_queries"]), 2)

    def test_demo_mirror_supports_offline_runner_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "demo_mirror"
            result = create_demo_mirror(root)
            self.assertTrue(result["ok"])

            catalog_db = root / "search_index" / "report_catalog.db"
            user_scope = root / "search_index" / "user_scope.yaml"
            self.assertTrue(catalog_db.exists())
            self.assertTrue(user_scope.exists())

            competition = runner.run_query(
                "海口-北京首都的包干航线，近三天的票价和客座率与外航相比，有没有什么异常或者可以改进的吗",
                mirror_root=root,
                db_path=catalog_db,
                user_scope_path=user_scope,
            )
            self.assertTrue(competition["ok"])
            self.assertEqual(
                competition["analysis_result"]["analysis_engine"],
                "future_flight_competition",
            )
            self.assertIn("海口-北京首都", str(competition.get("answer_text") or ""))

            airline = runner.run_query(
                "这个月的各航司净利润的同比，谁表现得最差",
                mirror_root=root,
                db_path=catalog_db,
                user_scope_path=user_scope,
            )
            self.assertTrue(airline["ok"])
            self.assertEqual(
                airline["analysis_result"]["analysis_engine"], "airline_yoy"
            )
            self.assertIn("首都航空", str(airline.get("answer_text") or ""))


if __name__ == "__main__":
    unittest.main()
