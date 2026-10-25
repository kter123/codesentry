# 统一框架 Review 1（正确性）

| # | 问题 | 修复 |
|---|---|---|
| 1 | Supervisor 初版在无候选时直接 report，绕过 Triage | 增加“空 Triage 收敛”一次，避免旧测试/人工复核链断裂 |
| 2 | 旧 `retrieval_agent` 测试参数被忽略导致流程不触发 | Supervisor 在无路径时走 audit_repo → triage，恢复旧链语义 |
| 3 | `agent_events.seq` 并发重复 | `UNIQUE(scan_id,seq)` + advisory xact lock |
| 4 | 事件写库失败会阻塞节点 | 写库失败仅降级为内存广播 |
| 5 | pause/stop 可能无限等待 | `pause_max_s` 超时自动 stop；节点边界检查 |
| 6 | `audit_events` 重复 node.start/end | 以 `agent_key=node:started_at` 去重 |
| 7 | Harness `template_for` 命名不一致 | 统一 `for_cwe` |
| 8 | Tool 网关参数可能非字符串 | argv 全部强制 str；固定 argv，无 shell |
| 9 | 知识包 `seed_builtins` 类型错误 | 显式 str/int 转换 |
| 10 | 工作台扫描选择可能指向测试临时仓库 | UI smoke 选择 work 根内扫描 |

## 验证

- 386 tests passed；6 个旧 graph 测试恢复。
- Playwright 21/21。
- 真实 Python Harness 仍可 `HARNESS_VERIFIED`。

## 结论

正确性阻断项已修复；Agent 树层级/事件回放为后续增强。
