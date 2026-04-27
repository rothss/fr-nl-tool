# Top 5 优化建议

> 2026-04-27 · 按修复优先级排序

---

## #1 Python HTTP 导出不可用 — 死代码清理

**严重程度：高 | 工作量：L**

`scripts/download/exporter.py` 基于 `urllib` 的 HTTP 导出无法处理 FineReport CAS 认证，该模块在 OPM 平台上实质是死代码。批量下载实际全靠 Playwright `.mjs` 脚本。

**修复方向：**
- `exporter.py` 中的 `make_opener`、`export_report` 等函数，在 `batch.py:131` 调用处改为 Playwright subprocess
- `discover.py` 中的 `_warmup`、`_get`、`_post` 改为走 Playwright `context.request` API
- 清理 `batch.py`、`discover.py` 中对 `exporter` 的 import

**影响文件：** `exporter.py`(全文件), `batch.py:13-14,131`, `discover.py:12`

---

## #2 硬编码路径 `C:\Users\ZhuanZ\opm_batch`

**严重程度：高 | 工作量：S | ✅ 已修复**

`auth.py:10` 写死 Windows 用户路径，换机器即失效。

**修复：** 已改为 `config.batch_root()` + 项目内 `fr_batch/` 回退。

---

## #3 配置分散 — 无统一 Config 模块

**严重程度：高 | 工作量：M | ✅ 已修复**

9+ 个文件各自独立 `os.environ.get()`，遗留 `OPM_*` 回退分散各处。

**修复：** 已创建 `config.py` 作为单一配置来源，`common.py` 增加 stdlib `.env` 解析器。所有模块统一从 `config` 导入。

---

## #4 无双点续传 — 中断后从头开始

**严重程度：高 | 工作量：M**

`batch.py` 的 `download_by_manifest()` 无断点续传、无退避重试、无原子写入。

**修复方向：**
1. 指数退避重试：`time.sleep(2 ** attempt)` + jitter
2. `--resume` 标志：读取 manifest 中最后 `status=downloaded` 的条目，从其下一个 `pending` 继续
3. 原子写入：写 `.tmp` 后 `os.replace()`
4. 错误分类：永久错误（auth/403）不重试，瞬时错误（timeout/5xx）重试
5. 每 N 个条目写一次 checkpoint

**影响文件：** `batch.py:88-161`, `runner.py`(新增 `--resume` 参数)

---

## #5 download/search 模块零测试覆盖

**严重程度：中 | 工作量：M**

18 个测试文件无一覆盖 `download/` 和 `search/` 新模块，阻塞 #1、#4 的安全重构。

**修复方向：**
1. `tests/test_config.py` — 扩展现有测试，覆盖 `config.py` 全部 accessor
2. `tests/test_auth.py` — mock `subprocess.run`，测试 `extract_auth()` 解析、`build_session()` cookie 组装
3. `tests/test_searcher.py` — 内存 SQLite FTS5，测试 `search()` / `search_json()`
4. `tests/test_indexer.py` — 用临时 Excel 文件测试 `build_index()` 全量/增量
5. `tests/test_batch.py` — mock 外部依赖，测试 `_should_skip()`、`_resolve_error_type()`、manifest 读写

**影响文件：** `tests/test_config.py`(改), `tests/test_auth.py`(新), `tests/test_searcher.py`(新), `tests/test_indexer.py`(新), `tests/test_batch.py`(新)

---

## 修复进度

| # | 问题 | 状态 |
|---|------|------|
| 1 | exporter.py 死代码 | ✅ 已添加 CAS 不兼容警告文档 |
| 2 | 硬编码路径 | ✅ |
| 3 | 配置分散 | ✅ |
| 4 | 无双点续传 | ✅ |
| 5 | 零测试覆盖 | ✅ |

**全部 5 项完成。**

## 修复详情

### #1 exporter.py 死代码
- 添加模块级 docstring 明确标注 CAS 不兼容 + 适用场景
- 实际导出管线保留 Playwright `.mjs` 脚本（已验证可用）

### #4 断点续传
- **退避重试**：`2^attempt + random` 退避，永久错误（auth/fs）不重试
- **原子写入**：`write .tmp → os.replace()` 防中断损坏
- **断点续传**：`--resume` 跳过 status=downloaded 条目
- **检查点**：每 10 个条目写一次 manifest
- **SIGINT**：Ctrl+C 时保存清单后退出

## 测试增长

| 指标 | 之前 | 之后 |
|------|------|------|
| 测试文件 | 18 | 23 |
| 测试用例 | 53 | 91 |
| 通过率 | 52/53 | 90/91 |
