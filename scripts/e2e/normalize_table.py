"""
Table data normalization for page-export consistency comparison.

Unifies page text and Excel cell values to enable meaningful comparison.
Handles:
  - Empty value normalization
  - Number formatting (thousands separators, etc.)
  - Percentage normalization
  - Date normalization
  - Text whitespace normalization
  - Merged cell filling
  - Alias resolution
"""

from __future__ import annotations

import math
import re
from typing import Any


# --- Empty value normalization ---

# Values considered equivalent to empty/null
EMPTY_EQUIVALENTS: set[str | None] = {None, "", "-", "--", "—", "N/A", "NA", "无"}


def is_empty(value: object) -> bool:
    """Check if a value should be treated as empty/None."""
    if value is None:
        return True
    s = str(value).strip()
    return s in EMPTY_EQUIVALENTS or s.lower() == "nan"


def normalize_empty(value: object) -> object:
    """Normalize empty-equivalent values to None."""
    if is_empty(value):
        return None
    return value


# --- Text normalization ---

def normalize_whitespace(text: object) -> str:
    """Remove leading/trailing whitespace, collapse whitespace, convert fullwidth spaces."""
    s = str(text or "").strip()
    # Full-width spaces to half-width
    s = s.replace("\u3000", " ")
    # Collapse consecutive whitespace
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_text(text: object) -> str:
    """Full text normalization: whitespace only (no aggressive synonym replacement)."""
    return normalize_whitespace(text)


# --- Number normalization ---

def _try_parse_number(raw: object) -> tuple[bool, float | None]:
    """Try to parse a raw value as a number. Returns (success, number_or_None)."""
    if raw is None:
        return False, None
    if isinstance(raw, (int, float)):
        if math.isnan(float(raw)) or math.isinf(float(raw)):
            return False, None
        return True, float(raw)
    s = str(raw).strip()
    if not s:
        return False, None

    # Handle negative parentheses: (1,234.50) → -1234.5
    negative = False
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
        negative = True

    # Remove thousands separators: both comma and Chinese-style
    cleaned = s.replace(",", "").replace("，", "")
    # Remove leading currency symbols
    cleaned = re.sub(r"^[¥$€£￥\s]+", "", cleaned)
    # Remove trailing currency symbols
    cleaned = re.sub(r"[¥$€£￥\s]+$", "", cleaned)

    # Handle Chinese units: 1.2万 → 12000, 3.5亿 → 350000000
    wan_match = re.match(r"^([\d.]+)\s*万$", cleaned)
    if wan_match:
        try:
            val = float(wan_match.group(1)) * 10000
            return True, -val if negative else val
        except (ValueError, TypeError):
            return False, None

    yi_match = re.match(r"^([\d.]+)\s*亿$", cleaned)
    if yi_match:
        try:
            val = float(yi_match.group(1)) * 100000000
            return True, -val if negative else val
        except (ValueError, TypeError):
            return False, None

    try:
        val = float(cleaned)
        if math.isnan(val) or math.isinf(val):
            return False, None
        return True, -val if negative else val
    except (ValueError, TypeError):
        return False, None


def normalize_number(value: object) -> object:
    """Normalize a value to a float if it represents a number, otherwise return as-is."""
    ok, num = _try_parse_number(value)
    if ok:
        return num
    return normalize_empty(value)


# --- Percentage normalization ---

_PERCENT_PATTERN = re.compile(r"^(-?[\d,，.]+)\s*%$")


def normalize_percent(value: object) -> object:
    """Normalize percentage values. "12.3%" -> 0.123, 0.123 -> 0.123."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    m = _PERCENT_PATTERN.match(s)
    if m:
        num_str = m.group(1).replace(",", "").replace("，", "")
        try:
            return float(num_str) / 100.0
        except (ValueError, TypeError):
            return None
    # Try as plain number
    ok, num = _try_parse_number(s)
    if ok and num is not None:
        return num
    return None


# --- Date normalization ---

_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})[\s\-\/年](\d{1,2})(?:[\s\-\/月](?:(\d{1,2})[\s\-\/日]?)?)?$"), "%Y-%m-%d"),
    (re.compile(r"^(\d{4})[\-\/](\d{1,2})[\-\/](\d{1,2})$"), "%Y-%m-%d"),
    (re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$"), "%Y-%m-%d"),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), "%Y-%m-%d"),
    (re.compile(r"^(\d{4})(\d{2})$"), "%Y-%m"),
]


def normalize_date(value: object, granularity: str = "month") -> object:
    """Normalize date values to consistent format.

    Supported input formats:
      "2026年5月" -> "2026-05"
      "2026/05" -> "2026-05"
      "2026-05" -> "2026-05"
      "2026-05-01" -> "2026-05-01"

    Args:
        value: Raw date value
        granularity: "month" or "day" - output format precision
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Could be Excel serial date - just convert to string
        s = str(int(value))
    else:
        s = str(value).strip()
    if not s or s.lower() == "nan" or s in EMPTY_EQUIVALENTS:
        return None
    for pattern, fmt in _DATE_PATTERNS:
        m = pattern.match(s)
        if m:
            groups = m.groups()
            if granularity == "month":
                month = groups[1].zfill(2)
                return f"{groups[0]}-{month}"
            else:
                if len(groups) >= 3 and groups[2] is not None:
                    month = groups[1].zfill(2)
                    day = str(groups[2]).zfill(2)
                    return f"{groups[0]}-{month}-{day}"
                month = groups[1].zfill(2)
                return f"{groups[0]}-{month}"
    # Already in ISO-like format
    if re.match(r"^\d{4}-\d{2}(-\d{2})?$", s):
        return s
    return s


# --- Merged cell filling ---

def fill_merged_cells(rows: list[dict], key_columns: list[str] | None = None) -> list[dict]:
    """Fill empty cells that result from Excel merged cells with values from above.

    For each column that may contain merged cells, if a cell is empty, fill it
    with the last non-empty value from above. This emulates Excel's merged-cell
    behavior where only the top-left cell has a value.

    Args:
        rows: List of row dicts
        key_columns: Specific columns to fill (default: all columns)

    Returns:
        New list of rows with merged cells filled
    """
    if not rows:
        return rows
    columns = key_columns or list(rows[0].keys())
    filled = [dict(row) for row in rows]
    for col in columns:
        last_value: object = None
        for row_dict in filled:
            current = row_dict.get(col)
            if is_empty(current):
                if last_value is not None:
                    row_dict[col] = last_value
            else:
                last_value = current
    return filled


# --- Alias resolution ---

def resolve_aliases(
    rows: list[dict],
    aliases: dict[str, dict[str, list[str]]],
) -> list[dict]:
    """Resolve column value aliases to canonical form.

    Args:
        rows: List of row dicts
        aliases: Dict of {column_name: {canonical: [alias1, alias2, ...]}}

    Example:
        aliases = {"航司": {"东方航空": ["东航", "中国东方航空"]}}
        A row with 航司="东航" will be normalized to 航司="东方航空"

    Returns:
        New list of rows with aliased values normalized
    """
    if not rows or not aliases:
        return rows
    # Build reverse mapping: alias -> canonical
    reverse_map: dict[str, dict[str, str]] = {}
    for col_name, col_aliases in aliases.items():
        if col_name not in reverse_map:
            reverse_map[col_name] = {}
        for canonical, alias_list in col_aliases.items():
            for alias in alias_list:
                reverse_map[col_name][str(alias).strip()] = str(canonical).strip()
            # Also map canonical to itself
            reverse_map[col_name][str(canonical).strip()] = str(canonical).strip()
    resolved = []
    for row in rows:
        new_row = dict(row)
        for col_name, mapping in reverse_map.items():
            if col_name in new_row:
                val = str(new_row.get(col_name) or "").strip()
                if val in mapping:
                    new_row[col_name] = mapping[val]
        resolved.append(new_row)
    return resolved


# --- Combined normalization ---

def normalize_cell(
    value: object,
    col_name: str = "",
    date_columns: list[str] | None = None,
    percent_columns: list[str] | None = None,
    numeric_columns: list[str] | None = None,
    date_granularity: str = "month",
) -> object:
    """Normalize a single cell value based on column type.

    Args:
        value: Raw cell value
        col_name: Column name for type inference
        date_columns: Columns to treat as dates
        percent_columns: Columns to treat as percentages
        numeric_columns: Columns to treat as numbers
        date_granularity: "month" or "day"

    Returns:
        Normalized value
    """
    # First, handle empty
    if is_empty(value):
        return None

    date_cols = date_columns or []
    percent_cols = percent_columns or []
    numeric_cols = numeric_columns or []

    if col_name in date_cols:
        return normalize_date(value, granularity=date_granularity)

    if col_name in percent_cols:
        result = normalize_percent(value)
        if result is not None:
            return result

    if col_name in numeric_cols or col_name in percent_cols:
        result = normalize_number(value)
        if result is not None and isinstance(result, (int, float)):
            return result

    # Default: try number, fall back to text
    ok, num = _try_parse_number(value)
    if ok and num is not None:
        return num

    return normalize_text(value)


def normalize_rows(
    rows: list[dict],
    columns: list[str] | None = None,
    date_columns: list[str] | None = None,
    percent_columns: list[str] | None = None,
    numeric_columns: list[str] | None = None,
    date_granularity: str = "month",
    fill_merged: bool = True,
    aliases: dict[str, dict[str, list[str]]] | None = None,
    ignore_columns: list[str] | None = None,
) -> list[dict]:
    """Normalize a list of row dicts for comparison.

    Args:
        rows: Raw row data
        columns: All columns (for filling merged cells)
        date_columns: Date-type columns
        percent_columns: Percentage-type columns
        numeric_columns: Numeric-type columns
        date_granularity: "month" or "day"
        fill_merged: Whether to fill merged cells
        aliases: Alias mapping for text normalization
        ignore_columns: Columns to exclude from normalization

    Returns:
        Normalized rows
    """
    if not rows:
        return rows

    ignored = set(ignore_columns or [])
    all_columns = columns or list(rows[0].keys())
    fill_columns = [c for c in all_columns if c not in ignored]

    # Step 1: Fill merged cells
    if fill_merged:
        result = fill_merged_cells(rows, key_columns=fill_columns)
    else:
        result = [dict(row) for row in rows]

    # Step 2: Resolve aliases
    if aliases:
        result = resolve_aliases(result, aliases)

    # Step 3: Normalize each cell
    normalized = []
    for row in result:
        new_row: dict[str, object] = {}
        for col_name, raw_value in row.items():
            if col_name in ignored:
                new_row[col_name] = raw_value
                continue
            new_row[col_name] = normalize_cell(
                raw_value,
                col_name=col_name,
                date_columns=date_columns,
                percent_columns=percent_columns,
                numeric_columns=numeric_columns,
                date_granularity=date_granularity,
            )
        normalized.append(new_row)

    return normalized
