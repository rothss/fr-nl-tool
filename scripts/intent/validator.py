from __future__ import annotations


def _apply_airport_codes(route: dict, alias_dict: dict | None) -> dict:
    route = dict(route or {})
    cities = ((alias_dict or {}).get("cities") or {})
    alias_to_canonical: dict[str, str] = {}
    for canonical, meta in cities.items():
        alias_to_canonical[str(canonical)] = str(canonical)
        for alias in meta.get("aliases") or []:
            alias_to_canonical[str(alias)] = str(canonical)
    origin_norm = str(route.get("origin_norm") or "").strip()
    dest_norm = str(route.get("destination_norm") or "").strip()
    if origin_norm in alias_to_canonical:
        origin_norm = alias_to_canonical[origin_norm]
        route["origin_norm"] = origin_norm
    if dest_norm in alias_to_canonical:
        dest_norm = alias_to_canonical[dest_norm]
        route["destination_norm"] = dest_norm
    if origin_norm and origin_norm in cities:
        route["origin_code"] = cities[origin_norm].get("airport_code")
    if dest_norm and dest_norm in cities:
        route["destination_code"] = cities[dest_norm].get("airport_code")
    return route


def validate_and_repair_intent(
    rule_candidate: dict,
    llm_candidate: dict | None = None,
    today=None,
    alias_dict: dict | None = None,
) -> dict:
    merged = dict(rule_candidate or {})
    if llm_candidate:
        for key, value in llm_candidate.items():
            if key == "parser_trace":
                merged[key] = list(merged.get(key) or []) + [str(x) for x in (value or [])]
                continue
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                child = dict(merged.get(key) or {})
                for child_key, child_value in value.items():
                    if child_key not in child or child.get(child_key) in (None, "", [], {}):
                        child[child_key] = child_value
                merged[key] = child
                continue
            if isinstance(value, list) and isinstance(merged.get(key), list):
                existing = [str(x) for x in (merged.get(key) or []) if str(x).strip()]
                incoming = [str(x) for x in (value or []) if str(x).strip()]
                merged[key] = list(dict.fromkeys(existing + incoming))
                continue
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
    merged["route"] = _apply_airport_codes(merged.get("route") or {}, alias_dict)

    missing_slots: list[str] = []
    route = merged.get("route") or {}
    if (route.get("origin_norm") and not route.get("destination_norm")) or (route.get("destination_norm") and not route.get("origin_norm")):
        missing_slots.append("route.destination" if route.get("origin_norm") else "route.origin")

    metrics = merged.get("metrics") or []
    if not metrics:
        missing_slots.append("metrics")

    time_info = merged.get("time") or {}
    if time_info.get("mode") and (not time_info.get("start_date") or not time_info.get("end_date")):
        missing_slots.append("time.range")

    score = 0.25
    if metrics:
        score += 0.25
    if route.get("origin_norm") and route.get("destination_norm"):
        score += 0.20
    if time_info.get("mode"):
        score += 0.20
    if (merged.get("analysis") or {}).get("mode"):
        score += 0.10
    merged["confidence"] = min(1.0, score)
    merged["missing_slots"] = missing_slots

    if merged.get("route", {}).get("origin_norm") and merged.get("route", {}).get("destination_norm"):
        if (merged.get("analysis") or {}).get("mode") == "competition_review":
            merged["domain"] = "opm_future_flight"
            merged["intent_type"] = "route_competition_diagnosis"
        else:
            merged["domain"] = "opm_route_query"
            merged["intent_type"] = "route_metric_lookup"
    if llm_candidate:
        merged["parser_trace"] = list(dict.fromkeys(list(merged.get("parser_trace") or []) + ["llm:slot_fill"]))
    return merged
