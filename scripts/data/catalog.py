from __future__ import annotations

import sqlite3
from pathlib import Path

from rank_report_candidates import rank_candidates


def load_catalog(db_path: str | Path) -> dict:
    path = Path(db_path)
    return {"db_path": path, "exists": path.exists()}


def _query_reports_by_name(db_path: Path, report_name: str) -> list[dict]:
    if not db_path.exists() or not str(report_name or "").strip():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, report_name, file_path, dir_path
            FROM reports
            WHERE report_name = ?
            ORDER BY id ASC
            """,
            (str(report_name),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "report_id": int(row["id"]),
            "report_name": str(row["report_name"] or ""),
            "file_path": str(row["file_path"] or ""),
            "dir_path": str(row["dir_path"] or ""),
            "score": 999.0,
            "score_breakdown": {"preferred_report_name": 999.0},
        }
        for row in rows
    ]


def find_report_candidates(
    intent: dict,
    catalog: dict | str | Path,
    preferred_report_name: str | None = None,
    top_n: int = 5,
) -> list[dict]:
    db_path = Path(catalog["db_path"]) if isinstance(catalog, dict) else Path(catalog)
    result: list[dict] = []

    seen: set[tuple[str, str]] = set()

    def _add(items: list[dict]) -> None:
        for item in items:
            key = (str(item.get("report_name") or ""), str(item.get("file_path") or ""))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)

    if preferred_report_name:
        _add(_query_reports_by_name(db_path, preferred_report_name))

    if db_path.exists():
        _add(rank_candidates(intent, db_path, top_n=max(top_n, 8)))

    return result[:top_n]
