# opm-nl-report-query 任务清单

> 更新时间：2026-04-27 | 接手 AI 请仔细阅读全部内容

---

## 一、已完成 — 开源重构 Phase 0-5

✅ **全部 5 个 Phase 已提交**，详见 git log：
```
11998d9  feat: Phase 1 完成 - 所有硬编码URL/路径配置化
9c2ac34  feat: Phase 0 完成 - dotenv配置化 + FR_*环境变量 + .gitignore
ab1d914  feat: 删除Hermes依赖文件，添加开源可行性分析报告
```

---

## 二、当前目标 — 全量下载 + 任意指标搜索

> **目标：** 从报表平台下载**全部**报表到本地，支持搜索其中**任意**指标

当前 `opm-nl-report-query` 只支持：
- 按需单报表下载（查询时触发，非全量）
- 预定义指标搜索（依赖 `synonyms.yaml`，非任意）

需要将兄弟项目的能力以模块化方式迁移进来：

| 兄弟项目 | 待迁移能力 | 迁移到 |
|---------|----------|--------|
| `excel-search-sqlite` | SQLite FTS5 全文索引 + 搜索 | `scripts/search/` |
| `opm-incremental-download` | FineReport 树发现 + 批量下载 | `scripts/download/` |
| `opm-market-horse-checkregister-export` | 稳定导出链参数 | `scripts/download/` |

---

## 三、模块架构

```
scripts/
├── download/                    # 新增 — 下载管线
│   ├── __init__.py
│   ├── auth.py                  # CDP 浏览器认证提取
│   ├── discover.py              # FineReport 报表树发现 → manifest.json
│   └── batch.py                 # 批量下载编排 (调用 opm_batch_acp.ps1)
│
├── search/                      # 新增 — 搜索管线
│   ├── __init__.py
│   ├── db.py                    # SQLite schema (workbooks/sheets/cells + FTS)
│   ├── normalizer.py            # 文本规范化 + 数值过滤
│   ├── parsers.py               # Excel/xls/csv 解析器
│   ├── indexer.py               # 索引编排 (全量 / 增量)
│   └── searcher.py              # FTS5 全文搜索 (JSON 输出)
│
├── runner.py                    # 修改 — 新增子命令
├── common.py                    # 不变
└── (其余已有文件保持不变)
```

### 模块依赖

```
auth.py          (无依赖)
discover.py      → auth.py
batch.py         → discover.py, auth.py, opm_batch_acp.ps1
db.py            (无依赖)
normalizer.py    (无依赖)
parsers.py       → normalizer.py
indexer.py       → db.py, parsers.py, normalizer.py
searcher.py      → db.py
runner.py        → download/*, search/*
```

### 模块大小约束

每个 `.py` 文件不超过 150 行，单一职责。

---

## 四、详细任务 — Phase 6: download/ 模块

### 6.1 `scripts/download/__init__.py`
- [x] 创建空文件

### 6.2 `scripts/download/auth.py` (~50行)
- [x] 完成 — 从 CDP 浏览器提取认证 cookie，回退到 Node.js subprocess

### 6.3 `scripts/download/discover.py` (~110行)
- [x] 完成 — 调用 `/v10/view/entry/tree` API，扁平化目录树，生成 manifest.json

### 6.4 `scripts/download/exporter.py` (~110行) — 新增
- [x] 完成 — Python HTTP 单报表导出 (access→sessionID→export)，替代 PS `Invoke-ParentExport`

### 6.5 `scripts/download/batch.py` (~160行)
- [x] 完成 — 批量下载编排器，调用 Playwright check_register 导出（Python HTTP 直连不兼容 FineReport CAS）

---

## 五、详细任务 — Phase 7: search/ 模块

### 7.1 `scripts/search/__init__.py`
- [x] 创建空文件

### 7.2 `scripts/search/db.py` (~112行)
- [x] 完成 — SQLite WAL模式连接 + 5表+2FTS schema

### 7.3 `scripts/search/normalizer.py` (~48行)
- [x] 完成 — 数值过滤（万元/吨/架/%等后缀识别）+ 中文文本保留

### 7.4 `scripts/search/parsers.py` (~141行)
- [x] 完成 — xlsx(openpyxl→XML回退) / xls(pandas) / csv 多格式解析

### 7.5 `scripts/search/indexer.py` (~114行)
- [x] 完成 — 全量/增量索引编排，文件发现 → 解析 → 入库 → FTS重建

### 7.6 `scripts/search/searcher.py` (~93行)
- [x] 完成 — 双路FTS5搜索 (cells_fts + report_names_fts)，去重，JSON输出

---

## 六、完成 — Phase 8: runner.py CLI 集成

### 8.1 `scripts/runner.py` 子命令

| 子命令 | 功能 | 状态 |
|--------|------|------|
| `query <text>` | NL 查询（默认） | ✅ |
| `discover` | 发现全部报表 → manifest.json | ✅ |
| `download [--all] [--folder NAME] [--extype ...]` | 批量下载 | ✅ |
| `index [--full] [--root DIR]` | 构建全文索引 | ✅ |
| `search <keywords>` | 搜索任意指标 | ✅ |

---

## 七、依赖关系 & 建议实施顺序

```
Phase 6 (download/)
  6.2 auth.py          ← 无依赖，先做
  6.3 discover.py      ← 依赖 auth.py
  6.4 batch.py         ← 依赖 opm_batch_acp.ps1（外部，已存在）

Phase 7 (search/)
  7.2 db.py            ← 无依赖，先做
  7.3 normalizer.py    ← 无依赖，先做
  7.4 parsers.py       ← 依赖 normalizer.py
  7.5 indexer.py       ← 依赖 db + parsers + normalizer
  7.6 searcher.py      ← 依赖 db

Phase 8 (runner.py)
  8.1 CLI 集成         ← 依赖 Phase 6 + 7
```

**推荐实施顺序：**
1. `auth.py` + `db.py` + `normalizer.py` (无依赖，可并行)
2. `discover.py` + `parsers.py`
3. `indexer.py` + `searcher.py` + `batch.py`
4. `runner.py` CLI 集成

---

## 八、环境依赖

| 依赖 | 用途 | 状态 |
|------|------|------|
| Python 3.10+ / openpyxl / pandas / pyyaml | requirements.txt | ✅ (stdlib urllib 替代 requests) |
| Node.js | 运行 extract_edge_auth.js 提取浏览器 cookie | ⚠️ 仅 Windows + CDP 模式需要 |
| CDP 浏览器 (Edge/Chromium) | 认证提取 (端口 9222) | 需用户启动 |
| OPM 登录态 | FineReport 平台访问 | 需用户在浏览器中登录 |

> **Linux 兼容性：** 下载管线 (discover/export/batch) 全部使用 Python stdlib，跨平台。
> 仅 `extract_edge_auth.js` 依赖 Node.js + CDP 浏览器提取认证 cookie ——
> 如果环境变量 `FR_AUTH_TOKEN` 已设置或 Cookie 通过其他方式注入，可跳过此步骤。

---

## 九、关键文件路径速查

| 文件 | 路径 |
|------|------|
| 本工程根目录 | `./` (项目目录) |
| CLI 入口 | `scripts/runner.py` |
| 下载管线 | `scripts/download/` (auth, discover, exporter, batch) |
| 搜索管线 | `scripts/search/` (db, normalizer, parsers, indexer, searcher) |
| 认证提取 | `fr_batch/extract_edge_auth.js` |
| 报表镜像 | `./fr_mirror/` |
| manifest | `./fr_mirror/manifest.json` |
| 索引库 | `./fr_mirror/search_index/excel_index.db` |

**所有路径均支持环境变量覆盖：**
```
FR_MIRROR_ROOT    → 报表镜像根目录
FR_BATCH_ROOT     → batch 工具目录
FR_BASE_URL       → FineReport 平台地址
FR_CDP_URL        → CDP 浏览器地址
```

---

## 十、完成度追踪

| Phase | 描述 | 状态 |
|-------|------|------|
| Phase 0-5 | 开源基础重构 | ✅ |
| Phase 6 | `scripts/download/` 模块 | ✅ |
| Phase 7 | `scripts/search/` 模块 | ✅ |
| Phase 8 | `runner.py` CLI 集成 | ✅ |
| Phase 9a | PowerShell→Python 重写（HTTP 层） | ⚠️ 不可行 — Python urllib 与 FineReport CAS 认证不兼容 |
| Phase 9b | Playwright 导出管线保留 | ✅ check_register + generic + component 三类导出均验证可用 |
| Phase 9c | 路径整合 | ✅ opm_mirror → fr_mirror 全量迁移 |
| Phase 9d | 多 Sheet 修复 | ✅ 16/16 恢复，Sheet 数从数百降至个位数 |
