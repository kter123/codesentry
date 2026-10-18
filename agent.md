# CodeSentry — 需求与架构规格（唯一需求源文件）

> **本文件是 codesentry 项目的唯一需求与架构来源（SSOT）**。所有后续执行（脚手架、里程碑、代码评审）以本文件为准；修改需求先改本文件。
>
> - 状态：草案 v0.1（2026-10-18），**待需求评审通过**
> - 位置说明：按用户要求保存在仓库根目录 `agent.md`，替代默认的 docs/specs 路径
> - 决策记录：本版含 4 个开放问题（见 §12），评审时需拍板；拍板前按文中默认值执行

---

## 1. 项目定位

**CodeSentry** 是一个基于 LLM 多智能体的代码安全审计平台：对给定代码仓库自动完成「静态扫描 → 数据流深挖 → RAG 上下文检索 → AI 三防降噪（去误报/验证可达性/补证据链）→ 中文审计报告」的端到端流程。

- **目标用户**：安全工程师、研发团队（本地 / 内网部署，CLI 优先）
- **交付形态**：v1 为 CLI 工具；v2 增加 WebUI
- **核心差异化**：中心化多 agent 编排（LangGraph）+ 引擎结果与 LLM 验证联动，输出带完整证据链（污点源 → 传播路径 → 汇聚点）的低误报报告
- **成功标准（v1 验收）**：
  1. 对样例漏洞仓库端到端跑通 `codesentry scan`，产出 SARIF + Markdown 双格式报告
  2. 报告中每条 finding 均附可复核证据（文件行号、调用链、引擎与 LLM 各自结论）
  3. 经 TriageAgent 过滤后报告的误报率显著低于引擎原始输出（目标：原始 finding 数下降 ≥ 50%，且已确认漏洞不漏报——漏报按零容忍回测）
  4. 单仓扫描成本受预算硬约束（默认 ≤ $10 / ≤ 50 万 token / ≤ 500 次工具调用，超限熔断并降级输出）

## 2. 需求评审：基础要求

### 2.1 功能需求（v1）

| 编号 | 需求 | 说明 |
|---|---|---|
| FR-1 | 仓库扫描 | `codesentry scan <repo>`：自动识别语言/框架/构建方式，生成仓库画像 |
| FR-2 | 双引擎静态分析 | Joern（CPG + 数据流/污点）+ Semgrep（规则快扫），结果归一为统一 Finding 模型 |
| FR-3 | AI 审计流水线 | 中心化多 agent 对引擎结果做验证、链路补全、置信度评级、去重合并 |
| FR-4 | RAG 检索 | 代码语义切块入库（pgvector）+ 安全知识库（CWE/OWASP/框架安全实践），支持相似检索与引用 |
| FR-5 | 审计报告 | Markdown（中文）+ SARIF 2.1.0 导出；报告含严重度、置信度、证据链、修复建议 |
| FR-6 | 预算与可观测 | token/成本/调用次数硬预算；全程落库可回放（checkpoint） |
| FR-7 | 规则自管理 | 引擎规则由用户配置/外置，平台不内置第三方规则包（合规要求，见 §3） |
| FR-8 | 人工复核开关 | `HUMAN_REVIEW=true` 时，报告发布前中断等待人工确认（LangGraph interrupt） |

### 2.2 非功能需求

- **NFR-1 语言支持**：v1 支持 Python、Java（源码级）、JavaScript/TypeScript；Go 预留（引擎均具备能力，仅不做 v1 测试基线）
- **NFR-2 可复现**：同一仓库 + 同配置下，确定性路由路径可复现（LLM 温度默认 0）
- **NFR-3 数据本地化**：所有代码、向量、结果存储于本地 PostgreSQL（Docker 挂载盘），代码不外发；仅 LLM 请求按需发送必要代码片段
- **NFR-4 部署**：`docker compose` 一键起数据库；应用可裸跑（Python venv）或容器化
- **NFR-5 合规**：依赖引入前做许可证检查（见 §3 红线），CI 中固定该检查

### 2.3 范围外（v1 明确不做）

SCA 依赖漏洞、容器/IaC 扫描、DAST、PR/MR 增量审计、多租户 SaaS、IDE 插件、自动修复补丁（v2 候选）。

## 3. 许可证合规（红线）

> 背景：CodeQL CLI 单独许可——仅对**开源代码**分析免费，对闭源/商业代码分析需 GitHub 商业授权（GitHub 官方 README 明确："If you'd like to use the CodeQL CLI to analyze closed-source code, you will need a separate commercial license"）。本项目定位为可商用审计平台，**因此整体弃用 CodeQL**（包括其 MIT 许可的查询包——避免与专有 CLI 组合使用带来的整体风险）。

| 组件 | 许可证 | 决策与用法 |
|---|---|---|
| CodeQL CLI / 查询包 | CLI 专有（GitHub 商业许可）；查询包 MIT 但不可脱离 CLI 独立使用 | **禁用**，任何里程碑不得引入 |
| Joern（jvm/scala 平台 + 各语言前端） | Apache-2.0 | **核心深度分析引擎**。作为外部进程调用，保留 NOTICE/版权声明，可随平台分发 |
| Semgrep CLI（OSS 版） | LGPL-2.1 | **快速规则扫描引擎**。以独立子进程方式调用（进程隔离，无链接问题），可商用 |
| semgrep/semgrep-rules 官方规则库 | Semgrep Rules License v1.0 | **不打包、不内置**进本平台发行物（许可仅允许内部业务使用，禁止用于竞争产品/SaaS）。平台提供规则配置机制：用户自行下载/指定规则路径 |
| 第三方规则（如 Trail of Bits 规则集） | 多为 AGPL-3.0 | 同上，用户自备，平台只提供加载通道，不随包分发 |
| vulnhuntr | AGPL-3.0 | **仅借鉴思路**（迭代上下文扩展、置信度评分），不复制任何代码 |
| 自研 Joern 查询 / Semgrep 规则（若项目后续产出） | 平台协议（建议 Apache-2.0） | 全部原创编写，不移植 CodeQL 查询逻辑 |

**红线清单（CI 检查项）**：不出现 codeql 相关依赖/二进制；发行物中不含官方 semgrep 规则文件；每个第三方依赖记录 license 字段。

## 4. 引擎选型：方案对比（替代 CodeQL）

| 方案 | 构成 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A（推荐）** | **Joern（深度）+ Semgrep（快扫）双引擎** | CPG 数据流/污点分析最接近 CodeQL 能力；Semgrep 补齐规则生态与速度；两者许可证均可商用 | 需维护两套结果归一；Joern 需 JVM | ✅ 采纳 |
| B | 仅 Semgrep | 轻量、零构建 | 跨文件/跨函数数据流追踪弱，深洞（二阶污点、跨服务链）检不出 | 否决 |
| C | 仅 Joern + LLM | 依赖最少 | 失去规则扫描的速度与生态，首筛覆盖率下降，LLM 成本上升 | 否决 |

> 顺带排除：Bearer CLI（Elastic License 2.0，限制作为服务提供）；CodeQL（§3）。

## 5. 同类项目调研与借鉴（第二步结论）

| 项目 | 许可证 | 借鉴点 | 边界 |
|---|---|---|---|
| **vulnhuntr**（Protect AI） | AGPL-3.0 | ① LLM 迭代式调用链扩展（发现疑似点后按需拉取相关函数/类，直到凑齐「入口 → 汇聚」全链）；② 两段式分析（全文件初筛 + 漏洞类型定向复筛）；③ 0–10 置信度评分与阈值出报 | 仅借鉴思路；不读其代码、不复制 prompt 结构之外可享有版权的表达 |
| **ZeroPath**（商业闭源） | — | 产品流程设计：报告前先做可达性验证与去噪；PR 内联评论模式（v2）；业务逻辑漏洞作为 LLM 增量价值主打 | 不接触其代码（闭源），仅产品行为层面参考 |
| **RepoAgent**（OpenBMB） | Apache-2.0 | AST 驱动的层级化代码理解：按函数/类切块、维护调用关系图——直接用于 RAG 切块策略 | 可参考实现思路，代码可选直接复用（同为 Apache-2.0，需保留声明） |
| **Atlantis / Team-Atlanta**（AIxCC 冠军系） | 多数组件 Apache-2.0 / MIT | 「检测 → 验证 → 修复 → 回归」闭环思想；多专家模块协作形态 | v1 只借鉴检测-验证闭环；修复生成列为 v2 |

**升级点（相对上述项目的差异化）**：中心化编排 + 统一预算熔断（vulnhuntr 等均无成本约束）；引擎 finding 与 RAG 证据双通道融合 triage；checkpointer 全程可回放审计。

## 6. 总体架构（第三步：中心化多 agent 设计）

```mermaid
flowchart TD
    CLI[CLI 层 Typer<br/>scan / report / init-db] --> ORCH

    subgraph ORCH[LangGraph 中心编排：单一共享状态 AuditState + Supervisor 路由 + 预算守卫]
        SUP[Supervisor（中心决策点）]
        A1[ReconAgent 仓库画像]
        A2[ScanAgent 引擎调度]
        A3[RetrievalAgent RAG 检索]
        A4[TriageAgent 验证降噪]
        A5[ReportAgent 报告生成]
        SUP <--> A1
        SUP <--> A2
        SUP <--> A3
        SUP <--> A4
        SUP <--> A5
    end

    A2 --> ENG[引擎层：Joern CPG/数据流 · Semgrep 规则扫 · tree-sitter AST 切块]
    A3 --> DB
    A2 --> DB
    SUP --> DB
    A4 --> LLM[LLM API（OpenAI 兼容，可指向本地 vLLM/国产模型）]
    SUP --> LLM

    subgraph DB[(PostgreSQL 16 + pgvector，Docker 挂载盘)]
        T1[scans / findings]
        T2[code_chunks 向量]
        T3[kb_chunks 安全知识库]
        T4[checkpoints / 预算台账]
    end
```

**中心化原则**：所有 agent 是无自主路由的「专家节点」，只接收 Supervisor 指令、只读写共享 `AuditState`；不采用 agent 间点对点 handoff。好处：预算单点管控、行为可审计、失败可回放。

## 7. 多 Agent 详细设计

### 7.1 共享状态 `AuditState`（TypedDict）

`repo_path`、`profile`（语言/框架/入口点）、`engine_findings[]`、`triaged_findings[]`、`evidence{finding_id: 调用链+代码切片}`、`budget{tokens, calls, cost_usd, max_*}`、`phase`、`messages[]`。

### 7.2 Agent 职责表

| Agent | 职责 | 输入 → 输出 | 可用工具 |
|---|---|---|---|
| **ReconAgent** | 识别语言/框架/构建、目录结构、入口点（路由、反序列化点、外部输入面），产出仓库画像与扫描计划 | repo → profile | 文件遍历、tree-sitter、启发式规则 |
| **ScanAgent** | 生成并执行 Joern CPG 构建与数据流查询、Semgrep 扫描；结果归一为 Finding（含 CWE、source/sink、置信度初值） | profile → engine_findings | joern 子进程、semgrep 子进程、SARIF 解析 |
| **RetrievalAgent** | 为每个候选 finding 拉取语义上下文：相关函数切片、历史漏洞、知识库条目 | findings + 问题 → evidence | pgvector 相似检索、全文检索、代码读取 |
| **TriageAgent** | 对每个候选做可达性验证与误报判别（复用 vulnhuntr 思路：按需迭代拉取调用链直到闭环），输出 保留/降级/否决 + 置信度 + 证据链 | findings + evidence → triaged_findings | LLM（深度模型）、代码读取、链路追踪 |
| **ReportAgent** | 去重合并、按严重度/置信度排序、生成中文 Markdown + SARIF 报告 | triaged_findings → 报告文件 | 模板渲染 |

### 7.3 路由策略（中心化 + 确定性优先）

默认走**确定性状态机**：`recon → scan → retrieval(+triage) × N → report`；仅当 TriageAgent 报告「证据不足需补查」或出现引擎间结论冲突时，Supervisor（LLM 决策）介入分配额外检索/复扫步骤，受预算守卫约束（超限即熔断，按当前已验证结果降级出报）。

### 7.4 预算守卫

沿用现有 `.env.example` 约定（`CODESENTRY_MAX_TOKENS=500000`、`MAX_TOOL_CALLS=500`、`MAX_COST_USD=10`、`MAX_FINDINGS=200`）；Supervisor 每步前检查，达到 80% 预警、100% 熔断进报告阶段。台账写入 PostgreSQL。

### 7.5 持久化与回放

LangGraph `PostgresSaver` 检查点（同一 PostgreSQL 实例，独立 schema）；`HUMAN_REVIEW=true` 时在 report 节点前 interrupt。

## 8. 数据架构

- **部署**：`pgvector/pgvector:pg16` 镜像；数据目录绑定到挂载盘（`CODESENTRY_PGDATA_HOST`，如 `/mnt/data/codesentry/pgdata`）；Joern CPG 工作目录同样落挂载盘（`CODESENTRY_WORK_DIR`）
- **核心表**：`projects`、`scans`、`findings`（引擎原始 + triage 结论 + 置信度 + 证据 JSON）、`code_chunks`（`embedding vector(d)` + 文件/符号元数据）、`kb_chunks`（知识库向量）、`budget_ledger`；LangGraph checkpoint 表
- **RAG 切块**：函数/类粒度（tree-sitter AST，借鉴 RepoAgent），向量 = 代码摘要 + 签名 + 调用关系；检索 = 向量相似 + 全文混合
- **知识库**：CWE/OWASP 官方文档（允许分发引用的公共资料）+ 用户自有安全规范，导入走 `codesentry kb import`

## 9. 技术栈与部署

- **Python 3.11+**；包管理 uv；代码规范 ruff + mypy；pytest
- **核心依赖**：langgraph、langchain-core、psycopg[binary]、pydantic v2、typer、rich、tree-sitter；Joern 需 JDK 17+（随附安装说明）
- **CLI 命令（v1）**：`codesentry init-db` / `scan <repo> [--out]` / `report <scan-id>` / `kb import <dir>` / `agents list`
- **里程碑**：
  - **M0 脚手架**：目录结构、docker-compose（含挂载盘卷）、配置加载、CLI 骨架、**更新 `.env.example`（移除 CodeQL 段，替换为 Joern/Semgrep 段）**、license 检查脚本
  - **M1 引擎集成**：Joern parse→CPG→查询、Semgrep 扫描、规则配置机制、统一 Finding 模型 + SARIF 导出
  - **M2 数据与 RAG**：pgvector 入库、切块、kb 导入、检索 API
  - **M3 多 agent 流水线**：LangGraph 编排全链路 + checkpointer + 预算守卫
  - **M4 质量评测**：自建样例漏洞仓库基线，统计检出/误报/漏报与成本，迭代 prompt
  - **M5 WebUI**：FastAPI + React（AntD）：扫描管理、finding 审阅、报告展示（设计另出小规格）

## 10. 错误处理与测试要点

- 引擎子进程超时/崩溃 → 记录并以另一引擎结果继续（引擎降级不阻塞流水线）
- LLM 调用失败 → 指数退避重试 3 次，仍失败则该 finding 标记「未验证」保留原始引擎结论
- 测试：Finding 归一化单测、pgvector 检索集成测试（testcontainers）、用小型漏洞样例仓做流水线端到端测试；LLM 相关逻辑以录制回放（mock）测试

## 11. 风险

| 风险 | 缓解 |
|---|---|
| Joern Java 源码级前端对复杂构建项目解析不全 | M1 起用样例仓验证；必要时 Java 走源码解析 + 用户自配构建命令双通道 |
| LLM 误报/漏报抖动 | 温度 0 + 确定性路由 + 置信度阈值出报 + 人工复核开关 |
| 成本失控 | §7.4 硬预算熔断 |
| Semgrep 规则合规误用 | 规则只经用户配置路径加载，发行物零内置（CI 检查） |

## 12. 开放问题（评审时拍板，默认值如下）

1. **产品形态**：内部工具还是可分发/SaaS 产品？→ 默认按更保守的「可分发」设计（因此不打包任何官方规则）
2. **v1 语言**：Python + Java + JS/TS 是否锁定？→ 默认锁定
3. **LLM 提供方**：OpenAI 兼容接口默认指向哪家 base_url / 是否需要默认支持本地 vLLM？→ 默认仅做 OpenAI 兼容抽象，不预置厂商
4. **平台自身协议**：建议 Apache-2.0 → 待定

## 13. 参考资料（本次调研来源）

- CodeQL CLI 许可条款：https://github.com/github/codeql/blob/main/README.md
- Semgrep CLI（LGPL-2.1）：https://github.com/semgrep/semgrep
- Semgrep 规则许可（内部使用限制）：https://docs.semgrep.dev/licensing
- Joern（Apache-2.0，CPG）：https://github.com/joernio/joern
- vulnhuntr（AGPL-3.0，LLM 迭代审计思路）：https://github.com/protectai/vulnhuntr
- RepoAgent（Apache-2.0，AST 切块）：https://github.com/OpenBMB/RepoAgent
- ZeroPath（商业产品流程参考）：https://zeropath.com/
- Team-Atlanta / Atlantis（AIxCC 获奖系统组件）：https://github.com/orgs/Team-Atlanta/repositories
