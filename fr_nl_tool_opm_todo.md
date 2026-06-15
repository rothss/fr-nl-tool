# fr-nl-tool `opm` 分支完善 TODO 文档

## 0. 文档目的

本文档用于指导其它 AI / 开发者继续完善 `fr-nl-tool` 项目的 `opm` 分支，重点补齐以下问题：

1. 页面展示数据与 Excel 导出数据一致性验证尚未完整闭环。
2. 页面显示 20 行、Excel 导出 3000 行时，应支持“页面可见数据是导出数据子集”的判定。
3. `opm` 分支已经实现部分比较逻辑，但真实 OPM / FineReport 环境下的登录态、live case、同一次导出文件进入索引、trace/HAR 留痕等仍需完善。
4. 最终目标是证明：

```text
同一次页面状态 → 同一个导出 Excel → 同一个索引 → 同一个自然语言查询结果
```

---

## 1. 当前状态判断

`opm` 分支已经完成了部分基础能力：

```text
[已完成] visible_prefix_ordered 比对模式
[已完成] visible_subset_by_key 比对模式
[已完成] current_page_equal 比对模式
[已完成] 基础 normalize_table
[已完成] 基础 export_extract
[已完成] 基础 page_extract
[已完成] 基础 verify-export 命令
[已完成] 部分 mock case
[已完成] 部分 unit test
```

但还存在以下关键缺口：

```text
[未完成] verify-export --auth-state 参数未打通
[未完成] BrowserSession 未真正支持 storageState / CDP 登录态复用
[未完成] workflow 引用的真实 live case 可能缺失
[未完成] verify 过的 Excel 不一定是后续 index/query 使用的 Excel
[未完成] 同一次页面状态与导出请求 payload 绑定不足
[未完成] FineReport 复杂 network / iframe / DOM 抽取适配不足
[未完成] trace / HAR / console log 留痕不足
[未完成] mock E2E 失败场景覆盖不足
[未完成] CI 门禁策略仍需完善
```

---

# P0：阻断问题修复

## TODO 0.1：验证新增 Python 文件格式

### 状态

✅ **已通过验证**。全部 7 个核心文件 `py_compile` 通过，无语法错误（2026-06-15 实测确认）：

```bash
python -m py_compile scripts/runner.py               # OK
python -m py_compile scripts/e2e/normalize_table.py   # OK
python -m py_compile scripts/e2e/compare_table.py     # OK
python -m py_compile scripts/e2e/export_extract.py    # OK
python -m py_compile scripts/e2e/page_extract.py      # OK
python -m py_compile scripts/e2e/verify_export.py     # OK
python -m py_compile scripts/e2e/browser_session.py   # OK
```

⚠️ **GitHub raw 视图的误判说明**：文件格式完全正常，raw 视图可能因换行符显示问题看起来像单行，实际不是。

### 仍需执行

```bash
python -m unittest discover -s tests -p "test_*.py" -v
black --check scripts tests
```

---

## TODO 0.2：将已有 `--auth-state` 参数传递到 BrowserSession（打通调用链）

### 问题

`runner.py` 已经解析了 `--auth-state`（第622行）：
```python
p_e2e.add_argument("--auth-state", default=None, help="Path to auth state file")
```

但该参数 **没有被传递到 BrowserSession**。BrowserSession.__init__ 不接受 `auth_state`/`cdp_url`，`start()` 只用 `chromium.launch()`（匿名模式），导致真实 OPM 页面无法访问。需要在 CLI → verify_export → BrowserSession 之间打通调用链。

### 涉及文件

```text
scripts/runner.py           ← --auth-state 已存在，需传递到 run_e2e_live()/run_verify_export_sync()
scripts/e2e/verify_export.py ← verify_export() 函数需接收 auth_state + cdp_url
scripts/e2e/browser_session.py ← 核心修改：支持三种模式
.github/workflows/test.yml
```

### 执行项

1. 在 `BrowserSession.__init__` 中新增 `auth_state` 和 `cdp_url` 参数
2. 在 `BrowserSession.start()` 中实现三种模式：
   - `cdp_url` → `connect_over_cdp(cdp_url)` + `contexts[0]`
   - `auth_state` → `chromium.launch()` + `new_context(storage_state=auth_state)`
   - 都没有 → 保持匿名 `chromium.launch()` 不变
3. 修改 `run_verify_export_sync()` 接收 `auth_state` 和 `cdp_url` 并传递到 `verify_export()`
4. 修改 `run_e2e_live()` 同样传递
5. `.gitignore` 新增 `.auth/` `test-results/` `.tmp/`


### 验收标准

执行：

```bash
python scripts/runner.py verify-export \
  --case tests/live_cases/mock_sales_prefix_ordered.json \
  --auth-state .auth/nonexistent.json \
  --artifacts test-results/page_export/mock \
  --output-format text
```

预期：

```text
[ ] 不再出现 argparse unknown argument
[ ] 如果 auth-state 文件不存在，应给出明确错误信息
[ ] mock case 不传 auth-state 仍可正常执行
```

---

## TODO 0.3：让 `BrowserSession` 真正支持登录态复用

### 问题

真实 OPM / FineReport 通常依赖 CAS、SSO、MFA 或已有登录态。如果 `BrowserSession` 只启动匿名浏览器，则无法稳定进入报表页面。

### 涉及文件

```text
scripts/e2e/browser_session.py
scripts/e2e/auth_refresh.py
scripts/runner.py
.gitignore
docs/E2E_LIVE.md
```

### 执行项

新增三种浏览器会话模式：

```text
1. storageState 模式：推荐 live E2E 使用
2. CDP 模式：兼容手动打开且已登录的浏览器
3. anonymous 模式：mock server / demo 使用
```

伪代码：

```python
if self.cdp_url:
    browser = await playwright.chromium.connect_over_cdp(self.cdp_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context(
        accept_downloads=True,
        viewport=self.viewport,
    )

elif self.auth_state:
    if not self.auth_state.exists():
        raise FileNotFoundError(f"auth_state not found: {self.auth_state}")

    browser = await playwright.chromium.launch(headless=self.headless)
    context = await browser.new_context(
        storage_state=str(self.auth_state),
        accept_downloads=True,
        viewport=self.viewport,
    )

else:
    browser = await playwright.chromium.launch(headless=self.headless)
    context = await browser.new_context(
        accept_downloads=True,
        viewport=self.viewport,
    )
```

新增 `auth-refresh` 命令：

```bash
python scripts/runner.py auth-refresh \
  --base-url "$FR_BASE_URL" \
  --out .auth/fr-opm.json
```

`auth-refresh` 逻辑：

```text
1. headed 模式打开浏览器
2. 用户手动完成 CAS / OPM 登录
3. 检测登录成功 selector 或 URL
4. 保存 Playwright storageState 到 .auth/fr-opm.json
```

`.gitignore` 增加：

```gitignore
.auth/
test-results/
.tmp/
```

### 验收标准

```text
[ ] auth-refresh 可生成 .auth/fr-opm.json
[ ] verify-export --auth-state .auth/fr-opm.json 可进入已登录页面
[ ] verify-export --cdp-url http://127.0.0.1:9222 可复用已登录浏览器
[ ] mock case 不需要 auth-state 也能跑
```

---

# P1：真实端到端闭环

## TODO 1.1：补齐真实 live case

### 问题

workflow 引用了 `tests/live_cases/opm_airline_profit_yoy.json`，但该文件可能不存在。即使存在，也需要避免硬编码敏感内网 URL。

### 涉及文件

```text
tests/live_cases/opm_airline_profit_yoy.json
tests/live_cases/opm_airline_profit_yoy.example.json
docs/E2E_LIVE.md
.github/workflows/test.yml
```

### 执行项

新增真实 live case 模板：

```json
{
  "name": "opm_airline_profit_yoy",
  "report": {
    "folder": "经营分析",
    "name": "航司净利润同比分析"
  },
  "navigation": {
    "base_url": "${FR_BASE_URL}",
    "report_url": "${FR_REPORT_URL}",
    "login_success_selector": "text=决策平台"
  },
  "params": {
    "month": "2026-05",
    "market": "ALL"
  },
  "page_extract": {
    "strategy": "network_then_dom",
    "data_api_patterns": [
      "/decision",
      "/reportserver",
      "/view/report"
    ],
    "table_locator": "iframe >> table",
    "visible_row_limit": 20,
    "wait_until": "networkidle"
  },
  "export": {
    "button_text_patterns": ["导出", "Excel", "下载"],
    "format": "xlsx",
    "scope": "current_filter_all_rows",
    "timeout_ms": 60000
  },
  "compare": {
    "mode": "visible_subset_by_key",
    "allow_extra_export_rows": true,
    "key_columns": ["航司", "月份"],
    "value_columns": ["净利润", "同比"],
    "numeric_tolerance": 0.01,
    "percent_tolerance": 0.0001,
    "allow_row_reorder": true
  },
  "expected": {
    "min_page_rows": 1,
    "min_export_rows": 1,
    "must_contain_columns": ["航司", "净利润", "同比"],
    "test_query": "这个月的各航司净利润的同比，谁表现得最差"
  }
}
```

### 验收标准

```text
[ ] workflow 引用的 live case 文件存在
[ ] case 中不硬编码敏感内网 URL
[ ] URL 可通过 FR_BASE_URL、FR_REPORT_URL 注入
[ ] docs/E2E_LIVE.md 说明如何配置 FR_AUTH_STATE_PATH
```

---

## TODO 1.2：保证被验证的 Excel 就是后续索引和查询使用的 Excel

### 问题

当前 `e2e-live` 可能先执行 `verify-export`，然后又独立执行 `download_all()`，再 index/query。这样验证过的 `export.xlsx` 不一定是进入索引的那个文件。

### 涉及文件

```text
scripts/runner.py
scripts/e2e/verify_export.py
scripts/e2e/artifacts.py
scripts/search/indexer.py
```

### 执行项

改造 `verify-export` 输出结构：

```json
{
  "ok": true,
  "artifacts_dir": "test-results/page_export/opm_airline_profit_yoy",
  "verified_export_path": "test-results/page_export/opm_airline_profit_yoy/export.xlsx",
  "verified_export_hash": "sha256:..."
}
```

新增 `e2e-live` 参数：

```bash
python scripts/runner.py e2e-live \
  --case tests/live_cases/opm_airline_profit_yoy.json \
  --use-verified-export \
  --mirror-root .tmp/e2e_mirror
```

推荐默认执行链路：

```text
1. verify-export 生成 export.xlsx
2. 将 verified export 复制到 mirror_root 下固定报表路径
3. index 这个 mirror_root
4. query 基于这个索引断言
```

不要默认重新执行 `download_all()`。

如需保留原批量下载能力，显式启用：

```bash
--download-mode batch
```

推荐默认：

```bash
--download-mode verified-export
```

### 验收标准

```text
[ ] e2e-live 结果中有 verified_export_hash
[ ] index 的文件 hash 与 verified_export_hash 一致
[ ] query 的 top_candidate 指向 verified export
[ ] verify-export 失败时不会执行 index/query
[ ] download_all 不再作为默认 Step 2
```

---

## TODO 1.3：绑定同一次页面状态与导出请求

### 问题

必须证明导出的 Excel 对应的是当前页面状态，而不是另一次筛选、排序或分页状态。

### 涉及文件

```text
scripts/e2e/browser_session.py
scripts/e2e/page_extract.py
scripts/e2e/verify_export.py
scripts/e2e/artifacts.py
```

### 执行项

新增 `run_context.json`：

```json
{
  "report": {
    "name": "航司净利润同比分析",
    "url": "...",
    "viewlet": "...",
    "report_id": "..."
  },
  "params": {
    "month": "2026-05",
    "market": "ALL"
  },
  "page_state": {
    "page_index": 1,
    "page_size": 20,
    "total_count": 3000,
    "sort": [
      {
        "column": "净利润",
        "direction": "desc"
      }
    ]
  },
  "page_data_request": {
    "url": "...",
    "method": "POST",
    "payload_hash": "sha256:..."
  },
  "page_data_response": {
    "status": 200,
    "body_hash": "sha256:..."
  },
  "export_request": {
    "url": "...",
    "method": "POST",
    "payload_hash": "sha256:..."
  },
  "export_file": {
    "path": "...",
    "hash": "sha256:..."
  }
}
```

### 验收标准

```text
[ ] page_snapshot.raw_hash 与 run_context.page_data_response.body_hash 对得上
[ ] export_file_hash 与实际 export.xlsx hash 对得上
[ ] 导出请求 payload 中包含当前筛选参数或等价编码
[ ] 页面排序 / 分页状态被记录
```

---

# P2：页面抽取与 FineReport 适配

## TODO 2.1：增强 network 抽取策略

### 问题

真实 FineReport 响应结构复杂，不能只支持简单 `rows` / `data` / `list[dict]`。

### 涉及文件

```text
scripts/e2e/page_extract.py
scripts/e2e/browser_session.py
scripts/e2e/finereport_adapters.py
tests/test_page_extract_finereport.py
```

### 执行项

新增 FineReport 响应适配器：

```text
1. 自动识别 reportserver / decision / view / entry 响应
2. 支持嵌套 JSON 中提取二维表
3. 支持 columns + rows 结构
4. 支持 cells 矩阵结构
5. 支持表头多行合并
6. 支持分页字段 total / pageIndex / pageSize
7. 支持响应不是 JSON 时跳过并记录候选
```

新增配置：

```json
{
  "page_extract": {
    "strategy": "network_then_dom",
    "network": {
      "include_patterns": ["/decision", "/reportserver"],
      "exclude_patterns": [".js", ".css", ".png"],
      "prefer_largest_table": true,
      "response_timeout_ms": 30000
    }
  }
}
```

### 验收标准

```text
[ ] mock server 提供嵌套 FineReport-like JSON，能抽出 rows
[ ] 无法识别 network 时自动 fallback DOM
[ ] artifacts 保存 matched_network_responses.json
[ ] 抽取失败时输出候选响应 URL 和 body hash
```

---

## TODO 2.2：增强 DOM / iframe / 虚拟滚动抽取

### 涉及文件

```text
scripts/e2e/page_extract.py
scripts/e2e/browser_session.py
tests/mock_fr_server/server.py
```

### 执行项

实现：

```text
1. 自动遍历 iframe
2. 支持 table
3. 支持 div[role=row] / aria grid
4. 支持冻结表头与冻结列去重
5. 支持只抽取可见区域 visible_row_limit
6. 支持滚动一次确认当前页稳定
7. 支持 table_locator 明确配置
```

### 验收标准

```text
[ ] iframe 内 table 可抽取
[ ] DOM 中重复冻结列不会产生重复字段
[ ] visible_row_limit=20 时只抽取 20 行
[ ] DOM 抽取输出 columns / rows / page_state
```

---

## TODO 2.3：增加页面稳定性等待

### 涉及文件

```text
scripts/e2e/browser_session.py
scripts/e2e/page_extract.py
```

### 执行项

新增等待配置：

```json
{
  "wait": {
    "network_idle_ms": 1000,
    "table_stable_ms": 1500,
    "loading_selectors": [".loading", ".fr-loading"],
    "ready_selectors": ["iframe", "table"],
    "max_wait_ms": 60000
  }
}
```

实现：

```text
1. 等待 loading 消失
2. 等待目标 table row count 连续两次一致
3. 等待关键列名出现
4. 等待导出按钮可点击
```

### 验收标准

```text
[ ] 慢加载 mock 页面可通过
[ ] 未加载完成就导出会被阻止
[ ] 超时错误能说明卡在哪个等待阶段
```

---

# P3：导出与 Excel 解析完善

## TODO 3.1：增强导出按钮定位

### 问题

真实 FineReport 可能通过菜单、iframe、图标按钮、二级菜单完成导出，不一定是单按钮。

### 涉及文件

```text
scripts/e2e/browser_session.py
scripts/e2e/verify_export.py
```

### 执行项

支持配置式导出步骤：

```json
{
  "export": {
    "steps": [
      {"type": "click", "selector": "text=导出"},
      {"type": "click", "selector": "text=Excel"},
      {"type": "wait_download"}
    ],
    "button_text_patterns": ["导出", "Excel", "下载"],
    "menu_timeout_ms": 5000
  }
}
```

### 验收标准

```text
[ ] 单按钮导出通过
[ ] 二级菜单导出通过
[ ] iframe 内导出按钮通过
[ ] 找不到按钮时保存 screenshot + accessibility snapshot
```

---

## TODO 3.2：增强 Excel 表头识别

### 涉及文件

```text
scripts/e2e/export_extract.py
scripts/e2e/normalize_table.py
tests/test_export_extract.py
```

### 执行项

支持：

```text
1. 自动识别表头行
2. 多行表头合并为字段名
3. 跳过标题区 / 参数区 / 空行
4. 支持指定 header_row
5. 支持指定 data_start_row
6. 支持指定 sheet_name
7. 支持隐藏行
8. 支持合并单元格
```

case 配置：

```json
{
  "export_extract": {
    "sheet_name": "航司净利润同比分析",
    "header_row": 3,
    "data_start_row": 4,
    "fill_merged_cells": true
  }
}
```

### 验收标准

```text
[ ] 标题区 + 多行表头 Excel 可解析
[ ] 合并单元格值向下 / 向右填充正确
[ ] 解析后列名与 case.must_contain_columns 对齐
```

---

## TODO 3.3：完善标准化和容差

### 涉及文件

```text
scripts/e2e/normalize_table.py
scripts/e2e/compare_table.py
tests/test_page_export_consistency.py
```

### 执行项

补齐：

```text
1. 数字：千分位、括号负数、中文单位 万/亿
2. 百分比：12.3% vs 0.123
3. 日期：2026年5月 / 2026-05 / Excel date serial
4. 空值：-- / — / N/A / 空单元格
5. 文本：全角半角、不可见空白
6. 别名：按字段配置，不做全局激进替换
```

配置示例：

```json
{
  "normalize": {
    "units": {
      "净利润": "万元"
    },
    "aliases": {
      "航司": {
        "东方航空": ["东航", "中国东方航空"]
      }
    }
  }
}
```

### 验收标准

```text
[ ] 1,234.50 vs 1234.5 PASS
[ ] 12.3% vs 0.123 PASS
[ ] 1.2万 vs 12000 PASS，前提 case 配置启用中文单位
[ ] 东方航空 vs 东航 只有配置 aliases 时 PASS
```

---

# P4：补齐 mock E2E 失败用例

## TODO 4.1：把失败场景做成完整 verify-export case

### 问题

单元测试覆盖了比较函数，但完整浏览器下载链路的失败场景不够。

### 涉及文件

```text
tests/live_cases/
tests/mock_fr_server/server.py
.github/workflows/test.yml
```

### 新增 case

```text
mock_sales_prefix_mismatch.json
mock_sales_subset_missing.json
mock_sales_subset_value_diff.json
mock_sales_percent_format.json
mock_sales_number_format.json
mock_sales_current_page_equal_fail_extra_rows.json
```

### 每个 case 的验收

```text
[ ] mismatch：verify-export 退出码为 1
[ ] missing：verify-export 退出码为 1
[ ] value_diff：diff_report.txt 包含 key / column / page / export
[ ] percent_format：退出码为 0
[ ] number_format：退出码为 0
[ ] current_page_equal_fail_extra_rows：退出码为 1
```

CI 示例：

```yaml
- name: Run negative mock cases
  run: |
    set +e
    python scripts/runner.py verify-export \
      --case tests/live_cases/mock_sales_subset_missing.json \
      --artifacts test-results/page_export/missing
    code=$?
    test "$code" -ne 0
```

---

# P5：artifacts 留痕完善

## TODO 5.1：保存 trace / HAR / console log

### 问题

真实 OPM 偶发失败时，如果没有 trace、HAR、console log，将很难定位是登录、网络、页面加载、导出按钮还是数据比对问题。

### 涉及文件

```text
scripts/e2e/browser_session.py
scripts/e2e/artifacts.py
scripts/e2e/verify_export.py
```

### 执行项

`BrowserSession.start()`：

```python
context = await browser.new_context(
    storage_state=...,
    accept_downloads=True,
    record_har_path=str(artifacts.path("network.har")),
)

await context.tracing.start(
    screenshots=True,
    snapshots=True,
    sources=True,
)

page.on("console", ...)
page.on("pageerror", ...)
page.on("requestfailed", ...)
```

`BrowserSession.stop()`：

```python
await context.tracing.stop(path=str(artifacts.path("trace.zip")))
```

保存文件：

```text
browser_console.log
request_failed.json
network.har
trace.zip
page_before_export.png
page_after_export.png
accessibility_snapshot.json
```

### 验收标准

```text
[ ] PASS 和 FAIL 都有 manifest
[ ] FAIL 必有 screenshot
[ ] FAIL 必有 trace.zip
[ ] FAIL 必有 network.har
[ ] FAIL 必有 diff_report.txt
[ ] console error 和 request failed 被记录
```

---

# P6：CI 策略完善

## TODO 6.1：把 mock E2E 变成 PR 必跑门禁

### 涉及文件

```text
.github/workflows/test.yml
```

### 执行项

PR 必跑：

```text
unit
py_compile
mock-page-export-positive
mock-page-export-negative
offline query tests
black --check
```

建议核心质量门禁不要使用 `continue-on-error: true`。

### 验收标准

```text
[ ] mock 正例失败会阻断 PR
[ ] mock 负例没有失败也会阻断 PR
[ ] py_compile 失败会阻断 PR
[ ] live job 只在 workflow_dispatch / schedule 跑
```

---

## TODO 6.2：live E2E 改为 self-hosted + 明确密钥约束

### 涉及文件

```text
.github/workflows/test.yml
docs/E2E_LIVE.md
```

### 执行项

live job 要求：

```text
1. runs-on: self-hosted
2. FR_AUTH_STATE_PATH 必须存在
3. FR_BASE_URL 必须存在
4. FR_REPORT_URL 必须存在
5. artifacts upload
```

前置检查：

```bash
test -f "$FR_AUTH_STATE_PATH"
test -n "$FR_BASE_URL"
test -n "$FR_REPORT_URL"
```

### 验收标准

```text
[ ] 无 auth state 时 live job fail fast
[ ] live job artifacts 可下载
[ ] live job 不在 pull_request 默认触发
```

---

# P7：文档完善

## TODO 7.1：新增 `docs/PAGE_EXPORT_CONSISTENCY.md`

### 内容必须包括

```text
1. 为什么 page_rows ⊆ export_rows，而不是 page_rows == export_rows
2. visible_prefix_ordered 使用场景
3. visible_subset_by_key 使用场景
4. current_page_equal 使用场景
5. 如何写 case json
6. 如何跑 mock
7. 如何跑 live
8. 如何查看 artifacts
9. 常见失败原因
```

### 验收标准

```text
[ ] 新人按文档能跑通 mock verify-export
[ ] 内网环境按文档能配置 auth-state
[ ] 文档中明确说明：页面 20 行、Excel 3000 行，页面 20 行一致即 PASS
```

---

# P8：最终验收清单

所有 TODO 完成后，必须满足：

```text
[ ] 所有新增 Python 文件语法正常
[ ] verify-export 支持 --auth-state
[ ] BrowserSession 支持 storageState / CDP / anonymous 三种模式
[ ] workflow 不再引用不存在的 case
[ ] live case 可通过环境变量注入 URL
[ ] 页面 20 行、Excel 3000 行、前 20 行一致 => PASS
[ ] 页面 20 行、Excel 3000 行、按 key 子集一致 => PASS
[ ] Excel 缺少页面行 => FAIL
[ ] Excel 对应字段值不一致 => FAIL
[ ] Excel 多出的 2980 行不算失败
[ ] current_page_equal 模式下 Excel 多行 => FAIL
[ ] verify-export 生成 page_snapshot.json
[ ] verify-export 生成 export_snapshot.json
[ ] verify-export 生成 compare_result.json
[ ] verify-export 生成 manifest.json
[ ] 失败时生成 diff_report.txt
[ ] 失败时生成 trace.zip
[ ] 失败时生成 network.har
[ ] 失败时生成 screenshot
[ ] e2e-live 使用 verify-export 产生的同一个 export.xlsx 建索引
[ ] verify-export 失败时阻断 index/query
[ ] mock E2E 是 PR 必跑
[ ] live E2E 是 self-hosted 手动 / 夜间跑
```

---

# 9. 合并门槛

本分支不能只证明“比较函数是对的”。

最终合并门槛是：

```text
必须证明：
同一次页面状态下导出的同一个 Excel，
已经通过页面展示数据一致性校验，
并且这个 Excel 被用于后续索引和自然语言查询。
```

也就是：

```text
页面可信 → 导出可信 → 索引可信 → 回答可信
```

其中最关键的判定规则是：

```text
当页面显示 20 行、Excel 导出 3000 行时，
只要页面当前显示的 20 行能在 Excel 中按顺序或按业务主键匹配成功，
且关键字段值一致，
就判定页面和导出数据一致。
Excel 多出的 2980 行不作为失败原因。
```
