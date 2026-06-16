"""
Artifact file existence validator for page-export verification.

Usage:
    python scripts/e2e/assert_artifacts.py --artifacts test-results/page_export/mock_subset --expect pass
    python scripts/e2e/assert_artifacts.py --artifacts test-results/page_export/mock_value_diff --expect fail

Exit code 0 = all required files present and valid
Exit code 1 = missing file(s) or invalid JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Files required for PASS cases
REQUIRED_PASS = [
    "page_snapshot.json",
    "export_snapshot.json",
    "compare_result.json",
    "manifest.json",
    "run_context.json",
    "page_before_export.png",
    "export.xlsx",
]

# Files required for FAIL cases
REQUIRED_FAIL = [
    "page_snapshot.json",
    "export_snapshot.json",
    "compare_result.json",
    "manifest.json",
    "run_context.json",
    "diff_report.txt",
    "page_before_export.png",
]

# JSON files to validate (must be parseable)
JSON_TO_VALIDATE = [
    "compare_result.json",
    "manifest.json",
    "run_context.json",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate artifacts completeness")
    parser.add_argument("--artifacts", required=True, help="Path to artifacts directory")
    parser.add_argument("--expect", choices=("pass", "fail", "live-fail-debug"), required=True,
                        help="Expected case outcome (pass/fail/live-fail-debug)")

    args = parser.parse_args()
    artifacts_dir = Path(args.artifacts)

    if not artifacts_dir.is_dir():
        print(f"ERROR: artifacts directory not found: {artifacts_dir}")
        sys.exit(1)

    required = REQUIRED_PASS if args.expect == "pass" else REQUIRED_FAIL
    missing: list[str] = []
    json_errors: list[str] = []

    # live-fail-debug mode: check diagnostic artifacts for iframe debugging
    if args.expect == "live-fail-debug":
        required = [
            "page_snapshot.json",
            "manifest.json",
            "run_context.json",
            "page_before_export.png",
        ]
        # At least one of frame_tree or frame_tree_timeout must exist
        has_frame = (artifacts_dir / "frame_tree.json").exists()
        has_timeout = (artifacts_dir / "frame_tree_timeout.json").exists()
        if not has_frame and not has_timeout:
            missing.append("frame_tree.json OR frame_tree_timeout.json")

    optional = ["trace.zip", "network.har", "browser_console.log", "request_failed.json"]
    if args.expect == "live-fail-debug":
        optional += ["frame_tree.json", "frame_tree_timeout.json", "candidate_network_responses.json"]

    for filename in required:
        fp = artifacts_dir / filename
        if not fp.exists():
            missing.append(filename)
        elif filename in JSON_TO_VALIDATE:
            try:
                json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception) as e:
                json_errors.append(f"{filename}: {e}")

    # Optional traces: log if present/missing but don't fail
    optional_present = [f for f in optional if (artifacts_dir / f).exists()]
    optional_missing = [f for f in optional if not (artifacts_dir / f).exists()]

    ok = True
    if missing:
        print(f"ERROR: Missing required files ({args.expect}):")
        for m in missing:
            print(f"  - {m}")
        ok = False
    if json_errors:
        print("ERROR: Invalid JSON files:")
        for e in json_errors:
            print(f"  - {e}")
        ok = False

    if optional_present:
        print(f"Optional artifacts present: {', '.join(optional_present)}")
    if optional_missing:
        print(f"Optional artifacts not found: {', '.join(optional_missing)}")

    if ok:
        print(f"All {len(required)} required artifacts present and valid ({args.expect})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
