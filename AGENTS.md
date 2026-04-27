# AGENTS.md — OPM NL Report Query

## Test command

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Run a single file: `python -m unittest tests.test_batch -v`

## Config: single source of truth

All config reads from `scripts/config.py`. Never use `os.environ.get()` directly.
`.env` is loaded at import time by `common.py` (stdlib parser, no python-dotenv needed).
Legacy `OPM_*` env fallbacks alias to `FR_*` keys in `config.py:_env()` only.

## Download pipeline

The Python HTTP exporter (`exporter.py`) does **NOT** work with the FineReport CAS platform.
All live exports go through Playwright `.mjs` scripts:

| Script | When |
|--------|------|
| `export_report_generic_live.mjs` | `.cpt` reports (6 fallback mechanisms) |
| `export_report_checkregister_live.mjs` | Reports with date/filter parameters |
| `export_report_component_live.mjs` | `.frm` component reports |

Batch download: `runner.py download --folder NAME --extype simple --resume`

## Storage

- `fr_mirror/` — downloaded reports + manifest.json + search_index (gitignored)
- `fr_batch/extract_edge_auth.js` — only tracked JS file in fr_batch/
- Paths default to project-relative; override via `.env` or env vars

## Environment prerequisites

- Edge/Chromium CDP at `127.0.0.1:9222` with OPM login session
- Node.js + Playwright at `FR_BATCH_ROOT` (for auth extraction and .mjs export scripts)
- `pip install -r requirements.txt` (openpyxl, pyyaml, numpy; python-dotenv optional)

## Known gotchas

- **Windows Store Python**: numpy/openpyxl/pyyaml may have corrupt caches; reinstall with `--ignore-installed --no-deps`
- **python-dotenv is broken in this env**: `common.py` has its own stdlib `.env` loader, do not re-add dotenv imports
- **`requests` package is broken**: download/ uses `urllib` stdlib only
- **`opener.cookies` doesn't exist** on `urllib.request.OpenerDirector`: iterate `handler.cookiejar` through `opener.handlers` instead
- **FTS5 search needs rebuild after index**: call `INSERT INTO cells_fts(cells_fts) VALUES ('rebuild')` after inserts
- **`__recovered` files**: FineReport retry artifacts, gitignored, should be cleaned up

## Module map

| Directory | Role | Self-contained? |
|-----------|------|-----------------|
| `scripts/download/` | auth, discover, batch download | Needs Playwright .mjs + CDP |
| `scripts/search/` | SQLite FTS5 index + search | Pure Python |
| `scripts/intent/` | NL query parsing | Pure Python |
| `scripts/analysis/` | Report-specific KPI analysis | Pure Python |
| `scripts/render/` | Answer rendering | Pure Python |

## Ignored reports

`references/ignored_reports.txt` lists reports excluded from quality checks
(all-zero data or export failures). Check this before flagging missing data.

## Key constraints from SKILL.md

- OpenClaw must call only `scripts/runner.py`, not internal modules directly
- Intent LLM may only fill missing slots; never choose reports or override execution
- Live refresh is optional, not guaranteed
