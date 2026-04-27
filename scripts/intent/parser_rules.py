from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from common import load_yaml_or_json, references_dir


def _contains_any(text: str, items: list[str]) -> bool:
    return any(x and x in text for x in items)


def _clean_city_phrase(s: str) -> str:
    text = str(s or "").strip()
    text = re.sub(r"^(查看|查询|帮我查|我的|请|帮我|看下|看一下)", "", text)
    text = re.sub(r"(今天|明天|后天|昨天|明后天).*$", "", text)
    text = re.sub(r"(未来|接下来)\d+天.*$", "", text)
    text = re.sub(r"(未来两天|接下来两天).*$", "", text)
    text = re.sub(r"\d{1,2}点.*$", "", text)
    text = re.sub(r"(那班|这一班|最后一班|最晚一班).*$", "", text)
    text = re.sub(r"(的)?(指定航线|航线|航段)$", "", text)
    text = re.sub(r"(的)?(客座率|票价|价格|余票).*$", "", text)
    text = text.replace("北京（首都）", "北京首都").replace("北京(首都)", "北京首都")
    return text.strip(" 的")


def load_synonyms(path: Path | None = None) -> dict:
    actual = path or (references_dir() / "synonyms.yaml")
    return load_yaml_or_json(actual)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys([str(x) for x in items if str(x).strip()]))


def _expand_relative_dates(normalized: str, today: date) -> dict:
    result = {
        "mode": None,
        "anchor": None,
        "offset_start": None,
        "offset_end": None,
        "start_date": None,
        "end_date": None,
        "dates": [],
    }
    if "明天" in normalized:
        d = today + timedelta(days=1)
        result.update(
            {
                "mode": "single_date",
                "anchor": "today",
                "offset_start": 1,
                "offset_end": 1,
                "start_date": d.isoformat(),
                "end_date": d.isoformat(),
                "dates": [d.isoformat()],
            }
        )
    elif "今天" in normalized:
        d = today
        result.update(
            {
                "mode": "single_date",
                "anchor": "today",
                "offset_start": 0,
                "offset_end": 0,
                "start_date": d.isoformat(),
                "end_date": d.isoformat(),
                "dates": [d.isoformat()],
            }
        )
    elif "后天" in normalized:
        d = today + timedelta(days=2)
        result.update(
            {
                "mode": "single_date",
                "anchor": "today",
                "offset_start": 2,
                "offset_end": 2,
                "start_date": d.isoformat(),
                "end_date": d.isoformat(),
                "dates": [d.isoformat()],
            }
        )
    if "近三天" in normalized:
        dates = [(today + timedelta(days=i)).isoformat() for i in range(3)]
        result.update(
            {
                "mode": "relative_past_range",
                "anchor": "today",
                "offset_start": 0,
                "offset_end": 2,
                "start_date": dates[0],
                "end_date": dates[-1],
                "dates": dates,
            }
        )
    m_future = re.search(r"(?:未来|接下来)(\d+)天", normalized)
    if m_future:
        days = int(m_future.group(1))
        if days > 0:
            dates = [(today + timedelta(days=i)).isoformat() for i in range(days)]
            result.update(
                {
                    "mode": "relative_future_range",
                    "anchor": "today",
                    "offset_start": 0,
                    "offset_end": days - 1,
                    "start_date": dates[0],
                    "end_date": dates[-1],
                    "dates": dates,
                }
            )
    if "未来两天" in normalized or "接下来两天" in normalized or "明后天" in normalized:
        dates = [today.isoformat(), (today + timedelta(days=1)).isoformat()]
        if "明后天" in normalized:
            dates = [(today + timedelta(days=1)).isoformat(), (today + timedelta(days=2)).isoformat()]
            start_offset, end_offset = 1, 2
        else:
            start_offset, end_offset = 0, 1
        result.update(
            {
                "mode": "relative_future_range",
                "anchor": "today",
                "offset_start": start_offset,
                "offset_end": end_offset,
                "start_date": dates[0],
                "end_date": dates[-1],
                "dates": dates,
            }
        )
    return result


def parse_intent_rules(normalized: dict, today: date | None = None) -> dict:
    today = today or date.today()
    text = str(normalized.get("cleaned_query") or "").strip()
    syn = load_synonyms()
    metric_map: dict[str, list[str]] = syn.get("metric_keywords", {})
    scope_terms_cfg: list[str] = syn.get("scope_keywords", [])

    metrics: list[str] = []
    for canonical, keys in metric_map.items():
        if _contains_any(text, [canonical] + list(keys)):
            metrics.append(canonical)
    metrics = _dedupe_keep_order(metrics)

    owner_scope = "mine" if ("我的" in text or "我负责" in text) else "all"
    scope_terms = [term for term in scope_terms_cfg if term in text]
    flight_numbers = _dedupe_keep_order(re.findall(r"[A-Z]{2}\d{3,4}", text.upper()))

    time_info = _expand_relative_dates(text, today)
    date_match = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    md_match = re.findall(r"(\d{1,2})月(\d{1,2})日", text)
    md_dates: list[str] = []
    for m, d in md_match:
        try:
            md_dates.append(date(today.year, int(m), int(d)).isoformat())
        except Exception:
            continue
    explicit_dates = _dedupe_keep_order(date_match + md_dates)
    if explicit_dates:
        time_info.update(
            {
                "mode": "single_date" if len(explicit_dates) == 1 else "explicit_range",
                "start_date": explicit_dates[0],
                "end_date": explicit_dates[-1],
                "dates": explicit_dates,
                "anchor": None,
                "offset_start": None,
                "offset_end": None,
            }
        )

    range_md = re.search(r"(\d{1,2})月(\d{1,2})日?\s*(?:到|至|~|-)\s*(?:(\d{1,2})月)?(\d{1,2})日?", text)
    if range_md:
        m1 = int(range_md.group(1))
        d1 = int(range_md.group(2))
        m2 = int(range_md.group(3) or range_md.group(1))
        d2 = int(range_md.group(4))
        try:
            s = date(today.year, m1, d1).isoformat()
            e = date(today.year, m2, d2).isoformat()
            time_info.update(
                {
                    "mode": "explicit_range",
                    "start_date": s,
                    "end_date": e,
                    "dates": [s, e],
                    "anchor": None,
                    "offset_start": None,
                    "offset_end": None,
                }
            )
        except Exception:
            pass

    route = {
        "origin_raw": None,
        "destination_raw": None,
        "origin_norm": None,
        "destination_norm": None,
        "origin_code": None,
        "destination_code": None,
    }
    route_match = re.search(
        r"(?:我的)?([\u4e00-\u9fff]{2,8})到([\u4e00-\u9fff]{2,16}?)(?=的|航段|航线|未来|接下来|近|今天|明天|后天|明后天|客座率|票价|价格|余票|，|,|$)",
        text,
    )
    if route_match:
        route["origin_raw"] = route_match.group(1)
        route["destination_raw"] = route_match.group(2)
        route["origin_norm"] = _clean_city_phrase(route_match.group(1))
        route["destination_norm"] = _clean_city_phrase(route_match.group(2))
    else:
        route_hyphen = re.search(r"([\u4e00-\u9fff]{2,8})[-]([\u4e00-\u9fff()]{2,12})", text)
        if route_hyphen:
            route["origin_raw"] = route_hyphen.group(1)
            route["destination_raw"] = route_hyphen.group(2)
            route["origin_norm"] = _clean_city_phrase(route_hyphen.group(1))
            route["destination_norm"] = _clean_city_phrase(route_hyphen.group(2).replace("(", "").replace(")", ""))

    analysis_mode = None
    compare_target = None
    question_type = None
    if any(x in text for x in ("异常", "改进", "外航相比", "竞航", "竞争对手", "竞对")):
        analysis_mode = "competition_review"
        compare_target = "competitor"
    if any(x in text for x in ("有什么问题", "哪里有问题", "异常")):
        question_type = "diagnosis"
    elif analysis_mode:
        question_type = "comparison"

    companies = (
        "CompanyA",
        "CompanyB",
        "CompanyC",
        "CompanyD",
        "CompanyE",
        "CompanyF",
        "CompanyG",
        "CompanyH",
        "CompanyI",
        "CompanyJ",
        "CompanyK",
    )
    company = next((c for c in companies if c in text), None)
    aircraft_type = next((t for t in ("宽体机", "窄体机", "支线机") if t in text), None)

    parser_trace = []
    if metrics:
        parser_trace.append("rules:metrics")
    if route.get("origin_norm") and route.get("destination_norm"):
        parser_trace.append("rules:route")
    if time_info.get("mode"):
        parser_trace.append(f"rules:time:{time_info['mode']}")
    if analysis_mode:
        parser_trace.append("rules:analysis")

    return {
        "raw_query": text,
        "domain": None,
        "intent_type": None,
        "metrics": metrics,
        "route": route,
        "flight": {"flight_numbers": flight_numbers},
        "time": time_info,
        "analysis": {
            "mode": analysis_mode,
            "compare_target": compare_target,
            "question_type": question_type,
        },
        "scope": {
            "owner_scope": owner_scope,
            "company": company,
            "aircraft_type": aircraft_type,
            "scope_terms": scope_terms,
        },
        "constraints": {
            "prefer_live_refresh": bool(time_info.get("mode") == "relative_future_range")
        },
        "confidence": 0.0,
        "missing_slots": [],
        "parser_trace": parser_trace,
    }
