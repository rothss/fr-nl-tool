# 贡献指南

感谢您对自然语言报表查询系统的关注！我们欢迎各种形式的贡献。

## 如何贡献

### 报告问题

- 使用 GitHub Issues 报告 bug
- 描述问题时请包含:
  - 操作系统和 Python 版本
  - 重现步骤
  - 期望行为 vs 实际行为
  - 错误日志（如有）

### 提交代码

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

### 代码规范

- 遵循 PEP 8 风格指南
- 添加必要的注释和文档字符串
- 为新功能添加单元测试
- 确保所有测试通过

### 测试

```bash
# 运行所有测试
python -m unittest discover -s tests -p "test_*.py" -v

# 运行特定测试
python -m unittest tests.test_config -v
```

### 提交信息规范

- `feat:` 新功能
- `fix:` 修复 bug
- `docs:` 文档更新
- `test:` 测试相关
- `refactor:` 代码重构
- `chore:` 构建/工具相关

## 开发环境设置

```bash
# 克隆仓库
git clone <repository-url>
cd opm-nl-report-query

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 复制环境变量模板
cp .env.example .env
```

## 联系

如有问题,请通过 GitHub Issues 联系。
