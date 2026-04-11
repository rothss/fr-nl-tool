from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from openpyxl import Workbook

from common import default_mirror_root
from excel_index_candidates import default_excel_index_db


def _run(args: list[str], timeout: int = 300) -> tuple[bool, str]:
    try:
        p = subprocess.run(args, check=False, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    out_b = p.stdout or b""
    err_b = p.stderr or b""

    def _dec(raw: bytes) -> str:
        if not raw:
            return ""
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")

    out = _dec(out_b).strip()
    err = _dec(err_b).strip()
    if p.returncode == 0:
        return True, out
    return False, (err or out)


def _safe_name(s: str) -> str:
    x = re.sub(r"[\\/:*?\"<>|]+", "_", s.strip())
    x = re.sub(r"\s+", "_", x)
    return x[:180].strip("_") or "component"


def _build_component_url(item: dict) -> str:
    import os

    raw = str(item.get("raw_url") or "").strip()
    if raw:
        return raw
    viewlet = str(item.get("viewlet") or "").strip()
    op = str(item.get("op") or "form_adaptive").strip() or "form_adaptive"
    from urllib.parse import quote

    base = os.environ.get(
        "FR_BASE_URL",
        os.environ.get("OPM_BASE_URL", "http://localhost:8075/webroot/decision"),
    )
    return (
        f"{base}/view/report?viewlet={quote(viewlet, safe='')}&op={quote(op, safe='')}"
    )


def _pick_components(discovered: dict) -> list[dict]:
    all_items = discovered.get("all") or []
    by_viewlet: dict[str, dict] = {}
    for item in all_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "cpt":
            continue
        viewlet = str(item.get("viewlet") or "").strip()
        if not viewlet:
            continue
        old = by_viewlet.get(viewlet)
        raw = str(item.get("raw_url") or "")
        has_params = "__parameters__=" in raw
        old_params = "__parameters__=" in str((old or {}).get("raw_url") or "")
        if old is None:
            by_viewlet[viewlet] = item
        elif has_params and not old_params:
            by_viewlet[viewlet] = item
    return sorted(by_viewlet.values(), key=lambda x: str(x.get("viewlet") or ""))


def _write_xlsx(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    if not rows:
        ws.append(["no_data"])
        wb.save(path)
        return
    headers: list[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            ks = str(k or "").strip()
            if not ks or ks in seen:
                continue
            seen.add(ks)
            headers.append(ks)
    ws.append(headers)
    for r in rows:
        ws.append([str(r.get(h, "")) for h in headers])
    wb.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover report components, export each to xlsx, and update sqlite index."
    )
    parser.add_argument(
        "--report-path",
        required=True,
        help="FR frm report path, e.g. doc/Fdjt/.../xxx.frm",
    )
    parser.add_argument("--mirror-root", default=str(default_mirror_root()))
    parser.add_argument("--output-dir", help="Where to place component xlsx files")
    parser.add_argument("--excel-db", help="Path to excel_index.db")
    parser.add_argument("--discover-wait-ms", type=int, default=30000)
    parser.add_argument(
        "--limit", type=int, default=0, help="Max components to export, 0 means all"
    )
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()

    mirror_root = Path(args.mirror_root)
    excel_db = (
        Path(args.excel_db)
        if args.excel_db
        else (
            default_excel_index_db(mirror_root)
            or (mirror_root / "search_index" / "excel_index.db")
        )
    )
    report_key = _safe_name(Path(args.report_path).stem)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else (mirror_root / "_components" / report_key)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    discover_js = (
        Path(__file__).resolve().parent / "discover_components_from_network.mjs"
    )
    ok_discover, discover_out = _run(
        [
            "node",
            str(discover_js),
            "--report-path",
            args.report_path,
            "--wait-ms",
            str(args.discover_wait_ms),
        ],
        timeout=max(120, int(args.discover_wait_ms / 1000) + 90),
    )
    if not ok_discover:
        print(
            json.dumps(
                {"ok": False, "stage": "discover", "error": discover_out},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    try:
        discovered = json.loads(discover_out)
    except Exception:
        print(
            json.dumps(
                {"ok": False, "stage": "discover_parse", "error": discover_out[:1000]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    components = _pick_components(discovered)
    if args.limit and args.limit > 0:
        components = components[: args.limit]

    fetch_js = Path(__file__).resolve().parent / "fetch_component_table_live.mjs"
    exported = []
    failed = []
    for idx, comp in enumerate(components, start=1):
        viewlet = str(comp.get("viewlet") or "")
        url = _build_component_url(comp)
        ok_fetch, fetch_out = _run(
            ["node", str(fetch_js), "--component-url", url, "--wait-ms", "5000"],
            timeout=120,
        )
        if not ok_fetch:
            failed.append({"viewlet": viewlet, "reason": fetch_out})
            continue
        try:
            payload = json.loads(fetch_out)
        except Exception:
            failed.append({"viewlet": viewlet, "reason": "fetch_json_parse_failed"})
            continue
        rows = payload.get("rows") or []
        fn = _safe_name(Path(viewlet).stem) + ".xlsx"
        out_xlsx = output_dir / fn
        try:
            _write_xlsx(out_xlsx, rows)
            exported.append(
                {
                    "index": idx,
                    "viewlet": viewlet,
                    "row_count": len(rows),
                    "file": str(out_xlsx),
                }
            )
        except Exception as exc:
            failed.append({"viewlet": viewlet, "reason": f"write_xlsx_failed: {exc}"})

    index_result = None
    if not args.skip_index:
        import os

        build_index_env = os.environ.get("FR_BUILD_INDEX_PY", "")
        if build_index_env:
            build_index_py = Path(build_index_env)
            if not build_index_py.is_absolute():
                build_index_py = Path(__file__).parent.parent / build_index_env
        else:
            build_index_py = Path(__file__).parent.parent / "scripts" / "build_index.py"
        ok_idx, idx_out = _run(
            [
                "python",
                str(build_index_py),
                "--root",
                str(mirror_root),
                "--db",
                str(excel_db),
                "--incremental",
            ],
            timeout=3600,
        )
        index_result = {"ok": ok_idx, "output": idx_out[-4000:]}

    print(
        json.dumps(
            {
                "ok": True,
                "report_path": args.report_path,
                "component_total": len(components),
                "exported_count": len(exported),
                "failed_count": len(failed),
                "output_dir": str(output_dir),
                "excel_db": str(excel_db),
                "exported": exported,
                "failed": failed,
                "index_result": index_result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
