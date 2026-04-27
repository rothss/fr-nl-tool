from __future__ import annotations

import json
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import base_url

from .auth import build_session, extract_auth
from .exporter import _get, _post, make_opener

_BASE_URL = base_url()
EXCLUDED_DIRS = {"test", "tmp", "回收站", "模板", "demo", "__pycache__"}
MANIFEST_VERSION = "3"


def _warmup(opener, base_url: str) -> None:
    try:
        _get(opener, base_url, referer=base_url)
    except Exception:
        pass


def fetch_tree(opener, base_url: str, auth_token: str = "") -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/v10/view/entry/tree?_=py_batch_" + str(int(time.time()))
    headers = {
        "Accept": "application/json",
        "User-Agent": "opm-nl-report-query/1.0",
        "Referer": base_url,
        "X-Requested-With": "XMLHttpRequest",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = __import__('urllib.request').Request(url, headers=headers)
    with opener.open(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    if isinstance(data, dict):
        if "errorCode" in data and data["errorCode"]:
            raise RuntimeError(f"Tree API error: {data.get('errorCode')} {data.get('errorMsg','')}")
        if "data" in data:
            nodes = data["data"] if isinstance(data["data"], list) else []
            return [n for n in nodes if n is not None]
    if isinstance(data, list):
        return data
    return []


def _flatten_tree(nodes: list[dict], path_parts: tuple[str, ...] = ()) -> list[dict]:
    entries: list[dict] = []
    for node in nodes:
        name = str(node.get("name") or node.get("title") or "").strip()
        node_type = str(node.get("type") or node.get("nodeType") or "").lower()
        child_path = path_parts + (name,) if name else path_parts

        if name.lower() in EXCLUDED_DIRS:
            continue

        children = node.get("children") or []
        has_children = isinstance(children, list) and len(children) > 0
        has_path = bool(node.get("path") or node.get("cptPath") or node.get("reportPath"))

        if node_type in ("folder", "dir") and has_children:
            entries.extend(_flatten_tree(children, child_path))
        elif has_path:
            entries.append({
                "directoryNames": list(child_path) if child_path else [name or "root"],
                "directoryPath": "/".join(child_path) if child_path else "/",
                "name": name,
                "path": node.get("path") or node.get("cptPath") or node.get("reportPath") or "",
                "id": node.get("id") or "",
                "type": node_type or "report",
            })
            if has_children:
                entries.extend(_flatten_tree(children, child_path))
        elif has_children:
            entries.extend(_flatten_tree(children, child_path))

    return entries


def build_manifest(
    base_url: str | None = None,
    output_path: Path | None = None,
    auth: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = base_url or _BASE_URL
    if auth is None:
        auth = extract_auth()
        if "error" in auth:
            return {"ok": False, "error": auth["error"]}

    session_info = build_session(auth, url)
    host = session_info["host"]
    opener = make_opener(session_info["cookies"], host)
    _warmup(opener, url)

    try:
        tree = fetch_tree(opener, url, auth_token=session_info.get("token", ""))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, RuntimeError) as e:
        return {"ok": False, "error": str(e)}

    entries = _flatten_tree(tree)

    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": url,
        "totalDirectories": len(entries),
        "totalReports": sum(1 for e in entries if e.get("path")),
        "entries": entries,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "manifest": manifest}
