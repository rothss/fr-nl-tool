from __future__ import annotations

from copy import deepcopy


def infer_stage(payload: dict) -> str:
    if payload.get("ok"):
        return "completed"
    reason = str(payload.get("reason") or "")
    if reason in {"no_report_match"}:
        return "planning"
    if reason in {"intent_low_confidence", "intent_missing_required_slots"}:
        return "intent"
    return "execution"


def infer_reason_code(payload: dict) -> str | None:
    if payload.get("ok"):
        return None
    reason = str(payload.get("reason") or "").strip()
    if reason:
        return reason
    if payload.get("live_refresh_error"):
        return "live_refresh_failed"
    return "query_failed"


def infer_message(payload: dict) -> str | None:
    if payload.get("ok"):
        return None
    if payload.get("message"):
        return str(payload["message"])
    reason = infer_reason_code(payload)
    if reason == "no_report_match":
        return "未找到匹配的报表。"
    if reason == "intent_low_confidence":
        return "意图解析置信度不足。"
    if reason == "intent_missing_required_slots":
        return "意图解析缺少关键槽位。"
    if reason == "live_refresh_failed":
        return "实时刷新失败。"
    return "查询执行失败。"


def infer_next_action(payload: dict) -> str | None:
    if payload.get("ok"):
        return None
    reason = infer_reason_code(payload)
    if reason == "no_report_match":
        return "refine_query"
    if reason == "live_refresh_failed":
        return "retry_or_check_login"
    return None


def to_openclaw_result(payload: dict) -> dict:
    raw = deepcopy(payload)
    result = {
        "ok": bool(raw.get("ok")),
        "stage": infer_stage(raw),
        "reason_code": infer_reason_code(raw),
        "intent": raw.get("intent"),
        "plan": raw.get("plan"),
        "source_meta": raw.get("source_meta"),
        "analysis_result": raw.get("analysis_result"),
        "answer_text": raw.get("answer_text"),
        "message": infer_message(raw),
        "next_action": infer_next_action(raw),
    }
    return result

