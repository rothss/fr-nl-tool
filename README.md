# FineReport NL Query Skill (FR Example)

全量下载帆软平台报表到本地，支持全局搜索指标所在的报表，并通过自然语言进行查询。

## 亮点

| 能力 | 说明 |
|------|------|
| **平台全量下载** | discover 发现全部报表树 → batch 批量导出为 xlsx，支持断点续传、指数退避重试 |
| **任意指标搜索** | SQLite FTS5 单元格级全文索引，输入任意中文指标名即可定位其所在的报表、Sheet、行列 |
| **自然语言查询** | "上海市场最新的总收入" → 意图解析 → 报表匹配 → 数据提取 → 结构化回答 |
| **多格式解析** | xlsx / xls / csv 全覆盖，openpyxl 主解析 + XML 回退，合并单元格自动回填 |
| **模块化架构** | 11 个 ≤150 行 Python 模块，单一职责，零循环依赖 |
| **退避重试 + 断点续传** | 下载中断后 `--resume` 跳过已完成条目，永久错误不重试，瞬时错误指数退避 |
| **自包含部署** | `.env` → `config.py` 单一配置源，`fr_mirror/` 项目内存储，无需外部路径依赖 |

## 项目状态

- ✅ NL 查询：意图解析 → 候选排序 → 数据提取 → 分析 → 渲染
- ✅ 全量下载：discover → manifest → batch export（Playwright check_register / generic）
- ✅ 任意指标搜索：SQLite FTS5 单元格级全文索引
- ⚠ 下载依赖 Playwright + CDP 浏览器（Python urllib 不兼容 FineReport CAS 认证）
- 91 个测试，91 通过

## 快速开始

```powershell
# 1. 配置
Copy-Item .env.example .env
pip install -r requirements.txt

# 2. 发现平台全部报表
python scripts/runner.py discover

# 3. 下载指定目录（需 CDP 浏览器登录 OPM）
python scripts/runner.py download --folder 销售指标

# 4. 构建全文索引
python scripts/runner.py index

# 5. 搜索任意指标
python scripts/runner.py search 总成本

# 6. 自然语言查询
python scripts/runner.py "总收入" --output-format json
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `runner.py query <text>` | 自然语言 KPI 查询（默认） |
| `runner.py discover` | 发现平台全部报表 → manifest.json |
| `runner.py download --all / --folder NAME` | 批量下载 |
| `runner.py index [--full]` | 构建/更新全文索引 |
| `runner.py search <keywords>` | 搜索任意指标 |

## 项目结构

```
scripts/
├── runner.py           CLI 统一入口
├── config.py           配置单一来源（.env → FR_* 变量）
├── common.py           stdlib .env 解析 + 工具函数
├── download/           下载管线
│   ├── auth.py         CAS 认证 (CDP 浏览器)
│   ├── auth_standard.py  标准登录 (Playwright, demo 平台)
│   ├── discover.py     FineReport 报表树发现
│   ├── exporter.py     Python HTTP 导出（⚠ CAS 平台不可用）
│   └── batch.py        批量下载编排（退避重试 + 断点续传）
├── search/             搜索管线（纯 Python）
│   ├── db.py           SQLite FTS5 schema
│   ├── normalizer.py   数值过滤
│   ├── parsers.py      xlsx/xls/csv 解析
│   ├── indexer.py      全量/增量索引
│   └── searcher.py     FTS5 搜索
├── intent/             NL 意图解析
├── analysis/           分析引擎
├── adapters/           OpenClaw 合约适配
├── planning/           查询计划
└── render/             答案渲染
references/             配置：同义词 · 列别名 · schema · 忽略清单
tests/                  91 个测试（23 个文件）
fr_mirror/              报表镜像 + manifest + 索引库（gitignored）
```

## 运行 Demo

项目内置 FineReport 官方演示平台适配（`demo.finereport.com`），无需内网环境即可体验完整流程：

```powershell
Copy-Item .env.demo .env
npx playwright install chromium    # 首次需要
pip install -r requirements.txt
python scripts/runner.py discover  # 发现 demo 报表树
python scripts/runner.py index --root ./fr_demo
python scripts/runner.py search 销售 --root ./fr_demo
```

详见 `docs/DEMO_PLATFORM.md`。

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `FR_BASE_URL` | FineReport 地址 | `https://demo.finereport.com/decision` |
| `FR_CDP_URL` | CDP 浏览器地址 | `http://127.0.0.1:9222` |
| `FR_MIRROR_ROOT` | 报表镜像目录 | `./fr_mirror` |
| `FR_BATCH_ROOT` | batch 工具目录 | `./fr_batch` |

所有配置从 `.env` 加载（`common.py` stdlib 解析器），通过 `config.py` 统一访问。不支持直接 `os.environ.get()`。

## 前置依赖

**必需：**
- Python 3.10+ / openpyxl / pandas / pyyaml
- Node.js + Playwright（认证提取和报表导出）
- CDP 浏览器已登录 OPM（端口 9222）

**可选：**
- `FR_AUTH_TOKEN` — 跳过 CDP 认证（仅无 CAS 的环境）

## Demo 体验

```powershell
python scripts/create_demo_mirror.py --root examples/demo_mirror
python scripts/runner.py "总收入" \
  --mirror-root examples/demo_mirror --user demo_user --output-format text
```

详见 `examples/demo_queries.md`。

## 开发

```bash
# 测试
python -m unittest discover -s tests -p "test_*.py" -v

# 单文件
python -m unittest tests.test_batch -v
```

## 已知限制

- Python HTTP 导出不兼容 FineReport CAS → 下载走 Playwright `.mjs`
- 需 CDP 浏览器 → 无法纯无人值守

## License

MIT
