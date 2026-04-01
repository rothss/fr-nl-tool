from __future__ import annotations

from pathlib import Path

from common import load_yaml_or_json, references_dir
from extract_structured_table import extract_table
from intent.normalize import load_airport_aliases

def _load_report_schema_registry() -> dict[str, dict]:
    path = references_dir() / "report_schemas.yaml"
    data = load_yaml_or_json(path)
    items = data.get("schemas") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}
    out: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        report_name = str(item.get("report_name") or "").strip()
        if report_name:
            out[report_name] = item
    return out


REPORT_SCHEMAS: dict[str, dict] = _load_report_schema_registry()


def get_report_schema(report_name: str | None) -> dict | None:
    if not report_name:
        return None
    return REPORT_SCHEMAS.get(str(report_name))


def _route_alias_to_code() -> dict[str, str]:
    alias_cfg = load_airport_aliases()
    mapping: dict[str, str] = {}
    for canonical, meta in (alias_cfg.get("cities") or {}).items():
        code = str(meta.get("airport_code") or "").strip()
        if not code:
            continue
        mapping[str(canonical)] = code
        for alias in meta.get("aliases") or []:
            mapping[str(alias)] = code
    return mapping


def _normalize_route_to_codes(route_text: object, alias_to_code: dict[str, str]) -> tuple[str | None, str | None]:
    text = str(route_text or "").strip()
    if not text or "-" not in text:
        return None, None
    left, right = text.split("-", 1)
    return alias_to_code.get(left.strip()), alias_to_code.get(right.strip())


def validate_schema_columns(columns: list[str], schema: dict | None) -> dict:
    if not schema:
        return {"schema_ok": True, "missing_identity_cols": [], "missing_metric_groups": []}
    required = [str(x) for x in schema.get("required_identity_cols") or []]
    missing_identity = [c for c in required if c not in columns]
    missing_metric_groups: list[str] = []
    for metric_name, metric_cols in (schema.get("metric_groups") or {}).items():
        if not any(str(col) in columns for col in (metric_cols or [])):
            missing_metric_groups.append(str(metric_name))
    return {
        "schema_ok": len(missing_identity) == 0,
        "missing_identity_cols": missing_identity,
        "missing_metric_groups": missing_metric_groups,
    }


def probe_local_file_against_intent(file_path: str | Path | None, report_name: str | None, intent: dict | None) -> dict:
    path = Path(str(file_path)) if file_path else None
    if not path or not path.exists():
        return {
            "file_exists": False,
            "schema_ok": False,
            "route_match_ok": False,
            "date_match_ok": False,
            "row_count": 0,
            "columns": [],
            "warnings": ["file_missing"],
        }
    schema = get_report_schema(report_name)
    extracted = extract_table(path)
    columns = [str(c) for c in (extracted.get("columns") or [])]
    schema_eval = validate_schema_columns(columns, schema)
    filters = ((intent or {}).get("filters") or {})
    route_match_ok = True
    date_match_ok = True
    warnings: list[str] = []
    rows = extracted.get("rows") or []
    alias_to_code = _route_alias_to_code()

    seg_from = str(filters.get("segment_from") or "").strip()
    seg_to = str(filters.get("segment_to") or "").strip()
    if seg_from and seg_to:
        req_left = alias_to_code.get(seg_from)
        req_right = alias_to_code.get(seg_to)
        route_match_ok = False
        for row in rows:
            left_code, right_code = _normalize_route_to_codes(row.get(schema.get("route_col", "航段") if schema else "航段"), alias_to_code)
            if req_left and req_right and left_code == req_left and right_code == req_right:
                route_match_ok = True
                break
            route_text = str(row.get(schema.get("route_col", "航段") if schema else "航段") or "")
            if seg_from in route_text and seg_to in route_text:
                route_match_ok = True
                break
        if not route_match_ok:
            warnings.append("route_mismatch")

    date_values = {str(x) for x in (filters.get("flight_date") or []) if str(x).strip()}
    if date_values:
        date_col = schema.get("date_col", "航班日期") if schema else "航班日期"
        date_match_ok = False
        for row in rows:
            cell = str(row.get(date_col) or "").split(" ")[0]
            if cell in date_values:
                date_match_ok = True
                break
        if not date_match_ok:
            warnings.append("date_mismatch")

    if not schema_eval["schema_ok"]:
        warnings.append("schema_invalid")

    return {
        "file_exists": True,
        "schema_ok": bool(schema_eval["schema_ok"]),
        "route_match_ok": route_match_ok,
        "date_match_ok": date_match_ok,
        "row_count": len(rows),
        "columns": columns,
        "warnings": warnings,
        "schema_name": schema.get("schema_name") if schema else None,
        "missing_identity_cols": schema_eval["missing_identity_cols"],
        "missing_metric_groups": schema_eval["missing_metric_groups"],
    }
