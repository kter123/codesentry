# Fusion Phase 2–5 Plan 审计

- 结论：通过，补 8 项执行细节。

| # | 问题 | 修订 |
|---|---|---|
| 1 | `agent_events.seq` 并发 path audit 可能重复 | 用 `scan_id+seq` 主键/唯一索引，插入冲突重试；或 PostgreSQL advisory lock per scan。 |
| 2 | SSE 长连接与测试 | 用 `StreamingResponse` + 1s 轮询；测试只校验首包和 limit，不阻塞。 |
| 3 | publish 事件写 DB 失败不能阻塞节点 | 事件写库与节点执行解耦，失败仅内存广播。 |
| 4 | Supervisor 不能成为无限循环 | 最大轮次 + budget + pending 检查；无变化时直接 triage。 |
| 5 | 工具网关 argv | 每个工具显式 argv 列表；路径参数必须在 repo 内；不允许用户传任意参数。 |
| 6 | 知识包与 kb_chunks | 知识包检索优先独立表；索引到 kb_chunks 时 source 前缀 `pack:`，避免重复。 |
| 7 | 即时分析 | 只接受 ≤200KB 文本；写 `work/instant-*`；走完整扫描；不执行代码。 |
| 8 | HTML/证据包 | HTML escape；证据包排除 `.env`、api_key、secret、password、work 源码（只放摘要）。 |

## 任务顺序

1. 事件/控制 DDL + scan_control + telemetry。
2. Supervisor。
3. 工作台。
4. Harness 模板/全语言/extract_function。
5. 工具网关 + UI。
6. 知识包。
7. 产品化 + 文档/验证。

## 风险

- 前端工作台较大，优先实现可用三栏，不做复杂动画。
- 全语言 Harness 镜像构建可能受网络限制；代码/配置先落地。
- 真实 JVWA 重扫可能耗时；先完成代码和单测，最后跑小样本。
