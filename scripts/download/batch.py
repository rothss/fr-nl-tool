from __future__ import annotations

import json
import os
import random
import signal
import sys
import time
import traceback
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
_CHECKPOINT_INTERVAL = 10
_PERMANENT_ERRORS = {"auth", "fs"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": "3", "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(manifest: dict, path: Path) -> None:
    """原子写入：先写 .tmp 再替换，防止中断导致清单损坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _should_skip(entry: dict, overwrite: str, resume: bool) -> bool:
    if overwrite == "always":
        return False
    if resume and entry.get("status") == "downloaded":
        return True
    if entry.get("status") not in ("pending", "failed", "partial"):
        if overwrite == "never":
            return True
    return False


def _is_permanent_error(error_type: str) -> bool:
    return error_type in _PERMANENT_ERRORS


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
    max_retry: int = 3,
    base_url: str = _BASE_URL,
    extype: str = "simple",
    resume: bool = False,
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

    if folder_filter:
        entries = [e for e in entries
                   if e.get("directoryNames") and e["directoryNames"][0] == folder_filter]

    stats = {"total": len(entries), "downloaded": 0, "skipped": 0, "failed": 0, "new_files": 0}
    _interrupted = False

    def _flush():
        _write_manifest(manifest, manifest_path)

    # 优雅退出：Ctrl+C 时保存清单
    def _on_signal(signum, frame):
        nonlocal _interrupted
        _interrupted = True
    signal.signal(signal.SIGINT, _on_signal)

    for idx, entry in enumerate(entries, start=1):
        if _interrupted:
            break

        dir_names = entry.get("directoryNames") or []

        if _should_skip(entry, overwrite, resume):
            if not resume or entry.get("status") != "skipped":
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
        _flush()

        success_count = 0
        failures: list[dict] = []
        files: list[str] = []

        for report in reports:
            if _interrupted:
                break
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
                        err_type = "export"
                        if attempt == max_retry:
                            failures.append({"reportId": rid, "reportName": rname,
                                             "error": result["error"], "errorType": err_type})
                        # 瞬时错误 → 退避重试
                        if not _is_permanent_error(err_type) and attempt < max_retry:
                            wait = (2 ** attempt) + random.random()
                            time.sleep(wait)
                except Exception as exc:
                    msg = str(exc)
                    err_type = _resolve_error_type(msg)
                    if _is_permanent_error(err_type):
                        # 永久错误不重试
                        failures.append({"reportId": rid, "reportName": rname,
                                         "error": msg, "errorType": err_type})
                        break
                    if attempt == max_retry:
                        failures.append({"reportId": rid, "reportName": rname,
                                         "error": msg, "errorType": err_type})
                    else:
                        wait = (2 ** attempt) + random.random()
                        time.sleep(wait)

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

        # 每 N 个条目写一次检查点
        if idx % _CHECKPOINT_INTERVAL == 0:
            _flush()

    _flush()
    stats["ok"] = stats["failed"] == 0
    if _interrupted:
        stats["interrupted"] = True
    return stats


def download_folder(
    folder_name: str,
    output_root: Path | None = None,
    overwrite: str = "never",
    extype: str = "simple",
    resume: bool = False,
) -> dict[str, Any]:
    root = output_root or _DEFAULT_OUTPUT
    manifest_path = root / _MANIFEST_NAME
    if not manifest_path.exists():
        return {"ok": False, "error": f"manifest not found: {manifest_path}. Run 'discover' first."}

    try:
        return download_by_manifest(
            manifest_path=manifest_path, output_root=root, overwrite=overwrite,
            folder_filter=folder_name, extype=extype, resume=resume,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()[:2000]}


def download_all(
    output_root: Path | None = None,
    overwrite: str = "never",
    extype: str = "simple",
    resume: bool = False,
) -> dict[str, Any]:
    root = output_root or _DEFAULT_OUTPUT
    manifest_path = root / _MANIFEST_NAME
    if not manifest_path.exists():
        return {"ok": False, "error": f"manifest not found: {manifest_path}. Run 'discover' first."}

    try:
        return download_by_manifest(
            manifest_path=manifest_path, output_root=root, overwrite=overwrite,
            extype=extype, resume=resume,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()[:2000]}
