# OPM Skill 项目对比分析

## 分析目标

在 `C:\Users\ZhuanZ\.codex\skills` 目录下的所有 skill 项目中，找出**最完备**的项目，用于实现：
- 报表的批量下载到本地 Excel
- 将数据提炼到 SQLite 数据库

---

## 项目概览

| 项目 | 批量下载 | Excel处理 | SQLite | 完备度 |
|------|---------|-----------|--------|--------|
| **opm-nl-report-query** | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| opm-metric-search-autorefresh | ✅ | ✅ | ✅ | ⭐⭐⭐⭐ |
| opm-incremental-download | ✅ | ❌ | ❌ | ⭐⭐⭐ |
| opm-market-horse-checkregister-export | ✅ | ✅ | ❌ | ⭐⭐⭐ |
| excel-search-sqlite | ❌ | ✅ | ✅ | ⭐⭐⭐ |
| opm-finereport-export | ❌ | ✅ | ❌ | ⭐ |

---

## 各项目详细分析

### 1. excel-search-sqlite

- **功能**：将本地 Excel/CSV 文件索引到 SQLite，支持全文搜索
- **批量下载**：❌ 不支持（仅处理本地已有文件）
- **Excel 处理**：✅ 支持（openpyxl、xlrd 解析）
- **SQLite**：✅ 支持（FTS5 全文索引）
- **完备度**：⭐⭐⭐ 仅搜索索引，无下载能力

**评价**：适合已有 Excel 文件的索引和搜索场景，但无法从源头下载报表。

---

### 2. opm-finereport-export

- **功能**：单报表导出（浏览器内 JS 脚本）
- **批量下载**：❌ 不支持
- **Excel 处理**：✅ 支持（导出 Excel）
- **SQLite**：❌ 不支持
- **完备度**：⭐ 仅单文件导出，功能最弱

**评价**：仅适合手动导出单个报表，无自动化能力。

---

### 3. opm-incremental-download

- **功能**：增量批量下载 OPM 报表到本地
- **批量下载**：✅ 支持（按目录增量下载）
- **Excel 处理**：❌ 不处理 Excel 内容
- **SQLite**：❌ 不支持
- **完备度**：⭐⭐⭐ 仅下载，无后续处理

**评价**：适合纯下载场景，但下载后的数据处理和索引需要额外工具。

---

### 4. opm-market-horse-checkregister-export

- **功能**：特定报表（航空集团市场体系考核报表）的月度批量导出
- **批量下载**：✅ 支持（按年月批量）
- **Excel 处理**：✅ 支持（生成 Excel 文件）
- **SQLite**：❌ 不支持
- **完备度**：⭐⭐⭐ 专用场景，不通用的批量下载

**评价**：针对特定报表定制开发，通用性差。

---

### 5. opm-metric-search-autorefresh

- **功能**：搜索本地 SQLite 索引，无结果时自动增量下载并重新索引
- **批量下载**：✅ 支持（调用 opm-incremental-download）
- **Excel 处理**：✅ 支持（调用 excel-search-sqlite 索引）
- **SQLite**：✅ 支持（调用 excel-search-sqlite）
- **完备度**：⭐⭐⭐⭐ 组合技能，但无数据提炼到 SQLite 数据库的能力

**评价**：组合了下载和索引能力，但缺乏深度的数据提炼和结构化处理。

---

### 6. opm-nl-report-query（当前项目）⭐⭐⭐⭐⭐

- **功能**：自然语言查询 OPM 报表，完整链路：意图解析 → 报表匹配 → 本地/实时获取 → Excel 解析 → 结构化输出
- **批量下载**：✅ 支持（`export_report_generic_live.mjs`、`export_components_and_index.py`）
- **Excel 处理**：✅ 支持（`extract_structured_table.py`、`build_report_catalog.py`）
- **SQLite**：✅ 支持（`build_report_catalog.py` 创建 catalog 数据库，`excel_index_candidates.py`）
- **完备度**：⭐⭐⭐⭐⭐ **最完备**

**核心能力**：
1. **完整的批量下载能力**：
   - `export_report_generic_live.mjs` - 通用报表实时导出
   - `export_components_and_index.py` - 组件批量导出并索引
   - `export_report_live.ps1` - PowerShell 增量刷新脚本
   - `export_future_kzl_live.mjs` - 特定报表快速导出

2. **完整的 Excel 处理**：
   - `extract_structured_table.py` - 结构化表格提取（支持多表头、跨页合并）
   - `build_report_catalog.py` - 构建报表目录（扫描所有 Excel，提取表头）
   - `extract_single_margin.py` / `extract_adjusted_profit_overview.py` - 特定报表提取

3. **完整的 SQLite 支持**：
   - `build_report_catalog.py` - 创建 `report_catalog.db`（含 FTS5 全文搜索）
   - `excel_index_candidates.py` - Excel 内容索引查询
   - `report_profiles.py` - 报表画像数据库

4. **架构优势**：
   - 30+ 脚本文件，分层架构（adapters/analysis/data/planning/render）
   - 完整的测试覆盖（20+ 测试文件）
   - 自然语言查询能力（意图解析 → 报表匹配 → 数据提取）

---

### 7. opm-nl-report-query_backup_20260331_01

- **功能**：opm-nl-report-query 的早期备份版本
- **批量下载**：✅ 支持（基础版）
- **Excel 处理**：✅ 支持（基础版）
- **SQLite**：✅ 支持（基础版）
- **完备度**：⭐⭐⭐⭐ 当前项目的旧版本，功能较少

**评价**：当前项目的旧版本，功能不如最新版完备。

---

## 结论

### 🏆 最完备的项目：**opm-nl-report-query（当前项目）**

**推荐理由**：

1. **端到端完整链路**：从报表下载 → Excel 处理 → SQLite 索引 → 自然语言查询，形成完整闭环
2. **批量下载能力强**：支持通用导出、组件导出、增量刷新等多种模式
3. **Excel 处理深入**：不仅下载，还能结构化提取、多表头处理、跨页合并
4. **SQLite 集成完善**：自动构建目录数据库、全文搜索、内容索引
5. **架构最先进**：分层设计、模块化、可扩展、有完整测试

---

## 快速使用指南

### 1. 构建报表目录（扫描本地 Excel 到 SQLite）

```powershell
python scripts/build_report_catalog.py
```

### 2. 批量导出组件并更新索引

```powershell
python scripts/export_components_and_index.py --report-path "doc/Fdjt/xxx.frm"
```

### 3. 实时导出特定报表

```powershell
node scripts/export_report_generic_live.mjs \
  --report-path "doc/Fdjt/xxx.cpt" \
  --output-file "output.xlsx"
```

### 4. 自然语言查询

```powershell
python scripts/runner.py "海口到北京的客座率" --output-format json
```

---

## 项目结构

```
opm-nl-report-query/
├── scripts/                    # 核心脚本
│   ├── runner.py              # 主入口（OpenClaw 调用）
│   ├── query_fr_nl.py         # 查询执行引擎
│   ├── build_report_catalog.py    # 构建报表目录 → SQLite
│   ├── extract_structured_table.py # Excel 结构化提取
│   ├── export_report_generic_live.mjs  # 通用报表导出
│   ├── export_components_and_index.py  # 组件批量导出
│   ├── intent/                # 意图解析层
│   ├── planning/              # 查询规划层
│   ├── data/                  # 数据管理层
│   ├── analysis/              # 分析引擎层
│   ├── render/                # 渲染层
│   ├── adapters/              # 适配器层
│   └── profiles/              # Profile 层
├── tests/                     # 测试目录（20+ 测试文件）
├── references/                # 配置文件
├── examples/                  # 示例数据
└── README.md                  # 项目说明
```

---

*分析时间：2026-04-24*
