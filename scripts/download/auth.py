from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from config import base_url, batch_root, cdp_url

_AUTH_SCRIPT_CANDIDATES = [
    batch_root() / "extract_edge_auth.js",
    Path(__file__).resolve().parents[2] / "fr_batch" / "extract_edge_auth.js",
]


def _find_auth_script() -> Path:
    for p in _AUTH_SCRIPT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"extract_edge_auth.js not found. Tried: {_AUTH_SCRIPT_CANDIDATES}"
    )


def extract_auth(cdp_url_val: str = "", base_url_val: str = "",
                 script_path: Path | None = None) -> dict[str, str]:
    cdp = cdp_url_val or cdp_url()
    url = base_url_val or base_url()
    script = script_path or _find_auth_script()

    proc = subprocess.run(
        ["node", str(script)],
        capture_output=True, text=True,
        env={**os.environ, "OPM_EDGE_CDP_URL": cdp, "OPM_BASE_URL": url},
        timeout=30,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or f"exit code {proc.returncode}"}
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"error": "invalid JSON from auth script", "raw": proc.stdout.strip()[:200]}


def build_session(auth: dict[str, str], base_url_val: str = "") -> dict[str, Any]:
    url = base_url_val or base_url()
    token = auth.get("fine_auth_token", "")
    ticket = auth.get("cas_login_ticket", "")
    remember = auth.get("fine_remember_login", "-1")
    host = url.split("://", 1)[1].split("/", 1)[0].split(":")[0]
    return {
        "token": token, "ticket": ticket, "remember": remember, "host": host,
        "cookies": {"fine_auth_token": token, "cas_login_ticket": ticket, "fine_remember_login": remember},
    }
