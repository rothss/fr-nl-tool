from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path

from .db import connect_db


@dataclass
class SearchHit:
    hit_type: str          # 'cell' | 'report'
    file_path: str
    file_name: str
    report_name: str       # relative path without extension
    sheet_name: str = ""
    row_no: int = 0
    col_no: int = 0
    cell_value: str = ""


def _resolve_report_name(file_path: str) -> str:
    p = Path(file_path)
    try:
        p = p.relative_to(Path.cwd())
    except ValueError:
        pass
    return str(p.with_suffix("")).replace("\\", "/")


def search(db_path: Path, keywords: str, limit: int = 20) -> list[SearchHit]:
    if not db_path.exists():
        return []

    safe_q = keywords.replace("-", " ")

    conn = sqlite3.connect(str(db_path))
    try:
        cell_rows = conn.execute(
            """
            SELECT w.file_name, w.file_path, s.sheet_name, c.row_no, c.col_no, c.cell_value
            FROM cells_fts f
            JOIN cells c ON c.id = f.rowid
            JOIN sheets s ON s.id = c.sheet_id
            JOIN workbooks w ON w.id = s.workbook_id
            WHERE cells_fts MATCH ?
            ORDER BY w.file_name, s.sheet_name, c.row_no, c.col_no
            """,
            (safe_q,),
        ).fetchall()

        report_rows = conn.execute(
            """
            SELECT w.file_name, w.file_path
            FROM report_names_fts f
            JOIN workbooks w ON w.id = f.workbook_id
            WHERE report_names_fts MATCH ?
            ORDER BY w.file_name
            """,
            (safe_q,),
        ).fetchall()
    finally:
        conn.close()

    hits: list[SearchHit] = []
    seen: set[tuple] = set()

    for fname, fpath in report_rows:
        key = ("report", fpath, "", 0, 0)
        if key in seen:
            continue
        seen.add(key)
        hits.append(SearchHit(
            hit_type="report",
            file_path=fpath, file_name=fname,
            report_name=_resolve_report_name(fpath),
            cell_value="\u62a5\u8868\u540d\u547d\u4e2d",
        ))

    for fname, fpath, sname, rno, cno, cval in cell_rows:
        key = ("cell", fpath, sname, rno, cno)
        if key in seen:
            continue
        seen.add(key)
        hits.append(SearchHit(
            hit_type="cell",
            file_path=fpath, file_name=fname,
            report_name=_resolve_report_name(fpath),
            sheet_name=sname, row_no=rno, col_no=cno, cell_value=cval,
        ))

    return hits[:limit]


def search_json(db_path: Path, keywords: str, limit: int = 20) -> list[dict]:
    return [asdict(h) for h in search(db_path, keywords, limit)]
