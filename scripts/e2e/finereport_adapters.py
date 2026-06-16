"""
FineReport network response adapters for extracting table data.

Adapters detect and parse various FineReport API response formats:
  - /decision /view/report: {data: {columns: [...], rows: [...]}}
  - /reportserver: XML/JSON response with table structure
  - /decision /entry: nested JSON with cell matrices
  - Generic: various list-of-dicts patterns

Usage:
    from .finereport_adapters import try_all_adapters
    columns, rows = try_all_adapters(response_body, request_url)
"""

from __future__ import annotations

import json
from typing import Any


def try_all_adapters(data: Any, url: str = "") -> tuple[list[str], list[dict]]:
    """Try all FineReport adapters in order and return first successful result.

    Args:
        data: Parsed JSON response body (dict or list)
        url: Request URL for adapter selection hints

    Returns:
        (columns, rows) tuple, or ([], []) if no adapter matched
    """
    adapters = [
        _adapt_decision_view_report,
        _adapt_decision_entry,
        _adapt_columns_rows_structure,
        _adapt_list_of_dicts,
        _adapt_cell_matrix,
    ]
    for adapter in adapters:
        cols, rows = adapter(data, url)
        if cols and len(rows) > 0:
            return cols, rows
    return [], []


def _adapt_decision_view_report(data: dict, url: str) -> tuple[list[str], list[dict]]:
    """FineReport /decision /view/report: {data: {columns: [...], rows: [...]}}"""
    if not isinstance(data, dict):
        return [], []
    inner = data.get("data") or data.get("result")
    if not isinstance(inner, dict):
        return [], []
    cols = inner.get("columns") or inner.get("columnNames") or []
    rows = inner.get("rows") or inner.get("data") or []
    if not cols and rows and isinstance(rows[0], dict):
        cols = list(rows[0].keys())
    if cols and isinstance(rows, list) and len(rows) > 0:
        normalized = _normalize_rows(rows, cols)
        return list(cols), normalized
    return [], []


def _adapt_decision_entry(data: dict, url: str) -> tuple[list[str], list[dict]]:
    """FineReport /decision /entry: nested {data: {content: [[...]]}} matrix"""
    if not isinstance(data, dict):
        return [], []
    content = data.get("data", {}).get("content") or data.get("content")
    if not isinstance(content, list) or len(content) < 2:
        return [], []
    # First row = headers, subsequent = data
    headers = [str(cell) for cell in content[0] if cell is not None]
    rows = []
    for row_cells in content[1:]:
        if not isinstance(row_cells, list):
            continue
        row = {}
        for i, cell in enumerate(row_cells):
            if i < len(headers):
                row[headers[i]] = str(cell) if cell is not None else ""
        if row:
            rows.append(row)
    return headers, rows


def _adapt_columns_rows_structure(data: dict, url: str) -> tuple[list[str], list[dict]]:
    """Generic {columns: [...], rows: [...]} or {header: [...], data: [...]}"""
    if not isinstance(data, dict):
        return [], []
    cols = data.get("columns") or data.get("header") or data.get("headers") or []
    rows = data.get("rows") or data.get("data") or data.get("records") or []
    if not cols and isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
        cols = list(rows[0].keys())
    if cols and isinstance(rows, list):
        normalized = _normalize_rows(rows, cols)
        return list(cols), normalized
    return [], []


def _adapt_list_of_dicts(data: Any, url: str) -> tuple[list[str], list[dict]]:
    """Generic list[dict]: auto-detect columns from first row keys"""
    if not isinstance(data, list) or len(data) == 0:
        return [], []
    if not isinstance(data[0], dict):
        return [], []
    cols = list(data[0].keys())
    return cols, data


def _cell_text(cell: object) -> str:
    """Extract text from a cell value, supporting dict and scalar types."""
    if cell is None:
        return ""
    if isinstance(cell, dict):
        for key in ("value", "text", "display", "content", "formattedValue", "html"):
            val = cell.get(key)
            if val is not None and val != "":
                return str(val)
        return ""
    return str(cell)


def _adapt_cell_matrix(data: dict, url: str) -> tuple[list[str], list[dict]]:
    """FineReport cell matrix: {cells: [[{value: ...}]]} structure"""
    if not isinstance(data, dict):
        return [], []
    cells = data.get("cells") or (data.get("data", {}).get("cells"))
    if not isinstance(cells, list) or len(cells) < 2:
        return [], []
    # Extract headers using _cell_text
    headers = [_cell_text(cell) for cell in cells[0]]
    if not any(h for h in headers):
        return [], []
    # Extract rows
    rows = []
    for row_cells in cells[1:]:
        if not isinstance(row_cells, list):
            continue
        row = {}
        for i, cell in enumerate(row_cells):
            if i >= len(headers):
                break
            row[headers[i]] = _cell_text(cell)
        if row:
            rows.append(row)
    return headers, rows


def _normalize_rows(rows: list, columns: list[str]) -> list[dict]:
    """Normalize rows to list of dicts regardless of input format."""
    if not rows:
        return []
    if isinstance(rows[0], dict):
        # Already dict format; ensure all expected columns present
        result = []
        for row in rows:
            r = {}
            for col in columns:
                val = row.get(col)
                if val is None:
                    val = ""
                elif not isinstance(val, str):
                    val = str(val)
                r[col] = val
            result.append(r)
        return result
    if isinstance(rows[0], list):
        # List format: map each column index to column name
        result = []
        for row_cells in rows:
            if not isinstance(row_cells, list):
                continue
            row = {}
            for i, cell in enumerate(row_cells):
                if i < len(columns):
                    val = str(cell) if cell is not None else ""
                    row[columns[i]] = val
            if row:
                result.append(row)
        return result
    return []
