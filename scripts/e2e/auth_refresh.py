"""
auth-refresh: Headed browser login to save Playwright storageState.

Opens a headed browser, auto-waits for successful login (detected via a
landing-page selector), then saves the authenticated state to a JSON file.

Usage:
    python scripts/e2e/auth_refresh.py \
        --base-url https://opm.hnair.net/webroot/decision \
        --out .auth/fr-opm.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


async def main() -> None:
    parser = argparse.ArgumentParser(description="Save Playwright storageState after login")
    parser.add_argument("--base-url", default="http://localhost:8075/webroot/decision",
                        help="OPM/FineReport base URL")
    parser.add_argument("--out", default=".auth/fr-opm.json", help="Output path")
    parser.add_argument("--login-selector", default="text=决策平台",
                        help="Selector that confirms successful login (Playwright text= / css / xpath)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Max wait in seconds for manual login (default: 300=5min)")
    parser.add_argument("--viewport-width", type=int, default=1280)
    parser.add_argument("--viewport-height", type=int, default=900)

    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Error: playwright is not installed.", file=sys.stderr)
        print("  pip install playwright && python -m playwright install chromium", file=sys.stderr)
        sys.exit(1)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            viewport={"width": args.viewport_width, "height": args.viewport_height},
        )
        page = await context.new_page()

        print("=" * 60)
        print("OPM Auth Refresh")
        print("=" * 60)
        print(f"Base URL:    {args.base_url}")
        print(f"Output:      {out_path.resolve()}")
        print(f"Timeout:     {args.timeout}s ({args.timeout // 60} min)")
        print(f"Landing sel: {args.login_selector}")
        print()
        print("A browser window has been opened.")
        print("Please complete your login in the browser.")
        print()

        # Navigate
        try:
            await page.goto(args.base_url, wait_until="networkidle", timeout=60000)
        except Exception:
            print("  ⚠ Page load timeout, continuing to wait for login...")
            await page.wait_for_timeout(3000)

        # Wait for login success selector to appear
        print(f"Waiting up to {args.timeout}s for login success selector...")
        t0 = time.monotonic()
        logged_in = False
        while (time.monotonic() - t0) < args.timeout:
            try:
                # Try the configured selector
                el = page.locator(args.login_selector).first
                if await el.is_visible(timeout=2000):
                    logged_in = True
                    break
            except Exception:
                pass
            # Also try URL changes (CAS redirect back to OPM)
            try:
                current_url = page.url
                if "/decision" in current_url and "login" not in current_url.lower():
                    # Already on decision page; check if the selector matches
                    pass
            except Exception:
                pass
            await page.wait_for_timeout(2000)

        if logged_in:
            print("  ✓ Login confirmed (selector matched).")
        else:
            print(f"  ⚠ Timeout reached ({args.timeout}s).")
            # Try one last check
            try:
                if await page.locator("text=决策平台").first.is_visible(timeout=3000):
                    print("  ✓ Fallback selector 'text=决策平台' matched, saving state.")
                    logged_in = True
            except Exception:
                pass

        # Save storage state
        storage = await context.storage_state()
        out_path.write_text(json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"  ✓ storageState saved to: {out_path.resolve()}")
        print(f"    cookies: {len(storage.get('cookies', []))}")
        print(f"    origins: {len(storage.get('origins', []))}")
        print()

        await browser.close()

    if not logged_in:
        print("⚠  Could not confirm login. The saved state may not be valid.")
        print("   Re-run with a longer --timeout and verify manually.")
        sys.exit(1)

    print("Done. You can now use:")
    print(f"  python scripts/runner.py verify-export --case ... --auth-state {args.out}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
