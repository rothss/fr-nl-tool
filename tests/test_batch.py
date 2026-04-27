"""Tests for download/batch.py — batch download orchestration."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class BatchTests(unittest.TestCase):

    def test_should_skip_never(self):
        from download.batch import _should_skip
        entry = {"status": "downloaded"}
        self.assertFalse(_should_skip(entry, "always", False))

    def test_should_skip_pending(self):
        from download.batch import _should_skip
        entry = {"status": "pending"}
        self.assertFalse(_should_skip(entry, "never", False))

    def test_should_skip_failed(self):
        from download.batch import _should_skip
        entry = {"status": "failed"}
        self.assertFalse(_should_skip(entry, "never", False))

    def test_should_skip_downloaded(self):
        from download.batch import _should_skip
        entry = {"status": "downloaded"}
        self.assertTrue(_should_skip(entry, "never", False))

    def test_should_skip_downloaded_resume(self):
        from download.batch import _should_skip
        entry = {"status": "downloaded"}
        self.assertTrue(_should_skip(entry, "never", True))

    def test_resolve_error_type_auth(self):
        from download.batch import _resolve_error_type
        self.assertEqual(_resolve_error_type("401 Unauthorized"), "auth")
        self.assertEqual(_resolve_error_type("login failed"), "auth")
        self.assertEqual(_resolve_error_type("token expired"), "auth")

    def test_resolve_error_type_network(self):
        from download.batch import _resolve_error_type
        self.assertEqual(_resolve_error_type("connection timed out"), "network")
        self.assertEqual(_resolve_error_type("connection refused"), "network")

    def test_resolve_error_type_export(self):
        from download.batch import _resolve_error_type
        self.assertEqual(_resolve_error_type("export bytes invalid"), "export")
        self.assertEqual(_resolve_error_type("<!doctype html>"), "export")
        self.assertEqual(_resolve_error_type("数据集配置错误"), "export")

    def test_resolve_error_type_fs(self):
        from download.batch import _resolve_error_type
        self.assertEqual(_resolve_error_type("access to the path is denied"), "fs")

    def test_read_write_manifest_roundtrip(self):
        from download.batch import _read_manifest, _write_manifest
        manifest = {"version": "3", "entries": [{"status": "pending"}]}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "manifest.json"
            _write_manifest(manifest, p)
            self.assertTrue(p.exists())
            readback = _read_manifest(p)
            self.assertEqual(readback["version"], "3")
            self.assertEqual(len(readback["entries"]), 1)

    def test_read_missing_manifest(self):
        from download.batch import _read_manifest
        result = _read_manifest(Path("/nonexistent/manifest.json"))
        self.assertEqual(result["version"], "3")
        self.assertEqual(result["entries"], [])


if __name__ == "__main__":
    unittest.main()
