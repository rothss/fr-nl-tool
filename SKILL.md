---
name: opm-nl-report-query
description: Answer natural-language OPM KPI questions by parsing intent, ranking matching reports, extracting structured table rows from local OPM mirror Excel files, and optionally falling back to live export. Use when users ask questions like "我的包干航线的客座率是多少", "HU7778明天的余票", or "未来航班竞航价格差".
---

# OPM NL Report Query

Use this skill to bridge business-language questions and OPM report data retrieval.

## Quick Start

Build report catalog:

```powershell
python C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\scripts\build_report_catalog.py
```

Query by natural language:

```powershell
python C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\scripts\runner.py "我的包干航线的客座率是多少" --user zhuanz --output-format json
```

For OpenClaw integration, always call the skill through `scripts\runner.py`, not `query_opm_nl.py` directly.
`runner.py` is the stable skill contract and returns the structured envelope OpenClaw should consume.

## Workflow

1. Parse natural-language query into intent.
2. Build a schema-aware query plan.
3. Rank report candidates from local catalog.
4. Locate report template path (`.cpt/.frm`) from `manifest.json`.
5. Run generic live export (`export_report_generic_live.mjs`) with widget auto-mapping when required.
6. Extract structured rows from exported/local Excel.
7. Resolve metric column by alias + fuzzy column match.
8. Apply owner/date/entity filters.
9. Return a structured OpenClaw envelope plus final answer text.

## OpenClaw Invocation Rules

1. OpenClaw should treat this skill as a single tool and call only `scripts\runner.py`.
2. OpenClaw should consume the returned JSON envelope instead of inspecting Excel files directly.
3. If the skill returns a structured failure, OpenClaw should not run ad hoc `read_excel(...).head()` or file-dump commands.
4. If a local intent LLM is configured, it may only fill missing slots. It must not choose report files or override execution policy.

## Optional Local Intent LLM

If you want a local small model to help with slot filling, set:

```powershell
$env:OPM_NL_INTENT_LLM_COMMAND = "your-local-intent-parser-command"
```

The command must read JSON from stdin and print JSON to stdout.
It is used only to fill missing intent slots and is optional; the skill works without it.

## Live Fallback

If local file is missing, stale, or contains header-only export, call:

```powershell
pwsh -NoProfile -File C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\scripts\export_report_live.ps1 -ReportName "未来航班客座率票价分析"
```

This wrapper delegates to existing OPM download/export scripts. If login is invalid, open fixed-profile Edge and ask the user to scan QR.

Generic exporter:

```powershell
node C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\scripts\export_report_generic_live.mjs --report-path "doc/Fdjt/xxx.cpt" --output-file "C:/Users/ZhuanZ/opm_mirror/tmp/live.xlsx" --filters-json "{\"flight_date\":[\"2026-03-29\"],\"company\":\"航空股份\"}"
```

## References

- `references/synonyms.yaml`: intent synonyms
- `references/column_aliases.yaml`: metric to column mappings
- `references/user_scope.example.yaml`: "我的" scope mapping template
