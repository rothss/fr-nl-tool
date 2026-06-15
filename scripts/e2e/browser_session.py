"""
Browser session management for Playwright-based page-export verification.

Provides browser lifecycle management (launch, navigate, cleanup) and
utilities for interacting with FineReport-like web applications.

Supports three authentication modes:
  1. CDP mode (--cdp-url): Connect to already logged-in browser
  2. storageState mode (--auth-state): Launch with saved auth state
  3. Anonymous mode (default): Launch fresh headless browser

Note: This module requires Playwright to be installed:
    pip install playwright
    python -m playwright install chromium
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .finereport_adapters import try_all_adapters


class BrowserSession:
    """Manages a Playwright browser session for one verification run.

    Supports CDP, storageState, and anonymous browser modes.

    Usage:
        # Anonymous mode (default)
        async with BrowserSession() as session:
            await session.navigate("https://example.com/report")
            page_data = await session.extract_table_data("#report-table")

        # CDP mode (reuse logged-in browser)
        async with BrowserSession(cdp_url="http://127.0.0.1:9222") as session:
            ...

        # storageState mode
        async with BrowserSession(auth_state=Path("/path/to/auth.json")) as session:
            ...
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 60000,
        download_dir: Path | None = None,
        viewport: dict | None = None,
        auth_state: Path | None = None,
        cdp_url: str | None = None,
        artifacts_dir: Path | None = None,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.download_dir = download_dir or Path(tempfile.mkdtemp(prefix="fr_export_"))
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self.auth_state = auth_state
        self.cdp_url = cdp_url
        self.artifacts_dir = artifacts_dir

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._mode = "anonymous"  # one of: cdp, storage_state, anonymous
        self._logs: list[str] = []          # console log entries
        self._errors: list[str] = []        # page errors
        self._request_failures: list[dict] = []  # failed requests
        self._har_recorded: bool = False

    @property
    def page(self):
        """Access the underlying Playwright page object."""
        return self._page

    @property
    def mode(self) -> str:
        """Return the authentication mode: cdp, storage_state, or anonymous."""
        return self._mode

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Launch browser and create a page using the configured mode."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Playwright is required for browser-based verification. "
                "Install with: pip install playwright && python -m playwright install chromium"
            )

        self._playwright = await async_playwright().start()

        # ── Mode 1: CDP ──
        if self.cdp_url:
            self._mode = "cdp"
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            # Try to use an existing context; if none, create one
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = await self._browser.new_context(
                    viewport=self.viewport,
                    accept_downloads=True,
                )
            # Use an existing OPM page if available, or create a new one
            existing_page = None
            if self._context.pages:
                existing_page = self._context.pages[0]
            self._page = existing_page or await self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)
            return

        # ── Mode 2: storageState ──
        if self.auth_state:
            self._mode = "storage_state"
            auth_path = Path(self.auth_state) if isinstance(self.auth_state, str) else self.auth_state
            if not auth_path.exists():
                raise FileNotFoundError(
                    f"auth_state file not found: {auth_path}. "
                    f"Run 'python scripts/runner.py auth-refresh' to generate it."
                )
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
            )
            har_path = None
            if self.artifacts_dir:
                har_path = str(self.artifacts_dir / "network.har")
            self._context = await self._browser.new_context(
                viewport=self.viewport,
                accept_downloads=True,
                storage_state=str(auth_path),
                record_har_path=har_path,
            )
            if har_path:
                self._har_recorded = True
            await self._context.tracing.start(
                screenshots=True,
                snapshots=True,
                sources=True,
            )
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)
            self._setup_listeners()
            return

        # ── Mode 3: Anonymous (default) ──
        self._mode = "anonymous"
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
        )
        har_path = None
        if self.artifacts_dir:
            har_path = str(self.artifacts_dir / "network.har")
        self._context = await self._browser.new_context(
            viewport=self.viewport,
            accept_downloads=True,
            record_har_path=har_path,
        )
        if har_path:
            self._har_recorded = True
        await self._context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._setup_listeners()

    async def stop(self):
        """Close browser and cleanup.
        
        In CDP mode, only close the page (not the browser or context),
        since the browser is shared with the user.
        
        Saves tracing/HAR/console artifacts if artifacts_dir is configured.
        """
        # Save artifacts before closing
        if self.artifacts_dir and self._mode != "cdp":
            try:
                await self._save_artifacts()
            except Exception as e:
                pass  # Best effort

        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
        if self._mode == "cdp":
            # In CDP mode, don't close context or browser (user's browser)
            self._page = None
            self._context = None
            self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            return
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    def _setup_listeners(self):
        """Set up console log, page error, and request failure listeners."""
        if not self._page:
            return
        self._page.on("console", lambda msg: self._logs.append(f"[{msg.type}] {msg.text}"))
        self._page.on("pageerror", lambda err: self._errors.append(str(err)))
        self._page.on("requestfailed", lambda req: self._request_failures.append({
            "url": req.url[:200],
            "error": req.failure.error_text if req.failure else "unknown",
        }))

    async def _save_artifacts(self):
        """Save trace, console logs, request failures to artifacts_dir."""
        if not self.artifacts_dir:
            return
        # Save trace
        if self._context:
            try:
                await self._context.tracing.stop(path=str(self.artifacts_dir / "trace.zip"))
            except Exception:
                pass
        # Save console logs
        if self._logs:
            (self.artifacts_dir / "browser_console.log").write_text(
                "\n".join(self._logs[-500:]), encoding="utf-8"
            )
        # Save request failures
        if self._request_failures:
            import json
            (self.artifacts_dir / "request_failed.json").write_text(
                json.dumps(self._request_failures, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    @property
    def logs(self) -> list[str]:
        """Return collected console logs."""
        return list(self._logs)

    @property
    def errors(self) -> list[str]:
        """Return collected page errors."""
        return list(self._errors)

    @property
    def request_failures(self) -> list[dict]:
        """Return collected request failures."""
        return list(self._request_failures)

    async def navigate(self, url: str, wait_until: str = "networkidle"):
        """Navigate to a URL and wait for page to be ready.

        Args:
            url: The URL to navigate to
            wait_until: Playwright wait_until strategy
        """
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")
        await self._page.goto(url, wait_until=wait_until)
        await self._page.wait_for_timeout(1000)  # Extra wait for dynamic content

    async def fill_text(self, selector: str, text: str):
        """Fill a text input field."""
        if not self._page:
            raise RuntimeError("Browser not started.")
        await self._page.fill(selector, text)

    async def click(self, selector: str):
        """Click an element by selector."""
        if not self._page:
            raise RuntimeError("Browser not started.")
        await self._page.click(selector)

    async def take_screenshot(self, path: Path) -> Path:
        """Take a screenshot of the current page."""
        if not self._page:
            raise RuntimeError("Browser not started.")
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path), full_page=True)
        return path

    async def extract_table_data(
        self,
        table_selector: str = "table",
        strategy: str = "dom",
        data_api_patterns: list[str] | None = None,
    ) -> dict:
        """Extract table data from the current page.

        Args:
            table_selector: CSS selector for the table element
            strategy: "dom" for DOM extraction, "network" for API interception
            data_api_patterns: URL patterns to intercept for network strategy

        Returns:
            Page snapshot dict with columns and rows
        """
        if not self._page:
            raise RuntimeError("Browser not started.")

        if strategy == "network" and data_api_patterns:
            # Try network interception first
            network_data = await self._intercept_network_data(data_api_patterns)
            if network_data:
                return network_data

        # Fall back to DOM extraction
        return await self._extract_table_from_dom(table_selector)

    async def _extract_table_from_dom(self, table_selector: str) -> dict:
        """Extract table data from DOM with enhanced iframe, aria-grid, and scroll support."""
        # Wait for page to be stable
        try:
            await self._page.wait_for_selector(f"{table_selector}, iframe, [role='grid'], [role='table']",
                                                timeout=15000)
        except Exception:
            pass

        # Wait for loading indicators to disappear
        try:
            await self._page.wait_for_selector(".loading, .fr-loading, [class*='loading']",
                                                state="hidden", timeout=8000)
        except Exception:
            pass

        # Wait for table row count to stabilize (re-check twice 1.5s apart)
        last_count = -1
        for _ in range(3):
            count = await self._page.evaluate("""(sel) => {
                const t = document.querySelector(sel) || document.querySelector('table');
                return t ? t.querySelectorAll('tr').length : 0;
            }""", table_selector)
            if count > 0 and count == last_count:
                break
            last_count = count
            await self._page.wait_for_timeout(1500)

        # Extract tables from main document, iframes, and aria grids
        table_data = await self._page.evaluate(f"""
            (selector) => {{
                function extractTable(el) {{
                    const rows = el.querySelectorAll('tr');
                    if (rows.length === 0) return null;
                    const headers = [];
                    const headerRow = el.querySelector('thead tr') || rows[0];
                    if (headerRow) {{
                        headerRow.querySelectorAll('th, td').forEach(c => {{
                            headers.push(c.textContent.trim());
                        }});
                    }}
                    const dataRows = [];
                    const startIdx = el.querySelector('thead') ? 0 : 1;
                    for (let i = startIdx; i < rows.length; i++) {{
                        const cells = rows[i].querySelectorAll('td, th');
                        if (cells.length === 0) continue;
                        const row = {{}};
                        let hasContent = false;
                        cells.forEach((cell, j) => {{
                            const key = headers[j] || 'COL_' + j;
                            row[key] = cell.textContent.trim();
                            if (row[key]) hasContent = true;
                        }});
                        if (hasContent) dataRows.push(row);
                    }}
                    return dataRows.length > 1 ? {{ columns: headers, rows: dataRows }} : null;
                }}

                function extractAriaGrid(el) {{
                    const rows = el.querySelectorAll('[role="row"]');
                    if (rows.length === 0) return null;
                    // Try to get headers from role="columnheader"
                    const headers = [];
                    const firstRow = rows[0];
                    firstRow.querySelectorAll('[role="columnheader"], [role="gridcell"]').forEach(c => {{
                        headers.push(c.textContent.trim() || c.getAttribute('aria-label') || '');
                    }});
                    const dataRows = [];
                    for (let i = 1; i < rows.length; i++) {{
                        const cells = rows[i].querySelectorAll('[role="gridcell"]');
                        if (cells.length === 0) continue;
                        const row = {{}};
                        let hasContent = false;
                        cells.forEach((cell, j) => {{
                            const key = headers[j] || 'COL_' + j;
                            row[key] = cell.textContent.trim();
                            if (row[key]) hasContent = true;
                        }});
                        if (hasContent) dataRows.push(row);
                    }}
                    return dataRows.length > 0 ? {{ columns: headers, rows: dataRows }} : null;
                }}

                // Collect tables from main document
                let tables = [];
                // 1. Try specified selector first
                const primary = document.querySelector(selector);
                if (primary) {{
                    const t = extractTable(primary);
                    if (t) tables.push(t);
                }}

                // 2. All plain tables
                document.querySelectorAll('table').forEach(t => {{
                    const extracted = extractTable(t);
                    if (extracted && extracted.rows.length > 1) tables.push(extracted);
                }});

                // 3. Aria grids
                document.querySelectorAll('[role="grid"], [role="table"]').forEach(el => {{
                    const extracted = extractAriaGrid(el);
                    if (extracted && extracted.rows.length > 1) tables.push(extracted);
                }});

                // 4. iframes
                document.querySelectorAll('iframe').forEach(f => {{
                    try {{
                        const doc = f.contentDocument || f.contentWindow?.document;
                        if (!doc) return;
                        doc.querySelectorAll('table').forEach(t => {{
                            const extracted = extractTable(t);
                            if (extracted && extracted.rows.length > 1) tables.push(extracted);
                        }});
                        doc.querySelectorAll('[role="grid"], [role="table"]').forEach(el => {{
                            const extracted = extractAriaGrid(el);
                            if (extracted && extracted.rows.length > 1) tables.push(extracted);
                        }});
                    }} catch(e) {{}}
                }});

                // Deduplicate and pick the table with most rows
                tables.sort((a, b) => b.rows.length - a.rows.length);
                return tables[0] || {{ columns: [], rows: [] }};
            }}
        """, table_selector)

        result = {
            "source": "dom",
            "columns": table_data.get("columns", []),
            "rows": table_data.get("rows", []),
        }
        if not result["columns"] and result["rows"]:
            result["columns"] = list(result["rows"][0].keys())
        return result

    async def _intercept_network_data(self, patterns: list[str]) -> dict | None:
        """Try to intercept network response data matching patterns.
        
        Uses finereport_adapters to parse various FineReport response formats.
        """
        captured_data: list[tuple[str, Any]] = []

        async def handle_response(response):
            url = response.url
            if any(pattern in url for pattern in patterns):
                try:
                    body = await response.json()
                    if isinstance(body, (dict, list)):
                        captured_data.append((url, body))
                except Exception:
                    pass

        self._page.on("response", handle_response)

        # Reload to capture responses
        await self._page.reload(wait_until="networkidle")
        await self._page.wait_for_timeout(2000)

        if captured_data:
            for url, data in captured_data:
                cols, rows = try_all_adapters(data, url)
                if cols and len(rows) > 0:
                    # Save matched responses info
                    matched = [{"url": url, "body_type": type(data).__name__, "rows": len(rows),
                                "cols": cols[:5]} for url, (_, _) in [(url, data)]]
                    self._captured_network_responses = getattr(self, "_captured_network_responses", []) + matched
                    return {"source": "network", "columns": cols, "rows": rows}
            # No adapter matched; save raw responses for debugging
            self._captured_network_responses = [
                {"url": u, "body_type": type(d).__name__, "keys": list(d.keys()) if isinstance(d, dict) else "list_of_length_" + str(len(d))}
                for u, d in captured_data[:5]
            ]

        return None

    async def click_export_multistep(
        self,
        steps: list[dict],
        download_timeout_ms: int = 60000,
    ) -> Path | None:
        """Execute a multi-step export sequence (e.g., click '导出' → click 'Excel' → wait download).

        Each step dict has:
            {"type": "click", "selector": "text=导出"}
            {"type": "wait_download"}
            {"type": "wait", "ms": 2000}

        Args:
            steps: List of step dicts
            download_timeout_ms: Max wait for the final download

        Returns:
            Path to the downloaded file, or None
        """
        if not self._page:
            raise RuntimeError("Browser not started.")
        if not steps:
            raise ValueError("export.steps must be a non-empty list")

        download_dir = self.download_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        download_promise = None

        for step in steps:
            step_type = step.get("type", "")
            if step_type == "click":
                selector = step.get("selector", "")
                if not selector:
                    continue
                try:
                    await self._page.click(selector, timeout=5000)
                except Exception:
                    # Try locator fallback
                    try:
                        btn = self._page.locator(selector).first
                        if await btn.is_visible(timeout=3000):
                            await btn.click()
                    except Exception:
                        # Only fail if this is the last click step and no download is pending
                        pass
            elif step_type == "wait_download":
                download_promise = self._page.wait_for_event(
                    "download", timeout=download_timeout_ms
                )
            elif step_type == "wait":
                ms = step.get("ms", 1000)
                await self._page.wait_for_timeout(ms)

        if download_promise:
            download = await download_promise
            file_path = download_dir / (download.suggested_filename or "export.xlsx")
            await download.save_as(str(file_path))
            return file_path
        return None

    async def click_export_and_download(
        self,
        button_text: str = "导出",
        button_selector: str | None = None,
        download_timeout_ms: int = 60000,
    ) -> Path | None:
        """Click an export button and wait for the download to complete.

        Args:
            button_text: Text to search for in buttons
            button_selector: Optional explicit CSS selector
            download_timeout_ms: Max wait for download

        Returns:
            Path to the downloaded file, or None if download failed
        """
        if not self._page:
            raise RuntimeError("Browser not started.")

        download_dir = self.download_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        # Set up download handler
        download_promise = self._page.wait_for_event("download", timeout=download_timeout_ms)

        # Try to find and click the export button
        if button_selector:
            await self._page.click(button_selector)
        else:
            # Try multiple common button patterns
            clicked = False
            for pattern in [button_text, button_text.upper(), button_text.lower(),
                          "Excel", "excel", "下载", "download", "Download"]:
                try:
                    btn = self._page.locator(f"button:has-text('{pattern}')").first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    continue

                try:
                    btn = self._page.locator(f"a:has-text('{pattern}')").first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                # Last resort: click any element containing export-like text
                await self._page.click(f"text={button_text}")

        # Wait for download
        download = await download_promise
        file_path = download_dir / (download.suggested_filename or "export.xlsx")
        await download.save_as(str(file_path))

        return file_path

    async def get_console_logs(self) -> list[str]:
        """Collect browser console logs."""
        if not self._page:
            return []
        logs: list[str] = []
        self._page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
        return logs
