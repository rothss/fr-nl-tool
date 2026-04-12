from __future__ import annotations

from extract_structured_table import extract_table
from profiles import extract_profile_rows, get_profile_analysis_binding


def extract_rows_for_report(report_name: str | None, file_path: str | None) -> dict:
    fp = str(file_path or "").strip()
    if not fp:
        return {"columns": [], "rows": [], "meaningful_row_count": 0, "sheet_count": 0}
    profile_rows = extract_profile_rows(report_name, file_path)
    if profile_rows is not None:
        return profile_rows
    return extract_table(__import__("pathlib").Path(fp))


def get_analysis_renderer(report_name: str | None, analysis_mode: str | None = None):
    binding = get_profile_analysis_binding(report_name, analysis_mode=analysis_mode)
    return None if binding is None else binding[1]


def get_analysis_engine(report_name: str | None, analysis_mode: str | None = None):
    binding = get_profile_analysis_binding(report_name, analysis_mode=analysis_mode)
    return None if binding is None else binding[0]


def describe_analysis_binding(
    report_name: str | None, analysis_mode: str | None = None
) -> dict:
    engine = get_analysis_engine(report_name, analysis_mode=analysis_mode)
    renderer = get_analysis_renderer(report_name, analysis_mode=analysis_mode)
    return {
        "report_name": str(report_name or ""),
        "analysis_mode": str(analysis_mode or ""),
        "bound": renderer is not None and engine is not None,
        "engine_name": None if engine is None else str(getattr(engine, "__name__", "")),
        "renderer_name": None
        if renderer is None
        else str(getattr(renderer, "__name__", "")),
    }
