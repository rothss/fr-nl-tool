from __future__ import annotations

import argparse
import json
from pathlib import Path

from adapters.openclaw_contract import to_openclaw_result
from common import default_catalog_db, default_mirror_root, default_profile_db
from data.schemas import probe_local_file_against_intent
from parse_query_intent import parse_query
from planning.planner import build_query_plan as build_schema_aware_plan
from query_opm_nl import run_query as execute_query


def build_plan(intent: dict, query_result: dict) -> dict:
    top = query_result.get("top_candidate") or {}
    local_probe = probe_local_file_against_intent(top.get("file_path"), top.get("report_name"), intent) if top else None
    plan = build_schema_aware_plan(intent, local_probe=local_probe)
    plan["report_name"] = top.get("report_name") or plan.get("report_name")
    plan["report_path"] = top.get("file_path") or plan.get("report_path")
    if query_result.get("used_live_refresh") and "used_live_refresh" not in plan["rationale"]:
        plan["rationale"].append("used_live_refresh")
    if query_result.get("freshness_force_live") and "freshness_force_live" not in plan["rationale"]:
        plan["rationale"].append("freshness_force_live")
    if query_result.get("live_refresh_error"):
        plan["fallback_plans"] = list(plan.get("fallback_plans") or []) + [{"type": "retry_live_refresh"}]
    if not plan.get("report_name"):
        plan["fallback_plans"] = list(plan.get("fallback_plans") or []) + [{"type": "refine_query"}]
    return plan


def build_source_meta(query_result: dict) -> dict | None:
    top = query_result.get("top_candidate") or {}
    if not top and not query_result.get("live_refresh_error"):
        return None
    probe = probe_local_file_against_intent(
        top.get("file_path"),
        top.get("report_name"),
        query_result.get("intent") or {},
    ) if top else {
        "schema_ok": False,
        "route_match_ok": False,
        "date_match_ok": False,
        "warnings": [],
    }
    return {
        "ok": bool(query_result.get("ok")),
        "source_type": "query_pipeline",
        "file_path": top.get("file_path"),
        "refreshed": bool(query_result.get("used_live_refresh")),
        "refresh_message": None if not query_result.get("live_refresh_error") else str(query_result.get("live_refresh_error")),
        "last_modified": None,
        "schema_ok": bool(probe.get("schema_ok", True)),
        "route_match_ok": bool(probe.get("route_match_ok", True)),
        "date_match_ok": bool(probe.get("date_match_ok", True)),
        "warnings": list(probe.get("warnings") or []) + ([str(query_result.get("live_refresh_error"))] if query_result.get("live_refresh_error") else []),
    }


def build_analysis_result(query_result: dict) -> dict | None:
    if not query_result.get("ok"):
        return None
    top = query_result.get("top_candidate") or {}
    filters = (query_result.get("intent") or {}).get("filters") or {}
    matched_dates = []
    if isinstance(filters.get("flight_date"), list):
        matched_dates = [str(x) for x in filters.get("flight_date") if x]
    elif filters.get("date_end"):
        matched_dates = [str(filters.get("date_end"))]
    matched_route = None
    if filters.get("segment_from") and filters.get("segment_to"):
        matched_route = f"{filters.get('segment_from')}-{filters.get('segment_to')}"
    return {
        "ok": True,
        "analysis_engine": build_plan(query_result.get("intent") or {}, query_result).get("analysis_engine"),
        "matched_route": matched_route,
        "matched_dates": matched_dates,
        "issues": [],
        "advice": [],
        "summary": str(query_result.get("answer_text") or "")[:200] or None,
        "report_name": top.get("report_name"),
        "metric_column": query_result.get("metric_column"),
        "row_count_after_filter": query_result.get("row_count_after_filter"),
    }


def apply_plan_aware_postprocess(query_result: dict) -> dict:
    if query_result.get("ok"):
        return query_result

    plan = query_result.get("plan") or {}
    source_meta = query_result.get("source_meta") or {}

    if query_result.get("live_refresh_error"):
        query_result["reason"] = "live_refresh_failed"
        query_result["message"] = f"实时刷新失败: {query_result.get('live_refresh_error')}"
        return query_result

    if plan.get("report_family") and not source_meta.get("schema_ok", True):
        query_result["reason"] = "report_schema_invalid"
        query_result["message"] = "报表结构不满足当前查询要求。"
        return query_result

    if plan.get("report_family") and not source_meta.get("route_match_ok", True) and not query_result.get("used_live_refresh"):
        query_result["reason"] = "route_not_found_in_report"
        query_result["message"] = "未在当前报表中找到请求航段。"
        return query_result

    if plan.get("report_family") and not source_meta.get("date_match_ok", True) and not query_result.get("used_live_refresh"):
        query_result["reason"] = "date_not_found_in_report"
        query_result["message"] = "未在当前报表中找到请求日期。"
        return query_result

    return query_result


def run_query(
    query: str,
    user: str | None = None,
    mirror_root: Path | None = None,
    db_path: Path | None = None,
    user_scope_path: Path | None = None,
    excel_index_db: Path | None = None,
    profile_db: Path | None = None,
) -> dict:
    mirror = mirror_root or default_mirror_root()
    db = db_path or default_catalog_db()
    user_scope = user_scope_path or Path(r"C:\Users\ZhuanZ\opm_mirror\search_index\user_scope.yaml")
    profile = profile_db or default_profile_db()

    intent = parse_query(query)
    query_result = execute_query(
        query=query,
        user=user,
        mirror_root=mirror,
        db_path=db,
        user_scope_path=user_scope,
        excel_index_db=excel_index_db,
        profile_db=profile,
    )
    query_result["intent"] = query_result.get("intent") or intent
    query_result["plan"] = build_plan(query_result["intent"], query_result)
    query_result["source_meta"] = build_source_meta(query_result)
    query_result = apply_plan_aware_postprocess(query_result)
    query_result["analysis_result"] = build_analysis_result(query_result)
    return to_openclaw_result(query_result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Structured OpenClaw entrypoint for OPM NL query.")
    parser.add_argument("query", help="Natural-language query")
    parser.add_argument("--user", help="User id for owner scope resolution")
    parser.add_argument("--mirror-root", default=str(default_mirror_root()))
    parser.add_argument("--db", default=str(default_catalog_db()))
    parser.add_argument("--excel-index", help="Path to excel_index.db (optional)")
    parser.add_argument("--profile-db", help="Path to report_profiles.db (optional)")
    parser.add_argument("--user-scope", default=r"C:\Users\ZhuanZ\opm_mirror\search_index\user_scope.yaml")
    parser.add_argument("--output-format", choices=("json", "text"), default="json")
    args = parser.parse_args()

    result = run_query(
        query=args.query,
        user=args.user,
        mirror_root=Path(args.mirror_root),
        db_path=Path(args.db),
        user_scope_path=Path(args.user_scope),
        excel_index_db=Path(args.excel_index) if args.excel_index else None,
        profile_db=Path(args.profile_db) if args.profile_db else None,
    )
    if args.output_format == "text":
        if result.get("ok"):
            print(result.get("answer_text") or "")
        else:
            print(result.get("message") or json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
