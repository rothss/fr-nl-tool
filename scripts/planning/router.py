from __future__ import annotations


def route_report_family(intent: dict) -> list[dict]:
    structured = (intent or {}).get("structured_intent") or {}
    filters = (intent or {}).get("filters") or {}
    metrics = [str(x) for x in ((structured.get("metrics") or intent.get("metrics") or ([] if not intent.get("metric") else [intent.get("metric")]))) if str(x).strip()]
    routed: list[dict] = []

    analysis_mode = str(((structured.get("analysis") or {}).get("mode")) or filters.get("analysis_mode") or "")
    time_mode = str(((structured.get("time") or {}).get("mode")) or "")
    has_route = bool(filters.get("segment_from") and filters.get("segment_to"))
    if has_route and analysis_mode == "competition_review":
        score = 0.80
        reasons = ["route_query", "competition_review"]
        if time_mode == "relative_future_range":
            score += 0.10
            reasons.append("future_time_range")
        if "价格" in metrics:
            score += 0.05
            reasons.append("fare_metric")
        if "客座率" in metrics:
            score += 0.05
            reasons.append("load_factor_metric")
        routed.append(
            {
                "report_family": "future_flight_competition",
                "report_name": "未来航班客座率票价分析",
                "score": min(score, 0.99),
                "reasons": reasons,
            }
        )

    if not routed and has_route:
        routed.append(
            {
                "report_family": "route_metric_lookup",
                "report_name": "未来航班客座率票价分析",
                "score": 0.55,
                "reasons": ["route_query_fallback"],
            }
        )
    return routed

