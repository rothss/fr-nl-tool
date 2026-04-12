# Demo Queries

先生成最小 demo mirror：

```powershell
python scripts/create_demo_mirror.py --root examples/demo_mirror
```

然后运行以下离线示例：

```powershell
python scripts/runner.py "海口-北京首都的包干航线，近三天的票价和客座率与外航相比，有没有什么异常或者可以改进的吗" --mirror-root examples/demo_mirror --db examples/demo_mirror/search_index/report_catalog.db --user-scope examples/demo_mirror/search_index/user_scope.yaml --output-format text
```

期望结果：

1. 命中报表 `未来航班客座率票价分析`
2. 输出中包含 `海口-北京首都`
3. 输出中包含至少一条异常判断或改进建议

```powershell
python scripts/runner.py "这个月的各航司净利润的同比，谁表现得最差" --mirror-root examples/demo_mirror --db examples/demo_mirror/search_index/report_catalog.db --user-scope examples/demo_mirror/search_index/user_scope.yaml --output-format text
```

期望结果：

1. 命中报表 `航空集团经营提升分析`
2. 输出中包含 `首都航空`
3. 输出中包含 `同比`
