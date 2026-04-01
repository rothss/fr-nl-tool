from __future__ import annotations


def decide_refresh_policy(intent: dict, candidate: dict, local_probe: dict) -> dict:
    structured = (intent or {}).get("structured_intent") or {}
    time_mode = str(((structured.get("time") or {}).get("mode")) or "")
    require_live_refresh = False
    reason_codes: list[str] = []

    if time_mode == "relative_future_range":
        require_live_refresh = True
        reason_codes.append("future_query")
    if not local_probe.get("file_exists", False):
        require_live_refresh = True
        reason_codes.append("file_missing")
    if not local_probe.get("schema_ok", True):
        require_live_refresh = True
        reason_codes.append("schema_invalid")
    if not local_probe.get("route_match_ok", True):
        require_live_refresh = True
        reason_codes.append("route_mismatch")
    if not local_probe.get("date_match_ok", True):
        require_live_refresh = True
        reason_codes.append("date_mismatch")

    return {
        "require_live_refresh": require_live_refresh,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "max_age_seconds": 1800 if time_mode == "relative_future_range" else 3600,
        "candidate_report_name": candidate.get("report_name"),
    }

