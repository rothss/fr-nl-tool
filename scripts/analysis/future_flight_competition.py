from __future__ import annotations

import re


def _to_float(v: object) -> float | None:
    s = str(v or "").strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    try:
        x = float(m.group(0))
    except Exception:
        return None
    if "%" in s or ("同比" in s and abs(x) <= 1.0):
        if abs(x) <= 1.0 and "%" not in s:
            return x * 100.0
        return x
    return x


def render_future_competition_review(rows: list[dict], report_name: str, source_path: str, filters: dict) -> str:
    main_rows = [r for r in rows if str(r.get("航班号", "")).strip()]
    if not main_rows:
        return f"未在命中报表中找到可分析的主航班数据。\n报表: {report_name}\n来源: {source_path}"

    findings: list[str] = []
    improvements: list[str] = []
    for r in main_rows:
        date_text = str(r.get("航班日期", "")).split(" ")[0]
        flight_no = str(r.get("航班号", "")).strip()
        dep_time = str(r.get("时刻", "")).split(" ")[-1][:5]
        load = _to_float(r.get("现在客座率"))
        target = _to_float(r.get("本DCP阶段标准客座率目标"))
        load_gap = _to_float(r.get("与竞航客座率差"))
        price_gap = _to_float(r.get("与竞航价格差"))
        if load is not None and abs(load) <= 1.0:
            load *= 100.0
        if target is not None and abs(target) <= 1.0:
            target *= 100.0
        if load_gap is not None and abs(load_gap) <= 1.0:
            load_gap *= 100.0

        if (target is not None) and (load is not None) and (target - load >= 5):
            findings.append(f"{date_text} {flight_no} {dep_time} 客座率 {load:.1f}% 低于阶段目标 {target:.1f}%")
        if (load_gap is not None) and (load_gap <= -5):
            findings.append(f"{date_text} {flight_no} {dep_time} 客座率较竞航低 {abs(load_gap):.1f} 个点")
        if (load is not None) and (load >= 86) and (price_gap is not None) and (price_gap <= -500):
            improvements.append(f"{date_text} {flight_no} {dep_time} 客座率已高位，仍比竞航低价 {abs(price_gap):.0f} 元，可试探提价")
        if (load is not None) and (load <= 60) and (price_gap is not None) and (price_gap < -300):
            improvements.append(f"{date_text} {flight_no} {dep_time} 已明显低价但客座率仍弱，需排查机型投放、时刻竞争和渠道投放，不宜只继续降价")
        elif (load is not None) and (load <= 80) and (price_gap is not None) and (price_gap >= -200):
            improvements.append(f"{date_text} {flight_no} {dep_time} 客座率偏弱但价格优势不明显，可考虑促销或放舱")

    head = (
        f"命中报表: {report_name}\n"
        f"分析航段: {str(filters.get('segment_from') or '')}-{str(filters.get('segment_to') or '')}\n"
        f"分析区间: {str(filters.get('date_start') or '-')} 到 {str(filters.get('date_end') or '-')}\n"
        f"来源: {source_path}"
    )
    abnormal = "；".join(findings[:4]) if findings else "近三天未见明显异常。"
    improve = "；".join(improvements[:4]) if improvements else "暂未识别出明确调价/投放改进点。"
    return f"{head}\n异常判断: {abnormal}\n改进建议: {improve}"

