"""
Main page-export consistency verification pipeline.

Orchestrates the full verification flow:
  1. Load test case configuration
  2. Open browser and navigate to report page
  3. Apply filter parameters
  4. Extract page visible data (page_snapshot)
  5. Click export and download Excel
  6. Parse Excel (export_snapshot)
  7. Normalize both snapshots
  8. Compare and produce result
  9. Save artifacts

Usage:
    python scripts/e2e/verify_export.py --case tests/live_cases/mock_sales_visible_subset.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import ArtifactManager
from .browser_session import BrowserSession
from .case_loader import load_case
from .compare_table import run_comparison, format_compare_result
from .diff_report import generate_diff_report
from .export_extract import extract_export_snapshot, save_export_snapshot
from .page_extract import extract_page_snapshot_async, save_page_snapshot


async def verify_export(
    case_path: Path,
    artifacts_dir: Path | None = None,
    headless: bool = True,
    timeout_ms: int = 60000,
    download_dir: Path | None = None,
) -> dict[str, Any]:
    """Run page-export consistency verification.

    Args:
        case_path: Path to test case JSON file
        artifacts_dir: Directory for output artifacts (auto-generated if None)
        headless: Run browser in headless mode
        timeout_ms: Overall timeout in milliseconds
        download_dir: Directory for downloaded exports

    Returns:
        Verification result dict
    """
    # 1. Load case
    case = load_case(case_path)
    case_name = case.get("name", case_path.stem)
    report_name = case.get("report", {}).get("name", "")
    params = case.get("params", {})
    start_time = datetime.now(timezone.utc)

    # 2. Setup artifacts
    if artifacts_dir is None:
        artifacts_dir = Path("test-results") / "page_export" / case_name
    artifacts = ArtifactManager(artifacts_dir)
    artifacts.ensure_dirs()

    errors: list[str] = []

    try:
        # 3. Open browser and navigate
        navigate_cfg = case.get("navigation", {})
        page_extract_cfg = case.get("page_extract", {})

        async with BrowserSession(
            headless=headless,
            timeout_ms=timeout_ms,
            download_dir=download_dir,
        ) as session:
            # Navigate to report
            report_url = navigate_cfg.get("report_url", "")
            if not report_url:
                base_url = navigate_cfg.get("base_url", "http://127.0.0.1:18080")
                report_folder = case.get("report", {}).get("folder", "")
                report_name_nav = case.get("report", {}).get("name", "")
                report_url = f"{base_url}/?folder={report_folder}&report={report_name_nav}"

            await session.navigate(report_url)

            # Apply filter parameters if any
            filter_selectors = navigate_cfg.get("filter_selectors", {})
            for param_name, selector in filter_selectors.items():
                if param_name in params:
                    await session.fill_text(selector, str(params[param_name]))

            await session.page.wait_for_timeout(2000)

            # Take screenshot before export
            try:
                await session.take_screenshot(artifacts.path("page_before_export.png"))
            except Exception as e:
                errors.append(f"screenshot_failed: {e}")

            # 4. Extract page data
            page_snapshot = await extract_page_snapshot_async(session, case)
            save_page_snapshot(page_snapshot, artifacts.path("page_snapshot.json"))

            # Validate page data
            expected_cfg = case.get("expected", {})
            min_page_rows = expected_cfg.get("min_page_rows", 0)
            must_contain_cols = expected_cfg.get("must_contain_columns", [])

            if len(page_snapshot.get("rows", [])) < min_page_rows:
                errors.append(
                    f"page has {len(page_snapshot.get('rows', []))} rows, "
                    f"expected at least {min_page_rows}"
                )
            for col in must_contain_cols:
                if col not in page_snapshot.get("columns", []):
                    errors.append(f"page missing required column: {col}")

            # 5. Click export and download
            export_cfg = case.get("export", {})
            export_url = export_cfg.get("url", "")

            if export_url:
                # Direct download from mock server
                import urllib.request
                export_path = artifacts.path("export.xlsx")
                urllib.request.urlretrieve(export_url, str(export_path))
            else:
                # Use browser interaction
                export_path = await session.click_export_and_download(
                    button_text=export_cfg.get("button_text", "导出"),
                    download_timeout_ms=export_cfg.get("timeout_ms", 60000),
                )
                if export_path:
                    # Move to artifacts
                    target = artifacts.path("export.xlsx")
                    target.write_bytes(export_path.read_bytes())
                    export_path = target

            if not export_path or not export_path.exists():
                errors.append("export_download_failed")

    except Exception as e:
        errors.append(f"browser_error: {e}")
        page_snapshot = {"source": "page", "columns": [], "rows": [], "error": str(e)}

    # 6. Parse Excel export
    export_path = artifacts.path("export.xlsx")
    export_snapshot = {"source": "export", "columns": [], "rows": [], "error": "export_not_downloaded"}

    if export_path.exists():
        try:
            compare_cfg = case.get("compare", {})
            export_snapshot = extract_export_snapshot(export_path, compare_config=compare_cfg)
            save_export_snapshot(export_snapshot, artifacts.path("export_snapshot.json"))
        except Exception as e:
            errors.append(f"export_parse_failed: {e}")

    # Validate export
    expected_cfg = case.get("expected", {})
    min_export_rows = expected_cfg.get("min_export_rows", 0)
    if export_snapshot.get("row_count", 0) < min_export_rows:
        errors.append(
            f"export has {export_snapshot.get('row_count', 0)} rows, "
            f"expected at least {min_export_rows}"
        )

    # 7. Run comparison
    compare_cfg = case.get("compare", {})
    compare_result = {}

    if not errors:
        page_rows = page_snapshot.get("rows", [])
        export_rows = export_snapshot.get("rows", [])
        compare_result = run_comparison(page_rows, export_rows, compare_cfg)
    else:
        compare_result = {
            "ok": False,
            "mode": compare_cfg.get("mode", "unknown"),
            "error": "; ".join(errors),
            "page_rows": len(page_snapshot.get("rows", [])),
            "export_rows": export_snapshot.get("row_count", 0),
        }

    # 8. Save artifacts and results
    artifacts.save_json("compare_result.json", compare_result)
    artifacts.save_json("page_snapshot.json", page_snapshot)
    artifacts.save_json("export_snapshot.json", export_snapshot)

    # Generate diff report on failure
    if not compare_result.get("ok"):
        diff_text = generate_diff_report(compare_result, case_name, report_name, params)
        artifacts.save_text("diff_report.txt", diff_text)

    # Save manifest
    finished_at = datetime.now(timezone.utc)
    manifest = {
        "case_name": case_name,
        "report_name": report_name,
        "params": params,
        "page_url": navigate_cfg.get("report_url", ""),
        "page_data_hash": page_snapshot.get("raw_hash", ""),
        "export_file_hash": export_snapshot.get("file_hash", ""),
        "started_at": start_time.isoformat(),
        "finished_at": finished_at.isoformat(),
        "status": "PASS" if compare_result.get("ok") else "FAIL",
        "errors": errors,
    }
    artifacts.save_json("manifest.json", manifest)

    # 9. Format result
    result = {
        "ok": compare_result.get("ok", False),
        "case_name": case_name,
        "report_name": report_name,
        "params": params,
        "compare_result": compare_result,
        "errors": errors,
        "artifacts_dir": str(artifacts.base_dir),
        "manifest": manifest,
        "text_report": format_compare_result(
            compare_result,
            case_name=case_name,
            report_name=report_name,
            params=params,
        ),
    }

    return result


def run_verify_export_sync(
    case_path: Path,
    artifacts_dir: Path | None = None,
    headless: bool = True,
    timeout_ms: int = 60000,
    download_dir: Path | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for verify_export."""
    return asyncio.run(verify_export(
        case_path=case_path,
        artifacts_dir=artifacts_dir,
        headless=headless,
        timeout_ms=timeout_ms,
        download_dir=download_dir,
    ))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify page-displayed data consistency with exported Excel"
    )
    parser.add_argument("--case", required=True, help="Path to test case JSON file")
    parser.add_argument("--artifacts", default=None, help="Directory for artifacts")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--timeout", type=int, default=60000, help="Timeout in ms")
    parser.add_argument("--download-dir", default=None, help="Download directory")
    parser.add_argument("--output-format", choices=("json", "text"), default="json")
    args = parser.parse_args()

    case_path = Path(args.case)
    if not case_path.exists():
        print(f"Error: case file not found: {args.case}", file=sys.stderr)
        sys.exit(1)

    artifacts_dir = Path(args.artifacts) if args.artifacts else None

    result = run_verify_export_sync(
        case_path=case_path,
        artifacts_dir=artifacts_dir,
        headless=not args.no_headless,
        timeout_ms=args.timeout,
        download_dir=Path(args.download_dir) if args.download_dir else None,
    )

    if args.output_format == "text":
        print(result.get("text_report", json.dumps(result, ensure_ascii=False, indent=2)))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
