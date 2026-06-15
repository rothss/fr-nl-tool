"""
Mock FineReport server for page-export consistency testing.

Provides mock HTTP endpoints that simulate FineReport behavior:
  - Serve mock page HTML showing table data
  - Serve mock Excel exports
  - Support different test scenarios via URL parameters
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

# ---- Fixture generation helpers ----

def _make_fixture_xlsx(
    filename: str,
    rows_data: list[dict],
    sheet_name: str = "Sheet1",
) -> Path:
    """Create an xlsx fixture file."""
    path = FIXTURES_DIR / filename
    df = pd.DataFrame(rows_data)
    df.to_excel(path, sheet_name=sheet_name, index=False)
    return path


def _make_fixture_html(
    filename: str,
    rows_data: list[dict],
    title: str = "Mock Report",
) -> Path:
    """Create an HTML fixture file with a table."""
    path = FIXTURES_DIR / filename
    if not rows_data:
        html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1><table></table></body></html>"
    else:
        columns = list(rows_data[0].keys())
        thead = "<tr>" + "".join(f"<th>{c}</th>" for c in columns) + "</tr>"
        tbody_rows = []
        for row in rows_data:
            cells = "".join(f"<td>{row.get(c, '')}</td>" for c in columns)
            tbody_rows.append(f"<tr>{cells}</tr>")
        tbody = "\n".join(tbody_rows)
        html = f"""<html>
<head><title>{title}</title></head>
<body>
<h1>{title}</h1>
<div class="report-container">
<table id="report-table">
<thead>{thead}</thead>
<tbody>
{tbody}
</tbody>
</table>
</div>
<div id="pagination">Page 1 of 1</div>
</body>
</html>"""
    path.write_text(html, encoding="utf-8")
    return path


# ---- Test data generators ----

def _generate_rows(n: int, prefix: str = "行") -> list[dict]:
    """Generate n rows of test data."""
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "航司": f"航司_{(i % 5) + 1}",
            "月份": f"2026-{(i % 12) + 1:02d}",
            "净利润": round(100 + i * 10.5 + (i % 3) * 5.3, 2),
            "同比": round(0.05 + i * 0.01, 3),
        })
    return rows


def ensure_fixtures() -> dict[str, Any]:
    """Ensure all fixture files exist. Returns fixture manifest."""
    fixtures: dict[str, Any] = {}

    # ---- Fixture A: page 20 rows, export 3000 rows, first 20 match ----
    rows_3000 = _generate_rows(3000)
    page_20 = rows_3000[:20]
    _make_fixture_xlsx("page_20_export_3000_pass.xlsx", rows_3000)
    _make_fixture_html("page_20_export_3000_pass.html", page_20, "Mock Sales Report")
    fixtures["page_20_export_3000_pass"] = {
        "html": "page_20_export_3000_pass.html",
        "xlsx": "page_20_export_3000_pass.xlsx",
        "case_file": "mock_sales_prefix_ordered.json",
    }

    # ---- Fixture B: page 20 rows, export 3000 rows, value mismatch ----
    rows_3000_b = _generate_rows(3000)
    # Modify row 7 value
    rows_3000_b[6]["净利润"] = 999.99  # different from what page would show
    _make_fixture_xlsx("page_20_export_3000_mismatch.xlsx", rows_3000_b)
    fixtures["page_20_export_3000_mismatch"] = {
        "html": "page_20_export_3000_pass.html",  # same page data
        "xlsx": "page_20_export_3000_mismatch.xlsx",
        "case_file": "mock_sales_prefix_mismatch.json",
    }

    # ---- Fixture C: page 20 rows, export missing one page row ----
    rows_2999 = _generate_rows(2999)
    # Page has 20 rows but export is missing the 15th row
    rows_2999_missing = rows_2999[:14] + rows_2999[15:]
    _make_fixture_xlsx("page_20_export_missing_row.xlsx", rows_2999_missing)
    fixtures["page_20_export_missing_row"] = {
        "html": "page_20_export_3000_pass.html",  # same page data
        "xlsx": "page_20_export_missing_row.xlsx",
        "case_file": "mock_sales_subset_missing.json",
    }

    # ---- Fixture D: subset by key, page 20 rows in export 3000 (any order) ----
    shuffled_3000 = rows_3000[:]
    # Shuffle some rows to test order independence
    shuffled_3000[5], shuffled_3000[10] = shuffled_3000[10], shuffled_3000[5]
    shuffled_3000[0], shuffled_3000[100] = shuffled_3000[100], shuffled_3000[0]
    _make_fixture_xlsx("page_20_export_3000_shuffled.xlsx", shuffled_3000)
    fixtures["page_20_export_3000_shuffled"] = {
        "html": "page_20_export_3000_pass.html",
        "xlsx": "page_20_export_3000_shuffled.xlsx",
        "case_file": "mock_sales_visible_subset.json",
    }

    # ---- Fixture E: percentage format differences ----
    pct_page = [
        {"航司": "东航", "月份": "2026-05", "净利润": 100, "同比": "12.3%"},
        {"航司": "南航", "月份": "2026-05", "净利润": 88, "同比": "5.1%"},
    ]
    pct_export = [
        {"航司": "东航", "月份": "2026-05", "净利润": 100, "同比": 0.123},
        {"航司": "南航", "月份": "2026-05", "净利润": 88, "同比": 0.051},
    ]
    _make_fixture_xlsx("percent_format_export.xlsx", pct_export)
    _make_fixture_html("percent_format_page.html", pct_page, "Percent Format Report")
    fixtures["percent_format"] = {
        "html": "percent_format_page.html",
        "xlsx": "percent_format_export.xlsx",
        "case_file": "mock_sales_percent_format.json",
    }

    # ---- Fixture F: number thousands format ----
    num_page = [
        {"航司": "东航", "月份": "2026-05", "净利润": "1,234.50", "同比": "12.3%"},
    ]
    num_export = [
        {"航司": "东航", "月份": "2026-05", "净利润": 1234.5, "同比": 0.123},
    ]
    _make_fixture_xlsx("number_format_export.xlsx", num_export)
    _make_fixture_html("number_format_page.html", num_page, "Number Format Report")
    fixtures["number_format"] = {
        "html": "number_format_page.html",
        "xlsx": "number_format_export.xlsx",
        "case_file": "mock_sales_number_format.json",
    }

    # ---- Fixture G: current page export (exact 20 rows) ----
    exact_20 = _generate_rows(20)
    _make_fixture_xlsx("current_page_export_20.xlsx", exact_20)
    _make_fixture_html("current_page_page_20.html", exact_20, "Current Page Report")
    fixtures["current_page_20"] = {
        "html": "current_page_page_20.html",
        "xlsx": "current_page_export_20.xlsx",
        "case_file": "mock_sales_current_page_equal.json",
    }

    return fixtures


# ---- Mock HTTP Server ----

class MockFRHandler(SimpleHTTPRequestHandler):
    """Handler that serves mock page HTML and Excel exports."""

    fixtures: dict[str, Any] = {}
    page_data: dict[str, list[dict]] = {}

    def log_message(self, format, *args):
        """Suppress default logging for cleaner test output."""
        if "--verbose" in sys.argv:
            super().log_message(format, *args)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # Serve Excel export
        if path.endswith(".xlsx"):
            filename = path.lstrip("/")
            file_path = FIXTURES_DIR / filename
            if file_path.exists():
                self._serve_file(file_path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                return
            self.send_error(404, "Fixture not found")
            return

        # Serve download endpoint
        if "/download" in path or "/export" in path:
            scenario = qs.get("scenario", ["page_20_export_3000_pass"])[0]
            fixture_info = self.fixtures.get(scenario, {})
            xlsx_name = fixture_info.get("xlsx", "page_20_export_3000_pass.xlsx")
            file_path = FIXTURES_DIR / xlsx_name
            if file_path.exists():
                self._serve_file(file_path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 attachment=file_path.name)
                return
            self.send_error(404, "Export not found")
            return

        # Serve page HTML
        scenario = qs.get("scenario", ["page_20_export_3000_pass"])[0]
        fixture_info = self.fixtures.get(scenario, {})
        html_name = fixture_info.get("html", "page_20_export_3000_pass.html")
        file_path = FIXTURES_DIR / html_name
        if file_path.exists():
            self._serve_file(file_path, "text/html; charset=utf-8")
            return

        # Serve data API endpoint (JSON)
        if "/api/data" in path:
            scenario = qs.get("scenario", ["page_20_export_3000_pass"])[0]
            rows = self.page_data.get(scenario, _generate_rows(20)[:20])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"rows": rows, "total": 3000}, ensure_ascii=False).encode("utf-8"))
            return

        # Default: serve index
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        fixtures_list = "\n".join(f"<li>{k}</li>" for k in sorted(self.fixtures.keys()))
        self.wfile.write(f"""<html>
<head><title>Mock FR Server</title></head>
<body>
<h1>Mock FineReport Server</h1>
<p>Available scenarios:</p>
<ul>{fixtures_list}</ul>
</body>
</html>""".encode("utf-8"))

    def _serve_file(self, file_path: Path, content_type: str, attachment: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())


def run_server(port: int = 18080) -> None:
    """Run the mock FineReport server."""
    print(f"Ensuring fixtures...")
    fixtures = ensure_fixtures()
    print(f"Fixtures ready: {len(fixtures)} scenarios")

    # Generate page data for each fixture
    page_data: dict[str, list[dict]] = {}
    for name in fixtures:
        rows = _generate_rows(3000)
        page_data[name] = rows[:20]

    MockFRHandler.fixtures = fixtures
    MockFRHandler.page_data = page_data

    server = HTTPServer(("127.0.0.1", port), MockFRHandler)
    print(f"Mock FR server running at http://127.0.0.1:{port}")
    print(f"Fixtures directory: {FIXTURES_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock FineReport server for testing")
    parser.add_argument("--port", type=int, default=18080, help="Port to listen on")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        sys.argv.append("--verbose")

    run_server(port=args.port)
