"""
Consistency comparison between page snapshot and export snapshot.

Supports three comparison modes:
  1. visible_prefix_ordered  - Page rows must match first N export rows in order
  2. visible_subset_by_key   - Page rows must exist in export (any order) by business key
  3. current_page_equal      - Page and export must be identical (same rows, same count)
  4. all_pages_equal         - All collected page rows must equal all export rows
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from .normalize_table import normalize_rows


def _make_key(row: dict, key_columns: list[str]) -> tuple:
    """Create a hashable key from a row using specified key columns."""
    return tuple(str(row.get(col, "") or "") for col in key_columns)


def _values_equal(a: object, b: object, tolerance: float = 0.0) -> bool:
    """Compare two normalized values with optional numeric tolerance.

    Args:
        a, b: Normalized values (both should be the same type after normalization)
        tolerance: Allowed difference for numeric comparison
    """
    # Both None/empty
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    # Both numeric
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if tolerance > 0:
            return abs(float(a) - float(b)) <= tolerance
        return float(a) == float(b)

    # One numeric, one string - try parsing
    if isinstance(a, (int, float)) and isinstance(b, str):
        from .normalize_table import _try_parse_number
        ok, num = _try_parse_number(b)
        if ok and num is not None:
            if tolerance > 0:
                return abs(float(a) - num) <= tolerance
            return float(a) == num
        return False

    if isinstance(a, str) and isinstance(b, (int, float)):
        from .normalize_table import _try_parse_number
        ok, num = _try_parse_number(a)
        if ok and num is not None:
            if tolerance > 0:
                return abs(num - float(b)) <= tolerance
            return num == float(b)
        return False

    # String comparison
    return str(a).strip() == str(b).strip()


def compare_visible_prefix_ordered(
    page_rows: list[dict],
    export_rows: list[dict],
    value_columns: list[str],
    tolerance: float = 0.0,
) -> dict:
    """Compare page rows against the first N export rows in order.

    Rule: export_rows[0:N] must equal page_rows[0:N] column by column.
    Extra export rows are allowed (not a failure).

    Returns:
        {
            "ok": bool,
            "mode": "visible_prefix_ordered",
            "page_rows": int,
            "export_rows": int,
            "matched_rows": int,
            "extra_export_rows": int,
            "diffs": [...],
        }
    """
    n = len(page_rows)
    if len(export_rows) < n:
        return {
            "ok": False,
            "mode": "visible_prefix_ordered",
            "page_rows": n,
            "export_rows": len(export_rows),
            "matched_rows": 0,
            "extra_export_rows": 0,
            "error": "export rows fewer than page rows",
            "diffs": [],
        }

    diffs: list[dict] = []
    for i in range(n):
        page_row = page_rows[i]
        export_row = export_rows[i]
        for col in value_columns:
            page_val = page_row.get(col)
            export_val = export_row.get(col)
            if not _values_equal(page_val, export_val, tolerance):
                diffs.append({
                    "row_index": i + 1,
                    "column": col,
                    "page": page_val,
                    "export": export_val,
                })

    return {
        "ok": len(diffs) == 0,
        "mode": "visible_prefix_ordered",
        "page_rows": n,
        "export_rows": len(export_rows),
        "matched_rows": n - len({d["row_index"] for d in diffs}) if diffs else n,
        "extra_export_rows": len(export_rows) - n,
        "diffs": diffs,
    }


def compare_visible_subset_by_key(
    page_rows: list[dict],
    export_rows: list[dict],
    key_columns: list[str],
    value_columns: list[str],
    tolerance: float = 0.0,
    allow_row_reorder: bool = True,
) -> dict:
    """Compare page rows exist in export by business key lookup.

    Rule: Every page row must have a matching row in export with the same key
    and consistent value columns. Extra export rows are allowed.
    Row order does not need to match.

    Returns:
        {
            "ok": bool,
            "mode": "visible_subset_by_key",
            "page_rows": int,
            "export_rows": int,
            "matched_rows": int,
            "extra_export_rows": int,
            "missing_in_export": [...],
            "diffs": [...],
        }
    """
    # Build export lookup map
    export_map: dict[tuple, list[dict]] = {}
    for row in export_rows:
        key = _make_key(row, key_columns)
        export_map.setdefault(key, []).append(row)

    missing_in_export: list[dict] = []
    diffs: list[dict] = []

    for page_row in page_rows:
        key = _make_key(page_row, key_columns)

        if key not in export_map:
            missing_in_export.append({
                "key": list(key),
                "page_row": page_row,
            })
            continue

        candidates = export_map[key]
        matched = False
        candidate_diffs: list[list[dict]] = []

        for export_row in candidates:
            row_diffs: list[dict] = []
            all_cols_matched = True

            for col in value_columns:
                page_val = page_row.get(col)
                export_val = export_row.get(col)
                if not _values_equal(page_val, export_val, tolerance):
                    row_diffs.append({
                        "column": col,
                        "page": page_val,
                        "export": export_val,
                    })
                    all_cols_matched = False

            if all_cols_matched:
                matched = True
                break

            candidate_diffs.append(row_diffs)

        if not matched:
            diffs.append({
                "key": list(key),
                "page_row": page_row,
                "export_candidates": candidates[:3],  # limit for readability
                "candidate_diffs": candidate_diffs[:3],
            })

    ok = len(missing_in_export) == 0 and len(diffs) == 0

    return {
        "ok": ok,
        "mode": "visible_subset_by_key",
        "page_rows": len(page_rows),
        "export_rows": len(export_rows),
        "matched_rows": len(page_rows) - len(missing_in_export) - len(diffs),
        "extra_export_rows": len(export_rows) - len(page_rows),
        "missing_in_export": missing_in_export,
        "diffs": diffs,
    }


def compare_current_page_equal(
    page_rows: list[dict],
    export_rows: list[dict],
    value_columns: list[str],
    tolerance: float = 0.0,
) -> dict:
    """Compare expecting page and export to be exactly equal.

    Rule: export_rows must equal page_rows exactly. No extra rows allowed.

    Returns:
        {
            "ok": bool,
            "mode": "current_page_equal",
            "page_rows": int,
            "export_rows": int,
            "diffs": [...],
        }
    """
    if len(page_rows) != len(export_rows):
        return {
            "ok": False,
            "mode": "current_page_equal",
            "page_rows": len(page_rows),
            "export_rows": len(export_rows),
            "error": f"row count mismatch: page={len(page_rows)}, export={len(export_rows)}",
            "diffs": [],
        }

    diffs: list[dict] = []
    for i in range(len(page_rows)):
        page_row = page_rows[i]
        export_row = export_rows[i]
        for col in value_columns:
            page_val = page_row.get(col)
            export_val = export_row.get(col)
            if not _values_equal(page_val, export_val, tolerance):
                diffs.append({
                    "row_index": i + 1,
                    "column": col,
                    "page": page_val,
                    "export": export_val,
                })

    return {
        "ok": len(diffs) == 0,
        "mode": "current_page_equal",
        "page_rows": len(page_rows),
        "export_rows": len(export_rows),
        "matched_rows": len(page_rows) - len({d["row_index"] for d in diffs}) if diffs else len(page_rows),
        "diffs": diffs,
    }


def compare_all_pages_equal(
    all_page_rows: list[dict],
    export_rows: list[dict],
    value_columns: list[str],
    tolerance: float = 0.0,
) -> dict:
    """Compare all collected page rows (from all pages) against export.

    Rule: All collected page rows must equal all export rows exactly.
    This is the most expensive mode (requires pagination).

    Returns:
        {
            "ok": bool,
            "mode": "all_pages_equal",
            "page_rows": int,
            "export_rows": int,
            "diffs": [...],
        }
    """
    return compare_current_page_equal(all_page_rows, export_rows, value_columns, tolerance)
    # Override the mode
    result = compare_current_page_equal(all_page_rows, export_rows, value_columns, tolerance)
    result["mode"] = "all_pages_equal"
    return result


def run_comparison(
    page_rows: list[dict],
    export_rows: list[dict],
    compare_config: dict,
) -> dict:
    """Run the appropriate comparison based on configuration.

    Args:
        page_rows: Normalized page rows
        export_rows: Normalized export rows
        compare_config: Comparison configuration dict with keys:
            - mode: "visible_prefix_ordered" | "visible_subset_by_key" | "current_page_equal" | "all_pages_equal"
            - key_columns: Key columns for subset_by_key mode
            - value_columns: Value columns to compare
            - numeric_tolerance: Numeric comparison tolerance
            - percent_tolerance: Percentage comparison tolerance
            - allow_row_reorder: Allow row order differences
            - allow_extra_export_rows: Allow export to have more rows than page

    Returns:
        Comparison result dict
    """
    mode = compare_config.get("mode", "visible_subset_by_key")
    value_columns = compare_config.get("value_columns", [])
    tolerance = compare_config.get("numeric_tolerance", 0.0)

    if mode == "visible_prefix_ordered":
        return compare_visible_prefix_ordered(
            page_rows, export_rows,
            value_columns=value_columns,
            tolerance=tolerance,
        )
    elif mode == "visible_subset_by_key":
        key_columns = compare_config.get("key_columns", [])
        return compare_visible_subset_by_key(
            page_rows, export_rows,
            key_columns=key_columns,
            value_columns=value_columns,
            tolerance=tolerance,
            allow_row_reorder=compare_config.get("allow_row_reorder", True),
        )
    elif mode == "current_page_equal":
        result = compare_current_page_equal(
            page_rows, export_rows,
            value_columns=value_columns,
            tolerance=tolerance,
        )
        return result
    elif mode == "all_pages_equal":
        result = compare_all_pages_equal(
            page_rows, export_rows,
            value_columns=value_columns,
            tolerance=tolerance,
        )
        return result
    else:
        return {
            "ok": False,
            "mode": mode,
            "error": f"unknown comparison mode: {mode}",
            "page_rows": len(page_rows),
            "export_rows": len(export_rows),
        }


def format_compare_result(result: dict, case_name: str = "", report_name: str = "",
                           params: dict | None = None) -> str:
    """Format comparison result as human-readable text.

    Args:
        result: Comparison result dict from run_comparison
        case_name: Test case name
        report_name: Report name
        params: Query/screen parameters

    Returns:
        Formatted text report
    """
    status = "PASS" if result.get("ok") else "FAIL"
    lines = [
        f"{status} page_export_consistency",
        "",
    ]

    if case_name:
        lines.append(f"Case: {case_name}")
    if report_name:
        lines.append(f"Report: {report_name}")
    if params:
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        lines.append(f"Params: {param_str}")

    lines.append("")
    lines.append(f"Mode: {result.get('mode', 'unknown')}")
    lines.append(f"Page rows: {result.get('page_rows', 0)}")
    lines.append(f"Export rows: {result.get('export_rows', 0)}")
    lines.append(f"Matched page rows: {result.get('matched_rows', 0)}")

    extra = result.get("extra_export_rows", 0)
    if extra > 0:
        lines.append(f"Extra export rows: {extra}")

    if result.get("diff_rows"):
        lines.append(f"Diff rows: {result.get('diff_rows')}")

    # Key columns for subset mode
    if result.get("mode") == "visible_subset_by_key":
        key_columns = result.get("key_columns", [])
        if key_columns:
            lines.append("")
            lines.append("Key columns:")
            for col in key_columns:
                lines.append(f"  - {col}")

    # Value columns
    value_columns = result.get("value_columns", [])
    if value_columns:
        lines.append("")
        lines.append("Value columns:")
        for col in value_columns:
            lines.append(f"  - {col}")

    # Missing rows
    missing = result.get("missing_in_export", [])
    if missing:
        lines.append("")
        lines.append(f"Missing rows: {len(missing)}")
        lines.append("")
        lines.append("Missing in export:")
        for item in missing[:5]:
            lines.append(f"  key = {item.get('key', [])}")
            page_row = item.get("page_row", {})
            lines.append(f"  page_row = {json.dumps(page_row, ensure_ascii=False)}")

    # Value diffs
    diffs = result.get("diffs", [])
    if missing:
        # Diffs from subset mode have a different structure
        lines.append("")
        lines.append(f"Different values: {len(diffs)} row(s)")
        for item in diffs[:5]:
            lines.append(f"  key = {item.get('key', [])}")
            cdiffs = item.get("candidate_diffs", [])
            for cd in cdiffs:
                if isinstance(cd, list):
                    for d in cd:
                        lines.append(
                            f"  column = {d.get('column')}  "
                            f"page = {d.get('page')}  "
                            f"export = {d.get('export')}"
                        )
    elif diffs:
        lines.append("")
        lines.append(f"Different values: {len(diffs)}")
        for d in diffs[:10]:
            lines.append(
                f"  row={d.get('row_index', '?')}  "
                f"col={d.get('column', '?')}:  "
                f"page={d.get('page')}  "
                f"export={d.get('export')}"
            )

    if result.get("error"):
        lines.append("")
        lines.append(f"Error: {result['error']}")

    return "\n".join(lines)
