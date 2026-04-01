# OPM NL Query Tests

运行方式：

```powershell
python -m unittest discover -s C:\Users\ZhuanZ\.codex\skills\opm-nl-report-query\tests -p "test_*.py" -v
```

当前测试分两类：

- `query_intent_cases.json`：自然语言解析回归用例。新增业务问法时，优先先把用例录入这里。
- `offline_query_cases.json`：基于本地镜像和目录库的离线集成用例。适合录入“应该命中哪个报表、答案里至少应包含什么”的场景。
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

编辑 `offline_query_cases.json`，每条用例格式如下：

```json
{
  "name": "示例名称",
  "query": "HU7778明天的余票",
  "user": "zhuanz",
  "expected": {
    "top_candidate.report_name": "未来航班客座率票价分析",
    "metric_column": "余票",
    "row_count_after_filter": 1,
    "answer_text_contains": [
      "HU7778",
      "余票"
    ]
  }
}
```

规则：

- 这类测试默认禁用 live export，只验证离线链路。
- 适合录入本机镜像里已经稳定存在的数据样例。
- 若本地镜像或索引库不存在，测试会自动跳过。

## 当前覆盖范围

- 状态页中已验证通过的典型问法
- `component_url_registry.yaml` 的绑定匹配与 URL 参数渲染
- 本地镜像上的离线查询回归

## 当前未覆盖

- 依赖 OPM 登录态的实时导出链路
- 依赖线上实时导出的端到端结果校验
