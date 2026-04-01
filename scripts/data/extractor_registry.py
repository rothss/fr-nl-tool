from __future__ import annotations

from analysis.airline_yoy import analyze_airline_yoy, render_airline_yoy_answer
from analysis.future_flight_competition import analyze_future_flight_competition, render_future_competition_review
from analysis.ranked_flights import (
    analyze_first_flight_bottom10,
    analyze_top_metric_flight,
    render_first_flight_bottom10_answer,
    render_top_metric_flight_answer,
)
from analysis.single_margin import analyze_single_margin, render_single_margin_answer
from extract_single_margin import extract_single_margin_rows
from extract_adjusted_profit_overview import extract_adjusted_profit_overview_rows
from extract_structured_table import extract_table


def extract_rows_for_report(report_name: str | None, file_path: str | None) -> dict:
    rn = str(report_name or "").strip()
    fp = str(file_path or "").strip()
    if not fp:
        return {"columns": [], "rows": [], "meaningful_row_count": 0, "sheet_count": 0}
    if rn == "航空集团收入利润概览（调整后）":
        rows = extract_adjusted_profit_overview_rows(__import__("pathlib").Path(fp))
        return {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "meaningful_row_count": len(rows),
            "sheet_count": 1,
        }
    if rn == "单机边际贡献":
        rows = extract_single_margin_rows(__import__("pathlib").Path(fp))
        return {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "meaningful_row_count": len(rows),
            "sheet_count": 1,
        }
    return extract_table(__import__("pathlib").Path(fp))


def get_analysis_renderer(report_name: str | None, analysis_mode: str | None = None):
    rn = str(report_name or "").strip()
    mode = str(analysis_mode or "").strip()
    if rn == "未来航班客座率票价分析" and mode == "competition_review":
        return render_future_competition_review
    if rn in {"航空集团经营提升分析", "航空集团收入利润概览（调整后）"}:
        return render_airline_yoy_answer
    if rn == "航空集团前十后十航班" and mode == "first_flight_bottom10":
        return render_first_flight_bottom10_answer
    if rn == "航空集团前十后十航班" and mode == "top_metric_flight":
        return render_top_metric_flight_answer
    if rn == "单机边际贡献":
        return render_single_margin_answer
    return None


def get_analysis_engine(report_name: str | None, analysis_mode: str | None = None):
    rn = str(report_name or "").strip()
    mode = str(analysis_mode or "").strip()
    if rn == "未来航班客座率票价分析" and mode == "competition_review":
        return analyze_future_flight_competition
    if rn in {"航空集团经营提升分析", "航空集团收入利润概览（调整后）"}:
        return analyze_airline_yoy
    if rn == "航空集团前十后十航班" and mode == "first_flight_bottom10":
        return analyze_first_flight_bottom10
    if rn == "航空集团前十后十航班" and mode == "top_metric_flight":
        return analyze_top_metric_flight
    if rn == "单机边际贡献":
        return analyze_single_margin
    return None


def describe_analysis_binding(report_name: str | None, analysis_mode: str | None = None) -> dict:
    engine = get_analysis_engine(report_name, analysis_mode=analysis_mode)
    renderer = get_analysis_renderer(report_name, analysis_mode=analysis_mode)
    return {
        "report_name": str(report_name or ""),
        "analysis_mode": str(analysis_mode or ""),
        "bound": renderer is not None and engine is not None,
        "engine_name": None if engine is None else str(getattr(engine, "__name__", "")),
        "renderer_name": None if renderer is None else str(getattr(renderer, "__name__", "")),
    }
