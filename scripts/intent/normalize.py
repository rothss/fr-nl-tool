from __future__ import annotations

import re
from pathlib import Path

from common import load_yaml_or_json, references_dir


def load_airport_aliases(path: Path | None = None) -> dict:
    actual = path or (references_dir() / "airport_aliases.yaml")
    if not actual.exists():
        return {"cities": {}}
    data = load_yaml_or_json(actual)
    return data if isinstance(data, dict) else {"cities": {}}


def normalize_query(query: str, alias_dict: dict | None = None) -> dict:
    alias_cfg = alias_dict or load_airport_aliases()
    cleaned = str(query or "").strip()
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace("－", "-").replace("—", "-").replace("–", "-")
    cleaned = re.sub(r"^(使用fr_nl的skill，?|用fr_nl的skill，?)", "", cleaned)

    tokens = [t for t in re.split(r"([到,\-])", cleaned) if t]
    return {
        "raw_query": str(query or ""),
        "cleaned_query": cleaned,
        "tokens": tokens,
        "replacements": [],
        "alias_dict": alias_cfg,
    }
