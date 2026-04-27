from __future__ import annotations

import numbers
import re

NUMERIC_CHUNK_RE = re.compile(r"\d+(?:\.\d+)?")
HAS_TEXT_RE = re.compile(r"[A-Za-z\u4e00-\u9fff]")
NUMERIC_BASE_RE = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")

KNOWN_NUMERIC_SUFFIXES: tuple[str, ...] = (
    "%", "‰", "kg", "t", "km", "m", "h", "min", "s",
    "元", "万元", "亿元", "千元", "吨", "架", "小时", "天", "月", "年",
    "次", "人", "人次", "班次", "公里",
)


def is_numeric_like_text(text: str) -> bool:
    candidate = text.strip().replace(",", "").replace("，", "").replace(" ", "")
    if not candidate:
        return False
    if candidate.startswith("(") and candidate.endswith(")") and len(candidate) > 2:
        candidate = candidate[1:-1]
    lower = candidate.lower()
    for suffix in KNOWN_NUMERIC_SUFFIXES:
        sl = suffix.lower()
        if lower.endswith(sl) and len(candidate) > len(suffix):
            candidate = candidate[:-len(suffix)]
            lower = candidate.lower()
            break
    return NUMERIC_BASE_RE.fullmatch(candidate) is not None


def normalize_value(value: object, drop_numeric: bool = False) -> str | None:
    if value is None:
        return None
    if drop_numeric and isinstance(value, numbers.Number):
        return None

    text = str(value).strip()
    if not text:
        return None
    if not drop_numeric:
        return text
    if is_numeric_like_text(text):
        return None

    cleaned = NUMERIC_CHUNK_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if not HAS_TEXT_RE.search(cleaned):
        return None
    return cleaned
