---
name: fr-nl-report-query
description: Answer natural-language FineReport KPI questions by parsing intent, ranking matching reports, extracting structured table rows from local mirror Excel files, and optionally falling back to live export. This repository currently ships with an OPM-focused example profile.
---

# FineReport NL Query Skill (OPM Example)

Use this skill to bridge business-language questions and FineReport-based report data retrieval. This repository currently includes an OPM-focused example profile.

## Quick Start

Build report catalog:

```powershell
python scripts/build_report_catalog.py
```

Query by natural language:

```powershell
python scripts/runner.py "我的示例范围内航线的客座率是多少" --user demo_user --output-format json
```

For OpenClaw integration, always call the skill through `scripts\runner.py`, not `query_fr_nl.py` directly.
`runner.py` is the stable skill contract and returns the structured envelope OpenClaw should consume.

## Capability Boundary

1. This repository supports an offline query path when local mirror files and catalog data are already available.
2. Live refresh and component export are optional enhancement paths, not guaranteed defaults.
3. If live refresh is needed, callers must provide compatible FineReport access plus any external helper tools required by their environment.
4. Callers should treat structured failure responses as terminal for the current invocation and should not inspect Excel files directly.

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
$env:FR_INTENT_LLM_COMMAND = "your-local-intent-parser-command"
```

The command must read JSON from stdin and print JSON to stdout.
It is used only to fill missing intent slots and is optional; the skill works without it.

## Live Fallback

If local file is missing, stale, or contains header-only export, call:

```powershell
pwsh -NoProfile -File scripts/export_report_live.ps1 -ReportName "未来航班客座率票价分析"
```

This wrapper is optional. It requires a compatible external refresh tool configured through `FR_REFRESH_TOOL_ROOT` plus a valid FineReport environment.

Generic exporter:

```powershell
node scripts/export_report_generic_live.mjs --report-path "reportlets/demo/xxx.cpt" --output-file "$env:FR_TMP_DIR/live.xlsx" --filters-json "{\"flight_date\":[\"2026-03-29\"],\"company\":\"CompanyA\"}"
```

## References

- `references/synonyms.yaml`: intent synonyms
- `references/column_aliases.yaml`: metric to column mappings
- `references/user_scope.example.yaml`: "我的" scope mapping template
