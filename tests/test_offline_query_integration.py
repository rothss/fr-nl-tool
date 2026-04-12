from __future__ import annotations

import json
import os
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import query_fr_nl  # noqa: E402


CASE_FILE = Path(__file__).with_name("offline_query_cases.json")
MIRROR_ROOT = Path(os.environ.get("FR_TEST_MIRROR_ROOT", "./fr_mirror"))
CATALOG_DB = MIRROR_ROOT / "search_index" / "report_catalog.db"
USER_SCOPE = MIRROR_ROOT / "search_index" / "user_scope.yaml"


def _get_by_path(payload: dict, dotted: str):
    cur = payload
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            raise KeyError(dotted)
        cur = cur[part]
    return cur


@unittest.skipUnless(
    MIRROR_ROOT.exists() and CATALOG_DB.exists() and USER_SCOPE.exists(),
    "local FR mirror not available",
)
class OfflineQueryIntegrationTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))

    def test_offline_cases(self) -> None:
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        for case in self.cases:
            with self.subTest(case=case["name"]):
                with (
                    patch.object(
                        query_fr_nl,
                        "should_force_live_refresh_by_freshness",
                        return_value=False,
                    ),
                    patch.object(
                        query_fr_nl,
                        "run_live_refresh",
                        return_value=(False, "disabled_in_test"),
                    ),
                    patch.object(
                        query_fr_nl,
                        "run_fast_future_kzl_export",
                        return_value=(False, "disabled_in_test"),
                    ),
                    patch.object(
                        query_fr_nl,
                        "run_generic_live_export",
                        return_value=(False, "disabled_in_test"),
                    ),
                    patch.object(query_fr_nl, "record_profile_hit", return_value=None),
                ):
                    result = query_fr_nl.run_query(
                        query=case["query"],
                        user=case.get("user"),
                        mirror_root=MIRROR_ROOT,
                        db_path=CATALOG_DB,
                        user_scope_path=USER_SCOPE,
                    )
                self.assertTrue(result.get("ok"), case["query"])
                for key, expected in (case.get("expected") or {}).items():
                    if key == "answer_text_contains":
                        answer_text = str(result.get("answer_text") or "")
                        for needle in expected:
                            self.assertIn(needle, answer_text)
                        continue
                    self.assertEqual(_get_by_path(result, key), expected)


if __name__ == "__main__":
    unittest.main()
