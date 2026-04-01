from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from common import default_catalog_db, load_yaml_or_json, references_dir


def load_aliases(path: Path | None = None) -> dict:
    actual = path or (references_dir() / "column_aliases.yaml")
    return load_yaml_or_json(actual)


def _query_tokens(text: str) -> list[str]:
    t = str(text or "").strip()
    if not t:
        return []
    parts = re.split(r"[，。；、\s,.;:：!?？“”\"'（）()]+", t)
    stop = {"多少", "是什么", "查看", "查询", "帮我", "我的", "请", "一下", "看下", "看一下", "的"}
    out = []
    for p in parts:
        p = p.strip()
        if not p or p in stop:
            continue
        if len(p) >= 2:
            out.append(p)
    return out[:12]


def rank_candidates(intent: dict, db_path: Path, top_n: int = 5, aliases: dict | None = None) -> list[dict]:
    metric = intent.get("metric")
    raw_query = str(intent.get("raw_query") or "")
    filters = intent.get("filters") or {}
    scope_terms: list[str] = intent.get("scope_terms") or []
    alias_cfg = aliases or load_aliases()
    metric_aliases = alias_cfg.get("metric_column_aliases", {}).get(metric, []) if metric else []
    q_tokens = _query_tokens(raw_query)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT r.id, r.report_name, r.file_path, r.dir_path, group_concat(h.header_text, ' || ') AS headers
        FROM reports r
        LEFT JOIN report_headers h ON h.report_id = r.id
        GROUP BY r.id, r.report_name, r.file_path, r.dir_path
        """
    ).fetchall()
    conn.close()

    result: list[dict] = []
    for row in rows:
        report_name = row["report_name"] or ""
        dir_path = row["dir_path"] or ""
        headers = row["headers"] or ""

        score = 0.0
        breakdown = {
            "scope_match": 0.0,
            "metric_match": 0.0,
            "name_match": 0.0,
            "alias_match": 0.0,
            "filter_shape_match": 0.0,
            "char_overlap": 0.0,
        }

        for term in scope_terms:
            if term and term in dir_path:
                breakdown["scope_match"] += 30.0
        if metric:
            if metric in headers:
                breakdown["metric_match"] += 35.0
            if metric in report_name:
                breakdown["name_match"] += 20.0
        for alias in metric_aliases:
            if alias and alias in headers:
                breakdown["alias_match"] += 12.0
        if "客座率" in report_name and metric == "客座率":
            breakdown["name_match"] += 10.0
        if q_tokens:
            for t in q_tokens:
                if t in report_name:
                    breakdown["name_match"] += 6.0
                if t in headers:
                    breakdown["metric_match"] += 4.0
                if t in dir_path:
                    breakdown["scope_match"] += 3.0

        if filters.get("flight_no"):
            if any(k in headers for k in ("航班号", "FLT_NO", "FLIGHT_NO")):
                breakdown["filter_shape_match"] += 8.0
        if filters.get("flight_date"):
            if any(k in headers for k in ("航班日期", "日期", "DATE", "DATE_S", "DATE_E")):
                breakdown["filter_shape_match"] += 8.0
        if filters.get("segment_from") and filters.get("segment_to"):
            if any(k in headers for k in ("航段", "航线", "SEGMENT", "ROUTE", "LEG")):
                breakdown["filter_shape_match"] += 10.0
        if filters.get("company"):
            if any(k in headers for k in ("公司", "航司", "COMP", "COMP_CODE")):
                breakdown["filter_shape_match"] += 10.0
        if filters.get("aircraft_type"):
            if any(k in headers for k in ("机型", "AC_TYPE", "AIRCRAFT_TYPE", "FLEET")):
                breakdown["filter_shape_match"] += 10.0

        if raw_query:
            rq_chars = {ch for ch in raw_query if "\u4e00" <= ch <= "\u9fff"}
            rn_chars = {ch for ch in report_name if "\u4e00" <= ch <= "\u9fff"}
            inter = len(rq_chars & rn_chars)
            if inter > 0:
                breakdown["char_overlap"] += min(6.0, inter * 0.6)

        score = sum(breakdown.values())
        if score <= 0:
            continue
        result.append(
            {
                "report_id": row["id"],
                "report_name": report_name,
                "file_path": row["file_path"],
                "dir_path": dir_path,
                "score": round(score, 2),
                "score_breakdown": breakdown,
            }
        )

    result.sort(key=lambda x: x["score"], reverse=True)
    return result[:top_n]


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank report candidates by parsed intent.")
    parser.add_argument("intent_json", help="Intent JSON string or path to json file")
    parser.add_argument("--db", default=str(default_catalog_db()))
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    raw = Path(args.intent_json)
    intent = json.loads(raw.read_text(encoding="utf-8")) if raw.exists() else json.loads(args.intent_json)
    ranked = rank_candidates(intent, Path(args.db), top_n=args.top)
    print(json.dumps(ranked, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
