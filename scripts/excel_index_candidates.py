from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path


def default_excel_index_db(mirror_root: Path) -> Path | None:
    env = os.environ.get("FR_EXCEL_INDEX_DB")
    if env:
        p = Path(env)
        if p.exists():
            return p
    p1 = mirror_root / "search_index" / "excel_index.db"
    if p1.exists():
        return p1
    fallback_env = os.environ.get("FR_EXCEL_INDEX_FALLBACK_DB")
    if fallback_env:
        p2 = Path(fallback_env)
        if not p2.is_absolute():
            p2 = Path(__file__).parent.parent / fallback_env
        if p2.exists():
            return p2
    return None


def _to_month_day(date_iso: str) -> str | None:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(date_iso or ""))
    if not m:
        return None
    return f"{int(m.group(2))}月{int(m.group(3))}日"


def _intent_terms(intent: dict) -> list[str]:
    filters = intent.get("filters") or {}
    metric = str(intent.get("metric") or "").strip()
    raw_query = str(intent.get("raw_query") or "")
    terms: list[str] = []
    if metric:
        terms.append(metric)
    for k in ("company", "aircraft_type", "depart_time"):
        v = str(filters.get(k) or "").strip()
        if v:
            terms.append(v)
    flight_nos = filters.get("flight_no") or []
    for v in flight_nos:
        sv = str(v).strip()
        if sv:
            terms.append(sv)
    dates = filters.get("flight_date") or []
    for v in dates:
        sv = str(v).strip()
        if sv:
            terms.append(sv)
            md = _to_month_day(sv)
            if md:
                terms.append(md)
    sf = str(filters.get("segment_from") or "").strip()
    st = str(filters.get("segment_to") or "").strip()
    if sf and st:
        terms.append(f"{sf}-{st}")
        terms.append(sf)
        terms.append(st)
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,20}", raw_query)
    terms.extend(tokens[:10])
    out: list[str] = []
    seen = set()
    for t in terms:
        x = str(t).strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _derive_dir_path(file_path: str, mirror_root: Path) -> str:
    p = Path(file_path)
    try:
        return str(p.parent.relative_to(mirror_root)).replace("\\", "/")
    except Exception:
        s = str(p).replace("\\", "/")
        for marker in ("/fr_mirror/", "/fr_mirror/"):
            i = s.find(marker)
            if i >= 0:
                rel = s[i + len(marker) :]
                pp = Path(rel).parent
                return str(pp).replace("\\", "/")
    return str(p.parent).replace("\\", "/")


def rank_candidates_from_excel_index(
    intent: dict, excel_index_db: Path, mirror_root: Path, top_n: int = 30
) -> list[dict]:
    if not excel_index_db.exists():
        return []
    terms = _intent_terms(intent)
    if not terms:
        return []

    score: dict[int, float] = {}
    meta: dict[int, tuple[str, str]] = {}
    metric = str(intent.get("metric") or "").strip()

    conn = sqlite3.connect(excel_index_db)
    try:
        for t in terms[:12]:
            q = t.replace('"', "").strip()
            if not q:
                continue
            try:
                rows = conn.execute(
                    """
                    SELECT workbook_id, file_path, file_name
                    FROM report_names_fts
                    WHERE report_names_fts MATCH ?
                    LIMIT 200
                    """,
                    (q,),
                ).fetchall()
            except Exception:
                rows = []
            for workbook_id, file_path, file_name in rows:
                wid = int(workbook_id)
                meta[wid] = (str(file_path), str(file_name))
                score[wid] = score.get(wid, 0.0) + (
                    16.0 if (metric and t == metric) else 8.0
                )

            try:
                rows2 = conn.execute(
                    """
                    SELECT s.workbook_id, w.file_path, w.file_name, COUNT(*) AS cnt
                    FROM cells_fts f
                    JOIN cells c ON c.id = f.rowid
                    JOIN sheets s ON s.id = c.sheet_id
                    JOIN workbooks w ON w.id = s.workbook_id
                    WHERE cells_fts MATCH ?
                    GROUP BY s.workbook_id, w.file_path, w.file_name
                    ORDER BY cnt DESC
                    LIMIT 200
                    """,
                    (q,),
                ).fetchall()
            except Exception:
                rows2 = []
            for workbook_id, file_path, file_name, cnt in rows2:
                wid = int(workbook_id)
                meta[wid] = (str(file_path), str(file_name))
                base = 20.0 if (metric and t == metric) else 4.0
                score[wid] = score.get(wid, 0.0) + min(20.0, base + float(cnt) * 0.6)
    finally:
        conn.close()

    ranked = sorted(score.items(), key=lambda x: x[1], reverse=True)[:top_n]
    out: list[dict] = []
    for wid, sc in ranked:
        file_path, file_name = meta.get(wid, ("", ""))
        if not file_path:
            continue
        report_name = Path(file_name).stem if file_name else Path(file_path).stem
        out.append(
            {
                "report_id": -wid,
                "report_name": report_name,
                "file_path": file_path,
                "dir_path": _derive_dir_path(file_path, mirror_root),
                "score": round(float(sc), 2),
                "score_breakdown": {"excel_index_match": round(float(sc), 2)},
            }
        )
    return out
