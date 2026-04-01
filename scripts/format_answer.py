from __future__ import annotations

from common import load_yaml_or_json, references_dir


def resolve_metric_column(metric: str | None, columns: list[str]) -> str | None:
    if not metric:
        return None
    aliases = load_yaml_or_json(references_dir() / "column_aliases.yaml")
    candidates: list[str] = aliases.get("metric_column_aliases", {}).get(metric, [])
    for c in candidates:
        if c in columns:
            return c
    if metric in columns:
        return metric
    for c in columns:
        if metric and metric in str(c):
            return c
    for c in columns:
        if metric and str(c) in metric:
            return c
    return None


def render_answer(
    metric: str | None,
    metric_col: str | None,
    rows: list[dict],
    report_name: str,
    file_path: str,
    top_n: int = 10,
) -> str:
    if not rows:
        return (
            f"未在命中报表中找到可用数据。\n"
            f"报表: {report_name}\n"
            f"来源: {file_path}"
        )

    if not metric_col:
        return (
            f"已命中报表，但未解析到指标列。\n"
            f"指标: {metric or '未指定'}\n"
            f"可用列: {', '.join(rows[0].keys())}\n"
            f"报表: {report_name}\n"
            f"来源: {file_path}"
        )

    lines = [
        f"指标: {metric} -> {metric_col}",
        f"命中报表: {report_name}",
        f"来源: {file_path}",
        f"结果条数: {len(rows)}",
    ]
    preview = rows[:top_n]
    for idx, row in enumerate(preview, start=1):
        flight_no = row.get("航班号", "")
        flight_date = row.get("航班日期", "")
        segment = row.get("航段", "")
        value = row.get(metric_col, "")
        # Most load-factor exports use decimal values (0-1). Render as percentage for readability.
        if metric and "客座率" in metric:
            try:
                v = float(value)
                if 0 <= v <= 1.2:
                    value = f"{v * 100:.2f}%"
            except Exception:
                pass
        if value in ("", None):
            hint = row.get("提示", "") or row.get("提示_2", "")
            if hint:
                value = f"(空值，提示={hint})"
        if metric == "单机边际贡献":
            try:
                value = f"{float(value):.2f}"
            except Exception:
                pass
        if flight_no or flight_date or segment:
            lines.append(f"[{idx}] {flight_no} {flight_date} {segment} {metric_col}={value}")
        else:
            company = row.get("公司", "")
            aircraft_type = row.get("机型", "")
            dt = row.get("日期", "")
            lines.append(f"[{idx}] {dt} {company} {aircraft_type} {metric_col}={value}")
    return "\n".join(lines)
