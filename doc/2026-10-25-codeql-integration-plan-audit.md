# CodeQL 引擎能力优化 · Plan 审计

- 对象：`doc/2026-10-25-codeql-integration-plan.md`
- 结论：**通过（4 项内联修复，3 项实现注意）**

## 已修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | cache 命中可能误用其他仓库 DB | key 用 repo sha + lang；DB 路径隔离 |
| 2 | `--overwrite` 与 cache 关系不清 | cache=false 才加 `--overwrite`；cache=true 命中跳过 create |
| 3 | build_command 在 none 模式可能误执行 | 仅 `build_mode=manual` 且命令非空时执行 |
| 4 | SARIF 路径可能和 scan 读取不一致 | 统一 `work_dir/codeql-<lang>.sarif`，scan 按该路径读取 |

## 实现注意

1. `database create` 的 `--search-path` 是否必填：本机实测传了可用；不传可能找不到 packs。
2. CodeQL `--build-mode=none` 支持的 language 有限；不支持时降级为 autobuild。
3. `resolve_codeql_config` 读 DB app_settings 不能抛异常；失败回退 env。

## 风险

- suite 名称随 packs 版本变化；默认 `*-security-extended.qls`，不存在时报错并提示可配置。
- CodeQL 扫描耗时；1800s 上限 + 失败降级。
- 真实验证需要 OSS=true；kvf 默认闭源，需合成/显式 OSS。

## 验收映射

- Task 1/2 单测；Task 3 mock；Task 4 真实 Java 小样。
- WebUI P2 不做页面，仅保留配置字段。
