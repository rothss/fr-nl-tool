# FineReport NL Query Skill (OPM Example)

一个基于 OpenClaw Skill 架构的 FineReport 自然语言查询参考实现，当前仓库内置 OPM 场景示例。

## 项目状态

1. 支持离线查询主链路：意图解析、报表候选排序、结构化结果输出。
2. 支持可选 live refresh / 组件抓取，但这些能力依赖额外 FineReport 环境和外部工具。
3. 当前更适合作为参考实现或示例 skill，而不是开箱即用的通用公共 skill。

## 快速开始

### 1. 环境配置

```powershell
Copy-Item .env.example .env

# 编辑 .env 文件,配置以下关键变量:
# FR_BASE_URL=http://your-fine-report-server:8080
# FR_MIRROR_ROOT=./fr_mirror
# FR_CDP_URL=http://localhost:9222
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

### 3. 构建报表目录

```powershell
python scripts/build_report_catalog.py
```

### 4. 运行查询

```powershell
python scripts/runner.py "海口到北京的客座率" --output-format json
```

## 运行边界

1. `scripts/runner.py` 是唯一稳定入口，返回 OpenClaw 可消费的结构化 JSON。
2. 离线链路依赖你已经准备好的本地镜像、catalog 和可选的 user scope。
3. live refresh、组件抓取、增量索引都属于可选增强能力，不是默认前提。
4. 未配置外部工具时，仓库应仍可运行基础离线查询和绝大多数单元测试。

## 架构分层

1. 通用运行层：`scripts/runner.py`、`scripts/planning/`、`scripts/data/`、`scripts/render/`
2. 示例 profile 层：`scripts/profiles/opm_example.py`
3. 示例配置层：`references/`
4. 公开 demo 层：`examples/` 和 `scripts/create_demo_mirror.py`

## Demo 快速体验

```powershell
python scripts/create_demo_mirror.py --root examples/demo_mirror
python scripts/runner.py "海口-北京首都的包干航线，近三天的票价和客座率与外航相比，有没有什么异常或者可以改进的吗" --mirror-root examples/demo_mirror --db examples/demo_mirror/search_index/report_catalog.db --user-scope examples/demo_mirror/search_index/user_scope.yaml --output-format text
```

更多可运行示例见 `examples/demo_queries.md`。

## 项目结构

```
.
├── scripts/           # 核心脚本
│   ├── runner.py     # 主入口
│   ├── query_fr_nl.py  # 查询执行
│   └── analysis/     # 分析引擎
├── references/       # 配置文件
│   ├── synonyms.yaml # 同义词映射
│   ├── report_schemas.yaml  # 报表结构定义
│   └── component_url_registry.yaml  # 组件URL注册
├── tests/           # 测试用例
└── .github/workflows/  # CI/CD配置
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| FR_BASE_URL | FineReport服务器地址 | - |
| FR_MIRROR_ROOT | 本地镜像根目录 | ./fr_mirror |
| FR_CDP_URL | Chrome DevTools地址 | - |
| FR_AUTH_TOKEN | 认证Token | - |
| FR_INTENT_LLM_COMMAND | LLM解析命令 | - |
| FR_BUILD_INDEX_PY | 可选外部索引构建脚本 | - |
| FR_REFRESH_TOOL_ROOT | 可选 live refresh 工具根目录 | - |

## 必需依赖与可选依赖

必需依赖：

1. Python 3.10+
2. `requirements.txt` 中的 Python 包
3. 本地 FineReport 镜像数据，或你自行准备的等价 demo 数据

可选依赖：

1. `FR_BUILD_INDEX_PY`：用于增量重建 Excel 索引
2. `FR_REFRESH_TOOL_ROOT`：用于 live refresh 下载链路
3. 浏览器 CDP 和登录态：用于自动化导出类脚本

## 开发

```bash
# 运行测试
python -m unittest discover -s tests -p "test_*.py" -v

# 代码检查
flake8 scripts tests
black --check scripts tests
```

## License

MIT License - 详见 LICENSE 文件

## 致谢

本项目基于 OpenClaw Skill 架构开发,感谢 Claude Code 和 OpenClaw 团队的支持。
