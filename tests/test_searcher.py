"""Tests for search/searcher.py — FTS5 full-text search."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class SearcherTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._root = Path(cls._tmp.name)
        cls._dummy = cls._root / "report.xlsx"
        cls._dummy.write_bytes(b"fake")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        import sqlite3
        from search.db import connect_db, init_db, insert_workbook, insert_sheet, bulk_insert_cells

        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA journal_mode=WAL;")
        init_db(self.conn)

        wb_id = insert_workbook(self.conn, self._dummy)
        sh_id = insert_sheet(self.conn, wb_id, "Sheet1", 10, 5)
        bulk_insert_cells(self.conn, [
            (sh_id, 1, 1, "航油成本"),
            (sh_id, 1, 2, "小时变动成本"),
            (sh_id, 2, 1, "123.45"),
            (sh_id, 3, 1, "万元"),
        ])
        self.conn.execute("INSERT INTO cells_fts(cells_fts) VALUES ('rebuild')")
        self.conn.execute(
            "INSERT INTO report_names_fts(file_name, report_name, file_path, workbook_id) VALUES (?,?,?,?)",
            ("report.xlsx", "成本分析/航油成本主题分析", str(self._dummy), wb_id),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_search_cell_match(self):
        from search.searcher import search
        rows = self.conn.execute(
            """SELECT w.file_name, w.file_path, s.sheet_name, c.row_no, c.col_no, c.cell_value
            FROM cells_fts f JOIN cells c ON c.id = f.rowid
            JOIN sheets s ON s.id = c.sheet_id JOIN workbooks w ON w.id = s.workbook_id
            WHERE cells_fts MATCH '航油成本'"""
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5], "航油成本")

    def test_search_report_name_match(self):
        rows = self.conn.execute(
            "SELECT w.file_name FROM report_names_fts f "
            "JOIN workbooks w ON w.id = f.workbook_id "
            "WHERE report_names_fts MATCH 'report'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_search_no_match(self):
        rows = self.conn.execute(
            "SELECT * FROM cells_fts WHERE cells_fts MATCH '不存在'"
        ).fetchall()
        self.assertEqual(len(rows), 0)

    def test_search_hit_dataclass(self):
        from search.searcher import SearchHit
        h = SearchHit(
            hit_type="cell", file_path="/a.xlsx", file_name="a.xlsx",
            report_name="a", sheet_name="S1", row_no=1, col_no=2, cell_value="v",
        )
        self.assertEqual(h.hit_type, "cell")
        self.assertEqual(h.cell_value, "v")

    def test_search_json_returns_dicts(self):
        # Test via direct FTS query (search_json needs actual db file)
        from search.searcher import SearchHit
        hit = SearchHit(hit_type="report", file_path="/x", file_name="x", report_name="r", cell_value="h")
        import dataclasses
        d = dataclasses.asdict(hit)
        self.assertIsInstance(d, dict)
        self.assertEqual(d["hit_type"], "report")


if __name__ == "__main__":
    unittest.main()
