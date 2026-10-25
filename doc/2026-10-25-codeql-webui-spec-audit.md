# CodeQL WebUI 接入 · Spec 审计

- 对象：`doc/2026-10-25-codeql-webui-spec.md`
- 结论：**通过（4 项内联修复，3 项转 Plan）**

## 已修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | 现有 settings 只允许 llm/embedding | Plan 明确扩展 `codeql` 分组与 key 白名单 |
| 2 | test 接口可能执行任意命令 | 只跑 `version` / `resolve languages`，不跑 build_command |
| 3 | 健康检查改动会破坏现有前端字符串契约 | 保留 `engines` 字符串，新增 `engine_details` 对象 |
| 4 | 扫描详情数据来源不明 | 明确读 artifacts 的 `graph_delta.engine_graph.codeql` |

## 转 Plan

1. settings 分组扩展与 `_read_setting` 默认映射。
2. `POST /api/engines/codeql/test` 的输出解析与 10s 超时。
3. Overview/Settings 前端类型与错误态。

## 风险

| 风险 | 缓解 |
|---|---|
| 保存空值导致自动探测失效 | 空值语义=自动；GET 明确提示 |
| build_command 注入 | 仅 manual；admin 权限；UI 警告 |
| CodeQL 探测慢 | 10s 超时；失败不阻塞保存 |

## 验收可行性

- 本机 CodeQL 已实测；API/前端可自动化测试。
