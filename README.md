# 自然语言报表查询系统

基于 OpenClaw Skill 架构的自然语言报表查询系统,支持 FineReport 报表的智能检索与分析。

## 快速开始

### 1. 环境配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件,配置以下关键变量:
# FR_BASE_URL=http://your-fine-report-server:8080
# FR_MIRROR_ROOT=./fr_mirror
# FR_CDP_URL=http://localhost:9222
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 构建报表目录

```bash
python scripts/build_report_catalog.py
```

### 4. 运行查询

```bash
python scripts/runner.py "海口到北京的客座率" --output-format json
```

## 项目结构

```
.
├── scripts/           # 核心脚本
│   ├── runner.py     # 主入口
│   ├── query_opm_nl.py  # 查询执行
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
