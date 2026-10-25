# 统一框架 Review 2（安全/可靠性）

| # | 检查项 | 结论 |
|---|---|---|
| 1 | 交互式/反弹 shell | 未实现；Harness 输出/命令仍受危险模式与沙箱约束 |
| 2 | Harness 沙箱 | 默认 network=none、read_only、cap_drop=ALL、no-new-privileges、512MB、超时 |
| 3 | 工具网关 | 白名单、固定 argv、无 shell；网络工具默认 disabled；缺工具 unavailable |
| 4 | 知识包 | 文本只做 RAG，不执行；200KB 上限 |
| 5 | 即时分析 | 只写临时仓库并走正常扫描，不执行粘贴代码 |
| 6 | 事件 SSE | 只读事件；事件 payload 截断；认证沿用 `/api` 中间件 |
| 7 | 暂停/停止 | 节点边界；stop 后不再认领路径；不杀线程 |
| 8 | 报告/证据包 | HTML escape；证据包不含源码/env/key/secret/password |
| 9 | 权限 | `/api/scans` 控制接口归 analyst；知识包/工具归现有 admin/analyst 前缀 |
| 10 | AGPL | 仅借鉴 DeepAudit 概念，未复制代码/Prompt/规则 |

## 残余风险

- Harness 代码由 LLM 生成，沙箱能降低但不能完全消除资源/逻辑风险；输出错误会标 plausible。
- 工具二进制状态依赖宿主环境；`unavailable` 是预期降级。
- 工作台事件内存上限 2000 条，长期审计需分页/归档。
- 父子 Agent 树尚未表达 handoff 层级。

## 结论

安全边界通过；无新增反弹/远程利用/静默下载能力。
