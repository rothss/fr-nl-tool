from __future__ import annotations

import re


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
    if not rows:
        return None
    keys = [str(k) for k in rows[0].keys()]
    airline_col = None
    for c in keys:
        cs = str(c)
        if any(x in cs for x in ("航司", "公司名称", "公司")):
            airline_col = cs
            break
    if not airline_col:
        return None
    yoy_cols = [c for c in keys if "同比" in str(c)]
    if metric_hint:
        hit = [c for c in yoy_cols if metric_hint in str(c)]
        if hit:
            yoy_cols = hit
    if not yoy_cols:
        for c in keys:
            vals = [str(r.get(c, "")).strip() for r in rows[:20]]
            if sum(1 for v in vals if "%" in v) >= 3:
                yoy_cols = [c]
                break
    if not yoy_cols:
        return None
    yoy_col = yoy_cols[0]
    rank_col = None
    for c in keys:
        if "排名" in str(c):
            rank_col = str(c)
            break
    candidates: list[dict] = []
    for r in rows:
        airline = str(r.get(airline_col, "")).strip()
        if (not airline) or any(x in airline for x in ("小计", "合计", "航空合计")):
            continue
        yoy = _to_float(r.get(yoy_col, ""))
        if yoy is None:
            continue
        rank_v = None
        if rank_col:
            m_rank = re.search(r"\d+", str(r.get(rank_col, "")).strip())
            if m_rank:
                try:
                    rank_v = int(m_rank.group(0))
                except Exception:
                    rank_v = None
        candidates.append({"airline": airline, "yoy": yoy, "row": r, "rank_v": rank_v})
    if not candidates:
        return None
    reverse = True if extreme != "worst" else False
    sorted_rows = sorted(candidates, key=lambda x: float(x["yoy"]), reverse=reverse)
    best = sorted_rows[0]
    if isinstance(best.get("rank_v"), int):
        rank = int(best["rank_v"])
    else:
        rank = (sorted_rows.index(best) + 1) if extreme != "worst" else len(sorted_rows)
    return {"airline": best["airline"], "yoy": best["yoy"], "rank": rank, "total": len(sorted_rows), "yoy_col": yoy_col}


def analyze_airline_yoy(intent: dict, extracted: dict, source_meta: dict) -> dict:
    rows = extracted.get("rows") or []
    filters = (intent or {}).get("filters") or {}
    metric = str((intent or {}).get("metric") or "")
    raw_query = str((intent or {}).get("raw_query") or "")
    extreme = str(filters.get("extreme") or "best")
    metric_hint = "净利润" if ("净利润" in metric or "净利润" in raw_query or str(filters.get("report_variant") or "") == "adjusted_profit_overview") else metric
    picked = pick_best_airline_yoy(rows, metric_hint=metric_hint, extreme=extreme)
    matched_dates: list[str] = []
    if filters.get("date_start") and filters.get("date_end"):
        matched_dates = [str(filters.get("date_start")), str(filters.get("date_end"))]
    elif isinstance(filters.get("flight_date"), list):
        matched_dates = [str(x) for x in filters.get("flight_date") if x]
    if not picked:
        return {
            "ok": False,
            "analysis_engine": "airline_yoy",
            "matched_route": None,
            "matched_dates": matched_dates,
            "issues": [],
            "advice": [],
            "summary": "未能在命中报表中解析到可用的航司同比列。",
        }
    direction = "表现最好" if extreme != "worst" else "表现最差"
    return {
        "ok": True,
        "analysis_engine": "airline_yoy",
        "matched_route": None,
        "matched_dates": matched_dates,
        "issues": [],
        "advice": [],
        "summary": f"{direction}: {picked['airline']}，同比 {picked['yoy']:.2f}%，排名 {picked['rank']}/{picked['total']}",
        "result_row": picked,
    }


def render_airline_yoy_answer(analysis_result: dict, intent: dict, source_meta: dict) -> str:
    report_name = str(source_meta.get("report_name") or "")
    source_path = str(source_meta.get("file_path") or "")
    filters = (intent or {}).get("filters") or {}
    if not analysis_result.get("ok"):
        return (
            f"命中报表: {report_name}\n"
            f"统计区间: {str(filters.get('date_start') or '-')} 到 {str(filters.get('date_end') or '-')}\n"
            f"{str(analysis_result.get('summary') or '未能解析同比结果。')}\n"
            f"来源: {source_path}"
        )
    row = analysis_result.get("result_row") or {}
    return (
        f"命中报表: {report_name}\n"
        f"统计区间: {str(filters.get('date_start') or '-')} 到 {str(filters.get('date_end') or '-')}\n"
        f"同比口径: {str(row.get('yoy_col') or '-')}\n"
        f"{'表现最好' if str(filters.get('extreme') or 'best') != 'worst' else '表现最差'}: {str(row.get('airline') or '-')}\n"
        f"排名: {int(row.get('rank') or 0)}/{int(row.get('total') or 0)}\n"
        f"同比: {float(row.get('yoy') or 0.0):.2f}%\n"
        f"来源: {source_path}"
    )
