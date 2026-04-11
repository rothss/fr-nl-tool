from __future__ import annotations

import argparse
import json
from pathlib import Path

from adapters.openclaw_contract import to_openclaw_result
from common import (
    default_catalog_db,
    default_mirror_root,
    default_profile_db,
    references_dir,
)
from data.catalog import find_report_candidates, load_catalog
from data.extractor_registry import extract_rows_for_report, get_analysis_engine
from data.schemas import probe_local_file_against_intent
from data.source_loader import acquire_source, should_block_on_preflight
from parse_query_intent import parse_query
from planning.planner import build_query_plan as build_schema_aware_plan
from planning.router import route_report_family
from query_opm_nl import run_query as execute_query
from render.answer_renderer import render_answer_text


def ensure_user_scope(path: Path) -> Path:
    """确保 user_scope.yaml 存在，如果不存在则创建默认文件。"""
    if path.exists():
        return path
    # 创建目录
    path.parent.mkdir(parents=True, exist_ok=True)
    # 复制示例文件内容
    example_path = references_dir() / "user_scope.example.yaml"
    default_content = (
        example_path.read_text(encoding="utf-8")
        if example_path.exists()
        else "default_user: default\nusers:\n  default:\n    包干航线:\n      航段: []\n      航班号: []\n"
    )
    path.write_text(default_content, encoding="utf-8")
    return path


def build_plan(intent: dict, query_result: dict) -> dict:
    top = query_result.get("top_candidate") or {}
    local_probe = (
        probe_local_file_against_intent(
            top.get("file_path"), top.get("report_name"), intent
        )
        if top
        else None
    )
    plan = build_schema_aware_plan(intent, local_probe=local_probe)
    plan["report_name"] = top.get("report_name") or plan.get("report_name")
    plan["report_path"] = top.get("file_path") or plan.get("report_path")
    if (
        query_result.get("used_live_refresh")
        and "used_live_refresh" not in plan["rationale"]
    ):
        plan["rationale"].append("used_live_refresh")
    if (
        query_result.get("freshness_force_live")
        and "freshness_force_live" not in plan["rationale"]
    ):
        plan["rationale"].append("freshness_force_live")
    if query_result.get("live_refresh_error"):
        plan["fallback_plans"] = list(plan.get("fallback_plans") or []) + [
            {"type": "retry_live_refresh"}
        ]
    if not plan.get("report_name"):
        plan["fallback_plans"] = list(plan.get("fallback_plans") or []) + [
            {"type": "refine_query"}
        ]
    return plan


def build_source_meta(query_result: dict) -> dict | None:
    top = query_result.get("top_candidate") or {}
    plan = query_result.get("plan") or {}
    source_path = (
        query_result.get("source_path")
        or top.get("file_path")
        or plan.get("report_path")
    )
    if not top and not query_result.get("live_refresh_error") and not source_path:
        return None
    acquire_payload = dict(query_result)
    if source_path:
        top_with_source = dict(top)
        top_with_source["file_path"] = source_path
        acquire_payload["top_candidate"] = top_with_source
    return acquire_source(plan, query_result.get("intent") or {}, acquire_payload)


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
        "analysis_engine": build_plan(
            query_result.get("intent") or {}, query_result
        ).get("analysis_engine"),
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
        query_result["message"] = (
            f"实时刷新失败: {query_result.get('live_refresh_error')}"
        )
        return query_result

    blocked, reason, message = should_block_on_preflight(plan, source_meta)
    if blocked:
        query_result["reason"] = reason
        query_result["message"] = message
        return query_result

    return query_result


def resolve_top_candidate(intent: dict, db_path: Path) -> dict | None:
    catalog = load_catalog(db_path)
    routed = route_report_family(intent)
    preferred_names = [
        str(item.get("report_name") or "").strip()
        for item in routed
        if str(item.get("report_name") or "").strip()
    ]
    seen_names: set[str] = set()
    for report_name in preferred_names:
        if report_name in seen_names:
            continue
        seen_names.add(report_name)
        candidates = find_report_candidates(
            intent, catalog, preferred_report_name=report_name, top_n=3
        )
        if candidates:
            return candidates[0]
    candidates = find_report_candidates(intent, catalog, top_n=3)
    return candidates[0] if candidates else None


def build_initial_plan(
    intent: dict, top_candidate: dict | None
) -> tuple[dict, dict | None]:
    local_probe = None
    if top_candidate:
        local_probe = probe_local_file_against_intent(
            top_candidate.get("file_path"),
            top_candidate.get("report_name"),
            intent,
        )
    plan = build_schema_aware_plan(intent, local_probe=local_probe)
    if top_candidate:
        plan["report_name"] = top_candidate.get("report_name") or plan.get(
            "report_name"
        )
        plan["report_path"] = top_candidate.get("file_path") or plan.get("report_path")
        plan["candidate_score"] = top_candidate.get(
            "score", plan.get("candidate_score")
        )
    return plan, local_probe


def try_local_pipeline(intent: dict, plan: dict, source_meta: dict) -> dict | None:
    if not source_meta.get("ok"):
        return None
    if plan.get("require_live_refresh"):
        if not source_meta.get("refreshed"):
            return None
    report_name = str(plan.get("report_name") or "")
    analysis_mode = str(
        ((intent.get("structured_intent") or {}).get("analysis") or {}).get("mode")
        or (intent.get("filters") or {}).get("analysis_mode")
        or ""
    )
    filters = intent.get("filters") or {}
    if (
        report_name == "航空集团前十后十航班"
        and bool(filters.get("first_flight"))
        and str(filters.get("rank_scope") or "") == "后十"
    ):
        analysis_mode = "first_flight_bottom10"
    elif (
        report_name == "航空集团前十后十航班"
        and str(filters.get("extreme") or "") == "best"
        and str(intent.get("metric") or "") in {"小时边际贡献", "总边贡"}
    ):
        analysis_mode = "top_metric_flight"
    analyzer = get_analysis_engine(report_name, analysis_mode=analysis_mode)
    if analyzer is None:
        return None
    file_path = str(source_meta.get("file_path") or "").strip()
    if not file_path:
        return None
    extracted = extract_rows_for_report(report_name, file_path)
    if report_name == "航空集团前十后十航班" and analysis_mode == "top_metric_flight":
        analysis_result = analyzer(intent, source_meta)
    else:
        analysis_result = analyzer(intent, extracted, source_meta)
    payload = {
        "ok": bool(analysis_result.get("ok")),
        "intent": intent,
        "plan": plan,
        "source_meta": source_meta,
        "analysis_result": analysis_result,
        "extracted": extracted,
    }
    answer_text = render_answer_text(payload)
    return {
        "ok": bool(analysis_result.get("ok")),
        "intent": intent,
        "plan": plan,
        "source_meta": source_meta,
        "analysis_result": analysis_result,
        "extracted": extracted,
        "answer_text": answer_text,
    }


def wrap_legacy_result(intent: dict, query_result: dict) -> dict:
    query_result["intent"] = query_result.get("intent") or intent
    query_result["plan"] = build_plan(query_result["intent"], query_result)
    query_result["source_meta"] = build_source_meta(query_result)
    query_result = apply_plan_aware_postprocess(query_result)
    query_result["analysis_result"] = build_analysis_result(query_result)
    return to_openclaw_result(query_result)


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
    user_scope = ensure_user_scope(
        user_scope_path or (default_mirror_root() / "search_index" / "user_scope.yaml")
    )
    profile = profile_db or default_profile_db()

    intent = parse_query(query)
    top_candidate = resolve_top_candidate(intent, db)
    if top_candidate is None:
        return to_openclaw_result(
            {
                "ok": False,
                "reason": "no_report_match",
                "intent": intent,
                "plan": build_schema_aware_plan(intent),
                "source_meta": None,
                "analysis_result": None,
            }
        )

    plan, _local_probe = build_initial_plan(intent, top_candidate)
    source_meta = acquire_source(
        plan,
        intent,
        {
            "ok": False,
            "used_live_refresh": False,
            "top_candidate": top_candidate,
        },
    )
    blocked, reason, message = should_block_on_preflight(plan, source_meta)
    if blocked and not source_meta.get("refreshed"):
        return to_openclaw_result(
            {
                "ok": False,
                "reason": reason,
                "message": message,
                "intent": intent,
                "plan": plan,
                "source_meta": source_meta,
                "analysis_result": None,
            }
        )

    local_payload = try_local_pipeline(intent, plan, source_meta)
    if local_payload is not None:
        return to_openclaw_result(local_payload)

    query_result = execute_query(
        query=query,
        user=user,
        mirror_root=mirror,
        db_path=db,
        user_scope_path=user_scope,
        excel_index_db=excel_index_db,
        profile_db=profile,
    )
    return wrap_legacy_result(intent, query_result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Structured OpenClaw entrypoint for OPM NL query."
    )
    parser.add_argument("query", help="Natural-language query")
    parser.add_argument("--user", help="User id for owner scope resolution")
    parser.add_argument("--mirror-root", default=str(default_mirror_root()))
    parser.add_argument("--db", default=str(default_catalog_db()))
    parser.add_argument("--excel-index", help="Path to excel_index.db (optional)")
    parser.add_argument("--profile-db", help="Path to report_profiles.db (optional)")
    parser.add_argument(
        "--user-scope",
        default=str(default_mirror_root() / "search_index" / "user_scope.yaml"),
    )
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
            print(
                result.get("message")
                or json.dumps(result, ensure_ascii=False, indent=2)
            )
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
