# Release Prep

本文件用于把当前仓库发布到 GitHub 时，直接复用仓库描述、topics、release notes 和首个公开版本建议。

## 推荐公开定位

`An OpenClaw skill reference implementation for natural-language querying over FineReport-based business reports, with an OPM-focused example profile and a runnable offline demo mirror.`

对应中文：

`一个面向 FineReport 业务报表自然语言查询的 OpenClaw skill 参考实现，内置 OPM 示例 profile，并提供可运行的离线 demo mirror。`

## GitHub Repository Description

推荐英文短描述：

`OpenClaw skill for querying FineReport business reports with natural language, including an OPM example profile and offline demo.`

推荐中文短描述：

`基于 OpenClaw 的 FineReport 自然语言查询 skill，内置 OPM 示例 profile 和离线 demo。`

## GitHub Topics

推荐 topics：

1. `openclaw`
2. `skill`
3. `finereport`
4. `nl-query`
5. `reporting`
6. `analytics`
7. `python`
8. `excel`
9. `opm`
10. `llm-tools`

如果你不想强调领域属性，可去掉：

1. `opm`

## 推荐首个公开版本

建议首个公开 tag：

`v0.1.0`

原因：

1. 现在已经具备公开仓库应有的基本完整度。
2. 但仍应视为早期公开版本，而不是稳定的 `1.0`。
3. 当前更适合“参考实现 / 示例 skill”，不是完全通用化产品。

## Release Title

推荐：

`v0.1.0 - First public release`

## Release Notes

可直接用于 GitHub Release：

```markdown
## Summary

First public release of the FineReport NL Query Skill (OPM Example).

This repository provides an OpenClaw-compatible skill reference implementation for querying FineReport-based business reports with natural language. It includes an OPM-focused example profile, structured OpenClaw output, and a runnable offline demo mirror for external evaluation.

## Highlights

- Added a stable `scripts/runner.py` entrypoint for OpenClaw integration
- Cleaned up private machine paths and converted external tool dependencies into optional capabilities
- Added a runnable offline demo mirror and demo queries under `examples/`
- Split profile-specific report bindings out of the main runtime flow
- Archived historical audit HTML files under `docs/archive/`
- Expanded automated coverage for contract behavior, demo flow, and profile bindings

## Current Scope

- Offline query flow is supported when local mirror files and catalog data are available
- Live refresh and export helpers remain optional, environment-dependent capabilities
- The repository currently ships with an OPM-focused example profile

## Notes

- This release is intended as a reference implementation and reusable example skill
- It is not yet a fully generalized, zero-config FineReport skill for all organizations
```

## 建议发布顺序

1. 确认 `git status` 干净或只保留你明确要保留的设计文档改动。
2. 推送当前分支到 GitHub。
3. 设置仓库描述和 topics。
4. 打 `v0.1.0` tag。
5. 按上面的 release notes 创建首个 release。

## 建议的发布前最后检查

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
git status --short
```

## 当前已知边界

1. 当前仓库仍包含 OPM 示例 profile，不是完全去领域化实现。
2. live refresh 仍依赖外部环境和可选工具链。
3. 更适合作为公开参考实现、示例 skill 和可运行 demo，而不是“所有组织拿来即用”的最终产品。
