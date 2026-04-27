"""Tests for config.py — centralized configuration module."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class ConfigModuleTests(unittest.TestCase):

    def test_import_config(self):
        from config import base_url, cdp_url, mirror_root, batch_root
        self.assertTrue(callable(base_url))
        self.assertTrue(callable(cdp_url))
        self.assertTrue(callable(mirror_root))
        self.assertTrue(callable(batch_root))

    def test_base_url_default(self):
        from config import base_url
        self.assertIn("opm.hnair.net", base_url())

    def test_cdp_url_default(self):
        from config import cdp_url
        self.assertIn("127.0.0.1", cdp_url())

    def test_mirror_root_resolves(self):
        from config import mirror_root
        p = mirror_root()
        self.assertIsInstance(p, Path)
        self.assertTrue(str(p).endswith("fr_mirror"))

    def test_catalog_db_path(self):
        from config import catalog_db
        p = catalog_db()
        self.assertIn("fr_mirror", str(p))
        self.assertTrue(str(p).endswith("report_catalog.db"))

    def test_excel_index_db_path(self):
        from config import excel_index_db
        p = excel_index_db()
        self.assertIn("excel_index.db", str(p))

    def test_manifest_json_path(self):
        from config import manifest_json
        p = manifest_json()
        self.assertTrue(str(p).endswith("manifest.json"))

    def test_login_patterns(self):
        from config import login_patterns
        p = login_patterns()
        self.assertIn("login", p)

    def test_env_fallback(self):
        from config import _env
        saved = os.environ.get("TEST_FR_KEY")
        try:
            os.environ["TEST_FR_KEY"] = "hello"
            self.assertEqual(_env("TEST_FR_KEY"), "hello")
            self.assertEqual(_env("MISSING_KEY", "TEST_FR_KEY"), "hello")
            self.assertEqual(_env("MISSING_KEY", default="fallback"), "fallback")
        finally:
            if saved is not None:
                os.environ["TEST_FR_KEY"] = saved
            elif "TEST_FR_KEY" in os.environ:
                del os.environ["TEST_FR_KEY"]


class DotenvLoaderTests(unittest.TestCase):

    def test_common_loads_dotenv(self):
        from common import _load_dotenv
        self.assertTrue(callable(_load_dotenv))

    def test_dotenv_sets_vars(self):
        saved = os.environ.get("FR_TEST_DUMMY")
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
                f.write("FR_TEST_DUMMY=hello_world\n")
                f.write("# comment line\n")
                f.write("FR_ANOTHER=123\n")
                tmp = f.name
            from common import _load_dotenv
            _load_dotenv(Path(tmp))
            self.assertEqual(os.environ.get("FR_TEST_DUMMY"), "hello_world")
            self.assertEqual(os.environ.get("FR_ANOTHER"), "123")
        finally:
            if saved is not None:
                os.environ["FR_TEST_DUMMY"] = saved
            elif "FR_TEST_DUMMY" in os.environ:
                del os.environ["FR_TEST_DUMMY"]
            if "FR_ANOTHER" in os.environ:
                del os.environ["FR_ANOTHER"]
            import tempfile
            Path(tmp).unlink(missing_ok=True)

    def test_dotenv_no_overwrite_existing(self):
        saved = os.environ.get("FR_BASE_URL")
        try:
            os.environ["FR_BASE_URL"] = "existing_value"
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
                f.write("FR_BASE_URL=should_not_overwrite\n")
                tmp = f.name
            from common import _load_dotenv
            _load_dotenv(Path(tmp))
            self.assertEqual(os.environ["FR_BASE_URL"], "existing_value",
                             "Should not overwrite existing env var")
        finally:
            if saved is not None:
                os.environ["FR_BASE_URL"] = saved
            elif "FR_BASE_URL" in os.environ:
                del os.environ["FR_BASE_URL"]
            Path(tmp).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
