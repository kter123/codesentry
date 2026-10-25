# CodeSentry 全量需求清单（2026-10-25）

> 状态：✅ 完成 / 🟡 部分完成 / ⏳ 待开发 / ⛔ 明确不做
> 基线：`f3c1633`（Phase 1 fusion）之后

## 1. 原有核心需求（requirements-core A–L）

| ID | 需求 | 状态 | 说明 |
|---|---|---|---|
| A | 六语言代码图、三引擎转图、增量构建、图查询 | ✅ | tree-sitter 六语言；Semgrep/CodeQL/Joern → GraphDelta |
| B | AuditAgent 主动审计、Triage 对抗验证、补查 | ✅ | 路径审计 + Triage + audit 补查 |
| C | DeployAgent 自主部署 | 🟡 | Docker/配方/依赖自主编排已做；kvf 真实 ready 未验证 |
| D | Agent/Prompt/Skills/工具/LLM 全可配置 | ✅ | Prompt 三段式、版本、A/B、工具白名单、Preset |
| E | RAG 五类语料、工具化经验 | ✅ | pgvector + bge-m3 + GraphRAG + 经验库 |
| F | LangGraph 运行时 | ✅ | StateGraph、PostgresSaver、Send、中断/恢复 |
| G | PoC/canary、四层置信度、报告 | ✅ | 路径级 PoC、canary、Markdown/SARIF |
| H | 控制面（LLM/Prompt/身份/审计） | ✅ | 多 Profile、加密、熔断、RBAC、审计日志 |
| I | Vue3 控制台、图/路径/复核 | ✅ | 21 路由 Playwright 通过 |
| J | 安全红线 | ✅ | 默认 PoC off、无反弹 shell、密钥掩码、私网阻断 |
| K | 运维/生命周期 | ✅ | retention、维护、通知、SDK、导入导出 |
| L | 非功能要求 | ✅ | 六语言、可复现、降级、本地部署 |

## 2. 上一轮 P0/P1 收口

| ID | 需求 | 状态 |
|---|---|---|
| P0-1 | CodeQL 全链路（Java/Python/JS） | ✅ |
| P0-2 | 路径级 PoC / entry_url | ✅ |
| P0-3 | 路径 UI 与图联动 | ✅ |
| P0-4 | kvf 部署 | 🟡（degraded，依赖 MySQL/Redis；依赖编排已实现，ready 未验证） |
| P0-5 | 路径审计成本收敛 | ✅ |
| P0-6 | 多语言引擎图 | ✅（含 JS 匿名回调） |
| P0-7 | 浏览器验证 | ✅（Playwright 21/21；Safari 环境 blocked） |
| P0-8 | 审计稳定性回归 | ✅ |
| P1-9/10 | 路径统计/详情 | ✅ |
| P1-11 | 通知渠道 | ✅ |
| P1-12 | 项目/定时扫描 | ✅ |
| P1-13 | 自定义 Agent Preset | ✅ |
| P1-14 | Agent 试跑对比 | ✅ |
| P1-15 | 配置导入导出 | ✅ |
| P1-16 | 报告路径可视化 | ✅ |
| P1-17 | 图 package 折叠 | ✅ |
| P1-18 | 生命周期清理 | ✅ |
| P1-19 | Python SDK 补全 | ✅ |

## 3. P2 安全扩展

| ID | 需求 | 状态 | 边界 |
|---|---|---|---|
| P2-1 | 部署依赖自主编排（MySQL/Redis/PostgreSQL） | ✅ | 自动起依赖/注入 env/health；kvf ready 待真实验证 |
| P2-2 | JS/TS 匿名回调节点 | ✅ | 路径 proven |
| P2-3 | CodeQL 预授权自动安装 | ✅ | 许可确认 + 官方 URL + SHA |
| P2-4 | 自动修复建议 | ✅ | 只产 patch，不写源码 |
| P2-5 | 远程 PoC target | 🟡 | 仅目标登记/过期/host 白名单/只读 probe；不做远程利用 |
| P2-6 | 交互式/反弹 shell | ⛔ | 明确不做 |
| P2-7 | DAST/容器/IaC 扫描 | ⏳ | 未做 |
| P2-8 | IDE 插件 | ⏳ | 未做 |
| P2-9 | 多租户/部门隔离 | ⛔ | 明确不做 |

## 4. DeepAudit × CodeSentry 融合需求（新增）

### Phase 1：可观测性 + Harness MVP（已完成）

| ID | 需求 | 状态 |
|---|---|---|
| F1 | 路径 finding 增量落库 | ✅ |
| F2 | 运行中 `/findings` 可见 | ✅ |
| F3 | 超时/失败状态、进度统计 | ✅ |
| F4 | Harness 生成 + Docker 沙箱执行 + verdict | ✅ MVP |
| F5 | Harness API + Finding 抽屉 | ✅ |
| F6 | verified/plausible/rejected 策略 | ✅ 基础 |

### Phase 2：Supervisor + Agent 工作台（待开发）

| ID | 需求 | 状态 |
|---|---|---|
| F7 | Supervisor 动态调度（白名单动作、预算/轮次） | ⏳ |
| F8 | `agent_events` 统一事件表 | ⏳ |
| F9 | SSE 断点续传/回放 | ⏳ |
| F10 | Agent 树、暂停/恢复/停止/发消息 | ⏳ |
| F11 | 审计工作台（左树/中流/右上下文/底部 tabs） | ⏳ |
| F12 | Agent 思考/工具/验证日志可视化 | ⏳ |
| F13 | 扫描取消 API（不再靠停服务） | ⏳ |

### Phase 3：Harness 全语言 + 工具网关（待开发）

| ID | 需求 | 状态 |
|---|---|---|
| F14 | Harness 全语言镜像（Python/JS/TS/PHP/Java/Go/Ruby/Shell） | 🟡 命令支持，镜像/模板未齐 |
| F15 | Harness 模板库（78/89/79/22/94/95/502/918/611/1333） | 🟡 仅通用生成 |
| F16 | 函数提取工具 `extract_function` | ⏳ |
| F17 | Harness 多 payload/多 detector | ⏳ |
| F18 | 工具网关（注册/权限/超时/成本/证据归一化） | ⏳ |
| F19 | 外部工具接入：Gitleaks/Bandit/OSV/npm audit/Safety | ⏳ |
| F20 | 外部工具结果转图 hint/evidence | ⏳ |
| F21 | 工具证据 UI | ⏳ |

### Phase 4：知识包（待开发）

| ID | 需求 | 状态 |
|---|---|---|
| F22 | 框架知识包（Flask/FastAPI/Django/Express/Spring/React） | ⏳ |
| F23 | 漏洞知识包（SQLi/XSS/SSRF/XXE/反序列化/路径遍历/认证/业务逻辑） | ⏳ |
| F24 | 知识包版本化/来源/启停 | ⏳ |
| F25 | RAG 按语言/框架/漏洞类型加权 | ⏳ |

### Phase 5：产品化（待开发）

| ID | 需求 | 状态 |
|---|---|---|
| F26 | 项目导入（GitHub/GitLab/Gitea/zip） | 🟡 已有 zip/git/项目表 |
| F27 | 即时分析（粘贴代码/单文件） | ⏳ |
| F28 | 审计 Dashboard（verified/plausible/coverage/tool health） | 🟡 概览已有基础 |
| F29 | PDF/HTML 报告 | 🟡 Markdown/SARIF 已有 |
| F30 | Agent 事件回放/证据包导出 | ⏳ |

## 5. 关键决策（已确认）

1. Harness 语言：**全部带上**（Python/JS/TS/PHP/Java/Go/Ruby/Shell）。
2. Harness 网络：**默认不允许**，配置化开启。
3. 前端：**Vue3**，参考 DeepAudit 信息架构，不整体换 React。
4. 结论策略：`verified` 进报告主列表；`plausible` 降级保留；`rejected` 不进主报告。
5. 外部工具首批候选：Gitleaks、Bandit、OSV、npm audit、Safety；后续 Kunlun-M、gosec、Brakeman、Trivy、Checkov、hadolint、Syft/Grype。
6. 不做：多租户、远程任意利用、交互式/反弹 shell、自动修改源码、CodeQL 静默下载。

## 6. 当前阻碍/待确认

- kvf 真实 `ready`：依赖编排已完成，但未做全量真实部署验证；需要 MySQL/Redis 镜像与授权。
- Harness 全语言镜像：目前默认 Python 镜像可用；Java/JS/PHP/Go/Ruby 需要统一 sandbox 镜像。
- JVWA 重新扫描：需勾 OSS、换更强 deep 模型；上次 scan 1610 已停止。
- Agent workbench 前端：Phase 2。
- 外部工具首批范围：建议先 5 个，避免一次接太多。

## 7. 建议执行顺序

1. Phase 2：Supervisor + `agent_events` + 审计工作台。
2. Phase 3：Harness 全语言镜像/模板 + 工具网关。
3. Phase 4：知识包。
4. Phase 5：产品化。
5. 并行补 kvf ready、JVWA 重扫回归、外部工具首批。
