# Demo 平台适配指南

> 面向 `demo.finereport.com` — FineReport 官方 11.0 演示平台

## 与 OPM 平台差异

| 维度 | OPM 平台 | Demo 平台 |
|------|---------|----------|
| Base URL | `/webroot/decision` | `/decision` |
| 认证 | CAS 统一登录 | SM4 加密表单登录 |
| CPT 路径前缀 | `doc/Fdjt/...` | `reportlets/...` |
| 报表数量 | 数百个 | ~20 个内置 demo 模板 |
| Python HTTP 直连 | ❌ CAS 不兼容 | ❌ 需 SM4 加密 |
| Playwright 导出 | ✅ 通过 CDP 浏览器 | ✅ 通过 Playwright 启动浏览器 |

## 前置条件

```powershell
# 安装 Playwright 浏览器（首次使用需要）
npx playwright install chromium

# 或手动安装
playwright install chromium
```

## 快速开始

### 1. 配置

```powershell
Copy-Item .env.example .env
# 编辑 .env，设置：
#   FR_BASE_URL=https://demo.finereport.com/decision
#   FR_MIRROR_ROOT=./fr_demo
```

### 2. 发现报表

```powershell
# Demo 平台使用标准登录（非 CAS）
python -c "
from download.auth_standard import login_standard
from download.discover import build_manifest
from pathlib import Path

auth = login_standard('demo', 'demo')
manifest = build_manifest(auth=auth, base_url='https://demo.finereport.com/decision',
                          output_path=Path('./fr_demo/manifest.json'))
print('Reports found:', manifest.get('manifest',{}).get('totalReports', 0))
"
```

### 3. 下载 + 索引 + 搜索

```powershell
python scripts/runner.py download --folder demo --output ./fr_demo
python scripts/runner.py index --root ./fr_demo
python scripts/runner.py search 销售 --root ./fr_demo
```

## 认证模块

两个 auth 模块对应两种平台：

| 模块 | 适用 | 依赖 |
|------|------|------|
| `download/auth.py` | CAS 平台 (OPM) | CDP 浏览器 + extract_edge_auth.js |
| `download/auth_standard.py` | 非 CAS 平台 (Demo) | Playwright + Chromium |

`auth_standard.py` 调用 `_login_standard.mjs`：
1. Playwright 启动 headless Chromium
2. 导航到登录页，填写用户名/密码
3. 点击登录按钮
4. 登录后提取 cookie 返回给 Python

## 限制

- Demo 平台仅包含 ~20 个内置模板，报表数量远少于生产环境
- 部分 demo 报表可能使用外部数据源（demo 环境可能无法连接）
- 适用于验证项目流程，不适合作为大规模数据镜像
