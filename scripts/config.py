"""Single source of truth for all configuration.

All modules import from here instead of reading os.environ directly.
Env vars are loaded from .env by common.py on first import.
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]


def _env(key: str, *aliases: str, default: str = "") -> str:
    for k in (key, *aliases):
        v = os.environ.get(k, "")
        if v:
            return v
    return default


def base_url() -> str:
    return _env("FR_BASE_URL", "OPM_BASE_URL", default="http://localhost:8080/webroot/decision")


def cdp_url() -> str:
    return _env("FR_CDP_URL", "OPM_EDGE_CDP_URL", default="http://127.0.0.1:9222")


def mirror_root() -> Path:
    v = _env("FR_MIRROR_ROOT", "OPM_MIRROR_ROOT")
    return Path(v) if v else (_PROJECT / "fr_mirror")


def batch_root() -> Path:
    v = _env("FR_BATCH_ROOT", "OPM_BATCH_ROOT")
    return Path(v) if v else (_PROJECT / "fr_batch")


def auth_token() -> str:
    return _env("FR_AUTH_TOKEN", "OPM_FINE_AUTH_TOKEN")


def edge_profile_dir() -> str:
    return _env("FR_EDGE_PROFILE_DIR", "OPM_EDGE_PROFILE_DIR")


def catalog_db() -> Path:
    return mirror_root() / "search_index" / "report_catalog.db"


def profile_db() -> Path:
    return mirror_root() / "search_index" / "report_profiles.db"


def manifest_json() -> Path:
    return mirror_root() / "manifest.json"


def excel_index_db() -> Path:
    return mirror_root() / "search_index" / "excel_index.db"


def login_patterns() -> str:
    return _env("FR_LOGIN_PATTERNS", default="login_required|unauthorized|请先登录")


def intent_llm_command() -> str:
    return _env("FR_INTENT_LLM_COMMAND")
