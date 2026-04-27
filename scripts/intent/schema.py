from __future__ import annotations

from typing import TypedDict


class NormalizedQuery(TypedDict):
    raw_query: str
    cleaned_query: str
    tokens: list[str]
    replacements: list[dict]


class IntentCandidate(TypedDict, total=False):
    raw_query: str
    domain: str | None
    intent_type: str | None
    metrics: list[str]
    route: dict
    flight: dict
    time: dict
    analysis: dict
    scope: dict
    constraints: dict
    confidence: float
    missing_slots: list[str]
    parser_trace: list[str]
