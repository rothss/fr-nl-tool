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
python C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\scripts\query_opm_nl.py "我的包干航线的客座率是多少" --user zhuanz
```

## Workflow

1. Parse natural-language query into intent.
2. Rank report candidates from local catalog.
3. Locate report template path (`.cpt/.frm`) from `manifest.json`.
4. Run generic live export (`export_report_generic_live.mjs`) with widget auto-mapping.
5. Extract structured rows from exported/local Excel.
6. Resolve metric column by alias + fuzzy column match.
7. Apply owner/date/entity filters.
8. Return scalar or table answer with data source path and refresh status.

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
