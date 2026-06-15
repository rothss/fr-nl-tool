# fr-nl-tool 页面展示数据与 Excel 导出数据一致性验证优化计划

## 1. 背景

当前项目已经可以围绕 FineReport / 帆软报表完成以下链路：

```text
打开报表页面 → 导出 Excel → 下载文件 → 解析 Excel → 建索引 → 自然语言查询
```

但这条链路仍然缺失一个关键验收环节：

```text
页面当前展示的数据 是否 与 下载出来的 Excel 数据一致
```

如果不验证这一点，后续索引和自然语言查询即使结果正确，也只能证明“基于下载文件的结果正确”，不能证明“下载文件就是用户在页面上看到的那份报表数据”。

尤其需要注意一种常见场景：

```text
页面只显示当前页 20 行
Excel 导出当前筛选条件下的全部 3000 行
```

在这种情况下，不应该要求页面数据和 Excel 数据行数完全相等。只要页面当前显示的 20 行，与 Excel 中对应的前 20 行或对应业务主键行一致，就应该判定为数据一致。

因此，本计划目标是为项目新增一套可复用、可 CI 化、可留痕的 **Page-vs-Export Consistency Test**。

---

## 2. 总体目标

新增一个端到端验证能力，用于证明：

```text
当前页面状态下展示的数据 ⊆ 当前页面状态下导出的 Excel 数据
```

并进一步保证：

```text
页面展示数据可信 → Excel 导出数据可信 → 索引数据可信 → 自然语言回答可信
```

最终 E2E 链路应变为：

```text
1. 打开指定报表
2. 设置固定筛选条件 / 查询参数
3. 等待页面渲染稳定
4. 抽取页面当前展示数据 page_snapshot
5. 点击导出 Excel
6. 捕获下载文件 export.xlsx
7. 解析 Excel 为 export_snapshot
8. 对 page_snapshot 和 export_snapshot 做一致性比对
9. 一致后再进入 index / query / answer 验证
```

---

## 3. 核心原则

### 3.1 Excel 允许包含页面未显示的额外行

这是本次优化的核心规则。

当页面显示 20 行，而 Excel 导出 3000 行时：

```text
page_rows = 20
export_rows = 3000
```

只要页面显示的 20 行能够在 Excel 中找到，并且关键字段和值字段一致，就应该判定为通过。

不应该因为 Excel 比页面多出 2980 行而判定失败。

### 3.2 页面数据是 Excel 数据的可验证子集

默认判断模型：

```text
page_visible_rows ⊆ export_rows
```

而不是：

```text
page_visible_rows == export_rows
```

只有在明确配置导出模式为“仅导出当前页”时，才要求两边行数完全一致。

### 3.3 优先使用结构化数据，不依赖截图或 OCR

页面数据抽取优先级：

```text
1. 拦截页面渲染接口响应 JSON
2. 从 DOM / iframe / 表格节点抽取文本
3. 截图仅作为失败诊断证据
4. OCR 不作为主断言来源
```

### 3.4 比对必须绑定同一次页面状态

必须记录并比对：

```text
报表 ID
报表名称
URL
筛选参数
排序状态
分页状态
页面数据请求 payload
页面数据响应 hash
导出请求 payload
导出文件 hash
```

避免出现“页面是一组条件，导出是另一组条件”的误判。

---

## 4. 一致性验证模式

新增 `compare.mode` 配置，支持以下几种模式。

### 4.1 `visible_prefix_ordered`

适用场景：

```text
页面显示当前筛选和排序下的第一页数据
Excel 导出当前筛选和排序下的全部数据
Excel 前 N 行应该与页面 N 行顺序一致
```

判定规则：

```text
export_row_count >= page_row_count
export_rows[0:N] 与 page_rows[0:N] 逐行逐列一致
```

示例：

```text
页面显示 20 行
Excel 导出 3000 行
只比对 Excel 前 20 行
前 20 行一致 → PASS
第 7 行金额不同 → FAIL
Excel 有额外 2980 行 → 不算失败
```

适合报表排序稳定、导出顺序与页面顺序严格一致的场景。

---

### 4.2 `visible_subset_by_key`

适用场景：

```text
页面显示当前页 20 行
Excel 导出全部 3000 行
导出顺序可能与页面顺序不完全一致
但存在稳定业务主键
```

判定规则：

```text
对 page_rows 生成 key
对 export_rows 生成 key
每一条 page_row 都必须能在 export_rows 中找到相同 key
找到后比对 value_columns
export_rows 中存在额外行不算失败
```

示例：

```text
key_columns = ["航司", "月份"]
value_columns = ["净利润", "同比"]

页面：
  东航 / 2026-05 / 净利润 100 / 同比 12.3%

Excel：
  共 3000 行，其中包含：
  东航 / 2026-05 / 净利润 100 / 同比 12.3%

判定：
  PASS
```

这是推荐默认模式。

---

### 4.3 `current_page_equal`

适用场景：

```text
导出按钮明确是“导出当前页”
页面显示 20 行
Excel 也应该只有这 20 行
```

判定规则：

```text
export_row_count == page_row_count
每一行内容一致
```

---

### 4.4 `all_pages_equal`

适用场景：

```text
测试脚本会自动翻页，采集页面全部分页数据
Excel 也导出全部数据
```

判定规则：

```text
all_page_rows 与 export_rows 完全一致
```

该模式成本最高，适合少量核心报表夜间回归，不建议每次 PR 都运行。

---

## 5. 默认策略

项目默认策略建议为：

```json
{
  "compare": {
    "mode": "visible_subset_by_key",
    "export_scope": "current_filter_all_rows",
    "allow_extra_export_rows": true
  }
}
```

即：

```text
页面当前可见数据必须存在于 Excel 中
Excel 可以包含页面未展示的更多行
```

当能够确认 Excel 导出顺序与页面顺序完全一致时，可以使用：

```json
{
  "compare": {
    "mode": "visible_prefix_ordered",
    "export_scope": "current_filter_all_rows",
    "allow_extra_export_rows": true
  }
}
```

---

## 6. 推荐目录结构

新增以下模块：

```text
scripts/
  e2e/
    __init__.py
    verify_export.py
    browser_session.py
    page_extract.py
    export_extract.py
    normalize_table.py
    compare_table.py
    diff_report.py
    artifacts.py
    case_loader.py

tests/
  live_cases/
    mock_sales_visible_subset.json
    mock_sales_prefix_ordered.json
    mock_sales_current_page_equal.json
    opm_airline_profit_yoy.json

  mock_fr_server/
    server.py
    fixtures/
      page_20_export_3000_pass.xlsx
      page_20_export_3000_mismatch.xlsx
      page_20_export_missing_row.xlsx
```

---

## 7. 新增命令

新增 CLI 命令：

```bash
python scripts/runner.py verify-export \
  --case tests/live_cases/opm_airline_profit_yoy.json \
  --auth-state .auth/fr-opm.json \
  --artifacts test-results/page_export
```

完整 E2E 命令：

```bash
python scripts/runner.py e2e-live \
  --case tests/live_cases/opm_airline_profit_yoy.json \
  --mirror-root .tmp/e2e_mirror \
  --auth-state .auth/fr-opm.json \
  --artifacts test-results/e2e
```

其中 `e2e-live` 应该先调用 `verify-export`，只有页面与导出一致后，才继续执行：

```text
download → index → query → answer assertion
```

---

## 8. 测试用例配置格式

示例文件：`tests/live_cases/opm_airline_profit_yoy.json`

```json
{
  "name": "airline_profit_yoy_page_export_consistency",
  "report": {
    "folder": "经营分析",
    "name": "航司净利润同比分析"
  },
  "navigation": {
    "base_url": "https://example.com/decision",
    "report_url": "https://example.com/decision/view/report?viewlet=xxx.cpt"
  },
  "params": {
    "month": "2026-05",
    "market": "ALL"
  },
  "page_extract": {
    "strategy": "network_then_dom",
    "data_api_patterns": [
      "/decision/view/report",
      "/decision/v10/entry/access",
      "/reportserver"
    ],
    "table_locator": "iframe >> table",
    "wait_until": "networkidle",
    "visible_row_limit": 20
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
    "ignore_columns": ["序号"],
    "numeric_tolerance": 0.01,
    "percent_tolerance": 0.0001,
    "ignore_formatting": true,
    "allow_row_reorder": true,
    "empty_equivalents": ["", "-", "--", "—", "N/A", null]
  },
  "expected": {
    "min_page_rows": 1,
    "min_export_rows": 1,
    "must_contain_columns": ["航司", "净利润", "同比"]
  }
}
```

---

## 9. Page Snapshot 数据结构

页面抽取后生成：

```json
{
  "source": "page",
  "report_name": "航司净利润同比分析",
  "url": "https://example.com/decision/view/report?viewlet=xxx.cpt",
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
  "columns": ["航司", "月份", "净利润", "同比"],
  "rows": [
    {
      "航司": "东航",
      "月份": "2026-05",
      "净利润": "100",
      "同比": "12.3%"
    }
  ],
  "raw_hash": "sha256:...",
  "captured_at": "2026-06-15T10:00:00+09:00"
}
```

---

## 10. Export Snapshot 数据结构

Excel 解析后生成：

```json
{
  "source": "export",
  "file": "test-results/page_export/export.xlsx",
  "file_hash": "sha256:...",
  "workbook": {
    "sheet_name": "航司净利润同比分析",
    "sheet_count": 1
  },
  "columns": ["航司", "月份", "净利润", "同比"],
  "rows": [
    {
      "航司": "东航",
      "月份": "2026-05",
      "净利润": 100,
      "同比": 0.123
    }
  ],
  "row_count": 3000,
  "parsed_at": "2026-06-15T10:00:10+09:00"
}
```

---

## 11. 标准化规则

新增 `normalize_table.py`，统一处理页面文本和 Excel 单元格差异。

### 11.1 空值标准化

以下值视为等价空值：

```text
null
""
"-"
"--"
"—"
"N/A"
"NA"
"无"
```

标准化为：

```python
None
```

---

### 11.2 数字标准化

需要支持：

```text
"1,234.50" → 1234.5
" 1234 " → 1234
"1,234" → 1234
```

---

### 11.3 百分比标准化

需要支持：

```text
"12.3%" → 0.123
"12.30%" → 0.123
0.123 → 0.123
```

注意：

```text
Excel 中百分比可能存为 0.123
页面上可能显示为 12.3%
两者应该判定一致
```

---

### 11.4 日期标准化

需要支持：

```text
"2026年5月" → "2026-05"
"2026/05" → "2026-05"
"2026-05" → "2026-05"
"2026-05-01" → "2026-05-01"
```

日期字段的具体粒度由测试用例配置决定。

---

### 11.5 文本标准化

默认处理：

```text
去除首尾空格
全角空格转半角
连续空白合并
```

不要默认做激进同义词替换。

例如：

```text
"东方航空" 和 "东航"
```

只有在配置了别名表时才视为等价。

配置示例：

```json
{
  "aliases": {
    "航司": {
      "东方航空": ["东航", "中国东方航空"],
      "南方航空": ["南航", "中国南方航空"]
    }
  }
}
```

---

### 11.6 合并单元格处理

Excel 中如果存在合并单元格，需要将左上角值填充到合并区域内。

示例：

```text
A1:A20 合并，A1 = "东航"
则 A2 到 A20 在解析后也应该视为 "东航"
```

---

## 12. 比对算法

### 12.1 `visible_prefix_ordered` 算法

伪代码：

```python
def compare_visible_prefix_ordered(page_rows, export_rows, value_columns, tolerance):
    n = len(page_rows)

    if len(export_rows) < n:
        return fail("export rows fewer than page rows")

    diffs = []

    for i in range(n):
        page_row = page_rows[i]
        export_row = export_rows[i]

        for col in value_columns:
            page_value = normalize(page_row.get(col))
            export_value = normalize(export_row.get(col))

            if not values_equal(page_value, export_value, tolerance):
                diffs.append({
                    "row_index": i + 1,
                    "column": col,
                    "page": page_value,
                    "export": export_value
                })

    if diffs:
        return fail("prefix rows mismatch", diffs)

    return pass_result({
        "mode": "visible_prefix_ordered",
        "page_rows": len(page_rows),
        "export_rows": len(export_rows),
        "matched_rows": len(page_rows),
        "extra_export_rows": len(export_rows) - len(page_rows)
    })
```

判定重点：

```text
export_rows 多出来的行不算失败
只要前 N 行与页面 N 行一致即可
```

---

### 12.2 `visible_subset_by_key` 算法

伪代码：

```python
def make_key(row, key_columns):
    return tuple(normalize(row.get(col)) for col in key_columns)


def compare_visible_subset_by_key(
    page_rows,
    export_rows,
    key_columns,
    value_columns,
    tolerance
):
    export_map = {}

    for row in export_rows:
        key = make_key(row, key_columns)
        export_map.setdefault(key, []).append(row)

    missing_in_export = []
    diffs = []

    for page_row in page_rows:
        key = make_key(page_row, key_columns)

        if key not in export_map:
            missing_in_export.append({
                "key": key,
                "page_row": page_row
            })
            continue

        candidates = export_map[key]

        matched = False
        candidate_diffs = []

        for export_row in candidates:
            row_diffs = []

            for col in value_columns:
                page_value = normalize(page_row.get(col))
                export_value = normalize(export_row.get(col))

                if not values_equal(page_value, export_value, tolerance):
                    row_diffs.append({
                        "column": col,
                        "page": page_value,
                        "export": export_value
                    })

            if not row_diffs:
                matched = True
                break

            candidate_diffs.append(row_diffs)

        if not matched:
            diffs.append({
                "key": key,
                "page_row": page_row,
                "candidate_diffs": candidate_diffs
            })

    if missing_in_export or diffs:
        return fail("visible page rows are not contained in export", {
            "missing_in_export": missing_in_export,
            "diffs": diffs
        })

    return pass_result({
        "mode": "visible_subset_by_key",
        "page_rows": len(page_rows),
        "export_rows": len(export_rows),
        "matched_rows": len(page_rows),
        "extra_export_rows": len(export_rows) - len(page_rows)
    })
```

判定重点：

```text
页面每一行都必须能在 Excel 中找到
Excel 多出的行不算失败
页面行顺序和 Excel 行顺序可以不同
```

---

## 13. 输出报告格式

### 13.1 成功输出

```text
PASS page_export_consistency

Case: airline_profit_yoy_page_export_consistency
Report: 航司净利润同比分析
Params: month=2026-05, market=ALL

Mode: visible_subset_by_key
Page rows: 20
Export rows: 3000
Matched page rows: 20
Extra export rows: 2980

Key columns:
  - 航司
  - 月份

Value columns:
  - 净利润
  - 同比

Artifacts:
  - page_snapshot.json
  - export_snapshot.json
  - export.xlsx
  - compare_result.json
  - trace.zip
  - screenshot.png
```

---

### 13.2 失败输出：Excel 缺少页面行

```text
FAIL page_export_consistency

Case: airline_profit_yoy_page_export_consistency
Report: 航司净利润同比分析

Mode: visible_subset_by_key
Page rows: 20
Export rows: 3000
Matched page rows: 19
Missing rows: 1

Missing in export:
  key = ["南航", "2026-05"]
  page_row = {
    "航司": "南航",
    "月份": "2026-05",
    "净利润": "88",
    "同比": "5.1%"
  }

Artifacts:
  - page_snapshot.json
  - export_snapshot.json
  - compare_result.json
  - export.xlsx
  - trace.zip
  - screenshot.png
```

---

### 13.3 失败输出：值不一致

```text
FAIL page_export_consistency

Case: airline_profit_yoy_page_export_consistency
Report: 航司净利润同比分析

Mode: visible_subset_by_key
Page rows: 20
Export rows: 3000
Matched page rows: 19
Diff rows: 1

Different values:
  key = ["东航", "2026-05"]
  column = "同比"
  page = 0.123
  export = 0.12
  tolerance = 0.0001

Artifacts:
  - page_snapshot.json
  - export_snapshot.json
  - compare_result.json
  - export.xlsx
  - trace.zip
  - screenshot.png
```

---

## 14. Artifacts 留痕要求

每次验证必须保存：

```text
test-results/page_export/<case_name>/
  page_snapshot.json
  export_snapshot.json
  compare_result.json
  export.xlsx
  page_before_export.png
  trace.zip
  browser_console.log
  network.har
  manifest.json
```

其中 `manifest.json` 包含：

```json
{
  "case_name": "airline_profit_yoy_page_export_consistency",
  "report_name": "航司净利润同比分析",
  "params": {
    "month": "2026-05",
    "market": "ALL"
  },
  "page_url": "...",
  "page_data_hash": "sha256:...",
  "export_file_hash": "sha256:...",
  "started_at": "...",
  "finished_at": "...",
  "status": "PASS"
}
```

---

## 15. Mock E2E 测试设计

必须新增 mock server，用于在不依赖真实 FineReport 的情况下验证一致性逻辑。

### 15.1 用例 A：页面 20 行，Excel 3000 行，前 20 行一致

预期：

```text
PASS
```

目的：

```text
证明 Excel 多出额外行时不会误判失败
```

配置：

```json
{
  "compare": {
    "mode": "visible_prefix_ordered",
    "allow_extra_export_rows": true
  }
}
```

---

### 15.2 用例 B：页面 20 行，Excel 3000 行，页面 20 行可按 key 在 Excel 中找到

预期：

```text
PASS
```

目的：

```text
证明页面行是 Excel 子集即可通过，不依赖顺序
```

配置：

```json
{
  "compare": {
    "mode": "visible_subset_by_key",
    "key_columns": ["航司", "月份"],
    "value_columns": ["净利润", "同比"]
  }
}
```

---

### 15.3 用例 C：页面 20 行，Excel 3000 行，但页面第 7 行数值不同

预期：

```text
FAIL
```

目的：

```text
证明子集存在但值不一致时会失败
```

---

### 15.4 用例 D：页面 20 行，Excel 3000 行，但 Excel 缺少页面某一行

预期：

```text
FAIL
```

目的：

```text
证明页面可见数据必须完整存在于 Excel
```

---

### 15.5 用例 E：页面显示百分比，Excel 存小数

页面：

```text
12.3%
```

Excel：

```text
0.123
```

预期：

```text
PASS
```

目的：

```text
证明百分比标准化正确
```

---

### 15.6 用例 F：页面显示千分位，Excel 存数字

页面：

```text
1,234.50
```

Excel：

```text
1234.5
```

预期：

```text
PASS
```

目的：

```text
证明数字格式标准化正确
```

---

### 15.7 用例 G：导出当前页模式

页面：

```text
20 行
```

Excel：

```text
20 行
```

配置：

```json
{
  "compare": {
    "mode": "current_page_equal"
  }
}
```

预期：

```text
PASS
```

如果 Excel 为 3000 行，则：

```text
FAIL
```

目的：

```text
证明在当前页导出模式下，不能允许额外行
```

---

## 16. 真实 FineReport 验收标准

真实环境中的验收至少覆盖 3 类报表：

```text
1. 明细表：页面分页展示，Excel 导出全部明细
2. 汇总表：页面显示聚合结果，Excel 导出同一汇总结果
3. 含百分比 / 金额 / 日期的指标表
```

每类至少 1 个 live case。

### 16.1 最低验收标准

```text
verify-export 命令可以在真实环境跑通
页面 20 行、Excel 3000 行时通过子集校验
失败时输出明确 diff
所有 artifacts 可定位问题
mock-e2e 在 CI 中自动运行
真实 live-e2e 可在 self-hosted runner 手动或夜间运行
```

---

## 17. CI 分层策略

### 17.1 PR 必跑

```text
unit tests
mock page-export consistency tests
offline query tests
```

### 17.2 夜间 / 手动运行

```text
真实 FineReport live tests
OPM / CAS 登录态测试
长耗时 all_pages_equal 测试
```

### 17.3 GitHub Actions 示例

```yaml
name: Tests

on:
  pull_request:
  push:
  workflow_dispatch:
  schedule:
    - cron: "0 18 * * *"

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python -m unittest discover -s tests -p "test_*.py" -v

  mock-page-export:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: npx playwright install chromium
      - run: python tests/mock_fr_server/server.py --port 18080 &
      - run: |
          python scripts/runner.py verify-export \
            --case tests/live_cases/mock_sales_visible_subset.json \
            --artifacts test-results/page_export

  live-page-export:
    if: github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: npx playwright install chromium
      - run: |
          python scripts/runner.py verify-export \
            --case tests/live_cases/opm_airline_profit_yoy.json \
            --auth-state "$FR_AUTH_STATE_PATH" \
            --artifacts test-results/page_export
```

---

## 18. 实施阶段拆分

### 阶段 1：实现快照和标准化

交付物：

```text
scripts/e2e/normalize_table.py
scripts/e2e/export_extract.py
scripts/e2e/compare_table.py
```

验收：

```text
能读取 xlsx
能填充合并单元格
能标准化数字、百分比、日期、空值
能执行 visible_prefix_ordered 和 visible_subset_by_key 比对
```

---

### 阶段 2：实现 mock server 和 mock 测试

交付物：

```text
tests/mock_fr_server/server.py
tests/live_cases/mock_*.json
tests/test_page_export_consistency.py
```

验收：

```text
页面 20 行、Excel 3000 行、前 20 行一致 → PASS
页面 20 行、Excel 3000 行、按 key 子集一致 → PASS
页面数值和 Excel 不一致 → FAIL
Excel 缺少页面行 → FAIL
```

---

### 阶段 3：接入 Playwright 页面抽取和下载

交付物：

```text
scripts/e2e/browser_session.py
scripts/e2e/page_extract.py
scripts/e2e/verify_export.py
```

验收：

```text
能打开 mock 页面
能抽取页面表格
能点击导出
能保存下载 xlsx
能生成 page_snapshot 和 export_snapshot
```

---

### 阶段 4：接入真实 FineReport

交付物：

```text
tests/live_cases/opm_*.json
.auth storageState 支持
self-hosted runner 配置文档
```

验收：

```text
真实报表页面可打开
真实筛选参数可设置
真实 Excel 可下载
页面可见数据与 Excel 子集一致
失败时 artifacts 完整
```

---

### 阶段 5：接入完整 E2E

交付物：

```text
scripts/runner.py e2e-live
```

执行顺序：

```text
verify-export
download
index
query
answer assertion
```

验收：

```text
页面与导出不一致时，阻断后续 index / query
页面与导出一致时，继续执行完整链路
```

---

## 19. 关键验收清单

开发完成后，必须满足以下条件：

```text
[ ] 支持 page_rows ⊆ export_rows 的一致性判断
[ ] 页面 20 行、Excel 3000 行、页面 20 行一致时判定 PASS
[ ] Excel 多出的 2980 行不作为失败原因
[ ] 支持按顺序前缀比对 visible_prefix_ordered
[ ] 支持按业务主键子集比对 visible_subset_by_key
[ ] 支持导出当前页完全一致 current_page_equal
[ ] 支持数字、百分比、日期、空值标准化
[ ] 支持 Excel 合并单元格填充
[ ] 支持失败 diff 输出
[ ] 支持 artifacts 留痕
[ ] mock-e2e 可在 CI 自动运行
[ ] live-e2e 可在 self-hosted runner 手动或夜间运行
[ ] verify-export 失败时完整阻断后续索引和查询
```

---

## 20. 其它 AI / 开发者落地指令

请基于本计划为 `fr-nl-tool` 项目实现页面展示数据与 Excel 导出数据一致性验证能力。

优先实现以下能力：

```text
1. 新增 compare_table.py
   - 实现 visible_prefix_ordered
   - 实现 visible_subset_by_key
   - 实现 current_page_equal

2. 新增 normalize_table.py
   - 数字标准化
   - 百分比标准化
   - 日期标准化
   - 空值标准化
   - 文本空白标准化
   - Excel 合并单元格填充

3. 新增 export_extract.py
   - 读取 xlsx
   - 自动识别表头
   - 输出 export_snapshot.json

4. 新增 page_extract.py
   - 优先拦截网络响应
   - 其次 DOM 表格抽取
   - 输出 page_snapshot.json

5. 新增 verify_export.py
   - 加载 case json
   - 打开页面
   - 设置筛选参数
   - 抽取页面数据
   - 点击导出
   - 解析 Excel
   - 执行一致性比对
   - 输出 compare_result.json
   - 保存 artifacts

6. 新增 mock tests
   - 页面 20 行、Excel 3000 行、一致 PASS
   - 页面 20 行、Excel 3000 行、值不一致 FAIL
   - 页面 20 行、Excel 3000 行、缺行 FAIL
   - 百分比格式差异 PASS
   - 数字千分位差异 PASS
```

最终标准：

```text
当页面显示 20 行、Excel 导出 3000 行时，只要页面当前显示的 20 行在 Excel 中能按顺序或按业务主键匹配成功，并且关键字段值一致，就判定页面和导出数据一致。
```
