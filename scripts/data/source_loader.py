from __future__ import annotations

from pathlib import Path

from data.schemas import probe_local_file_against_intent


def acquire_source(plan: dict, intent: dict, query_result: dict) -> dict:
    top = query_result.get("top_candidate") or {}
    file_path = top.get("file_path") or plan.get("report_path")
    report_name = top.get("report_name") or plan.get("report_name")
    probe = probe_local_file_against_intent(file_path, report_name, intent) if file_path else {
        "file_exists": False,
        "schema_ok": False,
        "route_match_ok": False,
        "date_match_ok": False,
        "warnings": ["file_missing"],
    }

    source_type = "query_pipeline"
    if query_result.get("used_live_refresh"):
        source_type = "live_refresh"
    elif probe.get("file_exists"):
        source_type = "local_file"

    refresh_message = None
    if query_result.get("live_refresh_error"):
        refresh_message = str(query_result.get("live_refresh_error"))

    return {
        "ok": bool(query_result.get("ok")),
        "source_type": source_type,
        "file_path": file_path,
        "report_name": report_name,
        "refreshed": bool(query_result.get("used_live_refresh")),
        "refresh_message": refresh_message,
        "last_modified": None,
        "schema_ok": bool(probe.get("schema_ok", True)),
        "route_match_ok": bool(probe.get("route_match_ok", True)),
        "date_match_ok": bool(probe.get("date_match_ok", True)),
        "warnings": list(probe.get("warnings") or []) + ([refresh_message] if refresh_message else []),
        "probe": probe,
    }


def should_block_on_preflight(plan: dict, source_meta: dict) -> tuple[bool, str | None, str | None]:
    if source_meta.get("schema_ok") is False and not source_meta.get("refreshed"):
        return True, "report_schema_invalid", "报表结构不满足当前查询要求。"
    if plan.get("report_family") and source_meta.get("route_match_ok") is False and not source_meta.get("refreshed"):
        return True, "route_not_found_in_report", "未在当前报表中找到请求航段。"
    if plan.get("report_family") and source_meta.get("date_match_ok") is False and not source_meta.get("refreshed"):
        return True, "date_not_found_in_report", "未在当前报表中找到请求日期。"
    return False, None, None

