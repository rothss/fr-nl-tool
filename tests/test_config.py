"""Tests for configuration and environment setup."""

import os
import sys
import unittest
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class ConfigTests(unittest.TestCase):
    """Test configuration loading and environment setup."""

    def test_common_module_imports(self):
        """Test that common.py can be imported."""
        try:
            from common import default_mirror_root, references_dir, skill_root

            self.assertTrue(callable(skill_root))
            self.assertTrue(callable(references_dir))
            self.assertTrue(callable(default_mirror_root))
        except ImportError as e:
            self.fail(f"Failed to import common module: {e}")

    def test_default_mirror_root_uses_env(self):
        """Test that default_mirror_root uses FR_MIRROR_ROOT env var."""
        from common import default_mirror_root

        # Save original value
        original = os.environ.get("FR_MIRROR_ROOT")

        try:
            # Test with custom value - use Path for cross-platform comparison
            test_path = "/custom/path"
            os.environ["FR_MIRROR_ROOT"] = test_path
            result = default_mirror_root()
            # Use Path comparison to handle Windows vs Unix path separators
            self.assertEqual(Path(result), Path(test_path))

            # Test fallback to OPM_MIRROR_ROOT
            del os.environ["FR_MIRROR_ROOT"]
            fallback_path = "/fallback/path"
            os.environ["OPM_MIRROR_ROOT"] = fallback_path
            result = default_mirror_root()
            self.assertEqual(Path(result), Path(fallback_path))
        finally:
            # Restore original
            if original is not None:
                os.environ["FR_MIRROR_ROOT"] = original
            elif "FR_MIRROR_ROOT" in os.environ:
                del os.environ["FR_MIRROR_ROOT"]
            if "OPM_MIRROR_ROOT" in os.environ:
                del os.environ["OPM_MIRROR_ROOT"]

    def test_references_dir_structure(self):
        """Test that references directory has required files."""
        from common import references_dir

        ref_dir = references_dir()
        self.assertTrue(ref_dir.exists(), f"References directory not found: {ref_dir}")

        # Check for required files
        required_files = [
            "user_scope.example.yaml",
            "synonyms.yaml",
            "report_schemas.yaml",
            "component_url_registry.yaml",
        ]

        for filename in required_files:
            file_path = ref_dir / filename
            self.assertTrue(
                file_path.exists(), f"Required reference file missing: {filename}"
            )

    def test_env_example_exists(self):
        """Test that .env.example file exists."""
        root = Path(__file__).resolve().parents[1]
        env_example = root / ".env.example"
        self.assertTrue(env_example.exists(), ".env.example file not found")

        # Check content has required variables
        content = env_example.read_text(encoding="utf-8")
        required_vars = ["FR_", "FR_MIRROR_ROOT", "FR_BASE_URL"]
        for var in required_vars:
            self.assertIn(var, content, f"Environment variable {var} not documented")

    def test_user_scope_example_is_generic(self):
        """Test that user_scope.example.yaml uses generic demo values."""
        root = Path(__file__).resolve().parents[1]
        example = root / "references" / "user_scope.example.yaml"
        self.assertTrue(example.exists(), "user_scope.example.yaml not found")

        content = example.read_text(encoding="utf-8")
        self.assertIn("default_user: demo_user", content)
        self.assertNotIn("test_user", content)

    def test_gitignore_does_not_ignore_tracked_tests(self):
        """Test that .gitignore no longer excludes the committed tests directory."""
        root = Path(__file__).resolve().parents[1]
        gitignore = root / ".gitignore"
        self.assertTrue(gitignore.exists(), ".gitignore not found")

        content = gitignore.read_text(encoding="utf-8")
        self.assertNotIn("tests/", content)


class Phase2FeaturesTests(unittest.TestCase):
    """Test Phase 2 configuration features."""

    def test_component_url_registry_relative_path(self):
        """Test that component_url_registry uses relative paths."""
        import yaml
        from common import references_dir

        registry_path = references_dir() / "component_url_registry.yaml"
        self.assertTrue(registry_path.exists())

        with open(registry_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Check that viewlet paths don't start with /doc/
        for component in data.get("components", []):
            viewlet = component.get("viewlet", "")
            self.assertFalse(
                viewlet.startswith("/doc/"),
                f"Viewlet path should not start with /doc/: {viewlet}",
            )

    def test_runner_ensure_user_scope(self):
        """Test that runner module has ensure_user_scope function."""
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl not available (Windows Store Python issue)")

        try:
            from runner import ensure_user_scope

            self.assertTrue(callable(ensure_user_scope))
        except ImportError as e:
            if "openpyxl" in str(e):
                self.skipTest("openpyxl import failed (environment issue)")
            self.fail(f"Failed to import ensure_user_scope: {e}")


if __name__ == "__main__":
    unittest.main()
