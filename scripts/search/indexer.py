from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import (
    bulk_insert_cells,
    clear_workbook_contents,
    connect_db,
    delete_workbook_cascade,
    get_existing_workbook,
    init_db,
    init_db_if_needed,
    insert_sheet,
    insert_workbook,
)
from .normalizer import normalize_value
from .parsers import SUPPORTED, parse_file

EXCLUDED_NAMES = {"manifest.csv", "manifest.backup.csv"}
EXCLUDED_NAME_PARTS = ("__recovered", "__nested_recovered")


@dataclass
class IndexStats:
    files_indexed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    sheets_indexed: int = 0
    cells_indexed: int = 0


def _iter_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED:
            continue
        if p.name.startswith("~$"):
            continue
        if p.name.lower() in EXCLUDED_NAMES:
            continue
        if any(part in p.stem for part in EXCLUDED_NAME_PARTS):
            continue
        result.append(p)
    return result


def _index_one(conn, path: Path, stats: IndexStats, drop_numeric: bool) -> None:
    wb_id = insert_workbook(conn, path)
    try:
        sheets_data = parse_file(path, drop_numeric=drop_numeric)
    except Exception:
        clear_workbook_contents(conn, wb_id)
        raise

    for sheet_name, rows in sheets_data.items():
        max_r = max((r for r, _, _ in rows), default=0)
        max_c = max((c for _, c, _ in rows), default=0)
        sheet_id = insert_sheet(conn, wb_id, sheet_name, max_r, max_c)
        stats.sheets_indexed += 1
        batch = [(sheet_id, r, c, v) for r, c, v in rows]
        stats.cells_indexed += bulk_insert_cells(conn, batch)
        conn.commit()
    stats.files_indexed += 1


def _index_incremental(conn, path: Path, stats: IndexStats, drop_numeric: bool) -> str:
    st = path.stat()
    existing = get_existing_workbook(conn, path)
    if existing is not None:
        _, mtime, size = existing
        if mtime == st.st_mtime and size == st.st_size:
            stats.files_skipped += 1
            return "skipped"
        delete_workbook_cascade(conn, existing[0])
    _index_one(conn, path, stats, drop_numeric)
    return "indexed"


def _rebuild_fts(conn, drop_numeric: bool) -> None:
    conn.execute("INSERT INTO cells_fts(cells_fts) VALUES ('rebuild')")
    conn.execute("DELETE FROM report_names_fts")
    wbs = conn.execute("SELECT id, file_name, file_path FROM workbooks").fetchall()
    batch: list[tuple[str, str, str, int]] = []
    for wb_id, fname, fpath in wbs:
        n_name = normalize_value(fname, drop_numeric=drop_numeric)
        rel = Path(fpath)
        try:
            rel = rel.relative_to(Path.cwd())
        except ValueError:
            pass
        rpt = normalize_value(str(rel.with_suffix("")).replace("\\", "/"), drop_numeric=drop_numeric)
        if n_name is None and rpt is None:
            continue
        batch.append((n_name or "", rpt or "", str(fpath), wb_id))
    conn.executemany(
        "INSERT INTO report_names_fts(file_name, report_name, file_path, workbook_id) VALUES (?,?,?,?)",
        batch,
    )
    conn.commit()


def build_index(
    root: Path,
    db_path: Path,
    incremental: bool = True,
    drop_numeric: bool = True,
) -> IndexStats:
    if not root.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root}")

    conn = connect_db(db_path)
    if incremental:
        init_db_if_needed(conn)
    else:
        init_db(conn)
    stats = IndexStats()
    files = _iter_files(root)

    try:
        for path in files:
            try:
                if incremental:
                    _index_incremental(conn, path, stats, drop_numeric)
                else:
                    _index_one(conn, path, stats, drop_numeric)
            except Exception:
                stats.files_failed += 1
                try:
                    conn.rollback()
                except Exception:
                    pass
        _rebuild_fts(conn, drop_numeric)
    finally:
        conn.close()

    return stats
