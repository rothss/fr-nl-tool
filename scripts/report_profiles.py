from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def init_profile_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS report_profiles (
                file_path TEXT PRIMARY KEY,
                report_name TEXT,
                dir_path TEXT,
                cpt_path TEXT,
                success_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                last_metric TEXT,
                last_metric_col TEXT,
                last_filters_json TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS report_profile_metrics (
                file_path TEXT NOT NULL,
                metric TEXT NOT NULL,
                metric_col TEXT,
                hit_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(file_path, metric)
            );

            CREATE TABLE IF NOT EXISTS report_profile_dimensions (
                file_path TEXT NOT NULL,
                dim_key TEXT NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(file_path, dim_key)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def apply_profile_boost(ranked: list[dict], db_path: Path, intent: dict) -> list[dict]:
    if not db_path.exists() or not ranked:
        return ranked
    metric = str(intent.get("metric") or "").strip()
    filters = intent.get("filters") or {}
    dim_keys = [k for k, v in filters.items() if v not in ("", None, [], {})]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        out: list[dict] = []
        for c in ranked:
            file_path = str(c.get("file_path") or "")
            score = float(c.get("score") or 0.0)
            breakdown = dict(c.get("score_breakdown") or {})
            prof = conn.execute(
                """
                SELECT success_count, fail_count
                FROM report_profiles
                WHERE file_path = ?
                """,
                (file_path,),
            ).fetchone()
            boost = 0.0
            if prof:
                succ = int(prof["success_count"] or 0)
                fail = int(prof["fail_count"] or 0)
                boost += min(15.0, succ * 1.2)
                boost -= min(8.0, fail * 0.8)
            if metric:
                mr = conn.execute(
                    """
                    SELECT hit_count
                    FROM report_profile_metrics
                    WHERE file_path = ? AND metric = ?
                    """,
                    (file_path, metric),
                ).fetchone()
                if mr:
                    boost += min(18.0, int(mr["hit_count"] or 0) * 2.0)
            for dk in dim_keys[:8]:
                dr = conn.execute(
                    """
                    SELECT hit_count
                    FROM report_profile_dimensions
                    WHERE file_path = ? AND dim_key = ?
                    """,
                    (file_path, dk),
                ).fetchone()
                if dr:
                    boost += min(6.0, int(dr["hit_count"] or 0) * 0.8)
            c2 = dict(c)
            c2["score"] = round(score + boost, 2)
            breakdown["profile_boost"] = round(boost, 2)
            c2["score_breakdown"] = breakdown
            out.append(c2)
        out.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
        return out
    finally:
        conn.close()


def record_profile_hit(
    db_path: Path,
    candidate: dict,
    intent: dict,
    metric_col: str | None,
    success: bool,
    cpt_path: str | None = None,
) -> None:
    init_profile_db(db_path)
    file_path = str(candidate.get("file_path") or "")
    report_name = str(candidate.get("report_name") or "")
    dir_path = str(candidate.get("dir_path") or "")
    metric = str(intent.get("metric") or "").strip()
    filters = intent.get("filters") or {}
    if not file_path:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO report_profiles(
                file_path, report_name, dir_path, cpt_path, success_count, fail_count, last_metric, last_metric_col, last_filters_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(file_path) DO UPDATE SET
                report_name=excluded.report_name,
                dir_path=excluded.dir_path,
                cpt_path=COALESCE(excluded.cpt_path, report_profiles.cpt_path),
                success_count=report_profiles.success_count + excluded.success_count,
                fail_count=report_profiles.fail_count + excluded.fail_count,
                last_metric=excluded.last_metric,
                last_metric_col=excluded.last_metric_col,
                last_filters_json=excluded.last_filters_json,
                updated_at=datetime('now')
            """,
            (
                file_path,
                report_name,
                dir_path,
                cpt_path or None,
                1 if success else 0,
                0 if success else 1,
                metric or None,
                metric_col or None,
                json.dumps(filters, ensure_ascii=False),
            ),
        )
        if metric and success:
            conn.execute(
                """
                INSERT INTO report_profile_metrics(file_path, metric, metric_col, hit_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(file_path, metric) DO UPDATE SET
                    metric_col=COALESCE(excluded.metric_col, report_profile_metrics.metric_col),
                    hit_count=report_profile_metrics.hit_count + 1
                """,
                (file_path, metric, metric_col or None),
            )
        if success:
            for k, v in (filters or {}).items():
                if v in ("", None, [], {}):
                    continue
                conn.execute(
                    """
                    INSERT INTO report_profile_dimensions(file_path, dim_key, hit_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(file_path, dim_key) DO UPDATE SET
                        hit_count=report_profile_dimensions.hit_count + 1
                    """,
                    (file_path, str(k)),
                )
        conn.commit()
    finally:
        conn.close()

