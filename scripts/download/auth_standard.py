"""
Standard (non-CAS) FineReport login via Playwright automation.

Used for platforms like demo.finereport.com that use encrypted form login
(SM4) instead of CAS redirect. No CDP browser needed — Playwright launches
its own Chromium instance.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from config import base_url as _default_base

_LOGIN_SCRIPT = Path(__file__).resolve().parent / "_login_standard.mjs"


def login_standard(username: str = "demo", password: str = "demo",
                   base_url: str = "") -> dict[str, str]:
    """Log into FineReport and return auth cookies via Playwright automation.

    Returns dict with fine_auth_token, JSESSIONID, and other cookies.
    On failure returns {"error": "..."}.
    """
    url = base_url or _default_base()
    script = _LOGIN_SCRIPT
    if not script.exists():
        return {"error": f"login script not found: {script}"}

    proc = subprocess.run(
        ["node", str(script), url, username, password],
        capture_output=True, text=True, timeout=60,
        env=os.environ,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or f"exit {proc.returncode}"}
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"error": "invalid JSON", "raw": proc.stdout.strip()[:200]}
