"""
Diff report generation for page-export consistency failures.

Produces human-readable failure reports that clearly show:
  - Which rows are missing from the export
  - Which values differ between page and export
  - Key identifiers for locating the problematic data
"""

from __future__ import annotations

import json
from typing import Any


def generate_diff_report(
    compare_result: dict,
    case_name: str = "",
    report_name: str = "",
    params: dict | None = None,
) -> str:
    """Generate a detailed diff report from a failed comparison result.

    Args:
        compare_result: Result from run_comparison
        case_name: Test case name
        report_name: Report name
        params: Filter parameters

    Returns:
        Formatted diff report text
    """
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("PAGE-EXPORT CONSISTENCY DIFF REPORT")
    lines.append("=" * 60)
    lines.append("")

    if case_name:
        lines.append(f"Case: {case_name}")
    if report_name:
        lines.append(f"Report: {report_name}")
    if params:
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        lines.append(f"Params: {param_str}")

    lines.append("")
    lines.append(f"Mode: {compare_result.get('mode', 'unknown')}")
    lines.append(f"Page rows: {compare_result.get('page_rows', 0)}")
    lines.append(f"Export rows: {compare_result.get('export_rows', 0)}")

    if compare_result.get("matched_rows") is not None:
        lines.append(f"Matched: {compare_result['matched_rows']}")

    if compare_result.get("error"):
        lines.append("")
        lines.append(f"ERROR: {compare_result['error']}")

    # Missing rows
    missing = compare_result.get("missing_in_export", [])
    if missing:
        lines.append("")
        lines.append("-" * 40)
        lines.append(f"MISSING IN EXPORT: {len(missing)} row(s)")
        lines.append("-" * 40)
        for item in missing:
            key = item.get("key", [])
            lines.append(f"  Key: {key}")
            page_row = item.get("page_row", {})
            lines.append(f"  Page data: {json.dumps(page_row, ensure_ascii=False)}")
            lines.append("")

    # Value diffs (from subset mode)
    diffs = compare_result.get("diffs", [])
    if missing and diffs:
        # Subset-mode diffs
        lines.append("-" * 40)
        lines.append(f"VALUE DIFFERENCES: {len(diffs)} row(s)")
        lines.append("-" * 40)
        for item in diffs:
            key = item.get("key", [])
            lines.append(f"  Key: {key}")
            page_row = item.get("page_row", {})
            lines.append(f"  Page: {json.dumps(page_row, ensure_ascii=False)}")
            for cd in item.get("candidate_diffs", []):
                if isinstance(cd, list):
                    for d in cd:
                        lines.append(
                            f"    {d.get('column', '?')}: "
                            f"page={d.get('page')} vs export={d.get('export')}"
                        )
            lines.append("")

    elif diffs:
        # Prefix/current-page-mode diffs
        lines.append("-" * 40)
        lines.append(f"VALUE DIFFERENCES: {len(diffs)}")
        lines.append("-" * 40)
        for d in diffs:
            lines.append(
                f"  Row {d.get('row_index', '?')}, "
                f"Column '{d.get('column', '?')}': "
                f"page='{d.get('page')}' vs export='{d.get('export')}'"
            )
        lines.append("")

    # Summary
    lines.append("=" * 60)
    lines.append("RESULT: FAIL")
    lines.append("=" * 60)

    return "\n".join(lines)
