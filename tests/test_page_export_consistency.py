"""
Tests for page-export data consistency verification.

Covers:
  - Normalization: empty, number, percent, date, whitespace
  - Comparison: visible_prefix_ordered, visible_subset_by_key, current_page_equal
  - Mock scenarios: pass, mismatch, missing row, format differences
"""

import json
import os
import sys
import unittest
from pathlib import Path

# Add scripts to path
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from e2e.normalize_table import (
    EMPTY_EQUIVALENTS,
    fill_merged_cells,
    is_empty,
    normalize_cell,
    normalize_date,
    normalize_empty,
    normalize_number,
    normalize_percent,
    normalize_rows,
    normalize_text,
    resolve_aliases,
)
from e2e.compare_table import (
    compare_current_page_equal,
    compare_visible_prefix_ordered,
    compare_visible_subset_by_key,
    format_compare_result,
    run_comparison,
)


class TestNormalizeEmpty(unittest.TestCase):
    """Test empty value normalization."""

    def test_is_empty_none(self):
        self.assertTrue(is_empty(None))

    def test_is_empty_string(self):
        self.assertTrue(is_empty(""))
        self.assertTrue(is_empty("-"))
        self.assertTrue(is_empty("--"))
        self.assertTrue(is_empty("—"))
        self.assertTrue(is_empty("N/A"))
        self.assertTrue(is_empty("NA"))
        self.assertTrue(is_empty("无"))

    def test_is_not_empty(self):
        self.assertFalse(is_empty("hello"))
        self.assertFalse(is_empty("0"))
        self.assertFalse(is_empty(0))
        self.assertFalse(is_empty(False))

    def test_normalize_empty(self):
        self.assertIsNone(normalize_empty(None))
        self.assertIsNone(normalize_empty(""))
        self.assertIsNone(normalize_empty("-"))
        self.assertEqual(normalize_empty("hello"), "hello")


class TestNormalizeText(unittest.TestCase):
    """Test text normalization."""

    def test_whitespace(self):
        self.assertEqual(normalize_text("  hello  "), "hello")
        self.assertEqual(normalize_text("hello  world"), "hello world")
        self.assertEqual(normalize_text("hello\u3000world"), "hello world")  # full-width space

    def test_empty_text(self):
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text("   "), "")


class TestNormalizeNumber(unittest.TestCase):
    """Test number normalization."""

    def test_integer(self):
        self.assertEqual(normalize_number(42), 42.0)
        self.assertEqual(normalize_number(0), 0.0)

    def test_float(self):
        self.assertEqual(normalize_number(3.14), 3.14)

    def test_string_integer(self):
        self.assertEqual(normalize_number("42"), 42.0)
        self.assertEqual(normalize_number(" 1234 "), 1234.0)

    def test_thousands_separator(self):
        self.assertEqual(normalize_number("1,234.50"), 1234.5)
        self.assertEqual(normalize_number("1,234"), 1234.0)

    def test_chinese_comma(self):
        self.assertEqual(normalize_number("1，234.50"), 1234.5)

    def test_non_number(self):
        self.assertEqual(normalize_number("hello"), "hello")
        self.assertIsNone(normalize_number(""))
        self.assertIsNone(normalize_number("-"))

    def test_currency(self):
        self.assertEqual(normalize_number("¥100"), 100.0)
        self.assertEqual(normalize_number("$50.5"), 50.5)


class TestNormalizePercent(unittest.TestCase):
    """Test percentage normalization."""

    def test_percent_string(self):
        self.assertAlmostEqual(normalize_percent("12.3%"), 0.123, places=5)
        self.assertAlmostEqual(normalize_percent("5.1%"), 0.051, places=5)
        self.assertAlmostEqual(normalize_percent("100%"), 1.0, places=5)
        self.assertAlmostEqual(normalize_percent("0%"), 0.0, places=5)

    def test_percent_decimal(self):
        self.assertEqual(normalize_percent(0.123), 0.123)

    def test_percent_with_comma(self):
        self.assertEqual(normalize_percent("1,234.5%"), 12.345)

    def test_percent_negative(self):
        self.assertEqual(normalize_percent("-5.0%"), -0.05)

    def test_empty_percent(self):
        self.assertIsNone(normalize_percent(""))
        self.assertIsNone(normalize_percent("-"))


class TestNormalizeDate(unittest.TestCase):
    """Test date normalization."""

    def test_chinese_format(self):
        self.assertEqual(normalize_date("2026年5月"), "2026-05")
        self.assertEqual(normalize_date("2026年12月"), "2026-12")

    def test_slash_format(self):
        self.assertEqual(normalize_date("2026/05"), "2026-05")

    def test_dash_format(self):
        self.assertEqual(normalize_date("2026-05"), "2026-05")
        self.assertEqual(normalize_date("2026-05-01", granularity="day"), "2026-05-01")

    def test_day_granularity(self):
        self.assertEqual(normalize_date("2026-05-01", granularity="day"), "2026-05-01")
        self.assertEqual(normalize_date("2026年5月1日", granularity="day"), "2026-05-01")

    def test_month_granularity(self):
        self.assertEqual(normalize_date("2026-05-01", granularity="month"), "2026-05")

    def test_empty_date(self):
        self.assertIsNone(normalize_date(""))
        self.assertIsNone(normalize_date("-"))


class TestMergedCells(unittest.TestCase):
    """Test merged cell filling."""

    def test_fill_simple(self):
        rows = [
            {"A": "X", "B": "1"},
            {"A": "", "B": "2"},
            {"A": "", "B": "3"},
        ]
        filled = fill_merged_cells(rows, key_columns=["A", "B"])
        self.assertEqual(filled[0]["A"], "X")
        self.assertEqual(filled[1]["A"], "X")
        self.assertEqual(filled[2]["A"], "X")

    def test_fill_multiple_blocks(self):
        rows = [
            {"A": "X", "B": "1"},
            {"A": "", "B": "2"},
            {"A": "Y", "B": "3"},
            {"A": "", "B": "4"},
        ]
        filled = fill_merged_cells(rows)
        self.assertEqual(filled[0]["A"], "X")
        self.assertEqual(filled[1]["A"], "X")
        self.assertEqual(filled[2]["A"], "Y")
        self.assertEqual(filled[3]["A"], "Y")

    def test_fill_specific_columns(self):
        rows = [
            {"A": "X", "B": "1"},
            {"A": "", "B": ""},
            {"A": "Y", "B": "3"},
        ]
        filled = fill_merged_cells(rows, key_columns=["A"])
        self.assertEqual(filled[0]["A"], "X")
        self.assertEqual(filled[1]["A"], "X")
        self.assertEqual(filled[2]["A"], "Y")
        # B column should NOT be filled (not in key_columns)
        self.assertEqual(filled[1]["B"], "")


class TestAliasResolution(unittest.TestCase):
    """Test alias resolution."""

    def test_resolve_alias(self):
        rows = [
            {"航司": "东航", "净利润": 100},
            {"航司": "中国东方航空", "净利润": 200},
        ]
        aliases = {
            "航司": {
                "东方航空": ["东航", "中国东方航空"],
            }
        }
        resolved = resolve_aliases(rows, aliases)
        self.assertEqual(resolved[0]["航司"], "东方航空")
        self.assertEqual(resolved[1]["航司"], "东方航空")

    def test_no_alias_change(self):
        rows = [{"航司": "南方航空", "净利润": 100}]
        aliases = {
            "航司": {
                "东方航空": ["东航"],
            }
        }
        resolved = resolve_aliases(rows, aliases)
        self.assertEqual(resolved[0]["航司"], "南方航空")


class TestNormalizeRows(unittest.TestCase):
    """Test combined row normalization."""

    def test_normalize_combined(self):
        rows = [
            {"航司": "东航", "月份": "2026年5月", "净利润": "1,234.50", "同比": "12.3%"},
        ]
        normalized = normalize_rows(
            rows,
            date_columns=["月份"],
            percent_columns=["同比"],
            numeric_columns=["净利润"],
            fill_merged=False,
        )
        self.assertEqual(normalized[0]["月份"], "2026-05")
        self.assertEqual(normalized[0]["净利润"], 1234.5)
        self.assertAlmostEqual(normalized[0]["同比"], 0.123, places=5)

    def test_normalize_ignore_columns(self):
        rows = [
            {"序号": "-", "航司": "东航", "净利润": "100"},
        ]
        normalized = normalize_rows(
            rows,
            ignore_columns=["序号"],
            fill_merged=False,
        )
        self.assertEqual(normalized[0]["序号"], "-")  # preserved as-is
        self.assertEqual(normalized[0]["净利润"], 100.0)


class TestCompareVisiblePrefixOrdered(unittest.TestCase):
    """Test visible_prefix_ordered comparison mode."""

    def test_pass_perfect_match(self):
        page = [
            {"A": 1, "B": 2},
            {"A": 3, "B": 4},
        ]
        export = [
            {"A": 1, "B": 2},
            {"A": 3, "B": 4},
            {"A": 5, "B": 6},  # extra row
        ]
        result = compare_visible_prefix_ordered(page, export, value_columns=["A", "B"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["matched_rows"], 2)
        self.assertEqual(result["extra_export_rows"], 1)

    def test_pass_page_subset_of_export(self):
        page = _make_rows(20, start=1)
        export = _make_rows(3000, start=1)
        result = compare_visible_prefix_ordered(page, export, value_columns=["A", "B"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["page_rows"], 20)
        self.assertEqual(result["export_rows"], 3000)
        self.assertEqual(result["extra_export_rows"], 2980)

    def test_fail_value_mismatch(self):
        page = [
            {"A": 1, "B": 2},
            {"A": 3, "B": 4},
        ]
        export = [
            {"A": 1, "B": 2},
            {"A": 3, "B": 99},  # mismatch on B
            {"A": 5, "B": 6},
        ]
        result = compare_visible_prefix_ordered(page, export, value_columns=["A", "B"])
        self.assertFalse(result["ok"])
        self.assertTrue(any(d["column"] == "B" and d["row_index"] == 2 for d in result["diffs"]))

    def test_fail_export_too_short(self):
        page = _make_rows(20, start=1)
        export = _make_rows(10, start=1)
        result = compare_visible_prefix_ordered(page, export, value_columns=["A", "B"])
        self.assertFalse(result["ok"])
        self.assertIn("export rows fewer", result.get("error", ""))


class TestCompareVisibleSubsetByKey(unittest.TestCase):
    """Test visible_subset_by_key comparison mode."""

    def test_pass_all_found(self):
        page = [
            {"航司": "A1", "月": "01", "V": 100},
            {"航司": "A2", "月": "02", "V": 200},
        ]
        export = [
            {"航司": "A1", "月": "01", "V": 100},
            {"航司": "A2", "月": "02", "V": 200},
            {"航司": "A3", "月": "03", "V": 300},  # extra
        ]
        result = compare_visible_subset_by_key(
            page, export,
            key_columns=["航司", "月"],
            value_columns=["V"],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["matched_rows"], 2)
        self.assertEqual(result["extra_export_rows"], 1)

    def test_pass_different_order(self):
        page = [
            {"航司": "A2", "月": "02", "V": 200},
            {"航司": "A1", "月": "01", "V": 100},
        ]
        export = [
            {"航司": "A1", "月": "01", "V": 100},
            {"航司": "A2", "月": "02", "V": 200},
        ]
        result = compare_visible_subset_by_key(
            page, export,
            key_columns=["航司", "月"],
            value_columns=["V"],
        )
        self.assertTrue(result["ok"])

    def test_fail_missing_key(self):
        page = [
            {"航司": "A1", "月": "01", "V": 100},
            {"航司": "A2", "月": "02", "V": 200},
        ]
        export = [
            {"航司": "A1", "月": "01", "V": 100},
        ]
        result = compare_visible_subset_by_key(
            page, export,
            key_columns=["航司", "月"],
            value_columns=["V"],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["missing_in_export"]), 1)

    def test_pass_large_subset(self):
        page = _make_subset_rows(20, start=1)
        export = _make_subset_rows(3000, start=1)
        result = compare_visible_subset_by_key(
            page, export,
            key_columns=["航司", "月份"],
            value_columns=["净利润", "同比"],
        )
        self.assertTrue(result["ok"])

    def test_fail_value_mismatch(self):
        page = [
            {"航司": "A1", "月": "01", "V": 100},
        ]
        export = [
            {"航司": "A1", "月": "01", "V": 999},
        ]
        result = compare_visible_subset_by_key(
            page, export,
            key_columns=["航司", "月"],
            value_columns=["V"],
        )
        self.assertFalse(result["ok"])

    def test_tolerance(self):
        page = [
            {"航司": "A1", "月": "01", "V": 100.0},
        ]
        export = [
            {"航司": "A1", "月": "01", "V": 100.005},
        ]
        result = compare_visible_subset_by_key(
            page, export,
            key_columns=["航司", "月"],
            value_columns=["V"],
            tolerance=0.01,
        )
        self.assertTrue(result["ok"])


class TestCompareCurrentPageEqual(unittest.TestCase):
    """Test current_page_equal comparison mode."""

    def test_pass_exact_match(self):
        page = _make_rows(20, start=1)
        export = _make_rows(20, start=1)
        result = compare_current_page_equal(page, export, value_columns=["A", "B"])
        self.assertTrue(result["ok"])

    def test_fail_row_count_mismatch(self):
        page = _make_rows(20, start=1)
        export = _make_rows(3000, start=1)
        result = compare_current_page_equal(page, export, value_columns=["A", "B"])
        self.assertFalse(result["ok"])
        self.assertIn("row count mismatch", result.get("error", ""))

    def test_fail_value_mismatch(self):
        page = _make_rows(5, start=1)
        export = _make_rows(5, start=1)
        export[2]["A"] = 999
        result = compare_current_page_equal(page, export, value_columns=["A", "B"])
        self.assertFalse(result["ok"])


class TestRunComparison(unittest.TestCase):
    """Test run_comparison dispatcher."""

    def test_prefix_mode(self):
        config = {"mode": "visible_prefix_ordered", "value_columns": ["A"]}
        page = [{"A": 1}, {"A": 2}]
        export = [{"A": 1}, {"A": 2}, {"A": 3}]
        result = run_comparison(page, export, config)
        self.assertEqual(result["mode"], "visible_prefix_ordered")
        self.assertTrue(result["ok"])

    def test_subset_mode(self):
        config = {
            "mode": "visible_subset_by_key",
            "key_columns": ["K"],
            "value_columns": ["V"],
        }
        page = [{"K": "x", "V": 1}]
        export = [{"K": "x", "V": 1}, {"K": "y", "V": 2}]
        result = run_comparison(page, export, config)
        self.assertTrue(result["ok"])

    def test_current_page_mode(self):
        config = {"mode": "current_page_equal", "value_columns": ["A"]}
        page = [{"A": 1}]
        export = [{"A": 1}]
        result = run_comparison(page, export, config)
        self.assertTrue(result["ok"])


class TestPercentFormatConsistency(unittest.TestCase):
    """Test that percentage format differences pass correctly (Section 15.5)."""

    def test_percent_string_vs_decimal(self):
        page = [
            {"航司": "东航", "月份": "2026-05", "净利润": 100, "同比": "12.3%"},
        ]
        export = [
            {"航司": "东航", "月份": "2026-05", "净利润": 100, "同比": 0.123},
        ]
        from e2e.normalize_table import normalize_rows
        page_norm = normalize_rows(
            page, percent_columns=["同比"], numeric_columns=["净利润"],
            fill_merged=False,
        )
        export_norm = normalize_rows(
            export, percent_columns=["同比"], numeric_columns=["净利润"],
            fill_merged=False,
        )
        result = compare_visible_subset_by_key(
            page_norm, export_norm,
            key_columns=["航司", "月份"],
            value_columns=["净利润", "同比"],
            tolerance=0.0001,
        )
        self.assertTrue(result["ok"], f"Expected PASS but got: {result}")


class TestNumberFormatConsistency(unittest.TestCase):
    """Test that number thousands format differences pass correctly (Section 15.6)."""

    def test_thousands_string_vs_number(self):
        page = [
            {"航司": "东航", "月份": "2026-05", "净利润": "1,234.50", "同比": 0.123},
        ]
        export = [
            {"航司": "东航", "月份": "2026-05", "净利润": 1234.5, "同比": 0.123},
        ]
        from e2e.normalize_table import normalize_rows
        page_norm = normalize_rows(
            page, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        export_norm = normalize_rows(
            export, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        result = compare_visible_subset_by_key(
            page_norm, export_norm,
            key_columns=["航司", "月份"],
            value_columns=["净利润", "同比"],
        )
        self.assertTrue(result["ok"], f"Expected PASS but got: {result}")

    def test_negative_parentheses(self):
        """(1,234.50) should normalize to -1234.5"""
        page = [
            {"航司": "东航", "月份": "2026-05", "净利润": "(1,234.50)", "同比": 0.05},
        ]
        export = [
            {"航司": "东航", "月份": "2026-05", "净利润": -1234.5, "同比": 0.05},
        ]
        from e2e.normalize_table import normalize_rows
        page_norm = normalize_rows(
            page, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        export_norm = normalize_rows(
            export, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        result = compare_visible_subset_by_key(
            page_norm, export_norm,
            key_columns=["航司", "月份"],
            value_columns=["净利润", "同比"],
        )
        self.assertTrue(result["ok"], f"Expected PASS but got: {result}")

    def test_chinese_wan_unit(self):
        """1.2万 should normalize to 12000"""
        page = [
            {"航司": "东航", "月份": "2026-05", "净利润": "1.2万", "同比": 0.05},
        ]
        export = [
            {"航司": "东航", "月份": "2026-05", "净利润": 12000, "同比": 0.05},
        ]
        from e2e.normalize_table import normalize_rows
        page_norm = normalize_rows(
            page, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        export_norm = normalize_rows(
            export, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        result = compare_visible_subset_by_key(
            page_norm, export_norm,
            key_columns=["航司", "月份"],
            value_columns=["净利润", "同比"],
        )
        self.assertTrue(result["ok"], f"Expected PASS but got: {result}")

    def test_chinese_yi_unit(self):
        """3.5亿 should normalize to 350000000"""
        page = [
            {"航司": "东航", "月份": "2026-05", "净利润": "3.5亿", "同比": 0.05},
        ]
        export = [
            {"航司": "东航", "月份": "2026-05", "净利润": 350000000, "同比": 0.05},
        ]
        from e2e.normalize_table import normalize_rows
        page_norm = normalize_rows(
            page, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        export_norm = normalize_rows(
            export, numeric_columns=["净利润"], percent_columns=["同比"],
            fill_merged=False,
        )
        result = compare_visible_subset_by_key(
            page_norm, export_norm,
            key_columns=["航司", "月份"],
            value_columns=["净利润", "同比"],
        )
        self.assertTrue(result["ok"], f"Expected PASS but got: {result}")

    def test_chinese_wan_no_config_needed(self):
        """Chinese 万 unit should work without explicit config (auto-detect)"""
        from e2e.normalize_table import _try_parse_number
        ok, val = _try_parse_number("1.2万")
        self.assertTrue(ok)
        self.assertAlmostEqual(val, 12000)

    def test_negative_parentheses_no_config_needed(self):
        """Negative parentheses should work without explicit config"""
        from e2e.normalize_table import _try_parse_number
        ok, val = _try_parse_number("(1234.50)")
        self.assertTrue(ok)
        self.assertAlmostEqual(val, -1234.50)


class TestFormatCompareResult(unittest.TestCase):
    """Test human-readable formatting."""

    def test_pass_format(self):
        result = {
            "ok": True,
            "mode": "visible_subset_by_key",
            "page_rows": 20,
            "export_rows": 3000,
            "matched_rows": 20,
            "extra_export_rows": 2980,
        }
        text = format_compare_result(result, case_name="test", report_name="R1")
        self.assertIn("PASS", text)
        self.assertIn("visible_subset_by_key", text)

    def test_fail_format(self):
        result = {
            "ok": False,
            "mode": "visible_prefix_ordered",
            "page_rows": 20,
            "export_rows": 3000,
            "matched_rows": 19,
            "extra_export_rows": 2980,
            "diffs": [
                {"row_index": 7, "column": "净利润", "page": 100, "export": 999}
            ],
        }
        text = format_compare_result(result, case_name="test", report_name="R1")
        self.assertIn("FAIL", text)
        self.assertIn("Different values", text)


# ---- Helpers ----

def _make_rows(n: int, start: int = 1) -> list[dict]:
    return [{"A": i, "B": i * 2} for i in range(start, start + n)]


def _make_subset_rows(n: int, start: int = 1) -> list[dict]:
    rows = []
    for i in range(start, start + n):
        rows.append({
            "航司": f"航司_{(i % 10) + 1}",
            "月份": f"2026-{(i % 12) + 1:02d}",
            "净利润": 100.0 + i * 10.5,
            "同比": round(0.05 + i * 0.005, 3),
        })
    return rows


if __name__ == "__main__":
    unittest.main()
