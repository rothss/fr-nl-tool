from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


_SCHEMA_SQL = """
DROP TABLE IF EXISTS report_names_fts;
DROP TABLE IF EXISTS cells_fts;
DROP TABLE IF EXISTS cells;
DROP TABLE IF EXISTS sheets;
DROP TABLE IF EXISTS workbooks;

CREATE TABLE workbooks (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    mtime REAL,
    size_bytes INTEGER
);

CREATE TABLE sheets (
    id INTEGER PRIMARY KEY,
    workbook_id INTEGER NOT NULL,
    sheet_name TEXT NOT NULL,
    max_row INTEGER NOT NULL,
    max_col INTEGER NOT NULL,
    UNIQUE(workbook_id, sheet_name),
    FOREIGN KEY (workbook_id) REFERENCES workbooks(id)
);

CREATE TABLE cells (
    id INTEGER PRIMARY KEY,
    sheet_id INTEGER NOT NULL,
    row_no INTEGER NOT NULL,
    col_no INTEGER NOT NULL,
    cell_value TEXT NOT NULL,
    FOREIGN KEY (sheet_id) REFERENCES sheets(id)
);

CREATE INDEX idx_sheets_workbook_id ON sheets(workbook_id);
CREATE INDEX idx_cells_sheet_id ON cells(sheet_id);
CREATE INDEX idx_cells_coord ON cells(sheet_id, row_no, col_no);

CREATE VIRTUAL TABLE cells_fts USING fts5(
    cell_value,
    content='cells',
    content_rowid='id'
);

CREATE VIRTUAL TABLE report_names_fts USING fts5(
    file_name,
    report_name,
    file_path UNINDEXED,
    workbook_id UNINDEXED
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def init_db_if_needed(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name='workbooks'"
    ).fetchone()
    if not row:
        init_db(conn)


def get_existing_workbook(conn: sqlite3.Connection, path: Path) -> tuple[int, float, int] | None:
    row = conn.execute(
        "SELECT id, mtime, size_bytes FROM workbooks WHERE file_path = ?",
        (str(path),),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), float(row[1]), int(row[2])


def delete_workbook_cascade(conn: sqlite3.Connection, workbook_id: int) -> None:
    sheet_ids = [
        r[0] for r in conn.execute("SELECT id FROM sheets WHERE workbook_id = ?", (workbook_id,))
    ]
    for sid in sheet_ids:
        conn.execute("DELETE FROM cells WHERE sheet_id = ?", (sid,))
    conn.execute("DELETE FROM sheets WHERE workbook_id = ?", (workbook_id,))
    conn.execute("DELETE FROM workbooks WHERE id = ?", (workbook_id,))
    conn.commit()


def insert_workbook(conn: sqlite3.Connection, path: Path) -> int:
    st = path.stat()
    cur = conn.execute(
        "INSERT INTO workbooks(file_path, file_name, extension, mtime, size_bytes) VALUES (?,?,?,?,?)",
        (str(path), path.name, path.suffix.lower(), st.st_mtime, st.st_size),
    )
    return int(cur.lastrowid)


def insert_sheet(conn: sqlite3.Connection, workbook_id: int, name: str, max_row: int, max_col: int) -> int:
    cur = conn.execute(
        "INSERT INTO sheets(workbook_id, sheet_name, max_row, max_col) VALUES (?,?,?,?)",
        (workbook_id, name, max_row, max_col),
    )
    return int(cur.lastrowid)


def bulk_insert_cells(conn: sqlite3.Connection, rows: list[tuple[int, int, int, str]]) -> int:
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO cells(sheet_id, row_no, col_no, cell_value) VALUES (?,?,?,?)",
        rows,
    )
    return len(rows)


def clear_workbook_contents(conn: sqlite3.Connection, workbook_id: int) -> None:
    sheet_ids = [
        r[0] for r in conn.execute("SELECT id FROM sheets WHERE workbook_id = ?", (workbook_id,))
    ]
    for sid in sheet_ids:
        conn.execute("DELETE FROM cells WHERE sheet_id = ?", (sid,))
    conn.execute("DELETE FROM sheets WHERE workbook_id = ?", (workbook_id,))
    conn.commit()
