from __future__ import annotations

from profiles import get_profile_report_name


def route_report_family(intent: dict) -> list[dict]:
    structured = (intent or {}).get("structured_intent") or {}
    filters = (intent or {}).get("filters") or {}
    metrics = [
        str(x)
        for x in (
            structured.get("metrics")
            or intent.get("metrics")
            or ([] if not intent.get("metric") else [intent.get("metric")])
        )
        if str(x).strip()
    ]
    routed: list[dict] = []

    analysis_mode = str(
        ((structured.get("analysis") or {}).get("mode"))
        or filters.get("analysis_mode")
        or ""
    )
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
                "report_name": get_profile_report_name("future_flight_competition"),
                "score": min(score, 0.99),
                "reasons": reasons,
            }
        )

    if str(filters.get("report_variant") or "") == "adjusted_profit_overview":
        routed.append(
            {
                "report_family": "adjusted_profit_overview",
                "report_name": get_profile_report_name("adjusted_profit_overview"),
                "score": 0.96,
                "reasons": ["adjusted_profit_variant", "airline_yoy"],
            }
        )
    elif str(filters.get("compare_scope") or "") == "airline_yoy" and (
        "净利润同比" in metrics or "净利润" in str(intent.get("raw_query") or "")
    ):
        routed.append(
            {
                "report_family": "airline_yoy",
                "report_name": get_profile_report_name("airline_yoy"),
                "score": 0.92,
                "reasons": ["airline_yoy", "net_profit_yoy"],
            }
        )

    if str(filters.get("rank_scope") or "") == "后十" and bool(
        filters.get("first_flight")
    ):
        routed.append(
            {
                "report_family": "ranked_flights",
                "report_name": get_profile_report_name("ranked_flights"),
                "score": 0.94,
                "reasons": ["bottom10", "first_flight"],
            }
        )
    elif str(filters.get("extreme") or "") == "best" and any(
        m in metrics for m in ("小时边际贡献", "总边贡")
    ):
        routed.append(
            {
                "report_family": "ranked_flights",
                "report_name": get_profile_report_name("ranked_flights"),
                "score": 0.93,
                "reasons": ["top_metric_flight"],
            }
        )
    elif "单机边际贡献" in metrics:
        routed.append(
            {
                "report_family": "single_margin",
                "report_name": get_profile_report_name("single_margin"),
                "score": 0.90,
                "reasons": ["single_margin"],
            }
        )

    if not routed and has_route:
        routed.append(
            {
                "report_family": "route_metric_lookup",
                "report_name": get_profile_report_name("route_metric_lookup"),
                "score": 0.55,
                "reasons": ["route_query_fallback"],
            }
        )
    return routed
