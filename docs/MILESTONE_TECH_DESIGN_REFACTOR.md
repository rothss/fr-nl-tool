# OPM NL Skill Milestone Notes

## Milestone

- Name: `TECH_DESIGN refactor complete`
- Baseline commit: `19e3857`
- Scope: restructure the `fr-nl-report-query` skill to match the target architecture in `TECH_DESIGN.md`

## What Changed

This milestone converts the skill from a monolithic execution path into a structured, layered runtime:

```text
runner
  -> intent
  -> planning
  -> data
  -> analysis
  -> render
  -> adapters
```

Major additions:

- `scripts/intent/`
  - `normalize.py`
  - `parser_rules.py`
  - `parser_llm.py`
  - `validator.py`
  - `schema.py`
- `scripts/planning/`
  - `router.py`
  - `refresh_policy.py`
  - `planner.py`
- `scripts/data/`
  - `catalog.py`
  - `schemas.py`
  - `source_loader.py`
  - `extractor_registry.py`
- `scripts/analysis/`
  - `future_flight_competition.py`
  - `airline_yoy.py`
  - `ranked_flights.py`
  - `single_margin.py`
- `scripts/render/`
  - `answer_renderer.py`
  - `failure_renderer.py`
- `scripts/adapters/`
  - `openclaw_contract.py`

## Functional Coverage

The structured pipeline now covers these business families:

1. `future_flight_competition`
   - route + future range + competitor comparison
   - example: `海口到北京首都未来两天的客座率和票价，和竞争对手比有什么问题`
2. `airline_yoy`
   - airline profit YoY ranking
   - example: `这个月的各航司净利润的同比，谁表现得最差`
3. `adjusted_profit_overview`
   - adjusted profit overview routing and analysis
   - example: `2月份的不含发动机大修和飞机退租的净利润，哪个航司提升最大`
4. `ranked_flights`
   - bottom 10 first-flight extraction
   - top metric flight on ranked report
5. `single_margin`
   - single-aircraft margin extraction and rendering

## Source Strategy

Source acquisition is no longer just passive metadata wrapping. `source_loader.py` now:

- probes local files against report schema and query intent
- decides whether local files are acceptable
- attempts structured refresh for supported report families
- emits `source_meta` with machine-readable refresh and match state

Current structured refresh coverage:

- `未来航班客座率票价分析`
- `单机边际贡献`
- `航空集团前十后十航班`
- `航空集团经营提升分析`
- `航空集团收入利润概览（调整后）`

## Externalized References

These design-time references are now present on disk:

- `references/airport_aliases.yaml`
- `references/intent_examples.json`
- `references/report_schemas.yaml`
- `references/component_url_registry.yaml`
- `tests/e2e_cases.json`

## Test Status

The repo now includes both unit and contract/integration coverage.

- Test files: `20`
- Total passing tests at milestone close: `40`

Executed command:

```powershell
python -m unittest discover -s C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\tests -p "test_*.py" -v
```

Result:

```text
Ran 40 tests
OK
```

## Remaining Technical Debt

The refactor target is complete, but some cleanup remains:

1. `query_opm_nl.py` still exists as legacy-compatible fallback.
2. Some live/component-heavy branches still rely on old helper paths.
3. `openpyxl` resource warnings still appear in certain test runs.
4. More real live-refresh end-to-end cases should be added over time.

## Recommended Next Steps

1. Gradually delete covered legacy branches from `query_opm_nl.py`.
2. Add live-refresh e2e fixtures for the highest-value report families.
3. Fix workbook resource warnings to keep CI output clean.
4. If needed, add a release note or versioned compatibility policy for OpenClaw callers.
