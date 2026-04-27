from __future__ import annotations


import inspect


from data.extractor_registry import get_analysis_renderer


def render_answer_text(query_result: dict) -> str | None:
    answer_text = query_result.get("answer_text")
    if answer_text is not None:
        return str(answer_text)
    analysis_result = query_result.get("analysis_result") or {}
    source_meta = query_result.get("source_meta") or {}
    intent = query_result.get("intent") or {}
    report_name = str(source_meta.get("report_name") or "")
    analysis_mode = str(
        ((intent.get("structured_intent") or {}).get("analysis") or {}).get("mode")
        or (intent.get("filters") or {}).get("analysis_mode")
        or ""
    )
    renderer = get_analysis_renderer(report_name, analysis_mode=analysis_mode)
    extracted = query_result.get("extracted") or {}
    if renderer is None or not extracted:
        return None
    params = list(inspect.signature(renderer).parameters)
    if params == ["rows", "report_name", "source_path", "filters"]:
        return renderer(
            extracted.get("rows") or [],
            report_name,
            str(source_meta.get("file_path") or ""),
            intent.get("filters") or {},
        )
    if params == ["analysis_result", "source_meta"]:
        return renderer(analysis_result, source_meta)
    return renderer(analysis_result, intent, source_meta)
