from __future__ import annotations

from pathlib import Path

from analysis.airline_yoy import analyze_airline_yoy, render_airline_yoy_answer
from analysis.future_flight_competition import (
    analyze_future_flight_competition,
    render_future_competition_review,
)
from analysis.ranked_flights import (
    analyze_first_flight_bottom10,
    analyze_top_metric_flight,
    render_first_flight_bottom10_answer,
    render_top_metric_flight_answer,
)
from analysis.single_margin import analyze_single_margin, render_single_margin_answer
from extract_adjusted_profit_overview import extract_adjusted_profit_overview_rows
from extract_single_margin import extract_single_margin_rows


REPORT_FAMILY_TO_NAME = {
    "future_flight_competition": "未来航班客座率票价分析",
    "route_metric_lookup": "未来航班客座率票价分析",
    "adjusted_profit_overview": "集团收入利润概览（调整后）",
    "airline_yoy": "集团经营提升分析",
    "ranked_flights": "集团前十后十航班",
    "single_margin": "单机边际贡献",
}

REPORT_FAMILY_TO_ENGINE = {
    "future_flight_competition": "future_flight_competition",
    "adjusted_profit_overview": "airline_yoy",
    "airline_yoy": "airline_yoy",
    "ranked_flights": "ranked_flights",
    "single_margin": "single_margin",
}

ANALYSIS_BINDINGS = {
    ("未来航班客座率票价分析", "competition_review"): (
        analyze_future_flight_competition,
        render_future_competition_review,
    ),
    ("集团经营提升分析", ""): (analyze_airline_yoy, render_airline_yoy_answer),
    ("集团收入利润概览（调整后）", ""): (
        analyze_airline_yoy,
        render_airline_yoy_answer,
    ),
    ("集团前十后十航班", "first_flight_bottom10"): (
        analyze_first_flight_bottom10,
        render_first_flight_bottom10_answer,
    ),
    ("集团前十后十航班", "top_metric_flight"): (
        analyze_top_metric_flight,
        render_top_metric_flight_answer,
    ),
    ("单机边际贡献", ""): (analyze_single_margin, render_single_margin_answer),
}


def get_profile_report_name(report_family: str | None) -> str | None:
    if not report_family:
        return None
    return REPORT_FAMILY_TO_NAME.get(str(report_family or "").strip())


def get_profile_analysis_engine_name(report_family: str | None) -> str | None:
    if not report_family:
        return None
    return REPORT_FAMILY_TO_ENGINE.get(str(report_family or "").strip())


def get_profile_analysis_binding(
    report_name: str | None, analysis_mode: str | None = None
):
    rn = str(report_name or "").strip()
    mode = str(analysis_mode or "").strip()
    binding = ANALYSIS_BINDINGS.get((rn, mode))
    if binding is not None:
        return binding
    return ANALYSIS_BINDINGS.get((rn, ""))


def extract_profile_rows(report_name: str | None, file_path: str | None) -> dict | None:
    rn = str(report_name or "").strip()
    fp = str(file_path or "").strip()
    if not fp:
        return None
    if rn == "集团收入利润概览（调整后）":
        rows = extract_adjusted_profit_overview_rows(Path(fp))
        return {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "meaningful_row_count": len(rows),
            "sheet_count": 1,
        }
    if rn == "单机边际贡献":
        rows = extract_single_margin_rows(Path(fp))
        return {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "meaningful_row_count": len(rows),
            "sheet_count": 1,
        }
    return None
