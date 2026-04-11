from __future__ import annotations

import argparse
import copy
import json
import hashlib
import os
import re
import sqlite3
import subprocess
import time
import shutil
from pathlib import Path

from analysis.airline_yoy import pick_best_airline_yoy as pick_best_airline_yoy_v2
from analysis.future_flight_competition import render_future_competition_review
from analysis.ranked_flights import (
    analyze_first_flight_bottom10,
    analyze_top_metric_flight,
    render_first_flight_bottom10_answer as render_first_flight_bottom10_answer_v2,
    render_top_metric_flight_answer as render_top_metric_flight_answer_v2,
)
from common import default_catalog_db, default_mirror_root, default_profile_db, find_report_cpt_path, is_stale_file, load_yaml_or_json, references_dir
from data.extractor_registry import get_analysis_renderer
from excel_index_candidates import default_excel_index_db, rank_candidates_from_excel_index
from extract_adjusted_profit_overview import extract_adjusted_profit_overview_rows
from extract_single_margin import extract_single_margin_rows
from extract_structured_table import extract_table
from filter_rows import apply_filters, load_user_scope
from format_answer import render_answer, resolve_metric_column
from parse_query_intent import parse_query
from rank_report_candidates import rank_candidates
from report_profiles import apply_profile_boost, record_profile_hit


def choose_top_candidate(ranked: list[dict], intent: dict) -> dict:
    if not ranked:
        raise ValueError("empty ranked")
    metric = str(intent.get("metric") or "")
    if metric == "单机边际贡献":
        for c in ranked:
            rn = str(c.get("report_name") or "")
            dp = str(c.get("dir_path") or "")
            if rn == "单机边际贡献" and "市场经营指标/主要经营指标" in dp:
                return c
        for c in ranked:
            rn = str(c.get("report_name") or "")
            if rn == "单机边际贡献":
                return c
        fixed = default_mirror_root() / "市场经营指标" / "主要经营指标" / "单机边际贡献.xlsx"
        if fixed.exists():
            return {
                "report_id": -1,
                "report_name": "单机边际贡献",
                "file_path": str(fixed),
                "dir_path": "市场经营指标/主要经营指标",
                "score": 0,
                "score_breakdown": {},
            }
    filters = intent.get("filters") or {}
    raw_query = str(intent.get("raw_query") or "")
    if str(filters.get("report_variant") or "") == "adjusted_profit_overview":
        return {
            "report_id": -3,
            "report_name": "航空集团收入利润概览（调整后）",
            "file_path": str(default_mirror_root() / "航空板块经营报表" / "航空集团收入利润概览（调整后）.xlsx"),
            "dir_path": "航空板块经营报表",
            "score": 0,
            "score_breakdown": {},
        }
    if bool(filters.get("compare_scope") == "airline_yoy") or ("航司" in raw_query and "同比" in raw_query):
        for c in ranked:
            rn = str(c.get("report_name") or "")
            if "航空集团经营提升分析" in rn:
                return c
        fixed = default_mirror_root() / "航空板块经营报表" / "航空集团经营提升分析.xlsx"
        return {
            "report_id": -2,
            "report_name": "航空集团经营提升分析",
            "file_path": str(fixed),
            "dir_path": "航空板块经营报表",
            "score": 0,
            "score_breakdown": {},
        }
    if ("前十后十" in raw_query) or ("后十" in raw_query) or bool(filters.get("rank_scope")):
        want_flight = ("航班" in raw_query) and ("航线" not in raw_query or "前十后十航班" in raw_query)
        for c in ranked:
            rn = str(c.get("report_name") or "")
            if "前十后十" in rn and ((want_flight and "航班" in rn) or ((not want_flight) and "航线" in rn)):
                return c
        for c in ranked:
            rn = str(c.get("report_name") or "")
            if "前十后十" in rn:
                return c
        fixed = default_mirror_root() / "航空板块经营报表" / "航空集团前十后十航班.xlsx"
        if fixed.exists():
            return {
                "report_id": -1,
                "report_name": "航空集团前十后十航班",
                "file_path": str(fixed),
                "dir_path": "航空板块经营报表",
                "score": 0,
                "score_breakdown": {},
            }
    has_route_or_time = bool(filters.get("segment_from") and filters.get("segment_to")) or bool(filters.get("depart_time"))
    if has_route_or_time:
        for c in ranked:
            if "客座率票价分析" in str(c.get("report_name") or ""):
                return c
        # Hard fallback for route/time flight query.
        fixed = default_mirror_root() / "包干航线" / "未来航班客座率票价分析.xlsx"
        if fixed.exists():
            return {
                "report_id": -1,
                "report_name": "未来航班客座率票价分析",
                "file_path": str(fixed),
                "dir_path": "包干航线",
                "score": 0,
                "score_breakdown": {},
            }
    return ranked[0]


def needs_live_refresh(extracted: dict, metric_col: str | None, filtered_count: int | None = None) -> bool:
    rows = extracted.get("rows") or []
    meaningful_row_count = int(extracted.get("meaningful_row_count") or 0)
    if len(rows) == 0 or meaningful_row_count == 0:
        return True
    if filtered_count is not None and filtered_count == 0:
        return True
    if metric_col:
        metric_non_empty = sum(1 for r in rows if str(r.get(metric_col, "")).strip())
        if metric_non_empty == 0:
            return True
    return False


def should_force_live_refresh_by_freshness(top_file: Path | None, db_path: Path | None, excel_index_db: Path | None, max_age_seconds: int = 3600) -> bool:
    if is_stale_file(top_file, max_age_seconds=max_age_seconds):
        return True
    if is_stale_file(db_path, max_age_seconds=max_age_seconds):
        return True
    if excel_index_db and is_stale_file(excel_index_db, max_age_seconds=max_age_seconds):
        return True
    return False


def update_catalog_entry(db_path: Path, file_path: Path) -> None:
    if not db_path.exists() or not file_path.exists():
        return
    try:
        st = file_path.stat()
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE reports SET mtime = ?, size_bytes = ? WHERE file_path = ?",
                (st.st_mtime, st.st_size, str(file_path)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return


def run_incremental_excel_index(mirror_root: Path, excel_db: Path | None) -> tuple[bool, str]:
    if not excel_db:
        return False, "excel_index_db_missing"
    build_index_py = Path(r"C:\Users\ZhuanZ\finereport-search\tools\excel-search-sqlite\scripts\build_index.py")
    if not build_index_py.exists():
        return False, "build_index_py_missing"
    try:
        proc = subprocess.run(
            ["python", str(build_index_py), "--root", str(mirror_root), "--db", str(excel_db), "--incremental"],
            check=False,
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, "excel_index_incremental_timeout"
    stdout = (proc.stdout or b"").decode("utf-8", errors="ignore").strip()
    stderr = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
    if proc.returncode == 0:
        return True, stdout
    return False, (stderr or stdout or "excel_index_incremental_failed")


def persist_refreshed_output(
    refreshed_file: Path | None,
    canonical_file: Path | None,
    mirror_root: Path,
    catalog_db: Path,
    excel_index_db: Path | None,
) -> tuple[bool, str]:
    if not refreshed_file or not refreshed_file.exists():
        return False, "refreshed_file_missing"
    if not canonical_file:
        return False, "canonical_file_missing"
    try:
        canonical_file.parent.mkdir(parents=True, exist_ok=True)
        if refreshed_file.resolve() != canonical_file.resolve():
            shutil.copy2(refreshed_file, canonical_file)
        update_catalog_entry(catalog_db, canonical_file)
        ok_idx, msg_idx = run_incremental_excel_index(mirror_root, excel_index_db)
        if not ok_idx:
            return False, msg_idx
        return True, msg_idx
    except Exception as exc:
        return False, str(exc)


def run_live_refresh(report_name: str, overwrite: str = "always") -> tuple[bool, str]:
    script = Path(__file__).resolve().parent / "export_report_live.ps1"
    try:
        proc = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script), "-ReportName", report_name, "-Overwrite", overwrite],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "live_refresh_timeout"
    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    def _sanitize(text: str) -> str:
        # Strip ANSI escape sequences to keep error payload readable.
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)

    stdout = _sanitize(_decode(stdout_b)).strip()
    stderr = _sanitize(_decode(stderr_b)).strip()
    if proc.returncode == 0:
        return True, stdout
    msg = (stderr or stdout or "").strip()
    return False, msg


def run_fast_future_kzl_export(intent: dict, output_file: str | None = None) -> tuple[bool, str]:
    script = Path(__file__).resolve().parent / "export_future_kzl_live.mjs"
    filters = intent.get("filters") or {}
    base_args = ["node", str(script)]
    if output_file:
        base_args += ["--output-file", output_file]
    dates = filters.get("flight_date") or []
    if dates:
        base_args += ["--date-start", str(dates[0]), "--date-end", str(dates[0])]
    if filters.get("date_start") and filters.get("date_end"):
        base_args += ["--date-start", str(filters.get("date_start")), "--date-end", str(filters.get("date_end"))]
    flight_nos = filters.get("flight_no") or []
    if flight_nos:
        base_args += ["--flight-no", str(flight_nos[0])]
        base_args += ["--comp-code", str(flight_nos[0])[:2]]
    seg_from = filters.get("segment_from")
    seg_to = filters.get("segment_to")
    if seg_from and seg_to:
        base_args += ["--segment-from", str(seg_from), "--segment-to", str(seg_to)]
        base_args += ["--segment-text", f"{seg_from}-{seg_to}"]

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    default_cdp = str(os.environ.get("FR_CDP_URL") or os.environ.get("OPM_EDGE_CDP_URL") or "http://127.0.0.1:9222").strip()
    cdp_candidates: list[str] = []
    for cdp in (default_cdp, "http://127.0.0.1:9222"):
        cdp = str(cdp or "").strip()
        if cdp and cdp not in cdp_candidates:
            cdp_candidates.append(cdp)

    last_error = "fast_future_export_failed"
    for cdp_url in cdp_candidates:
        env = os.environ.copy()
        env["FR_CDP_URL"] = cdp_url
        env["OPM_EDGE_CDP_URL"] = cdp_url  # backward compat
        try:
            proc = subprocess.run(
                base_args,
                check=False,
                capture_output=True,
                timeout=60,
                env=env,
            )
        except subprocess.TimeoutExpired:
            last_error = f"fast_future_export_timeout cdp={cdp_url}"
            continue
        out = _decode(proc.stdout or b"").strip()
        err = _decode(proc.stderr or b"").strip()
        if proc.returncode == 0:
            return True, out
        last_error = (err or out or f"fast_future_export_failed cdp={cdp_url}")
    return False, last_error


def run_fast_single_margin_export(output_file: str) -> tuple[bool, str]:
    script = Path(__file__).resolve().parent / "export_future_kzl_live.mjs"
    args = [
        "node",
        str(script),
        "--report-path",
        "doc/Fdjt/财务报表/单机边际贡献(变动成本新口径).cpt",
        "--output-file",
        output_file,
    ]
    try:
        proc = subprocess.run(
            args,
            check=False,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "fast_single_margin_export_timeout"
    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    out = _decode(stdout_b).strip()
    err = _decode(stderr_b).strip()
    if proc.returncode == 0:
        return True, out
    return False, (err or out)


def run_generic_live_export(report_path: str, output_file: str, intent: dict) -> tuple[bool, str]:
    script = Path(__file__).resolve().parent / "export_report_generic_live.mjs"
    filters = intent.get("filters") or {}
    args = [
        "node",
        str(script),
        "--report-path",
        report_path,
        "--output-file",
        output_file,
        "--filters-json",
        json.dumps(filters, ensure_ascii=False),
    ]
    try:
        proc = subprocess.run(
            args,
            check=False,
            capture_output=True,
            timeout=150,
        )
    except subprocess.TimeoutExpired:
        return False, "generic_live_export_timeout"
    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    out = _decode(stdout_b).strip()
    err = _decode(stderr_b).strip()
    if proc.returncode == 0:
        return True, out
    return False, (err or out)


def run_component_live_export(report_path: str, output_file: str, intent: dict, component_keyword: str) -> tuple[bool, str]:
    script = Path(__file__).resolve().parent / "export_report_component_live.mjs"
    filters = intent.get("filters") or {}
    args = [
        "node",
        str(script),
        "--report-path",
        report_path,
        "--output-file",
        output_file,
        "--component-keyword",
        str(component_keyword or ""),
        "--filters-json",
        json.dumps(filters, ensure_ascii=False),
    ]
    try:
        proc = subprocess.run(
            args,
            check=False,
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, "component_live_export_timeout"
    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    out = _decode(stdout_b).strip()
    err = _decode(stderr_b).strip()
    if proc.returncode == 0:
        return True, out
    return False, (err or out)


def load_component_url_registry() -> list[dict]:
    p = references_dir() / "component_url_registry.yaml"
    data = load_yaml_or_json(p)
    comps = data.get("components") if isinstance(data, dict) else None
    if not isinstance(comps, list):
        return []
    out: list[dict] = []
    for item in comps:
        if isinstance(item, dict):
            out.append(item)
    return out


def _derive_prev_year_date(iso_date: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(iso_date or ""))
    if not m:
        return ""
    y = int(m.group(1)) - 1
    return f"{y:04d}-{m.group(2)}-{m.group(3)}"


def _render_param_template(expr: object, filters: dict) -> str:
    s = str(expr or "").strip()
    m = re.match(r"^\{([a-zA-Z0-9_]+)(?:\|([^}]*))?\}$", s)
    if not m:
        return s
    key = str(m.group(1) or "").strip()
    default = str(m.group(2) or "")
    if key == "date_start_prev_year":
        return _derive_prev_year_date(str(filters.get("date_start") or "")) or default
    if key == "date_end_prev_year":
        return _derive_prev_year_date(str(filters.get("date_end") or "")) or default
    v = filters.get(key)
    if v is None:
        return default
    if isinstance(v, list):
        return str(v[0]) if v else default
    return str(v)


def select_component_binding(report_name: str, metric_hint: str, intent_metric: str, raw_query: str) -> dict | None:
    metric_text = f"{metric_hint} {intent_metric} {raw_query}"
    for b in load_component_url_registry():
        report_match = str(b.get("report_match") or "").strip()
        if report_match and report_match not in report_name:
            continue
        keys = b.get("metric_keywords") or []
        keys = [str(x).strip() for x in keys if str(x).strip()]
        if keys and not any(k in metric_text for k in keys):
            continue
        viewlet = str(b.get("viewlet") or "").strip()
        if not viewlet:
            continue
        return b
    return None


def build_component_url_from_binding(binding: dict, filters: dict) -> str | None:
    viewlet = str(binding.get("viewlet") or "").strip()
    if not viewlet:
        return None
    op = str(binding.get("op") or "form_adaptive").strip() or "form_adaptive"
    param_map = binding.get("parameter_map") or {}
    if not isinstance(param_map, dict):
        param_map = {}
    params: dict[str, str] = {}
    for k, expr in param_map.items():
        key = str(k or "").strip()
        if not key:
            continue
        params[key] = _render_param_template(expr, filters)
    from urllib.parse import quote
    base = os.environ.get("FR_BASE_URL", os.environ.get("OPM_BASE_URL", "http://localhost:8075/webroot/decision"))
    return (
        f"{base}?viewlet={quote(viewlet, safe='')}"
        f"&op={quote(op, safe='')}&__parameters__={quote(json.dumps(params, ensure_ascii=False), safe='')}"
    )


def run_component_url_table_fetch(component_url: str) -> tuple[bool, dict | str]:
    script = Path(__file__).resolve().parent / "fetch_component_table_live.mjs"
    args = ["node", str(script), "--component-url", component_url, "--wait-ms", "5000"]
    try:
        proc = subprocess.run(args, check=False, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "component_url_fetch_timeout"
    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    out = _decode(stdout_b).strip()
    err = _decode(stderr_b).strip()
    if proc.returncode != 0:
        return False, (err or out)
    try:
        payload = json.loads(out or "{}")
    except Exception:
        return False, f"component_url_fetch_json_parse_failed: {(out or '')[:400]}"
    return True, payload


def run_components_export_and_index(report_path: str, mirror_root: Path, limit: int = 0) -> tuple[bool, dict | str]:
    script = Path(__file__).resolve().parent / "export_components_and_index.py"
    args = [
        "python",
        str(script),
        "--report-path",
        report_path,
        "--mirror-root",
        str(mirror_root),
    ]
    if limit and limit > 0:
        args += ["--limit", str(limit)]
    try:
        proc = subprocess.run(args, check=False, capture_output=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return False, "components_export_and_index_timeout"
    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    out = _decode(stdout_b).strip()
    err = _decode(stderr_b).strip()
    if proc.returncode != 0:
        return False, (err or out)
    try:
        payload = json.loads(out or "{}")
    except Exception:
        return False, f"components_export_and_index_json_parse_failed: {(out or '')[:400]}"
    if not bool(payload.get("ok")):
        return False, payload
    return True, payload


def _component_discovery_cache_file(report_path: str, mirror_root: Path) -> Path:
    key = hashlib.md5(report_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return mirror_root / "_components" / "_cache" / f"discover_{key}.json"


def run_discover_components(report_path: str, mirror_root: Path, ttl_seconds: int = 21600) -> tuple[bool, list[dict] | str]:
    cache_file = _component_discovery_cache_file(report_path, mirror_root)
    try:
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age <= ttl_seconds:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                items = data.get("all") or []
                if isinstance(items, list):
                    return True, items
    except Exception:
        pass

    script = Path(__file__).resolve().parent / "discover_components_from_network.mjs"
    args = ["node", str(script), "--report-path", report_path, "--wait-ms", "30000"]
    try:
        proc = subprocess.run(args, check=False, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "discover_components_timeout"
    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""

    def _decode(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    out = _decode(stdout_b).strip()
    err = _decode(stderr_b).strip()
    if proc.returncode != 0:
        return False, (err or out)
    try:
        data = json.loads(out or "{}")
    except Exception:
        return False, f"discover_components_json_parse_failed: {(out or '')[:400]}"
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    items = data.get("all") or []
    if not isinstance(items, list):
        items = []
    return True, items


def select_component_url_from_discovery(items: list[dict], metric_hint: str, intent_metric: str, raw_query: str) -> str | None:
    metric_text = f"{metric_hint} {intent_metric} {raw_query}"
    scored: list[tuple[int, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("type") or "") != "cpt":
            continue
        viewlet = str(it.get("viewlet") or "")
        raw_url = str(it.get("raw_url") or "")
        if not viewlet:
            continue
        name = Path(viewlet).stem
        s = 0
        if metric_hint and metric_hint in name:
            s += 8
        if intent_metric and intent_metric in name:
            s += 6
        for token in ("同比", "排名", "净利润", "边际贡献", "单机", "航司"):
            if token in metric_text and token in name:
                s += 2
        if "__parameters__=" in raw_url:
            s += 3
        if s <= 0:
            continue
        scored.append((s, raw_url if raw_url else ""))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    top_url = scored[0][1]
    return top_url or None


def resolve_metric_with_filters(metric: str | None, columns: list[str], filters: dict) -> str | None:
    col = resolve_metric_column(metric, columns)
    if col:
        return col
    metric_text = str(metric or "").strip()
    if not metric_text:
        return None
    dates = filters.get("flight_date") or []
    if dates:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(dates[0]))
        if m:
            md = f"{int(m.group(2))}月{int(m.group(3))}日"
            for c in columns:
                cs = str(c)
                if metric_text in cs and md in cs:
                    return cs
    return None


def _normalize_route_text(v: object) -> str:
    s = str(v or "").strip()
    s = s.replace("—", "-").replace("–", "-").replace("＝", "=")
    s = re.sub(r"\s+", "", s)
    return s


def _extract_route_pairs(route_text: str) -> list[str]:
    s = _normalize_route_text(route_text)
    if not s:
        return []
    if not re.search(r"[\u4e00-\u9fff]", s):
        return []
    parts = [x for x in re.split(r"[=-]+", s) if x]
    if len(parts) < 2:
        return []
    out: list[str] = []
    for i in range(len(parts) - 1):
        a = parts[i]
        b = parts[i + 1]
        if not re.search(r"[\u4e00-\u9fff]", a) or not re.search(r"[\u4e00-\u9fff]", b):
            continue
        out.append(f"{a}-{b}")
    return out


def render_first_flight_bottom10_answer(rows: list[dict], report_name: str, source_path: str) -> tuple[str, list[str]]:
    analysis_result = analyze_first_flight_bottom10(
        {},
        {"rows": rows},
        {"file_path": source_path, "report_name": report_name},
    )
    text = render_first_flight_bottom10_answer_v2(
        analysis_result,
        {"file_path": source_path, "report_name": report_name},
    )
    return text, list(analysis_result.get("first_flight_routes") or [])


def render_top_metric_flight_answer(source_path: str, report_name: str, metric_hint: str) -> tuple[str, dict | None]:
    analysis_result = analyze_top_metric_flight(
        {"metric": metric_hint},
        {"file_path": source_path, "report_name": report_name},
    )
    text = render_top_metric_flight_answer_v2(
        analysis_result,
        {"metric": metric_hint},
        {"file_path": source_path, "report_name": report_name},
    )
    return text, (analysis_result.get("best_item") if analysis_result.get("ok") else None)


def is_fast_top_metric_flight_query(intent: dict) -> bool:
    filters = intent.get("filters") or {}
    metric = str(intent.get("metric") or "")
    raw_query = str(intent.get("raw_query") or "")
    return (
        metric in {"小时边际贡献", "总边贡"}
        and str(filters.get("extreme") or "") == "best"
        and ("航空集团" in raw_query or str(filters.get("group") or "") == "航空集团")
    )


def run_fast_top_metric_flight_query(intent: dict, mirror_root: Path, profile_db_path: Path, catalog_db: Path, excel_index_db: Path | None) -> dict:
    top = {
        "report_id": -11,
        "report_name": "航空集团前十后十航班",
        "file_path": str(mirror_root / "航空板块经营报表" / "航空集团前十后十航班.xlsx"),
        "dir_path": "航空板块经营报表",
        "score": 0,
        "score_breakdown": {"fast_path": 1.0},
    }
    report_cpt = "doc/Fdjt/市场监督/航空集团前十后十航线.cpt"
    query_hash = hashlib.md5(str(intent.get("raw_query") or "").encode("utf-8")).hexdigest()[:10]
    live_file = Path(top["file_path"]).with_name(f"航空集团前十后十航班_live_{query_hash}.xlsx")
    live_refresh_ok, live_refresh_msg = run_generic_live_export(report_cpt, str(live_file), intent)
    live_refresh_error = None if live_refresh_ok else live_refresh_msg
    writeback_msg = None
    if live_refresh_ok:
        ok_writeback, msg_writeback = persist_refreshed_output(
            live_file,
            Path(top["file_path"]),
            mirror_root=mirror_root,
            catalog_db=catalog_db,
            excel_index_db=excel_index_db,
        )
        if not ok_writeback:
            writeback_msg = msg_writeback
    source_path = str(live_file if live_file.exists() else Path(top["file_path"]))
    answer_text, best_item = render_top_metric_flight_answer(source_path, str(top["report_name"]), str(intent.get("metric") or ""))
    hit_ok = bool(best_item)
    record_profile_hit(
        profile_db_path,
        top,
        intent,
        str(intent.get("metric") or ""),
        success=hit_ok,
        cpt_path=report_cpt,
    )
    if live_refresh_error:
        answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"
    elif writeback_msg:
        answer_text = f"{answer_text}\n本地回写/索引更新失败: {writeback_msg}"
    payload = {
        "ok": True,
        "intent": intent,
        "used_live_refresh": True,
        "top_candidate": top,
        "candidate_count": 1,
        "meaningful_row_count": 1 if best_item else 0,
        "row_count_before_filter": 1 if best_item else 0,
        "row_count_after_filter": 1 if best_item else 0,
        "metric_column": str(intent.get("metric") or ""),
        "live_refresh_ok": live_refresh_ok,
        "live_refresh_error": live_refresh_error,
        "answer_text": answer_text,
    }
    if best_item:
        payload["best_item"] = best_item
    return payload


def lookup_profit_yoy_snapshot(intent: dict) -> dict | None:
    filters = intent.get("filters") or {}
    metric = str(intent.get("metric") or "")
    if metric != "净利润同比" or str(filters.get("extreme") or "") != "worst":
        return None
    start = str(filters.get("date_start") or "")
    end = str(filters.get("date_end") or "")
    if not start or not end:
        return None
    p = references_dir() / "airline_profit_yoy_snapshot.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    key = f"{start}_{end}"
    snap = data.get(key)
    if not isinstance(snap, dict):
        return None
    rows = snap.get("ranking") or []
    if not rows:
        return None
    worst = rows[-1] if isinstance(rows, list) else None
    if not isinstance(worst, dict):
        return None
    return {
        "report_name": str(snap.get("report_name") or "航空集团经营提升分析"),
        "subtable": str(snap.get("subtable") or "净利润"),
        "rank": int(worst.get("rank") or 0),
        "airline": str(worst.get("airline") or ""),
        "yoy": str(worst.get("yoy") or ""),
        "start": start,
        "end": end,
    }


def _to_float(v: object) -> float | None:
    s = str(v or "").strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    try:
        x = float(m.group(0))
    except Exception:
        return None
    if "%" in s or ("同比" in s and abs(x) <= 1.0):
        if abs(x) <= 1.0 and "%" not in s:
            return x * 100.0
        return x
    return x


def pick_best_airline_yoy(rows: list[dict], metric_hint: str, extreme: str) -> dict | None:
    return pick_best_airline_yoy_v2(rows, metric_hint=metric_hint, extreme=extreme)


def choose_candidate_by_local_fit(ranked: list[dict], intent: dict, user_scope_cfg: dict, user: str | None, probe_n: int = 8) -> dict:
    best = ranked[0]
    best_score = -1
    filters = intent.get("filters") or {}
    metric = intent.get("metric")
    for c in ranked[:probe_n]:
        try:
            extracted = extract_table(Path(c["file_path"]))
            cols = extracted.get("columns") or []
            rows = extracted.get("rows") or []
            metric_col = resolve_metric_with_filters(metric, cols, filters)
            filtered = apply_filters(rows, intent, user_scope_cfg=user_scope_cfg, user=user, metric_col=metric_col)
            fit = 0
            if metric_col:
                fit += 100
            if filtered:
                fit += 50
                fit += min(len(filtered), 20)
            if fit > best_score:
                best_score = fit
                best = c
        except Exception:
            continue
    return best


def probe_candidates_for_hit(ranked: list[dict], intent: dict, user_scope_cfg: dict, user: str | None, limit: int = 6) -> dict | None:
    filters = intent.get("filters") or {}
    metric = intent.get("metric")
    started = time.monotonic()
    budget = 15.0
    for c in ranked[: min(limit, 2)]:
        if (time.monotonic() - started) > budget:
            break
        try:
            extracted = extract_table(Path(c["file_path"]))
            cols = extracted.get("columns") or []
            rows = extracted.get("rows") or []
            metric_col = resolve_metric_with_filters(metric, cols, filters)
            filtered = apply_filters(rows, intent, user_scope_cfg=user_scope_cfg, user=user, metric_col=metric_col)
            if metric_col and filtered:
                return c
        except Exception:
            continue

        report_name = str(c.get("report_name") or "")
        if report_name == "未来航班客座率票价分析":
            continue
        report_cpt = find_report_cpt_path(report_name, str(c.get("file_path") or ""))
        if not report_cpt:
            continue
        if (time.monotonic() - started) > budget:
            break
        live_file = Path(str(c["file_path"])).with_name(f"{Path(str(c['file_path'])).stem}_live.xlsx")
        ok, _ = run_generic_live_export(report_cpt, str(live_file), intent)
        if not ok or (not live_file.exists()):
            continue
        try:
            extracted2 = extract_table(live_file)
            cols2 = extracted2.get("columns") or []
            rows2 = extracted2.get("rows") or []
            metric_col2 = resolve_metric_with_filters(metric, cols2, filters)
            filtered2 = apply_filters(rows2, intent, user_scope_cfg=user_scope_cfg, user=user, metric_col=metric_col2)
            if metric_col2 and filtered2:
                return c
        except Exception:
            continue
    return None


def load_candidates_in_dir(db_path: Path, dir_path: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, report_name, file_path, dir_path, size_bytes
            FROM reports
            WHERE dir_path = ?
            LIMIT ?
            """,
            (dir_path, limit),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "report_id": r["id"],
                "report_name": r["report_name"],
                "file_path": r["file_path"],
                "dir_path": r["dir_path"],
                "size_bytes": int(r["size_bytes"] or 0),
                "score": 0.0,
                "score_breakdown": {},
            }
        )
    return out


def merge_ranked_candidates(primary: list[dict], secondary: list[dict], top_n: int) -> list[dict]:
    merged: dict[str, dict] = {}
    for src in (primary, secondary):
        for c in src:
            fp = str(c.get("file_path") or "").strip().lower()
            if not fp:
                continue
            if fp not in merged:
                merged[fp] = dict(c)
                continue
            old = merged[fp]
            old_score = float(old.get("score") or 0.0)
            new_score = float(c.get("score") or 0.0)
            if new_score > old_score:
                merged[fp] = dict(c)
            else:
                sb_old = old.get("score_breakdown") or {}
                sb_new = c.get("score_breakdown") or {}
                if isinstance(sb_old, dict) and isinstance(sb_new, dict):
                    sb_old.update(sb_new)
                    old["score_breakdown"] = sb_old
    ranked = list(merged.values())
    ranked.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return ranked[:top_n]


def run_query(
    query: str,
    user: str | None,
    mirror_root: Path,
    db_path: Path,
    user_scope_path: Path,
    excel_index_db: Path | None = None,
    profile_db: Path | None = None,
) -> dict:
    intent = parse_query(query)
    profile_db_path = profile_db or default_profile_db()
    if is_fast_top_metric_flight_query(intent):
        return run_fast_top_metric_flight_query(intent, mirror_root=mirror_root, profile_db_path=profile_db_path, catalog_db=db_path, excel_index_db=excel_index_db or default_excel_index_db(mirror_root))
    filters = intent.get("filters") or {}
    snapshot_hit = lookup_profit_yoy_snapshot(intent)
    metric = str(intent.get("metric") or "")
    known_metrics = {"客座率", "价格", "余票", "单机边际贡献"}
    top_n = 30 if (filters.get("segment_from") and filters.get("segment_to")) or filters.get("depart_time") or (metric and metric not in known_metrics) or (metric == "单机边际贡献") else 8
    ranked_catalog = rank_candidates(intent, db_path, top_n=top_n)
    excel_db = excel_index_db or default_excel_index_db(mirror_root)
    ranked_excel = rank_candidates_from_excel_index(intent, excel_db, mirror_root, top_n=max(top_n, 30)) if excel_db else []
    ranked = merge_ranked_candidates(ranked_catalog, ranked_excel, top_n=max(top_n, 30))
    ranked = apply_profile_boost(ranked, profile_db_path, intent)
    if not ranked:
        return {"ok": False, "reason": "no_report_match", "intent": intent, "candidates": []}
    user_scope_cfg = load_user_scope(user_scope_path) if user_scope_path.exists() else {}
    if bool((intent.get("filters") or {}).get("compare_scope") == "airline_yoy"):
        if str(filters.get("report_variant") or "") == "adjusted_profit_overview":
            top = {
                "report_id": -3,
                "report_name": "航空集团收入利润概览（调整后）",
                "file_path": str(mirror_root / "航空板块经营报表" / "航空集团收入利润概览（调整后）.xlsx"),
                "dir_path": "航空板块经营报表",
                "score": 0,
                "score_breakdown": {},
            }
        else:
            top = {
                "report_id": -2,
                "report_name": "航空集团经营提升分析",
                "file_path": str(mirror_root / "航空板块经营报表" / "航空集团经营提升分析.xlsx"),
                "dir_path": "航空板块经营报表",
                "score": 0,
                "score_breakdown": {},
            }
    else:
        top = choose_top_candidate(ranked, intent)
    ordered = [top] + [x for x in ranked if x != top]
    if metric and metric not in known_metrics:
        probed = probe_candidates_for_hit(ordered, intent, user_scope_cfg=user_scope_cfg, user=user, limit=6)
        if probed:
            top = probed
    metric = str(intent.get("metric") or "")
    report_cpt = find_report_cpt_path(str(top.get("report_name") or ""), str(top.get("file_path") or ""))
    if (not report_cpt) and ("经营提升分析" in str(top.get("report_name") or "")):
        report_cpt = "doc/Fdjt/marketOperSup/航空集团经营提升分析/航空集团经营提升分析.frm"
    if (not report_cpt) and ("收入利润概览（调整后）" in str(top.get("report_name") or "")):
        report_cpt = "doc/frm/航空集团收入利润报表/航空集团收入利润概览（调整后）.frm"
    query_hash = hashlib.md5(str(intent.get("raw_query") or "").encode("utf-8")).hexdigest()[:10]
    generic_live_file = Path(str(top["file_path"])).with_name(f"{Path(str(top['file_path'])).stem}_live.xlsx")
    future_live_file = Path(str(top["file_path"])).with_name(f"{Path(str(top['file_path'])).stem}_live_{query_hash}.xlsx")
    freshness_force_live = should_force_live_refresh_by_freshness(
        Path(str(top.get("file_path") or "")) if str(top.get("file_path") or "").strip() else None,
        db_path,
        excel_db,
        max_age_seconds=3600,
    )
    if bool(filters.get("compare_scope") == "airline_yoy"):
        used_live_refresh = True
        live_refresh_error = None
        extreme = str(filters.get("extreme") or "best")
        metric_hint = "净利润" if ("净利润" in str(metric or "") or "净利润" in str(intent.get("raw_query") or "")) else "单机边际贡献"
        base_name = Path(str(top.get("file_path") or "")).stem or "航空集团经营提升分析"
        comp_live_file = (mirror_root / "航空板块经营报表" / f"{base_name}_{metric_hint}_component_live.xlsx")
        if report_cpt:
            live_refresh_ok, live_refresh_msg = run_component_live_export(report_cpt, str(comp_live_file), intent, component_keyword=metric_hint)
        else:
            live_refresh_ok, live_refresh_msg = False, "missing_report_cpt_path"
        source_path = comp_live_file
        rows_for_rank: list[dict] = []
        if live_refresh_ok and comp_live_file.exists():
            try:
                if "收入利润概览（调整后）" in str(top.get("report_name") or ""):
                    source_path = comp_live_file
                    rows_for_rank = extract_adjusted_profit_overview_rows(comp_live_file)
                else:
                    rows_for_rank = extract_table(comp_live_file).get("rows") or []
            except Exception:
                rows_for_rank = []
        if (not rows_for_rank) and Path(str(top.get("file_path") or "")).exists():
            try:
                source_path = Path(str(top["file_path"]))
                rows_for_rank = extract_table(source_path).get("rows") or []
            except Exception:
                rows_for_rank = []
        if not live_refresh_ok:
            live_refresh_error = live_refresh_msg
        if not rows_for_rank:
            binding = select_component_binding(
                report_name=str(top.get("report_name") or ""),
                metric_hint=metric_hint,
                intent_metric=str(metric or ""),
                raw_query=str(intent.get("raw_query") or ""),
            )
            component_url = build_component_url_from_binding(binding, filters) if binding else None
            if component_url:
                ok_component_url, payload_or_err = run_component_url_table_fetch(component_url)
                if ok_component_url:
                    payload = payload_or_err if isinstance(payload_or_err, dict) else {}
                    rows_for_rank = payload.get("rows") or []
                    source_path = str(component_url)
                    if rows_for_rank:
                        live_refresh_ok = True
                        live_refresh_error = None
                elif not live_refresh_error:
                    live_refresh_error = str(payload_or_err)
        if not rows_for_rank and report_cpt and str(report_cpt).endswith(".frm"):
            ok_discover, items_or_err = run_discover_components(str(report_cpt), mirror_root=mirror_root)
            if ok_discover:
                items = items_or_err if isinstance(items_or_err, list) else []
                auto_url = select_component_url_from_discovery(
                    items,
                    metric_hint=metric_hint,
                    intent_metric=str(metric or ""),
                    raw_query=str(intent.get("raw_query") or ""),
                )
                if auto_url:
                    ok_auto, payload_or_err = run_component_url_table_fetch(auto_url)
                    if ok_auto:
                        payload = payload_or_err if isinstance(payload_or_err, dict) else {}
                        rows_for_rank = payload.get("rows") or []
                        source_path = auto_url
                        if rows_for_rank:
                            live_refresh_ok = True
                            live_refresh_error = None
                    elif not live_refresh_error:
                        live_refresh_error = str(payload_or_err)
            elif not live_refresh_error:
                live_refresh_error = str(items_or_err)
        if (not rows_for_rank) and report_cpt and str(report_cpt).endswith(".frm"):
            ok_refresh, payload_or_err = run_components_export_and_index(str(report_cpt), mirror_root=mirror_root, limit=0)
            if ok_refresh:
                ok_discover2, items_or_err2 = run_discover_components(str(report_cpt), mirror_root=mirror_root, ttl_seconds=60)
                if ok_discover2:
                    items2 = items_or_err2 if isinstance(items_or_err2, list) else []
                    auto_url2 = select_component_url_from_discovery(
                        items2,
                        metric_hint=metric_hint,
                        intent_metric=str(metric or ""),
                        raw_query=str(intent.get("raw_query") or ""),
                    )
                    if auto_url2:
                        ok_auto2, payload_or_err2 = run_component_url_table_fetch(auto_url2)
                        if ok_auto2:
                            payload2 = payload_or_err2 if isinstance(payload_or_err2, dict) else {}
                            rows_for_rank = payload2.get("rows") or []
                            source_path = auto_url2
                            if rows_for_rank:
                                live_refresh_ok = True
                                live_refresh_error = None
                        elif not live_refresh_error:
                            live_refresh_error = str(payload_or_err2)
                elif not live_refresh_error:
                    live_refresh_error = str(items_or_err2)
            elif not live_refresh_error:
                live_refresh_error = str(payload_or_err)
        ranked = pick_best_airline_yoy(rows_for_rank, metric_hint=metric_hint, extreme=extreme)
        if ranked:
            yoy_text = f"{ranked['yoy']:.2f}%"
            answer_text = (
                f"命中报表: {top['report_name']}\n"
                f"统计区间: {str(filters.get('date_start') or '-') } 到 {str(filters.get('date_end') or '-')}\n"
                f"同比口径: {ranked['yoy_col']}\n"
                f"{'表现最好' if extreme != 'worst' else '表现最差'}: {ranked['airline']}\n"
                f"排名: {ranked['rank']}/{ranked['total']}\n"
                f"同比: {yoy_text}\n"
                f"来源: {str(source_path)}"
            )
            if live_refresh_error:
                answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"
            return {
                "ok": True,
                "intent": intent,
                "used_live_refresh": used_live_refresh,
                "top_candidate": top,
                "candidate_count": len(ranked_catalog),
                "meaningful_row_count": len(rows_for_rank),
                "row_count_before_filter": len(rows_for_rank),
                "row_count_after_filter": len(rows_for_rank),
                "metric_column": ranked["yoy_col"],
                "live_refresh_ok": live_refresh_ok,
                "live_refresh_error": live_refresh_error,
                "answer_text": answer_text,
            }
        answer_text = (
            f"命中报表: {top['report_name']}\n"
            f"统计区间: {str(filters.get('date_start') or '-')} 到 {str(filters.get('date_end') or '-')}\n"
            f"未能在命中组件中解析到可用的航司同比列。"
        )
        if snapshot_hit:
            answer_text = (
                f"命中报表: {snapshot_hit['report_name']}\n"
                f"命中子表: {snapshot_hit['subtable']}\n"
                f"统计区间: {snapshot_hit['start']} 到 {snapshot_hit['end']}\n"
                f"最差航司: {snapshot_hit['airline']}\n"
                f"排名: {snapshot_hit['rank']}\n"
                f"同比: {snapshot_hit['yoy']}\n"
                f"说明: 实时链路未解析成功，已回退快照结果。"
            )
            return {
                "ok": True,
                "intent": intent,
                "used_live_refresh": used_live_refresh,
                "top_candidate": {
                    "report_id": -1,
                    "report_name": snapshot_hit["report_name"],
                    "file_path": "",
                    "dir_path": "航空板块经营报表",
                    "score": 0,
                    "score_breakdown": {"snapshot_fallback": 1.0},
                },
                "candidate_count": len(ranked_catalog),
                "meaningful_row_count": 1,
                "row_count_before_filter": 1,
                "row_count_after_filter": 1,
                "metric_column": "净利润同比",
                "live_refresh_ok": live_refresh_ok,
                "live_refresh_error": live_refresh_error,
                "answer_text": answer_text,
            }
        if live_refresh_error:
            answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"
        return {
            "ok": False,
            "reason": "airline_yoy_not_resolved",
            "intent": intent,
            "top_candidate": top,
            "live_refresh_ok": live_refresh_ok,
            "live_refresh_error": live_refresh_error,
            "answer_text": answer_text,
        }
    if metric == "单机边际贡献" and "单机边际贡献" in str(top.get("report_name") or ""):
        filters = intent.get("filters") or {}
        target_date = None
        dates = filters.get("flight_date") or []
        if dates:
            target_date = str(dates[0])
        target_company = str(filters.get("company") or "")
        target_type = str(filters.get("aircraft_type") or "")

        used_live_refresh = True
        live_file = Path(str(top["file_path"])).with_name("单机边际贡献_live.xlsx")
        if report_cpt:
            live_refresh_ok, live_refresh_msg = run_generic_live_export(report_cpt, str(live_file), intent)
        else:
            live_refresh_ok, live_refresh_msg = run_fast_single_margin_export(str(live_file))
        live_refresh_error = None if live_refresh_ok else live_refresh_msg

        source_path = live_file if live_file.exists() else Path(str(top["file_path"]))
        rows = extract_single_margin_rows(source_path, target_date_iso=target_date)
        row_count_before_filter = len(rows)
        if target_company:
            rows = [r for r in rows if str(r.get("公司", "")).strip() == target_company]
        if target_type:
            rows = [r for r in rows if str(r.get("机型", "")).strip() == target_type]

        metric_col = "单机边际贡献"
        answer_text = render_answer(
            intent.get("metric"),
            metric_col,
            rows,
            top["report_name"],
            str(source_path),
        )
        hit_ok = bool(metric_col) and len(rows) > 0
        record_profile_hit(
            profile_db_path,
            top,
            intent,
            metric_col,
            success=hit_ok,
            cpt_path=report_cpt,
        )
        if live_refresh_error:
            answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"
        return {
            "ok": True,
            "intent": intent,
            "used_live_refresh": used_live_refresh,
            "top_candidate": top,
            "candidate_count": len(ranked),
            "meaningful_row_count": len(rows),
            "row_count_before_filter": row_count_before_filter,
            "row_count_after_filter": len(rows),
            "metric_column": metric_col,
            "live_refresh_ok": live_refresh_ok,
            "live_refresh_error": live_refresh_error,
            "source_path": str(source_path),
            "answer_text": answer_text,
        }

    extracted = extract_table(Path(top["file_path"]))
    source_path = str(top["file_path"])
    metric_col = resolve_metric_with_filters(intent.get("metric"), extracted.get("columns") or [], filters)
    rows = extracted.get("rows") or []
    filtered = apply_filters(rows, intent, user_scope_cfg=user_scope_cfg, user=user, metric_col=metric_col)
    relaxed_filters_applied: list[str] = []

    used_live_refresh = False
    live_refresh_ok = None
    live_refresh_error = None
    force_live_refresh = bool(
        filters.get("date_start")
        or filters.get("date_end")
        or filters.get("rank_scope")
        or filters.get("first_flight")
        or filters.get("extreme")
        or freshness_force_live
    )
    if force_live_refresh or needs_live_refresh(extracted, metric_col, filtered_count=len(filtered)):
        used_live_refresh = True
        if top["report_name"] == "未来航班客座率票价分析":
            live_refresh_ok, live_refresh_msg = run_fast_future_kzl_export(intent, output_file=str(future_live_file))
        elif report_cpt:
            live_refresh_ok, live_refresh_msg = run_generic_live_export(report_cpt, str(generic_live_file), intent)
        else:
            live_refresh_ok, live_refresh_msg = False, "missing_report_cpt_path"
        if not live_refresh_ok:
            live_refresh_ok, live_refresh_msg = run_live_refresh(top["report_name"], overwrite="always")
        if live_refresh_ok:
            source_path = str(
                future_live_file if top["report_name"] == "未来航班客座率票价分析" and future_live_file.exists()
                else Path(top["file_path"]) if top["report_name"] == "未来航班客座率票价分析"
                else (generic_live_file if generic_live_file.exists() else Path(top["file_path"]))
            )
            if generic_live_file.exists():
                persist_refreshed_output(
                    generic_live_file,
                    Path(str(top["file_path"])),
                    mirror_root=mirror_root,
                    catalog_db=db_path,
                    excel_index_db=excel_db,
                )
            extracted = extract_table(source_path)
            metric_col = resolve_metric_with_filters(intent.get("metric"), extracted.get("columns") or [], filters)
            rows = extracted.get("rows") or []
            filtered = apply_filters(rows, intent, user_scope_cfg=user_scope_cfg, user=user, metric_col=metric_col)
        else:
            live_refresh_error = live_refresh_msg

    if ("前十后十" in str(top.get("report_name") or "")) and bool(filters.get("first_flight")) and str(filters.get("rank_scope") or "") == "后十":
        source_path = str(generic_live_file if generic_live_file.exists() else Path(top["file_path"]))
        answer_text, first_flight_routes = render_first_flight_bottom10_answer(rows, str(top["report_name"]), source_path)
        hit_ok = len(first_flight_routes) > 0
        record_profile_hit(
            profile_db_path,
            top,
            intent,
            "首航航线",
            success=hit_ok,
            cpt_path=report_cpt,
        )
        if live_refresh_error:
            answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"
        return {
            "ok": True,
            "intent": intent,
            "used_live_refresh": used_live_refresh,
            "top_candidate": top,
            "candidate_count": len(ranked),
            "meaningful_row_count": int(extracted.get("meaningful_row_count") or 0),
            "row_count_before_filter": len(rows),
            "row_count_after_filter": len(rows),
            "metric_column": "首航航线",
            "live_refresh_ok": live_refresh_ok,
            "live_refresh_error": live_refresh_error,
            "freshness_force_live": freshness_force_live,
            "first_flight_routes": first_flight_routes,
            "answer_text": answer_text,
        }

    if ("前十后十" in str(top.get("report_name") or "")) and str(filters.get("extreme") or "") == "best" and str(intent.get("metric") or "") in {"小时边际贡献", "总边贡"}:
        source_path = str(generic_live_file if generic_live_file.exists() else Path(top["file_path"]))
        answer_text, best_item = render_top_metric_flight_answer(source_path, str(top["report_name"]), str(intent.get("metric") or ""))
        hit_ok = bool(best_item)
        record_profile_hit(
            profile_db_path,
            top,
            intent,
            str(intent.get("metric") or ""),
            success=hit_ok,
            cpt_path=report_cpt,
        )
        if live_refresh_error:
            answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"
        payload = {
            "ok": True,
            "intent": intent,
            "used_live_refresh": used_live_refresh,
            "top_candidate": top,
            "candidate_count": len(ranked),
            "meaningful_row_count": int(extracted.get("meaningful_row_count") or 0),
            "row_count_before_filter": len(rows),
            "row_count_after_filter": len(rows),
            "metric_column": str(intent.get("metric") or ""),
            "live_refresh_ok": live_refresh_ok,
            "live_refresh_error": live_refresh_error,
            "freshness_force_live": freshness_force_live,
            "answer_text": answer_text,
        }
        if best_item:
            payload["best_item"] = best_item
        return payload

    if str(top.get("report_name") or "") == "未来航班客座率票价分析" and str(filters.get("analysis_mode") or "") == "competition_review":
        analysis_file = Path(str(top["file_path"])).with_name("未来航班客座率票价分析_competition_review.xlsx")
        ok_analysis_export, analysis_msg = run_fast_future_kzl_export(intent, output_file=str(analysis_file))
        analysis_rows = rows
        source_path = str(analysis_file if analysis_file.exists() else (generic_live_file if generic_live_file.exists() else Path(top["file_path"])))
        if ok_analysis_export and analysis_file.exists():
            try:
                analysis_rows = extract_table(analysis_file).get("rows") or []
            except Exception:
                analysis_rows = rows
        elif live_refresh_error is None:
            live_refresh_error = analysis_msg
        analysis_renderer = get_analysis_renderer(str(top.get("report_name") or ""), analysis_mode=str(filters.get("analysis_mode") or ""))
        answer_text = analysis_renderer(analysis_rows, str(top["report_name"]), source_path, filters) if analysis_renderer else render_future_competition_review(analysis_rows, str(top["report_name"]), source_path, filters)
        if live_refresh_error:
            answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"
        return {
            "ok": True,
            "intent": intent,
            "used_live_refresh": used_live_refresh,
            "top_candidate": top,
            "candidate_count": len(ranked),
            "meaningful_row_count": len(analysis_rows),
            "row_count_before_filter": len(analysis_rows),
            "row_count_after_filter": len(analysis_rows),
            "metric_column": "competition_review",
            "live_refresh_ok": live_refresh_ok,
            "live_refresh_error": live_refresh_error,
            "freshness_force_live": freshness_force_live,
            "answer_text": answer_text,
        }

    if metric_col and len(filtered) == 0:
        for keys in (["flight_date"], ["company"], ["aircraft_type"], ["flight_date", "company"], ["flight_date", "aircraft_type"]):
            intent_relaxed = copy.deepcopy(intent)
            f2 = dict(intent_relaxed.get("filters") or {})
            changed = False
            for k in keys:
                if k in f2:
                    f2.pop(k, None)
                    changed = True
            if not changed:
                continue
            intent_relaxed["filters"] = f2
            filtered_relaxed = apply_filters(rows, intent_relaxed, user_scope_cfg=user_scope_cfg, user=user, metric_col=metric_col)
            if filtered_relaxed:
                filtered = filtered_relaxed
                relaxed_filters_applied = keys
                break

    # Unknown metric fallback: probe reports in the same directory and pick first executable hit.
    if False and (metric and metric not in known_metrics) and (not metric_col or len(filtered) == 0):
        probe_started = time.monotonic()
        probe_budget_sec = 45.0
        same_dir = load_candidates_in_dir(db_path, str(top.get("dir_path") or ""), limit=20)
        same_dir = sorted(same_dir, key=lambda x: int(x.get("size_bytes") or 0))
        unresolved: list[dict] = []
        for cand in same_dir[:8]:
            if (time.monotonic() - probe_started) > probe_budget_sec:
                break
            try:
                ext_local = extract_table(Path(cand["file_path"]))
                cols_local = ext_local.get("columns") or []
                rows_local = ext_local.get("rows") or []
                m_local = resolve_metric_with_filters(intent.get("metric"), cols_local, filters)
                f_local = apply_filters(rows_local, intent, user_scope_cfg=user_scope_cfg, user=user, metric_col=m_local)
                if m_local and f_local:
                    top = cand
                    extracted = ext_local
                    rows = rows_local
                    metric_col = m_local
                    filtered = f_local
                    break
            except Exception:
                pass
            unresolved.append(cand)
        if not metric_col or len(filtered) == 0:
            mt = str(metric or "")
            def _cand_priority(c: dict) -> int:
                rn = str(c.get("report_name") or "")
                score = 0
                if "单机" in rn or "机型" in rn:
                    score += 5
                if "运力" in rn and "运力" in mt:
                    score += 5
                overlap = len({ch for ch in rn if "\u4e00" <= ch <= "\u9fff"} & {ch for ch in mt if "\u4e00" <= ch <= "\u9fff"})
                score += overlap
                return -score
            for cand in sorted(unresolved, key=_cand_priority)[:3]:
                if (time.monotonic() - probe_started) > probe_budget_sec:
                    break
                rpt_cpt = find_report_cpt_path(str(cand.get("report_name") or ""), str(cand.get("file_path") or ""))
                if not rpt_cpt:
                    continue
                cand_live = Path(str(cand["file_path"])).with_name(f"{Path(str(cand['file_path'])).stem}_live.xlsx")
                ok_probe, _msg_probe = run_generic_live_export(rpt_cpt, str(cand_live), intent)
                if not ok_probe or (not cand_live.exists()):
                    continue
                try:
                    ext_live = extract_table(cand_live)
                    cols_live = ext_live.get("columns") or []
                    rows_live = ext_live.get("rows") or []
                    m_live = resolve_metric_with_filters(intent.get("metric"), cols_live, filters)
                    f_live = apply_filters(rows_live, intent, user_scope_cfg=user_scope_cfg, user=user, metric_col=m_live)
                    if m_live and f_live:
                        top = cand
                        extracted = ext_live
                        rows = rows_live
                        metric_col = m_live
                        filtered = f_live
                        live_refresh_ok = True
                        break
                except Exception:
                    continue
    answer_text = render_answer(
        intent.get("metric"),
        metric_col,
        filtered,
        top["report_name"],
        source_path,
    )
    if relaxed_filters_applied:
        answer_text = f"{answer_text}\n注意: 严格条件无结果，已放宽筛选条件: {', '.join(relaxed_filters_applied)}"
    hit_ok = bool(metric_col) and len(filtered) > 0
    record_profile_hit(
        profile_db_path,
        top,
        intent,
        metric_col,
        success=hit_ok,
        cpt_path=report_cpt,
    )
    if live_refresh_error:
        answer_text = f"{answer_text}\n实时刷新失败: {live_refresh_error}"

    return {
        "ok": True,
        "intent": intent,
        "used_live_refresh": used_live_refresh,
        "top_candidate": top,
        "candidate_count": len(ranked),
        "meaningful_row_count": int(extracted.get("meaningful_row_count") or 0),
        "row_count_before_filter": len(rows),
        "row_count_after_filter": len(filtered),
        "metric_column": metric_col,
        "live_refresh_ok": live_refresh_ok,
        "live_refresh_error": live_refresh_error,
        "freshness_force_live": freshness_force_live,
        "relaxed_filters_applied": relaxed_filters_applied,
        "source_path": source_path,
        "answer_text": answer_text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Natural-language OPM metric query entrypoint.")
    parser.add_argument("query", help="Natural-language query")
    parser.add_argument("--user", help="User id for owner scope resolution")
    parser.add_argument("--mirror-root", default=str(default_mirror_root()))
    parser.add_argument("--db", default=str(default_catalog_db()))
    parser.add_argument("--excel-index", help="Path to excel_index.db (optional)")
    parser.add_argument("--profile-db", help="Path to report_profiles.db (optional)")
    parser.add_argument("--user-scope", default=str(default_mirror_root() / "search_index" / "user_scope.yaml"))
    parser.add_argument("--json", action="store_true", help="Print JSON result instead of text")
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

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("ok"):
        print(result["answer_text"])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
