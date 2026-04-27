from __future__ import annotations

import json
import traceback
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import base_url, mirror_root

from .auth import build_session, extract_auth
from .discover import _warmup
from .exporter import export_report, make_opener

_BASE_URL = base_url()
_DEFAULT_OUTPUT = mirror_root()
_MANIFEST_NAME = "manifest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": "3", "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _should_skip(entry: dict, overwrite: str, output_root: Path) -> bool:
    if overwrite == "always":
        return False
    if entry.get("status") not in ("pending", "failed", "partial"):
        if overwrite == "never":
            return True
    return False


def _resolve_error_type(msg: str) -> str:
    m = msg.lower()
    if any(k in m for k in ("<!doctype", "<html", "出错", "incorrect date", "数据集", "配置错误",
                             "export bytes invalid", "row height", "column width")):
        return "export"
    if any(k in m for k in ("401", "403", "login", "token", "auth", "sessionid")):
        return "auth"
    if any(k in m for k in ("timeout", "timed out", "connection", "refused")):
        return "network"
    if any(k in m for k in ("path", "file", "directory", "access to the path")):
        return "fs"
    return "export"


def download_by_manifest(
    manifest_path: Path,
    output_root: Path | None = None,
    overwrite: str = "never",
    folder_filter: str | None = None,
    max_retry: int = 2,
    base_url: str = _BASE_URL,
    extype: str = "simple",
) -> dict[str, Any]:
    root = output_root or _DEFAULT_OUTPUT
    auth = extract_auth()
    if "error" in auth:
        return {"ok": False, "error": auth["error"]}

    session_info = build_session(auth, base_url)
    opener = make_opener(session_info["cookies"], session_info["host"])
    _warmup(opener, base_url)

    manifest = _read_manifest(manifest_path)
    entries = manifest.get("entries") or []
    manifest_path_actual = manifest_path

    if folder_filter:
        entries = [e for e in entries
                   if e.get("directoryNames") and e["directoryNames"][0] == folder_filter]

    stats = {"total": len(entries), "downloaded": 0, "skipped": 0, "failed": 0, "new_files": 0}

    for idx, entry in enumerate(entries, start=1):
        dir_names = entry.get("directoryNames") or []
        dir_label = "/".join(dir_names) if dir_names else str(idx)

        if _should_skip(entry, overwrite, root):
            entry["status"] = "skipped"
            stats["skipped"] += 1
            continue

        dir_path = root / Path(*dir_names) if dir_names else root
        reports = entry.get("reports") or []
        if not reports:
            single = {"id": entry.get("id", ""), "name": entry.get("name", ""),
                      "path": entry.get("path", "")}
            reports = [single] if single["id"] else []

        if not reports:
            entry["status"] = "no_report"
            stats["skipped"] += 1
            continue

        entry["status"] = "downloading"
        entry["lastAttempt"] = _now_iso()
        entry["error"] = None
        entry["errorType"] = None
        _write_manifest(manifest, manifest_path_actual)

        success_count = 0
        failures: list[dict] = []
        files: list[str] = []

        for report in reports:
            rid = report.get("id", "")
            rname = report.get("name", "report")
            target = dir_path / f"{rname}.xlsx"

            if overwrite != "always" and target.exists():
                files.append(str(target))
                success_count += 1
                continue

            for attempt in range(max_retry + 1):
                try:
                    result = export_report(opener, rid, rname, dir_path, base_url, preferred_extype=extype)
                    if result.get("ok"):
                        files.append(result["path"])
                        success_count += 1
                        break
                    else:
                        if attempt == max_retry:
                            failures.append({"reportId": rid, "reportName": rname,
                                             "error": result["error"], "errorType": "export"})
                except Exception as exc:
                    if attempt == max_retry:
                        msg = str(exc)
                        failures.append({"reportId": rid, "reportName": rname,
                                         "error": msg, "errorType": _resolve_error_type(msg)})

        entry["parentFiles"] = files
        entry["reportFailures"] = failures
        if failures:
            entry["status"] = "partial" if success_count > 0 else "failed"
            entry["error"] = "; ".join(f"{f['reportName']}: {f['error']}" for f in failures[:3])
            entry["errorType"] = failures[0].get("errorType", "export")
            if success_count:
                stats["downloaded"] += 1
            stats["failed"] += 1
        else:
            entry["status"] = "downloaded"
            stats["downloaded"] += 1
        stats["new_files"] += success_count
        entry["updatedAt"] = _now_iso()
        _write_manifest(manifest, manifest_path_actual)

    stats["ok"] = stats["failed"] == 0
    return stats


def download_folder(
    folder_name: str,
    output_root: Path | None = None,
    overwrite: str = "never",
    extype: str = "simple",
) -> dict[str, Any]:
    root = output_root or _DEFAULT_OUTPUT
    manifest_path = root / _MANIFEST_NAME
    if not manifest_path.exists():
        return {"ok": False, "error": f"manifest not found: {manifest_path}. Run 'discover' first."}

    try:
        return download_by_manifest(
            manifest_path=manifest_path,
            output_root=root,
            overwrite=overwrite,
            folder_filter=folder_name,
            extype=extype,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()[:2000]}


def download_all(
    output_root: Path | None = None,
    overwrite: str = "never",
    extype: str = "simple",
) -> dict[str, Any]:
    root = output_root or _DEFAULT_OUTPUT
    manifest_path = root / _MANIFEST_NAME
    if not manifest_path.exists():
        return {"ok": False, "error": f"manifest not found: {manifest_path}. Run 'discover' first."}

    try:
        return download_by_manifest(
            manifest_path=manifest_path,
            output_root=root,
            overwrite=overwrite,
            extype=extype,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()[:2000]}
