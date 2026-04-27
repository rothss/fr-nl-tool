"""Tests for download/auth.py — CDP authentication extraction."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class AuthTests(unittest.TestCase):

    def test_build_session_structure(self):
        from download.auth import build_session
        auth = {
            "fine_auth_token": "tok123",
            "cas_login_ticket": "ticket456",
            "fine_remember_login": "1",
        }
        result = build_session(auth, "https://example.com/decision")
        self.assertEqual(result["token"], "tok123")
        self.assertEqual(result["ticket"], "ticket456")
        self.assertEqual(result["remember"], "1")
        self.assertEqual(result["host"], "example.com")
        self.assertIn("cookies", result)
        self.assertEqual(result["cookies"]["fine_auth_token"], "tok123")

    def test_build_session_default_remember(self):
        from download.auth import build_session
        auth = {"fine_auth_token": "x", "cas_login_ticket": "y"}
        result = build_session(auth)
        self.assertEqual(result["remember"], "-1")

    def test_extract_auth_parses_valid_json(self):
        from download.auth import extract_auth
        valid_output = json.dumps({
            "fine_auth_token": "abc", "cas_login_ticket": "def",
            "fine_remember_login": "-1", "cookieCount": 4,
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.strip.return_value = valid_output
        mock_proc.stderr.strip.return_value = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = extract_auth()
            self.assertNotIn("error", result)
            self.assertEqual(result["fine_auth_token"], "abc")

    def test_extract_auth_handles_error(self):
        from download.auth import extract_auth
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr.strip.return_value = "connection refused"

        with patch("subprocess.run", return_value=mock_proc):
            result = extract_auth()
            self.assertIn("error", result)

    def test_extract_auth_handles_invalid_json(self):
        from download.auth import extract_auth
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.strip.return_value = "not json"
        mock_proc.stderr.strip.return_value = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = extract_auth()
            self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
