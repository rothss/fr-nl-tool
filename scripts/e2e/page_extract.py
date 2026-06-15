"""
Page data extraction.

Handles extracting page-snapshot data from browser DOM or network interception.
Produces standardized page_snapshot structure for consistency comparison.

Enhanced with:
  - FineReport network response adapter (via finereport_adapters)
  - iframe / aria grid DOM traversal
  - Page stability detection (loading indicator wait, row count stabilization)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .browser_session import BrowserSession
from .finereport_adapters import try_all_adapters
from .normalize_table import normalize_rows


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def extract_page_snapshot(
    session: BrowserSession,
    case_config: dict,
) -> dict[str, Any]:
    """Extract a page snapshot synchronously from an already-navigated session.

    This is the primary entry point for page data extraction.
    It must be called after the browser session has navigated to the report page
    and applied any necessary filters.

    Args:
        session: Active BrowserSession (already navigated to the report)
        case_config: Test case configuration

    Returns:
        Page snapshot dict
    """
    page_cfg = case_config.get("page_extract", {})
    strategy = page_cfg.get("strategy", "dom")
    table_selector = page_cfg.get("table_selector", "table")
    data_api_patterns = page_cfg.get("data_api_patterns")
    visible_row_limit = page_cfg.get("visible_row_limit", 20)

    # Extract raw data from browser
    raw_data = _extract_sync(session, strategy, table_selector, data_api_patterns)

    # Build snapshot
    params = case_config.get("params", {})
    report_info = case_config.get("report", {})
    report_url = case_config.get("navigation", {}).get("report_url", "")

    rows = raw_data.get("rows", [])
    columns = raw_data.get("columns", [])

    # Normalize page rows
    compare_cfg = case_config.get("compare", {})
    normalized_rows = normalize_rows(
        rows,
        columns=columns,
        date_columns=compare_cfg.get("date_columns", []),
        percent_columns=compare_cfg.get("percent_columns", []),
        numeric_columns=compare_cfg.get("numeric_columns", []),
        fill_merged=False,  # Page DOM doesn't have merged cells
        aliases=compare_cfg.get("aliases", {}),
        ignore_columns=compare_cfg.get("ignore_columns", []),
    )

    # Limit to visible rows
    if visible_row_limit and len(normalized_rows) > visible_row_limit:
        normalized_rows = normalized_rows[:visible_row_limit]

    raw_json = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    snapshot = {
        "source": "page",
        "report_name": report_info.get("name", ""),
        "url": report_url,
        "params": params,
        "page_state": {
            "visible_row_limit": visible_row_limit,
            "rows_visible": len(normalized_rows),
        },
        "columns": columns,
        "rows": normalized_rows,
        "raw_rows_count": len(rows),
        "raw_hash": f"sha256:{_sha256_hex(raw_json)}",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    return snapshot


def _extract_sync(
    session: BrowserSession,
    strategy: str,
    table_selector: str,
    data_api_patterns: list[str] | None,
) -> dict:
    """Synchronous wrapper around async page extraction."""
    import asyncio

    async def _do_extract():
        if strategy == "network" and data_api_patterns:
            return await session.extract_table_data(
                table_selector=table_selector,
                strategy="network",
                data_api_patterns=data_api_patterns,
            )
        return await session.extract_table_data(
            table_selector=table_selector,
            strategy="dom",
        )

    # Check if we're already in an event loop
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context - this should be called from async code
        raise RuntimeError(
            "extract_page_snapshot must be called from async context. "
            "Use 'await extract_page_snapshot_async()' instead."
        )
    except RuntimeError:
        # No running loop, create one
        return asyncio.run(_do_extract())


async def extract_page_snapshot_async(
    session: BrowserSession,
    case_config: dict,
) -> dict[str, Any]:
    """Async version of extract_page_snapshot.

    Use this when calling from within an existing async context.

    Args:
        session: Active BrowserSession (already navigated to the report)
        case_config: Test case configuration

    Returns:
        Page snapshot dict
    """
    page_cfg = case_config.get("page_extract", {})
    strategy = page_cfg.get("strategy", "dom")
    table_selector = page_cfg.get("table_selector", "table")
    data_api_patterns = page_cfg.get("data_api_patterns")
    visible_row_limit = page_cfg.get("visible_row_limit", 20)

    raw_data = await session.extract_table_data(
        table_selector=table_selector,
        strategy=strategy,
        data_api_patterns=data_api_patterns,
    )

    params = case_config.get("params", {})
    report_info = case_config.get("report", {})
    report_url = case_config.get("navigation", {}).get("report_url", "")

    rows = raw_data.get("rows", [])
    columns = raw_data.get("columns", [])

    compare_cfg = case_config.get("compare", {})
    normalized_rows = normalize_rows(
        rows,
        columns=columns,
        date_columns=compare_cfg.get("date_columns", []),
        percent_columns=compare_cfg.get("percent_columns", []),
        numeric_columns=compare_cfg.get("numeric_columns", []),
        fill_merged=False,
        aliases=compare_cfg.get("aliases", {}),
        ignore_columns=compare_cfg.get("ignore_columns", []),
    )

    if visible_row_limit and len(normalized_rows) > visible_row_limit:
        normalized_rows = normalized_rows[:visible_row_limit]

    raw_json = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    snapshot = {
        "source": "page",
        "report_name": report_info.get("name", ""),
        "url": report_url,
        "params": params,
        "page_state": {
            "visible_row_limit": visible_row_limit,
            "rows_visible": len(normalized_rows),
        },
        "columns": columns,
        "rows": normalized_rows,
        "raw_rows_count": len(rows),
        "raw_hash": f"sha256:{_sha256_hex(raw_json)}",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    return snapshot


def save_page_snapshot(snapshot: dict, output_path: Path) -> None:
    """Save page snapshot as JSON to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
