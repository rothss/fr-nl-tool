from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, rely on system env vars


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def references_dir() -> Path:
    return skill_root() / "references"


def default_mirror_root() -> Path:
    env_root = os.environ.get("FR_MIRROR_ROOT", "")
    if env_root:
        return Path(env_root)
    # Fallback for backward compatibility
    return Path(os.environ.get("OPM_MIRROR_ROOT", "./fr_mirror"))


def default_catalog_db() -> Path:
    return default_mirror_root() / "search_index" / "report_catalog.db"


def default_profile_db() -> Path:
    return default_mirror_root() / "search_index" / "report_profiles.db"


def default_manifest_json() -> Path:
    return default_mirror_root() / "manifest.json"


def is_stale_file(path: Path | None, max_age_seconds: int = 3600) -> bool:
    p = path if isinstance(path, Path) else None
    if not p or not p.exists():
        return True
    try:
        age = time.time() - p.stat().st_mtime
        return age > max_age_seconds
    except Exception:
        return True


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    p = path or default_manifest_json()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_report_cpt_path(report_name: str, file_path: str | None = None, manifest_path: Path | None = None) -> str | None:
    manifest = load_manifest(manifest_path)
    entries = manifest.get("entries") or []
    target_name = str(report_name or "").strip()
    target_file = str(file_path or "").strip().lower()
    for e in entries:
        reports = e.get("reports") or []
        directory_path = str(e.get("directoryPath") or "").strip().lower()
        if target_file and directory_path and target_file.startswith(directory_path):
            for r in reports:
                if str(r.get("name") or "").strip() == target_name:
                    p = str(r.get("path") or "").strip()
                    if p:
                        return p
    for e in entries:
        reports = e.get("reports") or []
        for r in reports:
            if str(r.get("name") or "").strip() == target_name:
                p = str(r.get("path") or "").strip()
                if p:
                    return p
    return None


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data or {}
    except Exception:
        # Minimal fallback parser for "key: [a,b]" style configs.
        data: dict[str, Any] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip().strip("'").strip('"')
        return data
