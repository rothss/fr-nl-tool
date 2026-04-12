# Examples

本目录放公开可复用的示例材料，不直接承诺生产可用性。

## 分层说明

1. `scripts/` 下的 `runner.py`、`planning/`、`data/`、`render/` 构成通用 skill 运行层。
2. `scripts/profiles/opm_example.py` 描述当前仓库内置的 OPM 示例 profile。
3. `references/` 中的报表 schema、组件映射和同义词属于示例配置层。
4. `scripts/create_demo_mirror.py` 用于生成最小离线 demo 数据，不依赖真实业务镜像。

## 快速体验

1. 生成 demo mirror：

```powershell
python scripts/create_demo_mirror.py --root examples/demo_mirror
```

2. 按 `examples/demo_queries.md` 里的命令运行离线示例查询。
