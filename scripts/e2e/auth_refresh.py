"""
auth-refresh: Headed browser login to save Playwright storageState.

Opens a headed browser, waits for the user to manually log in,
then saves the authenticated state to a JSON file for use with
verify-export --auth-state.

Usage:
    python -m e2e.auth_refresh \\
        --base-url https://opm.hnair.net/webroot/decision \\
        --out .auth/fr-opm.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


async def main() -> None:
    parser = argparse.ArgumentParser(description="Save Playwright storageState after manual login")
    parser.add_argument("--base-url", default="http://localhost:8075/webroot/decision",
                        help="OPM/FineReport base URL")
    parser.add_argument("--out", default=".auth/fr-opm.json", help="Output path")
    parser.add_argument("--login-selector", default="text=决策平台",
                        help="Selector that confirms successful login")
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
        print(f"Base URL: {args.base_url}")
        print(f"Output:   {out_path.resolve()}")
        print()
        print("A browser window has been opened.")
        print("Please complete the following steps in the browser:")
        print("  1. Wait for the login page to load.")
        print("  2. Enter your credentials (if CAS/SSO auto-redirects, just wait).")
        print("  3. After successful login, press Enter in this terminal.")
        print("  4. The session state will be saved.")
        print()

        await page.goto(args.base_url, wait_until="networkidle", timeout=60000)

        input("Press Enter after you have successfully logged in...")

        # Verify login by checking for the success selector
        try:
            await page.wait_for_selector(args.login_selector, timeout=10000)
            print("  ✓ Login confirmed.")
        except Exception:
            print("  ⚠ Could not confirm login with selector, saving state anyway.")
            print(f"    (looked for: {args.login_selector})")

        # Save storage state
        storage = await context.storage_state()
        out_path.write_text(json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"  ✓ storageState saved to: {out_path.resolve()}")
        print(f"    cookies: {len(storage.get('cookies', []))}")
        print(f"    origins: {len(storage.get('origins', []))}")
        print()

        await browser.close()

    print("Done. You can now use:")
    print(f"  python scripts/runner.py verify-export --case ... --auth-state {args.out}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
