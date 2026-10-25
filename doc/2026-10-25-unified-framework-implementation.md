# 统一框架 Phase 2–5 实现记录

- 日期：2026-10-25
- Spec：`doc/2026-10-25-unified-framework-spec.md`
- Plan：`doc/2026-10-25-unified-framework-plan.md`

## 已完成

### Phase 2：Supervisor + 事件流 + 工作台

- Supervisor 节点：`audit_paths / audit_repo / triage / report` 白名单动作，预算/轮次/候选决策写 `agent_events`。
- 图改造：`path_build → supervisor → audit_plan / audit_finalize / triage / report`；`audit_collect → supervisor`。
- `agent_events`：seq 连续、持久化、SSE 回放。
- `agent_nodes` + node_runs 回退：Agent 树。
- `scan_controls`：暂停/恢复/停止；节点边界检查；stop 标记 `stopped`。
- API：events/SSE/agent-tree/pause/resume/stop。
- Vue3 审计工作台：Agent 树、事件流、上下文、路径/Findings/验证/工具/报告；暂停/停止；图/报告入口。

### 新 Agent 管理嵌合

- `supervisor` / `verification` 已加入 `AGENT_NAMES`、Agent 默认配置、Prompt 种子/固定尾、Registry、Preset/Skills/LLM 绑定。
- Verification 使用自己的 Agent 配置生成 Harness。
- Agent 树按 `scan → group → node` 层级生成并在工作台缩进展示。

### Phase 3：Harness 全语言 + 工具网关

- Harness 模板：CWE-78/89/79/22/94/95/502/918/611/1333 + payload 组。
- Harness 语言命令：Python/JS/PHP/Java/Go/Ruby/Shell。
- `extract_function` API：按 scan/file/line 提取函数源码。
- 工具网关：Gitleaks/Bandit/OSV/npm audit/Safety；固定 argv、超时、网络开关、缺工具降级。
- `tool_runs` + 事件 + 工作台工具证据 tab。
- 工具结果只作证据，不直接进入 findings。

### Phase 4：知识包

- `knowledge_packs` 表；框架包（Flask/FastAPI/Django/Express/Spring）+ 漏洞包（SQLi/命令注入/路径遍历/SSRF/反序列化）。
- 内置包 seed、CRUD、启停、版本、检索加权（语言/框架/CWE）。
- `kb_search` 合并知识包结果，带 `pack:name@v` 来源。
- 知识库 UI 增加知识包列表/新增/启停。

### Phase 5：产品化

- 即时分析 API/UI：粘贴代码写入临时仓库，走完整扫描链路，跳转工作台。
- Dashboard API：scans/findings/verdict/paths/verified/tokens/tools。
- HTML 报告端点（escape）。
- 证据包 zip：findings/verifications/events/report，不含源码/密钥。
- 工作台报告 tab 提供 HTML/证据包入口。

## 质量门禁

- `pytest`：**386 passed, 2 skipped, 1 xfailed**
- `ruff`：通过
- `mypy`：122 source files，无问题
- 前端 `npm run build`：通过
- Playwright：**21/21** 路由通过（含工作台、即时分析、路径抽屉）
- 统一框架 Java 合成链路：scan `1730` `done`，4 findings、10 paths、49 agent_events、19 agent_nodes；证明 Supervisor/事件/实时 finding 在主链生效。

## 未完成/限制

- Harness 全语言已通过按语言镜像验证：Python/JavaScript/PHP/Ruby/Go/Java/Shell 均返回 `HARNESS_VERIFIED`；统一 `docker/harness/Dockerfile` 保留为可选一体镜像。
- 工具网关：Bandit/Safety 已安装；Gitleaks/OSV 未安装时返回 `unavailable`，不阻断扫描。
- `agent_nodes` 已按 `scan → group → node` 生成层级；工作台按 parent/depth 缩进展示。
- 暂停只在节点边界生效；长 LLM 节点需等当前节点结束。
- JVWA 全量扫描尝试在 CodeQL Java 建库阶段长时间无进展后停止；改用小 Java 合成项目完成统一链路验证。kvf ready 仍未执行。
- 全量事件回放 UI 是轮询/SSE 增量，未做时间轴拖拽。
