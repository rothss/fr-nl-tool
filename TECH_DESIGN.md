# OPM NL Skill Technical Design

## 1. Goals

This document defines the target architecture for the `opm_nl` skill so it can be called by OpenClaw with:

- fast first-pass intent resolution
- precise report routing and data-source selection
- robust live-refresh fallback
- structured intermediate outputs
- controlled degradation instead of ad hoc file inspection
- support for both rule-based parsing and local small-model intent extraction

The design specifically addresses the current failure mode where:

- the agent deviates from the skill main path after a partial failure
- time phrases such as `未来两天` are not recognized
- multi-metric requests such as `客座率和票价` are collapsed into one metric
- competitor diagnosis is not always detected
- stale or mismatched local Excel files can be treated as valid answers

## 2. Non-Goals

This design does not cover:

- UI changes in OpenClaw itself
- training a custom foundation model
- replacing existing OPM export scripts end to end
- generalized NL-to-SQL outside this skill domain

## 3. Design Principles

1. Structured outputs first.
2. Orchestration must be deterministic.
3. LLMs may assist parsing, but cannot control execution flow.
4. Report-specific logic belongs to report-specific modules.
5. Failure reasons must be machine-readable.
6. Local small models are used only for slot extraction, not free-form reasoning over raw files.
7. New parsing support must be added at the abstraction level, not as one-off query patches.
8. Every new parser capability must map to a reusable semantic slot or enum.
9. Regression coverage for a new pattern must include at least one sibling variant, not just the original failing phrase.

## 3.1 Anti-Specialization Guardrails

The redesign must avoid overfitting to currently observed failures.

Required guardrails:

1. Do not add behavior framed as `support exact phrase X only`.
2. Add new time support as normalized time semantics, not isolated phrase branches.
3. Add new comparison support as `analysis.mode` or related slots, not one-off output triggers.
4. Add new metric support as list extraction, not special casing a single metric pair.
5. Add new route support through alias dictionaries and canonical entities, not raw substring hacks for one city pair.
6. Every parser improvement must preserve backward compatibility for existing successful cases.
7. Every parser improvement must add variant regression cases from the same semantic family.

## 4. Target Runtime Flow

```text
User Query
  -> Input Normalization
  -> Intent Parsing
  -> Intent Validation / Repair
  -> Query Planning
  -> Data Acquisition
  -> Structured Extraction
  -> Analysis Engine
  -> Answer Rendering
  -> Structured OpenClaw Result
```

## 5. Proposed Directory Layout

```text
scripts/
  runner.py
  intent/
    schema.py
    normalize.py
    parser_rules.py
    parser_llm.py
    validator.py
  planning/
    planner.py
    router.py
    refresh_policy.py
  data/
    catalog.py
    source_loader.py
    extractor_registry.py
    extract_structured_table.py
    schemas.py
  analysis/
    future_flight_competition.py
    first_last_flight.py
    airline_yoy.py
    single_margin.py
  render/
    answer_renderer.py
    failure_renderer.py
  adapters/
    openclaw_contract.py
references/
  airport_aliases.yaml
  intent_examples.json
  report_schemas.yaml
tests/
  intent_cases.json
  e2e_cases.json
  test_intent_parser.py
  test_planner.py
  test_future_flight_competition.py
```

## 6. Main Modules and Responsibilities

### 6.1 `runner.py`

Single entry point for the skill.

Responsibilities:

- receive query text and runtime options
- invoke the fixed orchestration pipeline
- never inspect raw Excel files directly for ad hoc debugging
- return one structured result envelope

Interface:

```python
def run_query(
    query: str,
    user: str | None = None,
    prefer_live: bool | None = None,
    output_format: str = "json",
) -> dict: ...
```

CLI:

```powershell
python runner.py "海口到北京首都未来两天的客座率和票价，和竞争对手比有什么问题" --user zhuanz
```

### 6.2 `intent/normalize.py`

Responsibilities:

- normalize punctuation
- remove boilerplate prefixes
- normalize airport and city aliases
- normalize route separators

Interface:

```python
class NormalizedQuery(TypedDict):
    raw_query: str
    cleaned_query: str
    tokens: list[str]
    replacements: list[dict]

def normalize_query(query: str, alias_dict: dict) -> NormalizedQuery: ...
```

### 6.3 `intent/parser_rules.py`

Responsibilities:

- high-confidence extraction of:
  - flight numbers
  - route
  - explicit dates
  - relative time windows
  - analysis keywords
  - metric keywords

Interface:

```python
def parse_intent_rules(normalized: dict, today: date | None = None) -> dict: ...
```

### 6.4 `intent/parser_llm.py`

Responsibilities:

- fill missing slots when rule parsing is incomplete
- operate under strict JSON-only output mode
- never select report paths or perform execution

Interface:

```python
class LLMIntentParser:
    def __init__(self, model_name: str, provider: str = "local"): ...
    def parse(self, normalized_query: str, hints: dict | None = None) -> dict: ...
```

Supported outputs are validated against `IntentCandidate`.

### 6.5 `intent/validator.py`

Responsibilities:

- merge rule and LLM candidates
- validate against allowed enums
- normalize final dates and airport entities
- attach confidence and missing slots

Interface:

```python
def validate_and_repair_intent(
    rule_candidate: dict,
    llm_candidate: dict | None,
    today: date | None = None,
    alias_dict: dict | None = None,
) -> dict: ...
```

### 6.6 `planning/router.py`

Responsibilities:

- map intent types and metrics to report families
- define candidate reports
- rank report families before file-level selection

Interface:

```python
def route_report_family(intent: dict) -> list[dict]: ...
```

Example output:

```json
[
  {
    "report_family": "future_flight_competition",
    "report_name": "未来航班客座率票价分析",
    "score": 0.97,
    "reasons": ["route_query", "future_time_range", "fare_metric", "competitor_analysis"]
  }
]
```

### 6.7 `planning/refresh_policy.py`

Responsibilities:

- determine whether local file is acceptable
- decide whether live refresh is required before analysis
- check stale files, route mismatch, missing columns, incomplete competitor data

Interface:

```python
def decide_refresh_policy(intent: dict, candidate: dict, local_probe: dict) -> dict: ...
```

Example output:

```json
{
  "require_live_refresh": true,
  "reason_codes": ["future_query", "route_mismatch", "stale_file"],
  "max_age_seconds": 1800
}
```

### 6.8 `planning/planner.py`

Responsibilities:

- combine routed candidates, local probes, refresh policy, and analysis engine selection
- produce a deterministic plan

Interface:

```python
def build_query_plan(intent: dict, catalog: dict, local_probe: dict | None = None) -> dict: ...
```

### 6.9 `data/catalog.py`

Responsibilities:

- query report catalog db
- resolve report name to canonical file path and report cpt path
- provide candidate metadata

Interface:

```python
def load_catalog(db_path: str | Path) -> dict: ...
def find_report_candidates(intent: dict, catalog: dict) -> list[dict]: ...
```

### 6.10 `data/source_loader.py`

Responsibilities:

- load local Excel
- trigger live export when required
- persist refreshed output
- emit source metadata

Interface:

```python
def acquire_source(plan: dict, intent: dict) -> dict: ...
```

Example output:

```json
{
  "ok": true,
  "source_type": "live_export",
  "file_path": "C:\\Users\\ZhuanZ\\opm_mirror\\包干航线\\未来航班客座率票价分析.xlsx",
  "refreshed": true,
  "refresh_message": "ok",
  "last_modified": "2026-04-01T13:42:11+08:00"
}
```

### 6.11 `data/extractor_registry.py`

Responsibilities:

- select a report-specific extractor
- fall back to generic extractor when allowed

Interface:

```python
def get_extractor(report_name: str): ...
```

### 6.12 `data/schemas.py`

Responsibilities:

- define report-level contracts
- declare required columns and analysis support

Interface:

```python
def get_report_schema(report_name: str) -> dict | None: ...
```

### 6.13 `analysis/*.py`

Responsibilities:

- transform extracted rows into structured business findings
- never read raw files directly
- never decide refresh policy

Example interface:

```python
def analyze_future_flight_competition(intent: dict, extracted: dict, source_meta: dict) -> dict: ...
```

### 6.14 `render/answer_renderer.py`

Responsibilities:

- render concise final answer text from structured analysis result
- keep the final answer separate from machine-readable result

Interface:

```python
def render_answer(analysis_result: dict, intent: dict, source_meta: dict) -> str: ...
```

### 6.15 `render/failure_renderer.py`

Responsibilities:

- produce user-facing failure messages without losing structured reason codes

Interface:

```python
def render_failure(error_payload: dict) -> str: ...
```

### 6.16 `adapters/openclaw_contract.py`

Responsibilities:

- convert runner output into a stable OpenClaw envelope
- ensure failures and retries are machine-readable

Interface:

```python
def to_openclaw_result(payload: dict) -> dict: ...
```

## 7. Canonical Data Models

The following JSON schemas are the contract between modules.

### 7.1 `NormalizedQuery`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "NormalizedQuery",
  "type": "object",
  "required": ["raw_query", "cleaned_query", "tokens", "replacements"],
  "properties": {
    "raw_query": { "type": "string" },
    "cleaned_query": { "type": "string" },
    "tokens": {
      "type": "array",
      "items": { "type": "string" }
    },
    "replacements": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["from", "to", "type"],
        "properties": {
          "from": { "type": "string" },
          "to": { "type": "string" },
          "type": { "type": "string" }
        }
      }
    }
  }
}
```

### 7.2 `IntentCandidate`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "IntentCandidate",
  "type": "object",
  "required": [
    "raw_query",
    "domain",
    "intent_type",
    "metrics",
    "route",
    "flight",
    "time",
    "analysis",
    "scope",
    "constraints",
    "confidence",
    "missing_slots",
    "parser_trace"
  ],
  "properties": {
    "raw_query": { "type": "string" },
    "domain": { "type": ["string", "null"] },
    "intent_type": { "type": ["string", "null"] },
    "metrics": {
      "type": "array",
      "items": { "type": "string" }
    },
    "route": {
      "type": "object",
      "required": [
        "origin_raw",
        "destination_raw",
        "origin_norm",
        "destination_norm",
        "origin_code",
        "destination_code"
      ],
      "properties": {
        "origin_raw": { "type": ["string", "null"] },
        "destination_raw": { "type": ["string", "null"] },
        "origin_norm": { "type": ["string", "null"] },
        "destination_norm": { "type": ["string", "null"] },
        "origin_code": { "type": ["string", "null"] },
        "destination_code": { "type": ["string", "null"] }
      }
    },
    "flight": {
      "type": "object",
      "required": ["flight_numbers"],
      "properties": {
        "flight_numbers": {
          "type": "array",
          "items": { "type": "string" }
        }
      }
    },
    "time": {
      "type": "object",
      "required": [
        "mode",
        "start_date",
        "end_date",
        "anchor",
        "offset_start",
        "offset_end",
        "dates"
      ],
      "properties": {
        "mode": { "type": ["string", "null"] },
        "start_date": { "type": ["string", "null"], "format": "date" },
        "end_date": { "type": ["string", "null"], "format": "date" },
        "anchor": { "type": ["string", "null"] },
        "offset_start": { "type": ["integer", "null"] },
        "offset_end": { "type": ["integer", "null"] },
        "dates": {
          "type": "array",
          "items": { "type": "string", "format": "date" }
        }
      }
    },
    "analysis": {
      "type": "object",
      "required": ["mode", "compare_target", "question_type"],
      "properties": {
        "mode": { "type": ["string", "null"] },
        "compare_target": { "type": ["string", "null"] },
        "question_type": { "type": ["string", "null"] }
      }
    },
    "scope": {
      "type": "object",
      "required": ["owner_scope", "company", "aircraft_type"],
      "properties": {
        "owner_scope": { "type": ["string", "null"] },
        "company": { "type": ["string", "null"] },
        "aircraft_type": { "type": ["string", "null"] }
      }
    },
    "constraints": {
      "type": "object",
      "required": ["prefer_live_refresh"],
      "properties": {
        "prefer_live_refresh": { "type": "boolean" }
      }
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0
    },
    "missing_slots": {
      "type": "array",
      "items": { "type": "string" }
    },
    "parser_trace": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

### 7.3 `QueryPlan`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "QueryPlan",
  "type": "object",
  "required": [
    "report_family",
    "report_name",
    "report_path",
    "source_strategy",
    "require_live_refresh",
    "analysis_engine",
    "fallback_plans",
    "rationale"
  ],
  "properties": {
    "report_family": { "type": ["string", "null"] },
    "report_name": { "type": ["string", "null"] },
    "report_path": { "type": ["string", "null"] },
    "source_strategy": { "type": "string" },
    "require_live_refresh": { "type": "boolean" },
    "analysis_engine": { "type": ["string", "null"] },
    "fallback_plans": {
      "type": "array",
      "items": { "type": "object" }
    },
    "rationale": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

### 7.4 `SourceMeta`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SourceMeta",
  "type": "object",
  "required": [
    "ok",
    "source_type",
    "file_path",
    "refreshed",
    "refresh_message",
    "last_modified",
    "schema_ok",
    "route_match_ok",
    "date_match_ok"
  ],
  "properties": {
    "ok": { "type": "boolean" },
    "source_type": { "type": ["string", "null"] },
    "file_path": { "type": ["string", "null"] },
    "refreshed": { "type": "boolean" },
    "refresh_message": { "type": ["string", "null"] },
    "last_modified": { "type": ["string", "null"], "format": "date-time" },
    "schema_ok": { "type": "boolean" },
    "route_match_ok": { "type": "boolean" },
    "date_match_ok": { "type": "boolean" },
    "warnings": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

### 7.5 `ExtractedTable`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ExtractedTable",
  "type": "object",
  "required": ["columns", "rows", "meaningful_row_count", "sheet_count", "schema_name"],
  "properties": {
    "schema_name": { "type": ["string", "null"] },
    "columns": {
      "type": "array",
      "items": { "type": "string" }
    },
    "rows": {
      "type": "array",
      "items": { "type": "object" }
    },
    "meaningful_row_count": { "type": "integer", "minimum": 0 },
    "sheet_count": { "type": "integer", "minimum": 0 }
  }
}
```

### 7.6 `AnalysisResult`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AnalysisResult",
  "type": "object",
  "required": [
    "ok",
    "analysis_engine",
    "matched_route",
    "matched_dates",
    "issues",
    "advice",
    "summary"
  ],
  "properties": {
    "ok": { "type": "boolean" },
    "analysis_engine": { "type": ["string", "null"] },
    "matched_route": { "type": ["string", "null"] },
    "matched_dates": {
      "type": "array",
      "items": { "type": "string", "format": "date" }
    },
    "issues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["issue_type", "severity"],
        "properties": {
          "issue_type": { "type": "string" },
          "severity": { "type": "string" },
          "flight_no": { "type": ["string", "null"] },
          "date": { "type": ["string", "null"], "format": "date" },
          "details": { "type": "object" }
        }
      }
    },
    "advice": {
      "type": "array",
      "items": { "type": "string" }
    },
    "summary": { "type": ["string", "null"] }
  }
}
```

### 7.7 `OpenClawResultEnvelope`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "OpenClawResultEnvelope",
  "type": "object",
  "required": [
    "ok",
    "stage",
    "intent",
    "plan",
    "source_meta",
    "analysis_result",
    "answer_text",
    "reason_code"
  ],
  "properties": {
    "ok": { "type": "boolean" },
    "stage": { "type": "string" },
    "reason_code": { "type": ["string", "null"] },
    "intent": { "type": ["object", "null"] },
    "plan": { "type": ["object", "null"] },
    "source_meta": { "type": ["object", "null"] },
    "analysis_result": { "type": ["object", "null"] },
    "answer_text": { "type": ["string", "null"] },
    "message": { "type": ["string", "null"] },
    "next_action": { "type": ["string", "null"] }
  }
}
```

## 8. Report Schema Contract

For high-value reports, use report-specific schema definitions instead of generic heuristics only.

Example for `未来航班客座率票价分析`:

```json
{
  "report_name": "未来航班客座率票价分析",
  "schema_name": "future_flight_competition_v1",
  "required_identity_cols": ["航班号", "航班日期", "航段"],
  "metric_groups": {
    "客座率": ["现在客座率", "竞航客座率", "与竞航客座率差"],
    "票价": ["价格", "竞航价格", "与竞航价格差"]
  },
  "support_analysis_modes": ["competition_review", "pricing_review"],
  "noise_tokens": ["备注", "数据最后更新时间"],
  "soft_warning_tokens": ["新开航线"],
  "route_col": "航段",
  "date_col": "航班日期",
  "flight_col": "航班号"
}
```

Validation rules:

1. Required identity columns must exist.
2. If competitor analysis is requested, at least one competitor metric group must be present.
3. If all matched rows contain only soft warning tokens and no competitor values, result is degraded but not treated as parse failure.
4. Route and date match are checked after normalization, not via raw string includes only.

## 9. Intent Parsing Strategy

### 9.1 Hybrid Parsing

Use a three-stage strategy:

1. rule parser
2. local small-model parser
3. validator and repair

### 9.2 Rule Parser Scope

The rule parser should remain responsible for:

- flight number patterns
- explicit route extraction
- explicit date extraction
- relative time phrase detection
- high-confidence metric keywords
- competitor-analysis trigger phrases

### 9.3 LLM Parser Scope

The local LLM parser should only fill slots such as:

- missing time mode
- multi-metric extraction
- whether the query is diagnostic vs lookup
- whether `竞争对手比` means competitor review
- route extraction when syntax is loose

The local LLM parser must not:

- choose report files
- inspect Excel content
- infer non-existent facts
- override high-confidence explicit rule hits without validator approval

### 9.4 Local Small Model Prompt Contract

Recommended prompt shape:

```text
You are an OPM intent extraction engine.
Return JSON only.
Do not explain.
If a field is unknown, output null.

Fields:
- domain
- intent_type
- metrics
- route.origin_raw
- route.destination_raw
- time.mode
- time.start_date
- time.end_date
- analysis.mode
- analysis.compare_target
- confidence
```

The output is validated against `IntentCandidate`.

## 10. Time Semantics

Time parsing should move from phrase-specific branching to normalized time semantics.

Supported modes:

- `single_date`
- `explicit_range`
- `relative_past_range`
- `relative_future_range`
- `calendar_week`
- `calendar_month`

Examples:

- `近三天` -> `relative_past_range`
- `未来两天` -> `relative_future_range`
- `明天` -> `single_date`
- `4月1日到4月3日` -> `explicit_range`

Canonical representation:

```json
{
  "mode": "relative_future_range",
  "anchor": "today",
  "offset_start": 0,
  "offset_end": 1,
  "start_date": "2026-04-01",
  "end_date": "2026-04-02",
  "dates": ["2026-04-01", "2026-04-02"]
}
```

## 11. Airport and Route Normalization

Add `references/airport_aliases.yaml`.

Example:

```yaml
cities:
  海口:
    aliases: [海口, 海口美兰, 美兰, HAK]
    airport_code: HAK
  北京首都:
    aliases: [北京首都, 首都, 首都机场, PEK]
    airport_code: PEK
  北京大兴:
    aliases: [北京大兴, 大兴, PKX]
    airport_code: PKX
```

Normalization steps:

1. normalize user query entities to canonical airport nodes
2. normalize extracted Excel `航段`
3. compare route by canonical codes where possible

This prevents `海口` from accidentally matching `博鳌`.

## 12. Query Planning Rules

Planner policy for future-flight competition queries:

1. if route + future range + fare/load factor + competitor trigger are present:
   use `未来航班客座率票价分析`
2. if the query targets future flights:
   prefer live refresh when local file is stale or route/date mismatch exists
3. if local file schema is valid but route mismatch exists:
   do not answer from local file
4. if live refresh still returns unmatched route:
   return structured route-not-found failure
5. if route matches but competitor columns are empty:
   return degraded answer with explicit reason

## 13. Failure Taxonomy

All failures should use machine-readable reason codes.

Suggested reason codes:

- `intent_low_confidence`
- `intent_missing_required_slots`
- `report_family_not_found`
- `report_file_missing`
- `report_schema_invalid`
- `route_not_found_in_report`
- `date_not_found_in_report`
- `live_refresh_failed`
- `live_refresh_auth_required`
- `analysis_input_insufficient`
- `competitor_columns_missing`

Example failure payload:

```json
{
  "ok": false,
  "stage": "analysis",
  "reason_code": "route_not_found_in_report",
  "message": "未在当前报表中找到海口-北京首都航段",
  "details": {
    "requested_route": "海口-北京首都",
    "available_routes_sample": ["博鳌-北京首都"]
  },
  "next_action": "trigger_live_refresh"
}
```

## 14. OpenClaw Integration Contract

OpenClaw should invoke the skill through a single command and expect a single JSON result.

Recommended command pattern:

```powershell
python runner.py "海口到北京首都未来两天的客座率和票价，和竞争对手比有什么问题" --user zhuanz --output-format json
```

Required rules:

1. OpenClaw must not inspect the Excel file directly after a structured failure.
2. OpenClaw must not print ad hoc `read_excel(...).head()` outputs to the user.
3. If `reason_code == live_refresh_auth_required`, OpenClaw may instruct the user to re-login.
4. If `next_action == trigger_live_refresh`, OpenClaw may re-run the skill with refresh enabled, but still through the same skill entrypoint.

## 15. Example End-to-End Payload

```json
{
  "ok": true,
  "stage": "completed",
  "reason_code": null,
  "intent": {
    "raw_query": "海口到北京首都未来两天的客座率和票价，和竞争对手比有什么问题",
    "domain": "opm_future_flight",
    "intent_type": "route_competition_diagnosis",
    "metrics": ["客座率", "票价"],
    "route": {
      "origin_raw": "海口",
      "destination_raw": "北京首都",
      "origin_norm": "海口",
      "destination_norm": "北京首都",
      "origin_code": "HAK",
      "destination_code": "PEK"
    },
    "flight": { "flight_numbers": [] },
    "time": {
      "mode": "relative_future_range",
      "start_date": "2026-04-01",
      "end_date": "2026-04-02",
      "anchor": "today",
      "offset_start": 0,
      "offset_end": 1,
      "dates": ["2026-04-01", "2026-04-02"]
    },
    "analysis": {
      "mode": "competition_review",
      "compare_target": "competitor",
      "question_type": "diagnosis"
    },
    "scope": {
      "owner_scope": "all",
      "company": null,
      "aircraft_type": null
    },
    "constraints": { "prefer_live_refresh": true },
    "confidence": 0.95,
    "missing_slots": [],
    "parser_trace": ["rules:route", "rules:future_range", "rules:metrics", "llm:competition_review"]
  },
  "plan": {
    "report_family": "future_flight_competition",
    "report_name": "未来航班客座率票价分析",
    "report_path": "doc/Fdjt/市场监督/客座率监控/未来航班客座率票价分析-PG库.cpt",
    "source_strategy": "local_then_live_if_stale_or_mismatch",
    "require_live_refresh": true,
    "analysis_engine": "future_flight_competition",
    "fallback_plans": [{"type": "route_not_found_explain"}],
    "rationale": ["future_route_query", "competitor_review", "multi_metric_request"]
  },
  "source_meta": {
    "ok": true,
    "source_type": "live_export",
    "file_path": "C:\\Users\\ZhuanZ\\opm_mirror\\包干航线\\未来航班客座率票价分析.xlsx",
    "refreshed": true,
    "refresh_message": "ok",
    "last_modified": "2026-04-01T13:42:11+08:00",
    "schema_ok": true,
    "route_match_ok": true,
    "date_match_ok": true,
    "warnings": []
  },
  "analysis_result": {
    "ok": true,
    "analysis_engine": "future_flight_competition",
    "matched_route": "海口-北京首都",
    "matched_dates": ["2026-04-01", "2026-04-02"],
    "issues": [
      {
        "issue_type": "load_below_competitor",
        "severity": "high",
        "flight_no": "HUxxxx",
        "date": "2026-04-01",
        "details": {
          "load_gap_pct": -6.2,
          "price_gap": -320
        }
      }
    ],
    "advice": [
      "价格已低于竞航但客座率仍弱，建议排查时刻与渠道投放，而不是继续单纯降价"
    ],
    "summary": "未来两天海口-北京首都航段存在竞对弱势航班。"
  },
  "answer_text": "未来两天海口-北京首都航段存在竞对弱势航班，主要问题是低价但客座率仍弱。"
}
```

## 16. Testing Strategy

### 16.1 Intent Tests

Use `tests/intent_cases.json`.

Coverage:

- `近三天`
- `未来两天`
- `明天`
- `4月1日到4月3日`
- dual metrics like `客座率和票价`
- competitor diagnosis phrasing
- airport alias phrases
- route-only queries

### 16.2 Planner Tests

Ensure the planner:

- routes future-flight competitor queries to the correct family
- requires live refresh on stale files
- rejects route-mismatched local files

### 16.3 E2E Tests

Use `tests/e2e_cases.json`.

Expected assertions:

- final reason code is correct
- route matching is exact after normalization
- multi-metric requests preserve both metrics
- live refresh is triggered when policy requires

## 17. Migration Plan

### Phase 1: Stabilize Contract

- add `runner.py`
- add structured result envelope
- forbid ad hoc Excel inspection after failure
- move failure messages to reason-code based output

### Phase 2: Extract Intent Layer

- split parsing into `normalize.py`, `parser_rules.py`, `validator.py`
- add support for `relative_future_range`
- add dual-metric extraction
- add competitor-review detection improvements
- add airport and route alias normalization
- preserve the current legacy `parse_query()` return shape so downstream execution remains stable

### Phase 3: Add Schema-Aware Planning

- create `data/schemas.py`
- create `planning/planner.py`
- add route/date/schema matching gates

### Phase 4: Introduce Local Small-Model Parsing

- implement `parser_llm.py`
- restrict to JSON slot extraction
- merge through validator only

### Phase 5: Expand Analysis Engines

- isolate `future_flight_competition` logic
- add explicit degraded-answer paths for `新开航线` and empty competitor columns

## 18. Implementation Priorities

Highest impact first:

1. structured result envelope
2. fixed orchestrator
3. future-time parsing normalization
4. route/airport alias normalization
5. report schema registry
6. local small-model intent extraction

## 19. Risks

1. Local small models may over-extract nonexistent slots.
   Mitigation: validator and confidence thresholds.

2. Report exports may still return stale or summary-only files.
   Mitigation: route/date/schema checks before analysis.

3. Competitor columns may be missing for new routes.
   Mitigation: degraded-answer path with explicit reason codes.

4. Existing monolithic script behavior may hide implicit dependencies.
   Mitigation: migrate in phases and preserve fixture-based regression tests.

## 20. Success Criteria

The redesign is considered successful when:

- `未来两天` and similar future-range phrases parse correctly
- dual metrics remain intact through planning and analysis
- OpenClaw no longer returns raw Excel header dumps
- route mismatch produces structured failure instead of false answer
- local small-model parsing improves coverage without controlling execution
