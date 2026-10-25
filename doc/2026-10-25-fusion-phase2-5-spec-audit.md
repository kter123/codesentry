# Fusion Phase 2–5 Spec 审计

- 结论：有条件通过；以下 10 项在 plan 中必须落实。

## 阻断项

| # | 问题 | 修订 |
|---|---|---|
| 1 | 暂停/恢复不能阻塞工作线程无限等待 | 节点边界等待最多 `pause_max_s`（默认 300s）；超时自动视为 stop，写 `scan_controls` 原因。 |
| 2 | 停止不能只写 DB，正在执行的 LLM/工具无法立即中断 | 节点边界检查 + 当前 path audit 的 60s 超时；stop 后不再认领新路径；已运行节点自然结束。 |
| 3 | SSE 不能只发内存事件，刷新后丢失 | 事件先落 `agent_events`，SSE 从 DB 回放 + 订阅新事件；以 `seq` 断点续传。 |
| 4 | 工具网关可能执行任意命令 | 工具白名单 + 固定 argv + 参数校验；不拼接 shell；Docker 优先；无网络默认。 |
| 5 | 知识包内容不可信 | 只作为 RAG 文本，不执行；导入限大小；标记 source/version；不自动生成 Prompt。 |
| 6 | 即时分析不能把任意文本当 shell | 只写临时文件/仓库目录，走正常扫描；限制大小；不执行用户代码。 |
| 7 | 证据包可能泄露密钥/路径 | 脱敏：排除 api_key/secret/password；只打包 report/findings/verification/events 摘要。 |
| 8 | Agent 树事件量过大 | 分页/limit；事件 payload 截断 8k；前端虚拟滚动/最多 1000 条。 |
| 9 | Supervisor 不能绕过路径证据直接报 finding | 动作白名单；`finish` 前必须有 candidate/path evidence；无路径时只能 triage/report。 |
| 10 | Harness 全语言镜像缺失 | 统一 `harness_image` 配置；镜像/运行时不满足时 `environment_error`，不伪造 verified。 |

## 重要项

| # | 问题 | 修订 |
|---|---|---|
| 11 | 工具输出 schema 不统一 | 统一 `{status,items,evidence,error}`；Gitleaks/OSV 等归一化。 |
| 12 | 知识包检索与现有 kb_chunks 冲突 | 知识包写入独立表，同时可索引到 kb_chunks；检索来源标记 `knowledge_pack`。 |
| 13 | HTML 报告转义 | 所有文本 HTML escape；不执行脚本；不内嵌外部资源。 |
| 14 | Dashboard 统计口径 | 使用 findings.verdict + audit_paths + verification_runs，SQL 聚合。 |
| 15 | 取消 API 权限 | `/api/scans` 写操作 analyst；admin 才能跨项目清理。 |

## 结论

按上述修订进入 plan；Phase 2 先做事件/控制/Supervisor/工作台，Phase 3–5 随后。
