from __future__ import annotations


def analyze_single_margin(intent: dict, extracted: dict, source_meta: dict) -> dict:
    rows = extracted.get("rows") or []
    if not rows:
        return {
            "ok": False,
            "analysis_engine": "single_margin",
            "matched_route": None,
            "matched_dates": [],
            "issues": [],
            "advice": [],
            "summary": "未在命中报表中找到可用数据。",
        }
    return {
        "ok": True,
        "analysis_engine": "single_margin",
        "matched_route": None,
        "matched_dates": [str(rows[0].get("日期") or "")] if rows and rows[0].get("日期") else [],
        "issues": [],
        "advice": [],
        "summary": f"共命中 {len(rows)} 条单机边际贡献记录。",
        "rows": rows,
    }


def render_single_margin_answer(analysis_result: dict, intent: dict, source_meta: dict) -> str:
    report_name = str(source_meta.get("report_name") or "")
    source_path = str(source_meta.get("file_path") or "")
    rows = analysis_result.get("rows") or []
    if not analysis_result.get("ok") or not rows:
        return (
            f"未在命中报表中找到可用数据。\n"
            f"报表: {report_name}\n"
            f"来源: {source_path}"
        )
    lines = [
        "指标: 单机边际贡献 -> 单机边际贡献",
        f"命中报表: {report_name}",
        f"来源: {source_path}",
        f"结果条数: {len(rows)}",
    ]
    for idx, row in enumerate(rows[:10], start=1):
        lines.append(
            f"[{idx}] {row.get('日期','')} {row.get('公司','')} {row.get('机型','')} 单机边际贡献={float(row.get('单机边际贡献') or 0.0):.2f}"
        )
    return "\n".join(lines)
