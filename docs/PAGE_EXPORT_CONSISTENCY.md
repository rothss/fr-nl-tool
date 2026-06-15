# Page-Export Consistency Verification

验证 OPM/FineReport 页面展示数据与 Excel 导出数据的一致性。

## 1. 核心原理

**页面显示 20 行，Excel 导出 3000 行时，页面可见数据是导出数据的子集即判定一致。**

```text
判定规则：
只要页面当前显示的 20 行能在 Excel 中：
1. 按顺序匹配 Excel 前 20 行（visible_prefix_ordered）
2. 按业务 key 匹配到对应行（visible_subset_by_key）

且关键字段值一致，即判定页面和导出数据一致。
Excel 多出的 2980 行不作为失败原因。
```

## 2. 三种比对模式

| 模式 | 适用场景 | 允许多行 | 允许乱序 |
|------|---------|---------|---------|
| `visible_prefix_ordered` | 简单表格，前20行严格对应 | ✅ | ❌ |
| `visible_subset_by_key` | 复杂表格，按业务主键匹配 | ✅ | ✅ |
| `current_page_equal` | 页面=导出（行数必须一致） | ❌ | ❌ |

## 3. 快速开始

### 3.1 跑 mock 验证

```bash
# 启动 mock server
python tests/mock_fr_server/server.py --port 18080 &

# 正向 case（应 PASS）
python scripts/runner.py verify-export \
  --case tests/live_cases/mock_sales_prefix_ordered.json \
  --output-format text

# 负向 case（应 FAIL）
python scripts/runner.py verify-export \
  --case tests/live_cases/mock_sales_value_diff.json \
  --output-format text
```

### 3.2 生成 auth-state

```bash
# 打开浏览器，手动登录，保存登录态
python scripts/runner.py auth-refresh \
  --base-url "$FR_BASE_URL" \
  --out .auth/fr-opm.json
```

### 3.3 跑真实 OPM 验证

```bash
python scripts/runner.py verify-export \
  --case tests/live_cases/opm_airline_profit_yoy.example.json \
  --auth-state .auth/fr-opm.json \
  --output-format text
```

### 3.4 用 CDP 复用已登录浏览器

```bash
python scripts/runner.py verify-export \
  --case tests/live_cases/your_case.json \
  --cdp-url http://127.0.0.1:9222 \
  --output-format text
```

## 4. Case JSON 写法

### 4.1 最小示例

```json
{
  "name": "my_case",
  "navigation": {
    "report_url": "http://127.0.0.1:18080/?scenario=xxx"
  },
  "page_extract": {
    "strategy": "dom",
    "table_selector": "table",
    "visible_row_limit": 20
  },
  "export": {
    "button_text": "导出",
    "timeout_ms": 60000
  },
  "compare": {
    "mode": "visible_prefix_ordered",
    "allow_extra_export_rows": true,
    "value_columns": ["净利润", "同比"],
    "numeric_tolerance": 0.01,
    "percent_tolerance": 0.0001
  },
  "expected": {
    "min_page_rows": 1,
    "min_export_rows": 1,
    "must_contain_columns": ["航司", "净利润", "同比"]
  }
}
```

### 4.2 二级菜单导出

```json
{
  "export": {
    "steps": [
      {"type": "click", "selector": "text=导出"},
      {"type": "click", "selector": "text=Excel"},
      {"type": "wait_download"}
    ],
    "timeout_ms": 60000
  }
}
```

### 4.3 指定 Excel 表头行和数据起始行

```json
{
  "compare": {
    "mode": "visible_subset_by_key",
    "sheet_name": "销售报表",
    "header_row": 3,
    "data_start_row": 4,
    "fill_merged_cells": true
  }
}
```

### 4.4 配置字段别名

```json
{
  "compare": {
    "aliases": {
      "航司": {
        "东方航空": ["东航", "中国东方航空"]
      }
    }
  }
}
```

## 5. 查看 artifacts

```text
test-results/page_export/<case_name>/
├── page_snapshot.json          ← 页面抽取数据
├── export_snapshot.json         ← Excel 解析数据
├── compare_result.json          ← 比对结果
├── run_context.json             ← 运行上下文（页面状态/导出请求绑定）
├── manifest.json                ← 运行摘要
├── diff_report.txt              ← 差异详情（失败时）
├── trace.zip                    ← Playwright Trace（失败时，可用 trace.playwright.dev 查看）
├── network.har                  ← 网络请求记录
├── browser_console.log          ← 控制台日志
├── request_failed.json          ← 失败请求记录
├── page_before_export.png       ← 导出前截图
└── export.xlsx                  ← 下载的 Excel
```

### 5.1 用 Playwright Trace Viewer 回放

```bash
# 安装 Playwright CLI（如未安装）
pip install playwright
python -m playwright install

# 打开 trace
playwright show-trace test-results/page_export/<case_name>/trace.zip
```

## 6. 端到端闭环：e2e-live

```bash
# 验证 → 复制到镜像 → 建索引 → 查询断言
python scripts/runner.py e2e-live \
  --case tests/live_cases/opm_airline_profit_yoy.example.json \
  --auth-state .auth/fr-opm.json \
  --download-mode verified-export
```

`verified-export` 模式确保被验证的 Excel 就是进入索引/查询的同一个文件。

## 7. CI 中运行

### mock 正向/负向 E2E

```yaml
- name: Run mock positive case
  run: python scripts/runner.py verify-export --case tests/live_cases/mock_sales_prefix_ordered.json

- name: Run mock negative case
  run: |
    python scripts/runner.py verify-export --case tests/live_cases/mock_sales_value_diff.json
    test "$?" -ne 0  # 预期失败
```

### live E2E（手动触发）

```yaml
live-page-export:
  if: github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'
  runs-on: self-hosted
```

## 8. 常见失败原因

| 现象 | 可能原因 | 排查方法 |
|------|---------|---------|
| 导出按钮找不到 | 按钮在 iframe 内 | 用 `playwright show-trace trace.zip` 查看 DOM 快照 |
| 页面数据为 0 行 | loading 未消失 | 检查 `browser_console.log` 查看错误 |
| 数值不一致 | 百分比格式差异 | 确认 `percent_tolerance` 配置 |
| 12.3% vs 0.123 不一致 | 未配置 `percent_columns` | 在 `compare.percent_columns` 中列出百分比列 |
| run_context 中 total_count 为 null | page 无 FR 分页组件 | 正常，不影响比对 |

## 9. 完整验收命令

```bash
# 编译检查
python -m py_compile scripts/runner.py
python -m py_compile scripts/e2e/*.py
python -m py_compile tests/test_page_export_consistency.py

# 单元测试
python -m unittest tests.test_page_export_consistency -v

# mock 正向
python tests/mock_fr_server/server.py --port 18080 &
python scripts/runner.py verify-export --case tests/live_cases/mock_sales_prefix_ordered.json
python scripts/runner.py verify-export --case tests/live_cases/mock_sales_visible_subset.json
python scripts/runner.py verify-export --case tests/live_cases/mock_sales_current_page_equal.json

# mock 负向（预期退出码 != 0）
python scripts/runner.py verify-export --case tests/live_cases/mock_sales_value_diff.json || true
python scripts/runner.py verify-export --case tests/live_cases/mock_sales_extra_export_rows_fail.json || true
python scripts/runner.py verify-export --case tests/live_cases/mock_sales_rows_missing.json || true
```
