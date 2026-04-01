from __future__ import annotations

from analysis.future_flight_competition import render_future_competition_review


def get_analysis_renderer(report_name: str | None, analysis_mode: str | None = None):
    rn = str(report_name or "").strip()
    mode = str(analysis_mode or "").strip()
    if rn == "未来航班客座率票价分析" and mode == "competition_review":
        return render_future_competition_review
    return None


def describe_analysis_binding(report_name: str | None, analysis_mode: str | None = None) -> dict:
    renderer = get_analysis_renderer(report_name, analysis_mode=analysis_mode)
    return {
        "report_name": str(report_name or ""),
        "analysis_mode": str(analysis_mode or ""),
        "bound": renderer is not None,
        "renderer_name": None if renderer is None else str(getattr(renderer, "__name__", "")),
    }

