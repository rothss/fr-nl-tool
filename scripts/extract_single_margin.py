from __future__ import annotations

from datetime import date
from pathlib import Path
import re

import pandas as pd


def _to_month_day(date_iso: str | None) -> str | None:
    if not date_iso:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(date_iso).strip())
    if not m:
        return None
    mm = int(m.group(2))
    dd = int(m.group(3))
    return f"{mm}月{dd}日"


def _pick_metric_col(df: pd.DataFrame, month_day: str | None) -> int | None:
    if len(df) < 3:
        return None
    h1 = df.iloc[1].fillna("").astype(str)
    h2 = df.iloc[2].fillna("").astype(str)
    candidates: list[int] = []
    for c in range(df.shape[1]):
        if "单机边际贡献" in h1.iloc[c]:
            candidates.append(c)
    if not candidates:
        return None
    if month_day:
        for c in candidates:
            if month_day in h2.iloc[c]:
                return c
    return candidates[0]


def extract_single_margin_rows(path: Path, target_date_iso: str | None = None) -> list[dict]:
    df = pd.read_excel(path, sheet_name=0, header=None)
    if df.empty or df.shape[1] < 3:
        return []

    h1 = df.iloc[1].fillna("").astype(str)
    company_col = None
    type_col = None
    for c in range(df.shape[1]):
        if h1.iloc[c].strip() == "公司":
            company_col = c
        if h1.iloc[c].strip() == "机型":
            type_col = c
    if company_col is None:
        company_col = 1
    if type_col is None:
        type_col = 0

    month_day = _to_month_day(target_date_iso)
    metric_col = _pick_metric_col(df, month_day)
    if metric_col is None:
        return []

    if not month_day:
        v = str(df.iloc[2, metric_col]).strip()
        if re.match(r"^\d{1,2}月\d{1,2}日$", v):
            month_day = v

    current_type = None
    out: list[dict] = []
    for r in range(3, len(df)):
        raw_type = str(df.iat[r, type_col]).strip()
        company = str(df.iat[r, company_col]).strip()
        if raw_type and raw_type != "nan" and raw_type in ("宽体机", "窄体机", "支线机"):
            current_type = raw_type
        if not company or company == "nan" or company == "境内合计":
            continue
        value = df.iat[r, metric_col]
        try:
            fv = float(value)
        except Exception:
            continue
        out.append(
            {
                "日期": target_date_iso or date.today().isoformat(),
                "机型": current_type or "",
                "公司": company,
                "单机边际贡献": fv,
            }
        )
    return out
