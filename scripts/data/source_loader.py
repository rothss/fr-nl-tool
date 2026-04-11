from __future__ import annotations

import os
from pathlib import Path

from common import find_report_cpt_path

from data.schemas import probe_local_file_against_intent
from query_fr_nl import (
    run_fast_future_kzl_export,
    run_fast_single_margin_export,
    run_generic_live_export,
)


def _source_from_probe(
    file_path: str | None,
    report_name: str | None,
    probe: dict,
    refreshed: bool = False,
    refresh_message: str | None = None,
) -> dict:
    source_type = (
        "live_refresh"
        if refreshed
        else ("local_file" if probe.get("file_exists") else "query_pipeline")
    )
    return {
        "ok": bool(probe.get("file_exists")),
        "source_type": source_type,
        "file_path": file_path,
        "report_name": report_name,
        "refreshed": refreshed,
        "refresh_message": refresh_message,
        "last_modified": None,
        "schema_ok": bool(probe.get("schema_ok", True)),
        "route_match_ok": bool(probe.get("route_match_ok", True)),
        "date_match_ok": bool(probe.get("date_match_ok", True)),
        "warnings": list(probe.get("warnings") or [])
        + ([refresh_message] if refresh_message else []),
        "probe": probe,
    }


def _attempt_structured_refresh(
    plan: dict, intent: dict, file_path: str | None, report_name: str | None
) -> tuple[bool, str | None, str | None]:
    fp = str(file_path or "").strip()
    rn = str(report_name or "").strip()
    if not fp or not rn:
        return False, None, "missing_source_target"
    if rn == "未来航班客座率票价分析":
        ok, msg = run_fast_future_kzl_export(intent, output_file=fp)
        return ok, fp, None if ok else msg
    if rn == "单机边际贡献":
        ok, msg = run_fast_single_margin_export(fp)
        return ok, fp, None if ok else msg
    if rn == "航空集团前十后十航班":
        report_cpt = (
            find_report_cpt_path(rn, fp) or "doc/Fdjt/市场监督/航空集团前十后十航线.cpt"
        )
        ok, msg = run_generic_live_export(report_cpt, fp, intent)
        return ok, fp, None if ok else msg
    if rn in {"航空集团经营提升分析", "航空集团收入利润概览（调整后）"}:
        report_cpt = find_report_cpt_path(rn, fp)
        if not report_cpt:
            return False, None, "missing_report_cpt_path"
        out = fp
        ok, msg = run_generic_live_export(report_cpt, out, intent)
        return ok, out, None if ok else msg
    if (
        plan.get("report_path")
        and os.path.splitext(str(plan.get("report_path") or ""))[1].lower() == ".xlsx"
    ):
        report_cpt = find_report_cpt_path(rn, fp)
        if report_cpt:
            ok, msg = run_generic_live_export(report_cpt, fp, intent)
            return ok, fp, None if ok else msg
    return False, None, "unsupported_structured_refresh"


def acquire_source(plan: dict, intent: dict, query_result: dict) -> dict:
    top = query_result.get("top_candidate") or {}
    file_path = top.get("file_path") or plan.get("report_path")
    report_name = top.get("report_name") or plan.get("report_name")
    probe = (
        probe_local_file_against_intent(file_path, report_name, intent)
        if file_path
        else {
            "file_exists": False,
            "schema_ok": False,
            "route_match_ok": False,
            "date_match_ok": False,
            "warnings": ["file_missing"],
        }
    )
    if query_result.get("used_live_refresh"):
        refresh_message = (
            str(query_result.get("live_refresh_error") or "").strip() or None
        )
        return _source_from_probe(
            file_path,
            report_name,
            probe,
            refreshed=True,
            refresh_message=refresh_message,
        )

    if not plan.get("require_live_refresh"):
        return _source_from_probe(
            file_path, report_name, probe, refreshed=False, refresh_message=None
        )

    ok_refresh, refreshed_path, refresh_err = _attempt_structured_refresh(
        plan, intent, file_path, report_name
    )
    if ok_refresh:
        refreshed_probe = probe_local_file_against_intent(
            refreshed_path, report_name, intent
        )
        return _source_from_probe(
            refreshed_path,
            report_name,
            refreshed_probe,
            refreshed=True,
            refresh_message=None,
        )

    return _source_from_probe(
        file_path, report_name, probe, refreshed=False, refresh_message=refresh_err
    )


def should_block_on_preflight(
    plan: dict, source_meta: dict
) -> tuple[bool, str | None, str | None]:
    if source_meta.get("schema_ok") is False and not source_meta.get("refreshed"):
        return True, "report_schema_invalid", "报表结构不满足当前查询要求。"
    if (
        plan.get("report_family")
        and source_meta.get("route_match_ok") is False
        and not source_meta.get("refreshed")
    ):
        return True, "route_not_found_in_report", "未在当前报表中找到请求航段。"
    if (
        plan.get("report_family")
        and source_meta.get("date_match_ok") is False
        and not source_meta.get("refreshed")
    ):
        return True, "date_not_found_in_report", "未在当前报表中找到请求日期。"
    return False, None, None
