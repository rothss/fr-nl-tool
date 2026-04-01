# OPM NL Query Tests

运行方式：

```powershell
python -m unittest discover -s C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\tests -p "test_*.py" -v
```

当前测试分两类：

- `query_intent_cases.json`：自然语言解析回归用例。新增业务问法时，优先先把用例录入这里。
- `test_component_url_registry.py`：组件 URL 绑定和参数渲染的单元测试。

## 如何新增测试用例

编辑 `query_intent_cases.json`，每条用例格式如下：

```json
{
  "name": "示例名称",
  "query": "这个月的各航司净利润的同比，谁表现得最差",
  "expected": {
    "metric": "净利润同比",
    "owner_scope": "all",
    "filters": {
      "compare_scope": "airline_yoy",
      "extreme": "worst"
    }
  }
}
```

规则：

- `expected` 只需要填写你关心的字段，不必把完整解析结果全部写出来。
- `filters.flight_date`、`date_start`、`date_end` 这类与当前日期相关的字段会按“存在且非空”校验，避免年度变动导致测试脆弱。
- 如果要校验具体值，直接写期望字符串即可。

## 当前覆盖范围

- 状态页中已验证通过的典型问法
- `component_url_registry.yaml` 的绑定匹配与 URL 参数渲染

## 当前未覆盖

- 依赖 OPM 登录态的实时导出链路
- 依赖本地 Excel 镜像数据的端到端查询结果校验
