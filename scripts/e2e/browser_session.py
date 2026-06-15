"""
Browser session management for Playwright-based page-export verification.

Provides browser lifecycle management (launch, navigate, cleanup) and
utilities for interacting with FineReport-like web applications.

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


class BrowserSession:
    """Manages a Playwright browser session for one verification run.

    Usage:
        async with BrowserSession() as session:
            await session.navigate("https://example.com/report")
            page_data = await session.extract_table_data("#report-table")
            export_path = await session.click_export_and_download(
                button_text="导出",
                download_dir="/tmp"
            )
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 60000,
        download_dir: Path | None = None,
        viewport: dict | None = None,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.download_dir = download_dir or Path(tempfile.mkdtemp(prefix="fr_export_"))
        self.viewport = viewport or {"width": 1920, "height": 1080}

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    @property
    def page(self):
        """Access the underlying Playwright page object."""
        return self._page

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Launch browser and create a page."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Playwright is required for browser-based verification. "
                "Install with: pip install playwright && python -m playwright install chromium"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
        )
        self._context = await self._browser.new_context(
            viewport=self.viewport,
            accept_downloads=True,
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    async def stop(self):
        """Close browser and cleanup."""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
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
        """Extract table data from DOM."""
        # Wait for table to be visible
        try:
            await self._page.wait_for_selector(table_selector, timeout=15000)
        except Exception:
            pass

        table_data = await self._page.evaluate("""
            (selector) => {
                const table = document.querySelector(selector);
                if (!table) return { columns: [], rows: [] };

                // Extract headers
                const headers = [];
                const thead = table.querySelector('thead');
                const headerRow = thead ? thead.querySelector('tr') : table.querySelector('tr');
                if (headerRow) {
                    headerRow.querySelectorAll('th, td').forEach(cell => {
                        headers.push(cell.textContent.trim());
                    });
                }

                // Extract body rows
                const rows = [];
                const tbody = table.querySelector('tbody') || table;
                const dataRows = tbody.querySelectorAll('tr');
                // Skip header row if it was in tbody
                const startIdx = headerRow && !thead ? 1 : 0;
                for (let i = startIdx; i < dataRows.length; i++) {
                    const cells = dataRows[i].querySelectorAll('td, th');
                    if (cells.length === 0) continue;
                    const row = {};
                    cells.forEach((cell, j) => {
                        const key = headers[j] || `COL_${j}`;
                        row[key] = cell.textContent.trim();
                    });
                    // Only include rows with content
                    if (Object.values(row).some(v => v)) {
                        rows.push(row);
                    }
                }

                return { columns: headers, rows };
            }
        """, table_selector)

        return {
            "source": "dom",
            "columns": table_data.get("columns", []),
            "rows": table_data.get("rows", []),
        }

    async def _intercept_network_data(self, patterns: list[str]) -> dict | None:
        """Try to intercept network response data matching patterns."""
        captured_data: list[dict] = []

        async def handle_response(response):
            url = response.url
            if any(pattern in url for pattern in patterns):
                try:
                    body = await response.json()
                    if isinstance(body, (dict, list)):
                        captured_data.append({"url": url, "data": body})
                except Exception:
                    pass

        self._page.on("response", handle_response)

        # Reload to capture responses
        await self._page.reload(wait_until="networkidle")
        await self._page.wait_for_timeout(2000)

        if captured_data:
            # Return the first captured response data
            data = captured_data[0]["data"]
            if isinstance(data, list):
                if data and isinstance(data[0], dict):
                    columns = list(data[0].keys())
                    return {"source": "network", "columns": columns, "rows": data}
            elif isinstance(data, dict):
                rows = data.get("rows") or data.get("data") or []
                if rows and isinstance(rows[0], dict):
                    columns = list(rows[0].keys())
                    return {"source": "network", "columns": columns, "rows": rows}

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
