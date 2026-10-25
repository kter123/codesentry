# 新 Agent 与现有管理面嵌合设计

- 日期：2026-10-25
- 目标：Supervisor / Verification 不成为“体外循环”的新节点，而是纳入 Agent 配置、Prompt、LLM、能力矩阵、Skills、树/事件体系。

## 1. 新增 Agent

| Agent | 角色 | 默认模型 | 能力 | 说明 |
|---|---|---|---|---|
| `supervisor` | 编排 | fast | 无网络/无 shell | 白名单动作调度；确定性兜底 |
| `verification` | Harness 验证 | deep | 无网络/无 shell | 生成 harness、调用沙箱、写 verification_runs |

保留原有：recon、scan、audit、triage、deploy、poc_gen、report。

## 2. 管理面嵌合

- `AGENT_NAMES` 加入 supervisor/verification。
- `AGENT_DEFAULTS` 增加配置；`ensure_agent_configs` 自动插入行。
- `SEED_PROMPTS`/`INVARIANT_TAILS`/`_AGENT_TABLE` 增加种子与固定安全尾。
- Prompt 管理、Agent 详情、Preset、Skills 分配、A/B 自动生效。
- `run_supervisor` 接受 runtime；记录 prompt 快照/告警；禁用时仍可确定性兜底。
- `verify_finding` 使用 `prepare_agent("verification")`，生成 harness 时注入其 system prompt。
- `NODE_SPECS` 增加 supervisor/verification 描述（运行图仍以 supervisor 节点 + harness API 为入口）。

## 3. Agent 树

层级：

```text
scan:<scan_id>
  ├─ group:prepare   (recon, graph_build)
  ├─ group:engine    (scan, path_build)
  ├─ group:orchestrate (supervisor)
  ├─ group:audit     (audit_plan, audit_path, audit_collect, audit_finalize)
  ├─ group:decision  (triage)
  ├─ group:deliver   (deploy, poc_gen)
  └─ group:report    (report)
```

- `node_run` 自动 upsert root/group/node。
- `agent_nodes.parent_key` 表达层级。
- 工作台按 parent/depth 渲染缩进。
- 保持 `node_runs` 作为执行事实，`agent_nodes` 用于树展示。

## 4. Harness 运行时

- 按语言选择镜像：
  - python / javascript / php / java / go / ruby / shell
- 配置：`HARNESS_IMAGE` 为默认兜底；`HARNESS_PYTHON_IMAGE` 等覆盖。
- 每种语言固定执行命令；无镜像/运行时返回 `environment_error`，不伪报 verified。
- 统一 Dockerfile 仍保留，作为可选一体镜像。

## 5. 验收

- `/api/agents` 返回 9 个 Agent；UI 可配置 supervisor/verification。
- Prompt 管理可创建 supervisor/verification 版本。
- Agent 树 API 返回 root/group/node 层级；工作台缩进展示。
- Harness 对 Python 真实验证；其他语言按镜像可用性返回明确结果。
- 全量测试/构建/Playwright 通过。
