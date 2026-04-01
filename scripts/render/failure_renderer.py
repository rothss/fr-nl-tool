from __future__ import annotations


def render_failure_message(reason_code: str | None, payload: dict | None = None) -> str:
    reason = str(reason_code or "").strip()
    payload = payload or {}
    if reason == "no_report_match":
        return "未找到匹配的报表。"
    if reason == "intent_low_confidence":
        return "意图解析置信度不足。"
    if reason == "intent_missing_required_slots":
        return "意图解析缺少关键槽位。"
    if reason == "live_refresh_failed":
        err = str(payload.get("live_refresh_error") or payload.get("message") or "").strip()
        return f"实时刷新失败。{err}" if err else "实时刷新失败。"
    if reason == "report_schema_invalid":
        return "报表结构不满足当前查询要求。"
    if reason == "route_not_found_in_report":
        return "未在当前报表中找到请求航段。"
    if reason == "date_not_found_in_report":
        return "未在当前报表中找到请求日期。"
    return "查询执行失败。"


def infer_next_action(reason_code: str | None) -> str | None:
    reason = str(reason_code or "").strip()
    if reason == "no_report_match":
        return "refine_query"
    if reason == "live_refresh_failed":
        return "retry_or_check_login"
    if reason in {"route_not_found_in_report", "date_not_found_in_report"}:
        return "trigger_live_refresh"
    return None

