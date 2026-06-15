"""
Test case loader for page-export verification.

Loads and validates test case configuration from JSON files.
Supports loading from tests/live_cases/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_SECTIONS = ["name", "compare"]
OPTIONAL_SECTIONS = [
    "report",
    "navigation",
    "params",
    "page_extract",
    "export",
    "expected",
]


def load_case(case_path: Path) -> dict[str, Any]:
    """Load and validate a test case configuration.

    Args:
        case_path: Path to a JSON case file

    Returns:
        Validated case configuration dict

    Raises:
        FileNotFoundError: If case file doesn't exist
        ValueError: If case configuration is invalid
    """
    if not case_path.exists():
        raise FileNotFoundError(f"Case file not found: {case_path}")

    raw = json.loads(case_path.read_text(encoding="utf-8"))
    case = _apply_defaults(raw, case_path)

    # Validate required sections
    missing = [s for s in REQUIRED_SECTIONS if s not in case]
    if missing:
        raise ValueError(
            f"Case '{case_path}' missing required sections: {missing}"
        )

    # Validate compare config
    compare_cfg = case["compare"]
    mode = compare_cfg.get("mode", "visible_subset_by_key")
    if mode == "visible_subset_by_key" and not compare_cfg.get("key_columns"):
        raise ValueError(
            f"Case '{case_path}': mode=visible_subset_by_key requires key_columns"
        )

    return case


def _apply_defaults(raw: dict, case_path: Path) -> dict:
    """Apply default values to case configuration."""
    case = dict(raw)

    # Default name from filename
    if "name" not in case:
        case["name"] = case_path.stem

    # Default compare
    if "compare" not in case:
        case["compare"] = _default_compare()

    compare = case["compare"]
    # Default mode
    if "mode" not in compare:
        compare["mode"] = "visible_subset_by_key"
    # Default allow_extra_export_rows
    if "allow_extra_export_rows" not in compare:
        compare["allow_extra_export_rows"] = True
    # Default tolerances
    if "numeric_tolerance" not in compare:
        compare["numeric_tolerance"] = 0.01
    if "percent_tolerance" not in compare:
        compare["percent_tolerance"] = 0.0001
    # Default ignore_formatting
    if "ignore_formatting" not in compare:
        compare["ignore_formatting"] = True
    # Default empty_equivalents
    if "empty_equivalents" not in compare:
        compare["empty_equivalents"] = ["", "-", "--", "\u2014", "N/A", None]

    # Default page_extract
    if "page_extract" not in case:
        case["page_extract"] = {
            "strategy": "dom",
            "table_selector": "table",
            "visible_row_limit": 20,
        }

    # Default export
    if "export" not in case:
        case["export"] = {
            "format": "xlsx",
            "scope": "current_filter_all_rows",
            "timeout_ms": 60000,
        }

    # Default expected
    if "expected" not in case:
        case["expected"] = {
            "min_page_rows": 1,
            "min_export_rows": 1,
        }

    # Default params
    if "params" not in case:
        case["params"] = {}

    return case


def _default_compare() -> dict:
    """Default comparison configuration."""
    return {
        "mode": "visible_subset_by_key",
        "allow_extra_export_rows": True,
        "numeric_tolerance": 0.01,
        "percent_tolerance": 0.0001,
        "ignore_formatting": True,
        "allow_row_reorder": True,
        "empty_equivalents": ["", "-", "--", "\u2014", "N/A", None],
    }
