from __future__ import annotations

from planning.refresh_policy import decide_refresh_policy
from planning.router import route_report_family
from profiles import get_profile_analysis_engine_name


def build_query_plan(intent: dict, local_probe: dict | None = None) -> dict:
    routed = route_report_family(intent)
    top = (
        routed[0]
        if routed
        else {"report_family": None, "report_name": None, "score": 0.0, "reasons": []}
    )
    probe = local_probe or {
        "file_exists": False,
        "schema_ok": False,
        "route_match_ok": False,
        "date_match_ok": False,
    }
    refresh_policy = decide_refresh_policy(intent, top, probe)

    analysis_engine = get_profile_analysis_engine_name(top.get("report_family"))

    fallback_plans: list[dict] = []
    if "route_mismatch" in refresh_policy["reason_codes"]:
        fallback_plans.append({"type": "route_not_found_explain"})
    if "schema_invalid" in refresh_policy["reason_codes"]:
        fallback_plans.append({"type": "schema_validation_retry"})

    return {
        "report_family": top.get("report_family"),
        "report_name": top.get("report_name"),
        "report_path": None,
        "source_strategy": "local_then_live_if_stale_or_mismatch",
        "require_live_refresh": bool(refresh_policy["require_live_refresh"]),
        "analysis_engine": analysis_engine,
        "fallback_plans": fallback_plans,
        "rationale": list(top.get("reasons") or [])
        + [f"refresh:{x}" for x in refresh_policy["reason_codes"]],
        "candidate_score": top.get("score"),
        "refresh_policy": refresh_policy,
    }
