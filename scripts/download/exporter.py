"""
FineReport HTTP 导出模块

⚠ 注意：Python urllib 的 cookie 机制与 FineReport CAS 统一登录平台不兼容。
在 opm.hnair.net 等 CAS 平台上下载管线不可用。该平台的可靠导出需走
Playwright/CDP 浏览器的 .mjs 脚本（export_report_generic_live.mjs 等）。

此模块适用于：
- 无 CAS 认证的 FineReport 实例
- 已通过 FR_AUTH_TOKEN 注入认证的场景
- 开发/测试环境的 mock 数据
"""

from __future__ import annotations

import http.cookiejar
import urllib.request
from pathlib import Path
from typing import Any

from config import base_url

_BASE_URL = base_url()


def _is_xlsx(data: bytes) -> bool:
    return len(data) > 4 and data[0] == 0x50 and data[1] == 0x4B


def _safe_name(name: str) -> str:
    invalid = '<>:"/\\|?*'
    result = str(name or "report").strip()
    for ch in invalid:
        result = result.replace(ch, "_")
    return result[:200]


def make_opener(cookies: dict[str, str], domain: str) -> urllib.request.OpenerDirector:
    cj = http.cookiejar.CookieJar()
    for name, value in cookies.items():
        if not value:
            continue
        ck = http.cookiejar.Cookie(
            version=0, name=name, value=value,
            port=None, port_specified=False,
            domain=domain, domain_specified=True, domain_initial_dot=False,
            path="/", path_specified=True,
            secure=True, expires=None,
            discard=False, comment=None, comment_url=None,
            rest={}, rfc2109=False,
        )
        cj.set_cookie(ck)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def _post(opener: urllib.request.OpenerDirector, url: str, body: str = "",
          referer: str = "", origin: str = "") -> bytes:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "opm-nl-report-query/1.0",
    }
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    data = body.encode("utf-8") if body else b""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with opener.open(req, timeout=120) as resp:
        return resp.read()


def _get(opener: urllib.request.OpenerDirector, url: str, referer: str = "") -> bytes:
    headers = {"User-Agent": "opm-nl-report-query/1.0"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=60) as resp:
        return resp.read()


def _get_session_cookie(opener: urllib.request.OpenerDirector) -> str:
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPCookieProcessor):
            for cookie in handler.cookiejar:
                if cookie.name == "sessionID":
                    return cookie.value or ""
    return ""


def export_report(
    opener: urllib.request.OpenerDirector,
    report_id: str,
    report_name: str,
    output_dir: Path,
    base_url: str = _BASE_URL,
    preferred_extype: str = "simple",
) -> dict[str, Any]:
    """
    导出单个 FineReport 报表为 xlsx。

    extype 顺序说明 (按 FineReport 文档):
      simple  = 原样导出, 不拆分分页 -> Sheet 最少 (默认优先)
      sheet   = 分页分 Sheet 导出 -> 大型报表可能产生几百个 Sheet
      page    = 分页导出但不分 Sheet -> 备用
    如果 simple/sheet/page 都失败，尝试 op=write 回退。
    """
    base = base_url.rstrip("/")
    origin = base.split("://", 1)[1].split("/", 1)[0]
    origin_url = base.split("://", 1)[0] + "://" + origin

    access_url = f"{base}/v10/entry/access/{report_id}"
    _get(opener, access_url, referer=base)

    sid = _get_session_cookie(opener)
    if not sid:
        raise RuntimeError("sessionID missing after access")

    _post(opener, f"{base}/view/report?op=fr_dialog&cmd=parameters_d",
          referer=access_url, origin=origin_url)

    # 优先顺序: 用户指定 > simple(原样) > sheet(分页分Sheet) > page(分页) > op=write
    candidates = [preferred_extype] if preferred_extype else []
    for t in ("simple", "sheet", "page"):
        if t not in candidates:
            candidates.append(t)

    last_bytes = b""
    last_method = ""
    for extype in candidates:
        last_method = f"op=export/extype={extype}"
        body = f"op=export&sessionID={sid}&format=excel&extype={extype}"
        data = _post(opener, f"{base}/view/report", body=body,
                     referer=access_url, origin=origin_url)
        last_bytes = data
        if _is_xlsx(data):
            output_dir.mkdir(parents=True, exist_ok=True)
            file_path = output_dir / f"{_safe_name(report_name)}.xlsx"
            file_path.write_bytes(data)
            return {"ok": True, "path": str(file_path), "bytes": len(data), "extype": extype}

    # op=write 回退 (填报报表专用)
    last_method = "op=write"
    body = f"op=write&sessionID={sid}&format=excel&extype=simple"
    data = _post(opener, f"{base}/view/report", body=body,
                 referer=access_url, origin=origin_url)
    if _is_xlsx(data):
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{_safe_name(report_name)}.xlsx"
        file_path.write_bytes(data)
        return {"ok": True, "path": str(file_path), "bytes": len(data), "extype": "write"}

    return {"ok": False, "error": f"export failed: {last_method} bytes={len(last_bytes)}"}
