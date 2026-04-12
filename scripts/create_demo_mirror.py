from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

from build_report_catalog import build_catalog
from profiles.opm_example import profile_metadata


def _write_future_flight_report(path: Path, today: date) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(
        [
            "航班号",
            "航班日期",
            "航段",
            "时刻",
            "现在客座率",
            "本DCP阶段标准客座率目标",
            "与竞航客座率差",
            "与竞航价格差",
        ]
    )
    rows = [
        [
            "DEMO1001",
            today.isoformat(),
            "海口-北京首都",
            "08:10",
            "72%",
            "85%",
            "-9%",
            "-380",
        ],
        [
            "DEMO1002",
            (today + timedelta(days=1)).isoformat(),
            "海口-北京首都",
            "12:30",
            "88%",
            "82%",
            "3%",
            "-120",
        ],
        [
            "DEMO1003",
            (today + timedelta(days=2)).isoformat(),
            "海口-北京首都",
            "18:45",
            "58%",
            "78%",
            "-12%",
            "-520",
        ],
    ]
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _write_airline_yoy_report(path: Path, today: date) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(["航班日期", "航司", "净利润同比", "排名"])
    snapshot_date = (today - timedelta(days=2)).isoformat()
    rows = [
        [snapshot_date, "航空股份", "12%", 1],
        [snapshot_date, "天津航空", "4%", 5],
        [snapshot_date, "首都航空", "-8%", 11],
    ]
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _write_user_scope(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "default_user: demo_user\nusers:\n  demo_user:\n    包干航线:\n      航段:\n        - 海口-北京首都\n      航班号:\n        - DEMO1001\n",
        encoding="utf-8",
    )


def _write_manifest(path: Path) -> None:
    meta = profile_metadata()
    future_name = meta["report_names"]["future_flight_competition"]
    airline_name = meta["report_names"]["airline_yoy"]
    payload = {
        "entries": [
            {
                "directoryPath": "包干航线",
                "reports": [
                    {
                        "name": future_name,
                        "path": "doc/Fdjt/demo/future_flight_competition.cpt",
                    }
                ],
            },
            {
                "directoryPath": "航空板块经营报表",
                "reports": [
                    {
                        "name": airline_name,
                        "path": "doc/Fdjt/demo/airline_yoy.cpt",
                    }
                ],
            },
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def create_demo_mirror(root: Path, today: date | None = None) -> dict:
    actual_today = today or date.today()
    meta = profile_metadata()
    future_report = (
        root / "包干航线" / f"{meta['report_names']['future_flight_competition']}.xlsx"
    )
    airline_report = (
        root / "航空板块经营报表" / f"{meta['report_names']['airline_yoy']}.xlsx"
    )
    search_index = root / "search_index"
    catalog_db = search_index / "report_catalog.db"
    user_scope = search_index / "user_scope.yaml"
    manifest = root / "manifest.json"

    _write_future_flight_report(future_report, actual_today)
    _write_airline_yoy_report(airline_report, actual_today)
    _write_user_scope(user_scope)
    _write_manifest(manifest)
    stats = build_catalog(root, catalog_db)
    return {
        "ok": True,
        "root": str(root),
        "catalog_db": str(catalog_db),
        "user_scope": str(user_scope),
        "manifest": str(manifest),
        "reports": [str(future_report), str(airline_report)],
        "catalog_stats": stats,
        "demo_queries": list(meta["demo_queries"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a minimal demo FineReport mirror for offline skill evaluation."
    )
    parser.add_argument("--root", default="./examples/demo_mirror")
    args = parser.parse_args()
    result = create_demo_mirror(Path(args.root).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
