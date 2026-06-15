from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters.openclaw_contract import to_openclaw_result
from common import (
    default_catalog_db,
    default_manifest_json,
    default_mirror_root,
    default_profile_db,
    references_dir,
)
from data.catalog import find_report_candidates, load_catalog
from data.extractor_registry import extract_rows_for_report, get_analysis_engine
from data.schemas import probe_local_file_against_intent
from data.source_loader import acquire_source, should_block_on_preflight
from download.auth import extract_auth
from download.batch import download_all, download_folder
from download.discover import build_manifest
from parse_query_intent import parse_query
from planning.planner import build_query_plan as build_schema_aware_plan
from planning.router import route_report_family
from query_fr_nl import run_query as execute_query
from render.answer_renderer import render_answer_text
from search.indexer import IndexStats, build_index
from search.searcher import search, search_json


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


def _cmd_query(args: argparse.Namespace) -> None:
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


def _cmd_discover(args: argparse.Namespace) -> None:
    output = Path(args.manifest) if args.manifest else default_manifest_json()
    auth = extract_auth() if not args.skip_auth else None
    if auth and "error" in auth:
        print(json.dumps(auth, ensure_ascii=False, indent=2))
        return
    result = build_manifest(
        base_url=args.base_url,
        output_path=output,
        auth=auth,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _cmd_download(args: argparse.Namespace) -> None:
    output_root = Path(args.output) if args.output else default_mirror_root()

    if args.folder:
        result = download_folder(
            args.folder, output_root=output_root,
            overwrite=args.overwrite, extype=args.extype, resume=args.resume,
        )
    elif args.all:
        result = download_all(
            output_root=output_root,
            overwrite=args.overwrite, extype=args.extype, resume=args.resume,
        )
    else:
        result = {"ok": False, "error": "specify --all or --folder NAME"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _cmd_index(args: argparse.Namespace) -> None:
    root = Path(args.root) if args.root else default_mirror_root()
    db_path = Path(args.db) if args.db else (root / "search_index" / "excel_index.db")
    stats: IndexStats = build_index(
        root=root, db_path=db_path,
        incremental=not args.full,
        drop_numeric=not args.keep_numeric,
    )
    print(json.dumps({
        "ok": True,
        "files_indexed": stats.files_indexed,
        "files_skipped": stats.files_skipped,
        "files_failed": stats.files_failed,
        "sheets_indexed": stats.sheets_indexed,
        "cells_indexed": stats.cells_indexed,
        "db_path": str(db_path),
    }, ensure_ascii=False))


def _cmd_search(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve() if args.root else default_mirror_root().resolve()
    db_path = Path(args.db) if args.db else (root / "search_index" / "excel_index.db")
    hits = search_json(db_path, " ".join(args.keywords), limit=args.limit)
    if not hits:
        print("No matches found.")
        return

    def _rel_path(file_path: str) -> str:
        p = Path(file_path)
        try:
            return str(p.parent.resolve().relative_to(root)).replace("\\", "/")
        except (ValueError, OSError):
            pass
        s = str(p).replace("\\", "/")
        for marker in ("/opm_mirror/", "/fr_mirror/"):
            i = s.find(marker)
            if i >= 0:
                rel = s[i + len(marker):]
                pp = Path(rel).parent
                return str(pp).replace("\\", "/")
        return str(p.parent).replace("\\", "/")

    groups: dict[str, dict] = {}
    for h in hits:
        fp = h["file_path"]
        if fp not in groups:
            name = h.get("file_name") or ""
            groups[fp] = {
                "file_name": name,
                "report_name": Path(name).stem if name else Path(fp).stem,
                "file_path": fp,
                "name_hit": h["hit_type"] == "report",
                "cells": {},
            }
        if h["hit_type"] == "report":
            groups[fp]["name_hit"] = True
        else:
            sheet = h["sheet_name"]
            val = h["cell_value"]
            if sheet not in groups[fp]["cells"]:
                groups[fp]["cells"][sheet] = []
            if val not in groups[fp]["cells"][sheet]:
                groups[fp]["cells"][sheet].append(val)

    for idx, (fp, g) in enumerate(groups.items(), start=1):
        name_tag = " [文件名命中]" if g["name_hit"] else ""
        print(f"[{idx}] {g['report_name']}{name_tag}")
        print(f"路径: {_rel_path(fp)}")
        cell_count = sum(len(v) for v in g["cells"].values())
        print(f"匹配条数: {cell_count}")
        if g["cells"]:
            print("匹配内容:")
            for sheet_name, values in g["cells"].items():
                merged = " | ".join(values)
                print(f"  [{sheet_name}] {merged}")
        print()


def _cmd_verify_export(args: argparse.Namespace) -> None:
    """Handle verify-export command."""
    from e2e.verify_export import run_verify_export_sync

    case_path = Path(args.case)
    if not case_path.exists():
        print(f"Error: case file not found: {args.case}", file=sys.stderr)
        sys.exit(1)

    result = run_verify_export_sync(
        case_path=case_path,
        artifacts_dir=Path(args.artifacts) if args.artifacts else None,
        headless=not args.no_headless,
        timeout_ms=args.timeout,
        download_dir=Path(args.download_dir) if args.download_dir else None,
    )

    if args.output_format == "text":
        print(result.get("text_report", json.dumps(result, ensure_ascii=False, indent=2)))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    sys.exit(0 if result.get("ok") else 1)


def _cmd_e2e_live(args: argparse.Namespace) -> None:
    """Handle e2e-live command: verify-export -> download -> index -> query."""
    from e2e.verify_export import run_verify_export_sync

    case_path = Path(args.case)
    if not case_path.exists():
        print(f"Error: case file not found: {args.case}", file=sys.stderr)
        sys.exit(1)

    artifacts_dir = Path(args.artifacts)

    # Step 1: verify-export
    print("=== Step 1/4: Page-Export Consistency Verification ===")
    verify_result = run_verify_export_sync(
        case_path=case_path,
        artifacts_dir=artifacts_dir / "verify_export",
        headless=not args.no_headless,
        timeout_ms=args.timeout,
    )

    if not verify_result.get("ok"):
        print("E2E BLOCKED: page-export consistency check failed.")
        print(verify_result.get("text_report", ""))
        sys.exit(1)

    print("Page-Export Consistency: PASS")

    # Step 2-4: download -> index -> query
    mirror_root = Path(args.mirror_root) if args.mirror_root else default_mirror_root()

    # Step 2: download
    print("=== Step 2/4: Download Reports ===")
    download_result = download_all(
        output_root=mirror_root,
        overwrite="if_missing",
    )
    print(json.dumps(download_result, ensure_ascii=False, indent=2))

    # Step 3: index
    print("=== Step 3/4: Build Search Index ===")
    db_path = mirror_root / "search_index" / "excel_index.db"
    stats = build_index(
        root=mirror_root,
        db_path=db_path,
        incremental=True,
        drop_numeric=True,
    )
    print(json.dumps({
        "ok": True,
        "files_indexed": stats.files_indexed,
        "files_skipped": stats.files_skipped,
        "files_failed": stats.files_failed,
    }, ensure_ascii=False))

    # Step 4: query assertion
    print("=== Step 4/4: Query Assertion ===")
    case_config = json.loads(case_path.read_text(encoding="utf-8"))
    test_query = case_config.get("expected", {}).get("test_query", "航司净利润同比")
    query_result = run_query(
        query=test_query,
        mirror_root=mirror_root,
        db_path=default_catalog_db(),
        user_scope_path=mirror_root / "search_index" / "user_scope.yaml",
        excel_index_db=db_path,
    )

    result = {
        "ok": query_result.get("ok", False),
        "verify_export_ok": True,
        "steps": ["verify-export: PASS", "download: DONE", "index: DONE", "query: DONE"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if result.get("ok") else 1)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    known_commands = {"query", "discover", "download", "index", "search", "verify-export", "e2e-live"}
    if argv is None:
        import sys
        argv = sys.argv[1:]

    # Backward compatible: bare positional = "query <text>"
    if argv and argv[0] not in known_commands and not argv[0].startswith("-"):
        argv = ["query"] + argv

    parser = argparse.ArgumentParser(description="OPM NL report query & download tool")
    sub = parser.add_subparsers(dest="command")

    p_q = sub.add_parser("query", help="Natural-language KPI query")
    p_q.add_argument("query_text", help="Natural-language query text")
    p_q.add_argument("--user")
    p_q.add_argument("--mirror-root", default=str(default_mirror_root()))
    p_q.add_argument("--db", default=str(default_catalog_db()))
    p_q.add_argument("--excel-index")
    p_q.add_argument("--profile-db")
    p_q.add_argument("--user-scope", default=str(default_mirror_root() / "search_index" / "user_scope.yaml"))
    p_q.add_argument("--output-format", choices=("json", "text"), default="json")

    p_d = sub.add_parser("discover", help="Discover all reports from platform")
    p_d.add_argument("--base-url", default=None)
    p_d.add_argument("--manifest", default=str(default_manifest_json()))
    p_d.add_argument("--skip-auth", action="store_true")

    p_dl = sub.add_parser("download", help="Batch download reports")
    p_dl.add_argument("--all", action="store_true")
    p_dl.add_argument("--folder")
    p_dl.add_argument("--output", default=str(default_mirror_root()))
    p_dl.add_argument("--overwrite", choices=("never", "if_missing", "always"), default="never")
    p_dl.add_argument("--extype", choices=("simple", "sheet", "page"), default="simple",
                      help="Export style: simple=原样导出(少Sheet), sheet=分页分Sheet, page=分页")
    p_dl.add_argument("--resume", action="store_true", help="Resume from last successful entry")

    p_i = sub.add_parser("index", help="Build full-text search index")
    p_i.add_argument("--root", default=str(default_mirror_root()))
    p_i.add_argument("--db", default=None)
    p_i.add_argument("--full", action="store_true")
    p_i.add_argument("--keep-numeric", action="store_true")

    p_s = sub.add_parser("search", help="Search any metric across indexed reports")
    p_s.add_argument("--root", default=str(default_mirror_root()))
    p_s.add_argument("--db", default=None)
    p_s.add_argument("--limit", type=int, default=20)
    p_s.add_argument("keywords", nargs="+", help="Search keywords")

    # verify-export command
    p_ve = sub.add_parser("verify-export", help="Verify page data consistency with exported Excel")
    p_ve.add_argument("--case", required=True, help="Path to test case JSON file")
    p_ve.add_argument("--artifacts", default=None, help="Directory for test artifacts")
    p_ve.add_argument("--no-headless", action="store_true", help="Show browser window")
    p_ve.add_argument("--timeout", type=int, default=60000, help="Timeout in ms")
    p_ve.add_argument("--download-dir", default=None, help="Download directory")
    p_ve.add_argument("--output-format", choices=("json", "text"), default="json")

    # e2e-live command: verify-export + download + index + query
    p_e2e = sub.add_parser("e2e-live", help="Full E2E: verify-export -> download -> index -> query -> assertion")
    p_e2e.add_argument("--case", required=True, help="Path to test case JSON file")
    p_e2e.add_argument("--mirror-root", default=None, help="Mirror root for download/index")
    p_e2e.add_argument("--auth-state", default=None, help="Path to auth state file")
    p_e2e.add_argument("--artifacts", default="test-results/e2e", help="Directory for artifacts")
    p_e2e.add_argument("--no-headless", action="store_true")
    p_e2e.add_argument("--timeout", type=int, default=60000)

    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()

    if args.command == "query":
        run_result = run_query(
            query=args.query_text,
            user=args.user,
            mirror_root=Path(args.mirror_root),
            db_path=Path(args.db),
            user_scope_path=Path(args.user_scope),
            excel_index_db=Path(args.excel_index) if args.excel_index else None,
            profile_db=Path(args.profile_db) if args.profile_db else None,
        )
        if args.output_format == "text":
            print(run_result.get("answer_text") or run_result.get("message") or "")
            return
        print(json.dumps(run_result, ensure_ascii=False, indent=2))

    elif args.command == "discover":
        _cmd_discover(args)

    elif args.command == "download":
        _cmd_download(args)

    elif args.command == "index":
        _cmd_index(args)

    elif args.command == "search":
        _cmd_search(args)

    elif args.command == "verify-export":
        _cmd_verify_export(args)

    elif args.command == "e2e-live":
        _cmd_e2e_live(args)

    else:
        parser = argparse.ArgumentParser()
        parser.print_help()


if __name__ == "__main__":
    main()
