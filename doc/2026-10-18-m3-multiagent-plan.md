# CodeSentry M3（多 agent 流水线）实现计划 = Spec v1.0

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）跟踪。
>
> - **spec 审计结论（§0 第 3 步）：** 已审计（2026-10-18）。对照 agent.md v1.4 §7（AuditState/Agent 职责/路由/预算/持久化/遥测）+ §9 M3（LangGraph 全链路 + checkpointer + 预算守卫 + 遥测直写 node_runs + Prompt/Skill 注入与版本快照 + 人工复核中断 + 增量审计 diff 可达闭包 + PoCGenAgent）：全覆盖；增量审计 FR-10 在 M3 交付；LLM 调用按 D5 OpenAI 兼容抽象（用户自配，平台不预置；测试用录制回放 mock——§10）。数值逐条照抄；无越界（WebUI 留 M5）。**审计结论：通过。**
> - **需求源：** 根目录 `agent.md` v1.4

**目标：** LangGraph 中心化多 agent 全链路（Supervisor + 6 专家节点 + AuditState 共享态）+ 预算守卫熔断 + 节点遥测直写 `node_runs` + Prompt/Skill 注入与版本快照 + 人工复核中断（HUMAN_REVIEW）+ 增量审计（`codesentry diff`，本地 git diff 可达闭包）+ PoCGenAgent（生成利用链路 + 分级 PoC + `POC_RUN` 三档判定）。

**架构：** LangGraph StateGraph 编排，`AuditState` TypedDict 共享态；主链路确定性 `recon → scan → (retrieval → triage → poc_gen[有保留 finding]) × N → report`；Supervisor 仅在三类异常点介入（证据不足补查 / 引擎冲突 / agent 失败重规划），受预算守卫约束；`PostgresSaver` checkpoint（langgraph schema）；节点结束时写 `node_runs`（§7.3）；Prompt 从 `prompt_versions` 活跃版本加载，缺回退代码内种子并告警；Skill 从 `skills`/`skill_versions` 加载按 agent 分配，注入 system 上下文（生效 Prompt 后），8K/32K 上限截断（D33/D34）；扫描快照 prompt/skill 版本体进 `scans`（NFR-2）；LLM 客户端 OpenAI 兼容（D5），温度 0（D14）。

**技术栈：** langgraph / langchain-core / psycopg / pydantic v2 / typer；测试 LLM 全 mock（录制回放——§10），checkpointer 用本机 codesentry-db。

---

## 全局约束（自 agent.md 逐条）

- **编排中心化**（D4/§6)：agents 无自主路由，仅接收 Supervisor 指令、读写共享 AuditState；无点对点 handoff；主链路确定性
- AuditState 字段（§7.1）：`repo_path/license_declaration/diff_scope/profile/engine_findings/triaged_findings/evidence/poc_results/budget/prompt_versions/skills_snapshot/phase/messages`
- 预算守卫（D14）：MAX_TOKENS=500000 / MAX_TOOL_CALLS=500 / MAX_COST_USD=10 / MAX_FINDINGS=200；达 80% 预警、100% 熔断进报告；台账写 `budget_ledger`；env 覆写
- LLM 失败：指数退避重试 3 次，仍失败该 finding 标「未验证」保留引擎原始结论（§10）
- PoC（D27–D32，FR-13/FR-14）：`POC_RUN=off`（默认）→ 全部 finding 最高 plausible；sandbox=target 双重授权；危险 payload 静态检查拒（rm 类/反弹 shell 模板）；生成失败 → 保留 finding 标 plausible 注原因；试跑失败 ≠ false_positive
- Skill 注入（D34）：单 Skill ≤ 8192 token、单 agent ≤ 32768 token；超限告警截断；env 可调
- Prompt 版本（D33/§10）：DB 生效源；缺失/损坏回退种子 + 告警（WebUI 标红留 M5 接口）
- HUMAN_REVIEW=true（FR-9/D14 默认关）：report 前 interrupt；恢复由 WebUI 复核队列触发（CLI 扫描同入队列）
- 增量审计（FR-10）：`diff <base>...<head>` 只审计变更代码及其可达链路；可 CI/CD（退出码+SARIF 产物）
- NFR-2 可复现：prompt/skill version 快照落 scans；温度 0
- 遥测（D22）：每节点起止/耗时/token/工具调用/状态写 node_runs；不引入消息队列

## 审查重点（Review Focus）

1. **Supervisor 无限循环**——重规划必须带 max_steps 上限（默认 3 次重规划后熔断进报告）+ 预算守卫双保险
2. **checkpointer save UUID 泄漏重复**——线程 id/scan_id 唯一；scan 中断重入不得串号
3. **PoC 危险 payload 绕过静态检查**——检查在**执行前**强制（rm/rm -rf/sudo 类命令、反弹 shell 样式、DNS 出网模板），命中拒绝并标 rejecting reason
4. **Prompt 注入的 skill 正文逃逸 system 边界**——skill 拼接固定于「生效 Prompt 之后、用户输入之前」，分隔符不可为空；截断要有「截断告警」落 messages
5. **增量 diff 范围误扩至不可达文件**——可达闭包算法显式「从 diff 文件出发沿调用图索取」而非「全仓扫描后交集」，测试钉闭包边界

---

## 文件结构

```
src/codesentry/
├── agents/
│   ├── __init__.py
│   ├── state.py             # AuditState TypedDict + 常量
│   ├── llm.py               # OpenAI 兼容 LLM 客户端（退避重试×3）
│   ├── prompts.py           # 种子 prompt + 从 DB 加载生效版本回退
│   ├── skills.py            # SKILL.md 解析/加载/截断（8K/32K）
│   ├── ground.py            # 通用 agent 节点工具（遥测 hook、预算记账）
│   ├── recon.py             # ReconAgent（profile + diff 可达闭包）
│   ├── scan.py              # ScanAgent（调度复用 M1 引擎层）
│   ├── retrieval.py         # RetrievalAgent（M2 检索 API）
│   ├── triage.py            # TriageAgent（LLM 验证降噪 + vuln_cases 位置预留）
│   ├── poc_gen.py           # PoCGenAgent
│   └── report.py            # ReportAgent（M1 报告层 + 修复建议由 triage 携带）
├── orchestrator/
│   ├── graph.py             # StateGraph 构建（langgraph 引入点）
│   ├── budget.py            # 预算守卫（计数/预警/熔断/落账）
│   ├── telemetry.py         # node_runs 写入
│   └── human_review.py      # interrupt + 恢复
├── cli_commands.py          # diff/agents/skills 命令接真
└── tests/…
```

---

### 任务 1：AuditState + LLM 客户端（TDD）

- [ ] `AuditState` TypedDict 精确字段 + 默认构造；LLM `complete(prompt, model_role)` OpenAI 兼容调用温度 0、指数退避×3 后抛错；mock 测试
- [ ] `feat(m3): AuditState + OpenAI-compatible LLM client with backoff (D5, D14, §7)`

### 任务 2：预算守卫（TDD）

- [ ] `BudgetGuard`：计数 tokens/tool_calls/cost；`check()` → ok|warn|breach；`record()` 落 budget_ledger；`MAX_FINDINGS` 超限时 triage 按置信度截尾；预警 80% / 熔断 100% 状态在 AuditState.phase
- [ ] `feat(m3): budget guard with warn/meltdown + ledger (D14, §7.3)`

### 任务 3：遥测 hook（TDD）

- [ ] `node_runs` 写入函数（起止/耗时/tokens/tool_calls/status/error）；graph 每个 wrapper 记录；测试直查 DB（skip-if-no-db）
- [ ] `feat(m3): node telemetry direct-to-DB (D22)`

### 任务 4：Prompt 加载 + Skill 注入（TDD）

- [ ] 种子 prompt 常量（六 agent 各一段极简正体）；`load_prompt(agent)` DB 活跃 → 缺失回退种子+警告标记；`load_skills(agent, override)` 按 skill_assignments 默认集 ⊕ 扫描覆写；`build_system(prompt, skills)` 拼接 + SKILL body 截断（超限告警）；SKILL.md 解析（frontmatter+正文+参考文件引用渐进披露——M3 保存正文与引用清单，不解析执行）
- [ ] `feat(m3): prompt versioned loader with seed fallback + skill injection caps (D33, D34)`

### 任务 5：核心 agent 节点（TDD，LLM mock）

- [ ] ReconAgent：M1 recon 深化 + framework 检测 + entry_points；diff_mode 时产出「diff 可达闭包」（调用图 BFS 从 diff 文件出发展开到 sink 的闭包——本地 python 调用图 BlAME 用 tree-sitter 提取）
- [ ] ScanAgent：LicenseGate + M1 select/run_engines + 归一 findings
- [ ] RetrievalAgent：M2 hybrid_search 取 code/kb evidence
- [ ] TriageAgent：LLM 验证（保留/降级/否决 + 置信度 + 证据链述 + 修复建议），失败标「未验证」
- [ ] ReportAgent：M1 报告 + 修复建议 + meta（license/diff scope/prompt+skill 快照）
- [ ] `feat(m3): six agent nodes (deterministic, Supervisor-guided) (§7.2)`

### 任务 6：PoCGenAgent（TDD，mock LLM + sandbox 静检）

- [ ] 分级 PoC：HTTP 类 → request 序列（curl 脚本模板）+ 本地类 → payload/注入点/本地调用 PoC；`POC_RUN` off/sandbox/target；off→plausible；sandbox 静态检查危险模式拒；执行日志落 poc_results；verdict 三档
- [ ] `feat(m3): PoCGenAgent — exploit chain + tiered PoC + POC_RUN gating (FR-13/FR-14, D27-D32)`

### 任务 7：LangGraph 组装 + checkpointer（TDD）

- [ ] StateGraph 构建：主链确定性 edges；Supervisor 条件边（triage 报「证据不足」→ 补查一次；引擎冲突 → supervisor 决策；失败 → 重规划 max 3）；PostgresSaver（langgraph schema）；scan_id 线程唯一
- [ ] `feat(m3): LangGraph graph assembly + PostgresSaver checkpoint (D4, §7.3)`

### 任务 8：人工复核中断（TDD）

- [ ] HUMAN_REVIEW=true → report 前 `interrupt`；恢复入口 `resume(scan_id, decisions)`；CLI 扫描同进队列；测试 interrupt 状态 + 决策应用后恢复
- [ ] `feat(m3): human-review interrupt + WebUI-ready resume (FR-9, D20)`

### 任务 9：CLI diff/agents/skills 接真（TDD）

- [ ] `codesentry diff <repo> <base>...<head>`：git diff 文件表 → 可达闭包 → 走同 graph（mode=diff）→ 报告 + SARIF + 退出码（CI 可用：有 high+ confidence≥0.7 → exit 1）
- [ ] `codesentry agents list`：DB agent_configs 列表（种子同步）
- [ ] `codesentry skills list|upload|enable`：SKILL.md 上传（frontmatter 校验 + 超限拒绝）、启停
- [ ] `feat(m3): diff/agents/skills CLI commands wired (FR-10, FR-12)`

### 任务 10：收尾

- [ ] ruff/mypy/pytest 全量；端到端真跑（本机库 + mock LLM）；deps license 记录更新；验收回填
- [ ] `chore(m3): acceptance — full pipeline green`

---

## 任务依赖

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10（流水线节点间依赖深，串行为主；任务 5 内部 6 agent 可拆并发）。
