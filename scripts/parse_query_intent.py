from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path

from common import load_yaml_or_json, references_dir


def _contains_any(text: str, items: list[str]) -> bool:
    return any(x and x in text for x in items)


def _clean_city_phrase(s: str) -> str:
    text = str(s or "").strip()
    text = re.sub(r"^(查看|查询|帮我查|我的|请|帮我|看下|看一下)", "", text)
    text = re.sub(r"(今天|明天|后天|昨天).*$", "", text)
    text = re.sub(r"\d{1,2}点.*$", "", text)
    text = re.sub(r"(那班|这一班|最后一班|最晚一班).*$", "", text)
    text = re.sub(r"(的)?(包干航线|航线|航段)$", "", text)
    text = text.replace("北京（首都）", "北京首都").replace("北京(首都)", "北京首都")
    return text.strip(" 的")


def load_synonyms(path: Path | None = None) -> dict:
    actual = path or (references_dir() / "synonyms.yaml")
    return load_yaml_or_json(actual)


def parse_query(text: str, synonyms: dict | None = None) -> dict:
    syn = synonyms or load_synonyms()
    metric_map: dict[str, list[str]] = syn.get("metric_keywords", {})
    scope_terms_cfg: list[str] = syn.get("scope_keywords", [])

    normalized = text.strip()
    metric = None
    for canonical, keys in metric_map.items():
        if _contains_any(normalized, [canonical] + list(keys)):
            metric = canonical
            break
    if not metric:
        m = re.search(r"的([\u4e00-\u9fffA-Za-z0-9]{2,20})(?:是多少|多少|是什么|为多少)", normalized)
        if m:
            metric = m.group(1).strip()
        else:
            all_m = re.findall(r"([\u4e00-\u9fffA-Za-z0-9]{2,40})(?:是多少|多少|是什么|为多少)", normalized)
            if all_m:
                guess = all_m[-1].strip()
                guess = re.sub(r"^\d{1,2}月\d{1,2}日", "", guess)
                guess = re.sub(r"^\d{4}-\d{2}-\d{2}", "", guess)
                for t in ("航空股份", "首都航空", "天津航空", "祥鹏航空", "西部航空", "北部湾航空", "福州航空", "乌鲁木齐航空", "长安航空", "金鹏航空", "香港航空", "宽体机", "窄体机", "支线机"):
                    guess = guess.replace(t, "")
                guess = re.sub(r"是$", "", guess)
                metric = guess.strip()

    owner_scope = "mine" if ("我的" in normalized or "我负责" in normalized) else "all"

    scope_terms: list[str] = []
    for term in scope_terms_cfg:
        if term in normalized:
            scope_terms.append(term)

    # Chinese text often touches flight numbers directly, so \b is unreliable here.
    flight_no_match = re.findall(r"[A-Z]{2}\d{3,4}", normalized.upper())
    date_match = re.findall(r"\d{4}-\d{2}-\d{2}", normalized)
    md_match = re.findall(r"(\d{1,2})月(\d{1,2})日", normalized)
    for m, d in md_match:
        try:
            y = date.today().year
            date_match.append(date(y, int(m), int(d)).isoformat())
        except Exception:
            pass
    today = date.today()
    if "明天" in normalized:
        date_match.append((today + timedelta(days=1)).isoformat())
    if "今天" in normalized:
        date_match.append(today.isoformat())
    if "后天" in normalized:
        date_match.append((today + timedelta(days=2)).isoformat())
    if "昨天" in normalized:
        date_match.append((today - timedelta(days=1)).isoformat())
    filters: dict[str, object] = {}
    if flight_no_match:
        filters["flight_no"] = list(dict.fromkeys(flight_no_match))
    if date_match:
        filters["flight_date"] = list(dict.fromkeys(date_match))
    if "这个月" in normalized or "本月" in normalized:
        month_start = today.replace(day=1).isoformat()
        # OPM部分经营报表存在T+2延迟，默认取到D-2。
        month_end = (today - timedelta(days=2)).isoformat()
        filters["date_start"] = month_start
        filters["date_end"] = month_end
        filters["flight_date"] = [month_end]
    if "上周" in normalized:
        start_this_week = today - timedelta(days=today.weekday())
        start_last_week = start_this_week - timedelta(days=7)
        end_last_week = start_this_week - timedelta(days=1)
        filters["date_start"] = start_last_week.isoformat()
        filters["date_end"] = end_last_week.isoformat()
        filters["flight_date"] = [end_last_week.isoformat()]
    if "近三天" in normalized:
        filters["date_start"] = today.isoformat()
        filters["date_end"] = (today + timedelta(days=2)).isoformat()
        filters["flight_date"] = [today.isoformat(), (today + timedelta(days=1)).isoformat(), (today + timedelta(days=2)).isoformat()]
    if ("date_start" not in filters) and ("date_end" not in filters):
        m_only = re.search(r"(?<!\d)(\d{1,2})月(?!\d)", normalized)
        if m_only:
            y = today.year
            mon = int(m_only.group(1))
            try:
                start = date(y, mon, 1)
                if mon == 12:
                    month_end_day = date(y + 1, 1, 1) - timedelta(days=1)
                else:
                    month_end_day = date(y, mon + 1, 1) - timedelta(days=1)
                safe_end = today - timedelta(days=2)
                end = min(month_end_day, safe_end) if mon == today.month else month_end_day
                if end >= start:
                    filters["date_start"] = start.isoformat()
                    filters["date_end"] = end.isoformat()
                    filters["flight_date"] = [end.isoformat()]
            except Exception:
                pass

    range_md = re.search(r"(\d{1,2})月(\d{1,2})日?\s*(?:到|至|~|—|-)\s*(?:(\d{1,2})月)?(\d{1,2})日?", normalized)
    if range_md:
        y = date.today().year
        m1 = int(range_md.group(1))
        d1 = int(range_md.group(2))
        m2 = int(range_md.group(3) or range_md.group(1))
        d2 = int(range_md.group(4))
        try:
            s = date(y, m1, d1).isoformat()
            e = date(y, m2, d2).isoformat()
            filters["date_start"] = s
            filters["date_end"] = e
            # Keep end-date as fallback single date for old downstream paths.
            filters["flight_date"] = [e]
        except Exception:
            pass

    hm = re.search(r"(\d{1,2})点(?:(\d{1,2})分?)?", normalized)
    if hm:
        hh = int(hm.group(1))
        mm = int(hm.group(2) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            filters["depart_time"] = f"{hh:02d}:{mm:02d}"

    route_match = re.search(
        r"(?:我的)?([\u4e00-\u9fff]{2,8})到([\u4e00-\u9fff]{2,8}?)(?:的|航段|航线|$)",
        normalized,
    )
    if route_match:
        filters["segment_from"] = _clean_city_phrase(route_match.group(1))
        filters["segment_to"] = _clean_city_phrase(route_match.group(2))
    else:
        route_hyphen = re.search(r"([\u4e00-\u9fff]{2,8})[-—–]([\u4e00-\u9fff（）()]{2,12})", normalized)
        if route_hyphen:
            filters["segment_from"] = _clean_city_phrase(route_hyphen.group(1))
            filters["segment_to"] = _clean_city_phrase(
                route_hyphen.group(2).strip().replace("（", "").replace("）", "")
            )

    if "最后一班" in normalized or "最晚一班" in normalized:
        filters["last_flight"] = True
    if "那班" in normalized and "depart_time" in filters:
        filters["closest_time"] = True
    if "后十" in normalized:
        filters["rank_scope"] = "后十"
    elif "前十" in normalized:
        filters["rank_scope"] = "前十"
    if "首航" in normalized:
        filters["first_flight"] = True
    if "航空集团" in normalized:
        filters["group"] = "航空集团"
    if ("净利润" in normalized and "同比" in normalized) or ("利润同比" in normalized):
        metric = metric or "净利润同比"
    if ("净利润" in normalized) and (("提升最大" in normalized) or ("提升最多" in normalized) or ("提升" in normalized and "最大" in normalized)):
        metric = metric or "净利润同比"
        filters["compare_scope"] = "airline_yoy"
        filters["extreme"] = "best"
    if ("不含发动机大修" in normalized) or ("飞机退租" in normalized):
        filters["report_variant"] = "adjusted_profit_overview"
        filters["profit_caliber"] = "经营考核利润口径-不含发动机大修和飞机退租"
    if ("最差" in normalized) or ("表现得最差" in normalized):
        filters["extreme"] = "worst"
    if ("最好" in normalized) or ("表现最好" in normalized):
        filters["extreme"] = "best"
    if ("最高" in normalized) or ("第一名" in normalized) or ("排名第一" in normalized):
        filters["extreme"] = "best"
    if ("航司" in normalized and "同比" in normalized) or ("各航司" in normalized and "同比" in normalized):
        filters["compare_scope"] = "airline_yoy"
    if ("异常" in normalized) or ("改进" in normalized) or ("外航相比" in normalized) or ("竞航" in normalized):
        filters["analysis_mode"] = "competition_review"

    aircraft_types = ("宽体机", "窄体机", "支线机")
    for t in aircraft_types:
        if t in normalized:
            filters["aircraft_type"] = t
            break

    companies = (
        "航空股份",
        "首都航空",
        "天津航空",
        "祥鹏航空",
        "西部航空",
        "北部湾航空",
        "福州航空",
        "乌鲁木齐航空",
        "长安航空",
        "金鹏航空",
        "香港航空",
    )
    for c in companies:
        if c in normalized:
            filters["company"] = c
            break

    return {
        "raw_query": normalized,
        "metric": metric,
        "scope_terms": scope_terms,
        "owner_scope": owner_scope,
        "time_range": None,
        "filters": filters,
        "expected_shape": "scalar_or_list",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse natural-language query into intent JSON.")
    parser.add_argument("query", help="Natural-language query text")
    parser.add_argument("--synonyms", help="Path to synonyms yaml/json")
    args = parser.parse_args()

    syn = load_synonyms(Path(args.synonyms)) if args.synonyms else load_synonyms()
    intent = parse_query(args.query, synonyms=syn)
    print(json.dumps(intent, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
