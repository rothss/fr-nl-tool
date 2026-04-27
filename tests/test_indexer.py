"""Tests for search/indexer.py — Excel indexing pipeline."""
import sys
import sqlite3
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class IndexerTests(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        from search.db import init_db
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_insert_workbook_and_sheet_roundtrip(self):
        from search.db import insert_workbook, insert_sheet, get_existing_workbook
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake xlsx")
            tmp = f.name
        try:
            wb_id = insert_workbook(self.conn, Path(tmp))
            self.assertGreater(wb_id, 0)

            sh_id = insert_sheet(self.conn, wb_id, "Page1", 100, 20)
            self.assertGreater(sh_id, 0)

            existing = get_existing_workbook(self.conn, Path(tmp))
            self.assertIsNotNone(existing)
            self.assertEqual(existing[0], wb_id)
        finally:
            os.unlink(tmp)

    def test_bulk_insert_cells(self):
        from search.db import insert_workbook, insert_sheet, bulk_insert_cells
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake")
            tmp = f.name
        try:
            wb_id = insert_workbook(self.conn, Path(tmp))
            sh_id = insert_sheet(self.conn, wb_id, "S1", 10, 5)
            rows = [(sh_id, 1, 1, "hello"), (sh_id, 1, 2, "world")]
            n = bulk_insert_cells(self.conn, rows)
            self.assertEqual(n, 2)
            cnt = self.conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
            self.assertEqual(cnt, 2)
        finally:
            os.unlink(tmp)

    def test_delete_workbook_cascade(self):
        from search.db import insert_workbook, insert_sheet, bulk_insert_cells, delete_workbook_cascade
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp = f.name
        try:
            wb_id = insert_workbook(self.conn, Path(tmp))
            sh_id = insert_sheet(self.conn, wb_id, "S1", 1, 1)
            bulk_insert_cells(self.conn, [(sh_id, 1, 1, "x")])
            delete_workbook_cascade(self.conn, wb_id)
            self.assertEqual(
                self.conn.execute("SELECT COUNT(*) FROM workbooks").fetchone()[0], 0)
            self.assertEqual(
                self.conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0], 0)
        finally:
            os.unlink(tmp)

    def test_index_stats_dataclass(self):
        from search.indexer import IndexStats
        s = IndexStats(files_indexed=3, sheets_indexed=5, cells_indexed=100, files_failed=1, files_skipped=2)
        self.assertEqual(s.files_indexed, 3)
        self.assertEqual(s.files_failed, 1)
        self.assertEqual(s.files_skipped, 2)

    def test_iter_files_filters(self):
        from search.indexer import _iter_files
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "good.xlsx").write_text("")
            (root / "bad.txt").write_text("")
            (root / "~$temp.xlsx").write_text("")
            (root / "manifest.csv").write_text("")
            files = _iter_files(root)
            names = {f.name for f in files}
            self.assertIn("good.xlsx", names)
            self.assertNotIn("bad.txt", names)
            self.assertNotIn("~$temp.xlsx", names)
            self.assertNotIn("manifest.csv", names)


if __name__ == "__main__":
    unittest.main()
