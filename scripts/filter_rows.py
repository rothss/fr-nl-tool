from __future__ import annotations

import re
from pathlib import Path

from common import load_yaml_or_json


def load_user_scope(path: Path) -> dict:
    return load_yaml_or_json(path)


def _normalize_date_text(v: object) -> str:
    text = str(v or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else text


def _normalize_month_day(v: object) -> str:
    text = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if m:
        return f"{m.group(2)}-{m.group(3)}"
    m2 = re.match(r"^(\d{1,2})月(\d{1,2})日$", text)
    if m2:
        return f"{int(m2.group(1)):02d}-{int(m2.group(2)):02d}"
    return ""


def _extract_time_rank(v: object) -> int:
    text = str(v or "").strip()
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if not m:
        return -1
    hh = int(m.group(1))
    mm = int(m.group(2))
    return hh * 60 + mm


def _to_minutes(hm: str) -> int:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(hm or "").strip())
    if not m:
        return -1
    return int(m.group(1)) * 60 + int(m.group(2))


def _norm_text(v: object) -> str:
    return re.sub(r"\s+", "", str(v or "").strip())


def _text_match(target: str, value: str) -> bool:
    t = _norm_text(target)
    v = _norm_text(value)
    if not t or not v:
        return False
    return v == t or (t in v) or (v in t)


def _segment_match(segment: str, src: str, dst: str) -> bool:
    seg = (segment or "").strip()
    if not seg:
        return False
    parts = seg.split("-")
    if len(parts) >= 2:
        left = parts[0]
        right = parts[1]
        return (src in left) and (dst in right)
    # Fallback for non-standard formatting.
    i = seg.find(src)
    j = seg.find(dst)
    return i >= 0 and j > i


def _values_by_tokens(row: dict, exact_keys: set[str], key_tokens: list[str]) -> list[str]:
    vals: list[str] = []
    for k, v in row.items():
        ks = str(k or "").strip()
        if not ks:
            continue
        if ks in exact_keys or any(t in ks for t in key_tokens):
            vals.append(str(v or "").strip())
    return vals


def _metric_suffix(metric_col: str | None) -> str:
    mc = str(metric_col or "").strip()
    if not mc:
        return ""
    m = re.search(r"_(\d+)$", mc)
    return f"_{m.group(1)}" if m else ""


def _values_for_dim(row: dict, exact_keys: set[str], key_tokens: list[str], metric_col: str | None) -> list[str]:
    vals_all = _values_by_tokens(row, exact_keys, key_tokens)
    if not vals_all:
        return vals_all
    suffix = _metric_suffix(metric_col)
    keys = [str(k or "").strip() for k in row.keys()]
    matched_keys = [k for k in keys if (k in exact_keys or any(t in k for t in key_tokens))]
    if not matched_keys:
        return vals_all
    if suffix:
        preferred = [k for k in matched_keys if k.endswith(suffix)]
        if preferred:
            return [str(row.get(k, "")).strip() for k in preferred]
        return vals_all
    preferred = [k for k in matched_keys if not re.search(r"_\d+$", k)]
    if preferred:
        return [str(row.get(k, "")).strip() for k in preferred]
    return vals_all


def apply_filters(
    rows: list[dict],
    intent: dict,
    user_scope_cfg: dict | None = None,
    user: str | None = None,
    metric_col: str | None = None,
) -> list[dict]:
    out = rows
    filters = intent.get("filters") or {}

    flight_nos = set((filters.get("flight_no") or []))
    if flight_nos:
        out2: list[dict] = []
        for r in out:
            vals = _values_for_dim(r, {"航班号"}, ["航班号"], metric_col)
            if not vals:
                continue
            if any(v.upper() in flight_nos for v in vals if v):
                out2.append(r)
        out = out2

    dates = set((filters.get("flight_date") or []))
    if dates:
        out2_exact: list[dict] = []
        for r in out:
            vals = _values_for_dim(r, {"航班日期", "日期"}, ["日期", "date", "Date"], metric_col)
            if not vals:
                # If report has no date dimension columns, do not hard-filter this row.
                out2_exact.append(r)
                continue
            if any(_normalize_date_text(v) in dates for v in vals if v):
                out2_exact.append(r)
        if out2_exact:
            out = out2_exact
        else:
            # Soft fallback: when strict YYYY-MM-DD has no hit, try month-day match for non-flight tables.
            # This keeps flight queries strict while improving cross-year matching on KPI日报类报表.
            has_flight_dims = False
            for r in out:
                keys = [str(k or "") for k in r.keys()]
                if any(("航班号" in k) or ("航段" in k) for k in keys):
                    has_flight_dims = True
                    break
            if not has_flight_dims:
                target_md = {x for x in (_normalize_month_day(d) for d in dates) if x}
                if target_md:
                    out2_md: list[dict] = []
                    for r in out:
                        vals = _values_for_dim(r, {"航班日期", "日期"}, ["日期", "date", "Date"], metric_col)
                        if not vals:
                            continue
                        if any(_normalize_month_day(_normalize_date_text(v)) in target_md for v in vals if v):
                            out2_md.append(r)
                    out = out2_md
                else:
                    out = out2_exact
            else:
                out = out2_exact

    seg_from = str(filters.get("segment_from") or "").strip()
    seg_to = str(filters.get("segment_to") or "").strip()
    if seg_from and seg_to:
        out2: list[dict] = []
        for r in out:
            vals = _values_for_dim(r, {"航段", "航线"}, ["航段", "航线"], metric_col)
            if any(_segment_match(v, seg_from, seg_to) for v in vals if v):
                out2.append(r)
        out = out2

    company = str(filters.get("company") or "").strip()
    if company:
        out2: list[dict] = []
        for r in out:
            vals = _values_for_dim(r, {"公司", "航司"}, ["公司", "航司"], metric_col)
            if any(_text_match(company, v) for v in vals if v):
                out2.append(r)
        out = out2

    ac_type = str(filters.get("aircraft_type") or "").strip()
    if ac_type:
        out2: list[dict] = []
        for r in out:
            vals = _values_for_dim(r, {"机型"}, ["机型"], metric_col)
            if any(_text_match(ac_type, v) for v in vals if v):
                out2.append(r)
        out = out2

    has_explicit_segment = bool(seg_from and seg_to)
    has_explicit_flight = bool(flight_nos)

    if intent.get("owner_scope") == "mine" and user_scope_cfg and not has_explicit_segment and not has_explicit_flight:
        default_user = user or user_scope_cfg.get("default_user")
        user_data = (user_scope_cfg.get("users") or {}).get(default_user, {})
        package = user_data.get("包干航线", {})
        segments = set(package.get("航段", []))
        flights = {str(x).strip().upper() for x in package.get("航班号", [])}

        if segments:
            out = [r for r in out if str(r.get("航段", "")).strip() in segments]
        if flights:
            out = [r for r in out if str(r.get("航班号", "")).strip().upper() in flights]

    if filters.get("last_flight") and out:
        out = sorted(out, key=lambda r: _extract_time_rank(r.get("时刻", "")), reverse=True)
        out = [out[0]]
    elif filters.get("closest_time") and filters.get("depart_time") and out:
        target = _to_minutes(str(filters.get("depart_time")))
        if target >= 0:
            out = sorted(
                out,
                key=lambda r: abs(_extract_time_rank(r.get("时刻", "")) - target)
                if _extract_time_rank(r.get("时刻", "")) >= 0
                else 10**9,
            )
            out = [out[0]]

    return out
