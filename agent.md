# CodeSentry — 需求与架构规格（唯一需求源文件）

> **本文件是 codesentry 项目的唯一需求与架构来源（SSOT）**。所有后续执行（脚手架、里程碑、代码评审）以本文件为准；修改需求先改本文件。
>
> - 状态：**v1.0（2026-10-18）**——全部决策已与需求方逐项确认（见 §12 决策记录 D1–D16），待需求方对全文做最终批准
> - 位置：按需求方要求保存于仓库根目录 `agent.md`

---

## 1. 项目定位

**CodeSentry** 是基于 LLM 多智能体的代码安全审计平台：对目标仓库自动完成「三引擎静态扫描 → 数据流深挖 → RAG 上下文检索 → AI 验证降噪 → 中文审计报告」的端到端流程。

- **目标用户**：安全工程师、研发团队（本地 / 内网部署）
- **交付形态（已确认）**：v1 = **CLI（含增量审计）+ 基础 WebUI（M5）**；v2 扩展完整 WebUI
- **核心差异化**：中心化多 agent 编排（LangGraph）+ 三引擎许可分流 + 引擎结果与 LLM 验证联动，输出带完整证据链（污点源 → 传播路径 → 汇聚点）的低误报报告
- **成功标准（v1 验收）**：
  1. 六种语言各有至少一个样例漏洞仓库，`codesentry scan` 端到端跑通，产出 SARIF 2.1.0 + Markdown 双格式报告
  2. 报告中每条 finding 均附可复核证据（文件行号、调用链、引擎与 LLM 各自结论）
  3. 经 TriageAgent 过滤后误报显著下降（目标：原始 finding 数下降 ≥ 50%，已确认漏洞零漏报——按 M4 基线回测）
  4. 单仓扫描受预算硬约束（≤ $10 / ≤ 50 万 token / ≤ 500 次工具调用，超限熔断并降级输出）

## 2. 基础要求

### 2.1 功能需求（v1）

| 编号 | 需求 | 说明 |
|---|---|---|
| FR-1 | 仓库扫描 | `codesentry scan <repo>`：识别语言/框架/构建方式，产出仓库画像与扫描计划 |
| FR-2 | 三引擎静态分析 | CodeQL（仅开源代码场景）+ Joern（CPG 数据流/污点）+ Semgrep（规则快扫），结果归一为统一 Finding 模型 |
| FR-3 | 许可分流（Gate） | 扫描时用户声明目标代码许可状态（`--oss` / 默认闭源处理）；仅声明为开源时启用 CodeQL，声明记录进扫描台账。平台**不代为分发 CodeQL CLI**，仅探测用户自装二进制 |
| FR-4 | AI 审计流水线 | 中心化多 agent 对引擎结果做验证、链路补全、置信度评级、去重合并 |
| FR-5 | RAG 检索 | AST 函数/类粒度切块入库（pgvector）+ 安全知识库（CWE/OWASP 公共资料 + 用户自有规范），向量 + 全文混合检索与引用 |
| FR-6 | 审计报告 | 中文 Markdown + SARIF 2.1.0 导出；含严重度、置信度、证据链、修复建议 |
| FR-7 | 预算与可观测 | token/成本/调用次数硬预算；全程落库可回放（LangGraph checkpoint） |
| FR-8 | 规则自管理 | 平台作为**可分发展品不内置任何第三方规则包**；提供规则配置机制（路径/目录/自研规则），随包附少量原创规则（Apache-2.0） |
| FR-9 | 人工复核开关 | `CODESENTRY_HUMAN_REVIEW=true` 时（默认关）报告发布前中断等待人工确认（LangGraph interrupt） |
| FR-10 | 增量审计（已提入 v1） | `codesentry diff <base>...<head>`：基于本地 git diff 只审计变更代码及其可达链路；CLI 可直接嵌入 CI/CD 流水线（退出码 + SARIF 产物）；基础 WebUI 提供增量结果查看（M5） |

### 2.2 非功能需求

- **NFR-1 语言支持（已确认）**：v1 覆盖 **Python、Java、JS/TS、Go、C/C++、PHP** 六门；各引擎覆盖度见 §4.2，弱组合在 M1 实测并标注降级策略
- **NFR-2 可复现**：同一仓库 + 同配置下路由路径可复现（LLM 温度默认 0，已确认）
- **NFR-3 数据本地化**：代码、向量、结果全部存本地 PostgreSQL（Docker 挂载盘）；代码不外发，仅 LLM 请求按需携带必要片段
- **NFR-4 部署**：`docker compose` 一键起数据库；应用可裸跑（Python venv）或容器化；Joern 需 JDK 17+
- **NFR-5 合规**：依赖引入前做许可证检查（脚本进 CI），红线见 §3

### 2.3 范围外（v1 不做，已确认）

SCA 依赖漏洞、容器/IaC 扫描、DAST、多租户 SaaS、IDE 插件、自动修复补丁（均为 v2+ 候选）。~~PR 增量审计~~ 已提入 v1（FR-10）。

## 3. 许可证合规（红线）

> 背景：CodeQL CLI 单独许可，对**开源项目**分析免费；对闭源/商业代码分析需 GitHub 商业授权。本项目场景（已确认）：**CodeQL 仅在目标为开源代码时使用**，闭源仓库走 Joern + Semgrep。

| 组件 | 许可证 | 决策与用法 |
|---|---|---|
| CodeQL CLI | GitHub 专有许可（开源场景免费） | **按场景使用**：仅当用户声明目标是开源代码（FR-3 Gate）；平台不打包、不随包分发，用户自行从 GitHub 官方下载安装，平台仅探测 `CODESENTRY_CODEQL_BIN` |
| CodeQL 查询包（ql 仓库） | MIT | 随 CodeQL CLI 按上述场景限制使用 |
| Joern（jvm/scala 平台 + 各语言前端） | Apache-2.0 | **全场景通用深度引擎**。外部进程调用，随分发保留 NOTICE/版权声明 |
| Semgrep CLI（OSS 版） | LGPL-2.1 | **全场景通用快扫引擎**。独立子进程调用（进程隔离，无链接问题），可商用 |
| semgrep/semgrep-rules 官方规则库 | Semgrep Rules License v1.0 | **不打包、不内置**（许可仅允许内部业务使用，禁止用于竞争产品/SaaS）。用户自行下载并经规则配置机制加载 |
| 第三方规则（如 Trail of Bits 规则集 AGPL-3.0） | 各自许可 | 同上：用户自备，平台只提供加载通道 |
| bge-m3（Embedding 模型） | MIT | 用户本地部署，模型文件落挂载盘（D10） |
| vulnhuntr | AGPL-3.0 | **仅借鉴思路**（迭代上下文扩展、两段式分析、置信度评分），不复制任何代码 |
| CodeSentry 自身 | **Apache-2.0（已确认）** | 自研查询/规则/代码均为原创；不移植 CodeQL 查询逻辑 |

**红线清单（CI 检查项）**：发行物中不含 CodeQL CLI 二进制；不含官方 semgrep 规则文件；依赖清单逐项记录 license 字段并阻塞不合许可的引入。

## 4. 引擎设计

### 4.1 引擎组合与调度（已确认：三引擎全带 + 并行调度）

| 引擎 | 角色 | 适用范围 |
|---|---|---|
| **CodeQL** | 开源场景首选深度引擎（查询套件成熟度最高） | 仅开源代码场景（FR-3 Gate） |
| **Joern** | 全场景通用深度引擎：CPG 构建 + 自研数据流/污点查询 | 六门语言全适用，闭源场景主力 |
| **Semgrep** | 全场景通用快扫引擎：规则首筛、低成本低延迟 | 六门语言全适用 |

**调度策略（已确认：并行双引擎）**：开源场景 CodeQL + Semgrep 并行（CodeQL 主力，Semgrep 补规则面）；闭源场景 Joern + Semgrep 并行（Joern 主力）。两路结果交叉印证降噪；单引擎超时/崩溃互为降级，不阻塞流水线（§10）。

### 4.2 语言 × 引擎覆盖矩阵（NFR-1 依据）

| 语言 | CodeQL | Joern 前端 | Semgrep | 备注 |
|---|---|---|---|---|
| Python | ✅ | pysrc2cpg（较新，M1 验证） | ✅ | |
| Java | ✅ | javasrc2cpg | ✅ | **源码级 + 可选构建**（D15）：默认纯源码分析，用户可在 `.env` 配置构建命令，CodeQL autobuild 可选启用以提升精度 |
| JS/TS | ✅ | jssrc2cpg | ✅ | TS 统一按 JS 处理 |
| Go | ✅ | gosrc2cpg（较新，M1 验证） | ✅ | |
| C/C++ | ✅ | fuzzyc2cpg（成熟） | ✅（规则面较窄） | |
| PHP | ❌ 不支持 | php2cpg（实验性，M1 验证） | ✅ | PHP 场景 CodeQL 缺位：Joern + Semgrep 组合 |

M1 交付物：每个「语言 × 引擎」组合至少 1 个可运行验证样例；不可用组合显式降级并写进扫描报告元数据。

## 5. 同类项目调研与借鉴（第二步结论）

| 项目 | 许可证 | 借鉴点 | 边界 |
|---|---|---|---|
| **vulnhuntr**（Protect AI） | AGPL-3.0 | ① LLM 迭代式调用链扩展（按需拉取相关函数/类直到凑齐「入口 → 汇聚」全链）；② 两段式分析（全文件初筛 + 漏洞类型定向复筛）；③ 0–10 置信度评分与阈值出报 | 仅借鉴思路，不读其代码、不复制表达 |
| **ZeroPath**（商业闭源） | — | 产品流程：报告前先做可达性验证与去噪；PR 内联评论体验；业务逻辑漏洞作为 LLM 增量价值 | 不接触其代码，仅产品行为层面参考 |
| **RepoAgent**（OpenBMB） | Apache-2.0 | AST 驱动的层级化代码理解：函数/类粒度切块、调用关系图——用于 RAG 切块策略 | 同协议可参考复用，保留声明 |
| **Atlantis / Team-Atlanta**（AIxCC 冠军系） | 多数组件 Apache-2.0 / MIT | 「检测 → 验证 → 修复 → 回归」闭环思想、多专家模块协作形态 | v1 只借鉴检测-验证闭环；修复生成为 v2+ |

**相对上述项目的升级点**：中心化编排 + 统一预算熔断；三引擎许可分流（现有项目均无此问题域）；引擎 finding 与 RAG 证据双通道融合 triage；checkpointer 全程可回放。

## 6. 总体架构（第三步：中心化多 agent 设计）

```mermaid
flowchart TD
    CLI[CLI 层 Typer<br/>init-db / scan / diff / report / kb / engines / agents] --> ORCH
    WEB[基础 WebUI（M5）<br/>FastAPI + React + AntD] --> ORCH

    subgraph ORCH[LangGraph 中心编排：共享状态 AuditState + Supervisor + 预算守卫]
        SUP[Supervisor（中心决策点）]
        A1[ReconAgent 仓库画像]
        A2[ScanAgent 引擎调度+许可Gate]
        A3[RetrievalAgent RAG 检索]
        A4[TriageAgent 验证降噪]
        A5[ReportAgent 报告生成]
        SUP <--> A1 & A2 & A3 & A4 & A5
    end

    A2 --> ENG[引擎层：CodeQL（仅OSS）· Joern CPG/数据流 · Semgrep 规则扫 · tree-sitter AST 切块]
    A2 --> DB
    A3 --> DB
    SUP --> DB
    A4 --> LLM[LLM API（OpenAI 兼容抽象，可指向云端或本地 vLLM）]
    A3 --> EMB[Embedding 双通道：OpenAI 兼容接口 / 本地 bge-m3（挂载盘）]
    SUP --> LLM

    subgraph DB[(PostgreSQL 16 + pgvector 单实例分 schema，Docker 挂载盘)]
        T1[scans / findings / budget_ledger]
        T2[code_chunks 向量]
        T3[kb_chunks 安全知识库]
        T4[LangGraph checkpoints]
    end
```

**中心化原则（已确认：混合编排）**：所有 agent 是无自主路由的「专家节点」，只接收 Supervisor 指令、只读写共享 `AuditState`，无 agent 间点对点 handoff。主链路为**确定性状态机**；仅在异常情形（证据不足需补查、引擎结论冲突）由 LLM Supervisor 介入动态调度，且始终受预算守卫约束。收益：预算单点管控、行为可审计、失败可回放。

## 7. 多 Agent 详细设计

### 7.1 共享状态 `AuditState`（TypedDict）

`repo_path`、`license_declaration`（oss/proprietary + 声明时间戳）、`diff_scope`（增量模式时：变更文件集 + 可达闭包）、`profile`（语言/框架/入口点）、`engine_findings[]`、`triaged_findings[]`、`evidence{finding_id: 调用链+代码切片}`、`budget{tokens, calls, cost_usd, max_*}`、`phase`、`messages[]`。

### 7.2 Agent 职责表

| Agent | 职责 | 输入 → 输出 | 可用工具 |
|---|---|---|---|
| **ReconAgent** | 语言/框架/构建识别、目录结构、入口点（路由、反序列化点、外部输入面）；增量模式下先计算 diff 可达闭包；产出画像与扫描计划 | repo [diff_scope] → profile | 文件遍历、tree-sitter、启发式规则 |
| **ScanAgent** | 执行许可 Gate（FR-3）；按 §4.1 策略并行调度引擎；结果归一为统一 Finding（CWE、source/sink、置信度初值） | profile + license → engine_findings | codeql/joern/semgrep 子进程、SARIF 解析 |
| **RetrievalAgent** | 为候选 finding 拉取语义上下文：相关函数切片、相似历史漏洞、知识库条目 | findings + 问题 → evidence | pgvector 混合检索、代码读取 |
| **TriageAgent** | 可达性验证与误报判别（vulnhuntr 思路：按需迭代拉取调用链直到闭环）；输出 保留/降级/否决 + 置信度 + 证据链 | findings + evidence → triaged_findings | LLM（深度模型）、代码读取、链路追踪 |
| **ReportAgent** | 去重合并、严重度/置信度排序、生成中文 Markdown + SARIF | triaged_findings → 报告文件 | 模板渲染 |

### 7.3 路由策略（已确认：混合编排）

- **确定性主链路**：`recon → scan → (retrieval → triage) × N → report`
- **LLM Supervisor 介入点**：① TriageAgent 报告「证据不足需补查」；② 引擎间结论冲突（如同一点位 CodeQL 报/Joern 不报）；③ 主链路某 agent 失败需重规划
- **预算守卫（已确认默认值）**：`MAX_TOKENS=500000`、`MAX_TOOL_CALLS=500`、`MAX_COST_USD=10`、`MAX_FINDINGS=200`（环境变量可覆写）；达 80% 预警、100% 熔断进入报告阶段（按已验证结果降级出报）；台账写 PostgreSQL `budget_ledger`
- **持久化**：LangGraph `PostgresSaver`（**单实例分 schema**，已确认；业务表与 checkpoint 分 schema 隔离）；`HUMAN_REVIEW=true` 时 report 节点前 interrupt

## 8. 数据架构

- **部署（已确认）**：`pgvector/pgvector:pg16` 镜像**单实例**，业务 schema 与 LangGraph checkpoint schema 分层隔离；数据目录绑定挂载盘（`CODESENTRY_PGDATA_HOST`，如 `/mnt/data/codesentry/pgdata`）；Joern CPG 与扫描工作目录同落挂载盘（`CODESENTRY_WORK_DIR`）
- **核心表**：`projects`、`scans`（含 license 声明、扫描模式 full/diff）、`findings`（引擎原始 + triage 结论 + 置信度 + 证据 JSON）、`code_chunks`（`embedding vector(d)` + 文件/符号元数据）、`kb_chunks`、`budget_ledger`；checkpoint 表
- **RAG 切块（已确认）**：AST 函数/类粒度（tree-sitter，借鉴 RepoAgent）；向量 = 代码摘要 + 签名 + 调用关系
- **Embedding（已确认：双通道兼顾）**：提供统一 Embedding 接口层——① OpenAI 兼容远程接口（`CODESENTRY_EMBEDDING_MODEL` 可配）；② 本地部署 bge-m3（模型文件落挂载盘，经 vLLM/Ollama/自托管推理服务暴露，同样走 OpenAI 兼容协议）。二者按配置切换，维度入库时自动探测
- **知识库**：CWE/OWASP 官方公共资料 + 用户自有安全规范；`codesentry kb import <dir>` 导入

## 9. 技术栈与里程碑

- **Python 3.11+**；uv 管理依赖；ruff + mypy；pytest
- **核心依赖**：langgraph、langchain-core、psycopg[binary]、pydantic v2、typer、rich、tree-sitter；外部二进制：JDK 17+（Joern）、用户自装 CodeQL；WebUI：FastAPI + React + Ant Design（已确认）
- **CLI 命令（已确认七命令）**：`init-db` / `scan <repo> [--oss] [--out]` / `diff <base>...<head> [--oss]` / `report <scan-id>` / `kb import <dir>` / `engines check`（探测三引擎与 JDK）/ `agents list`
- **里程碑**：
  - **M0 脚手架**：目录结构、docker-compose（挂载盘卷、单实例分 schema）、配置加载、CLI 骨架、`.env.example` 扩展（Joern/Semgrep/Embedding 双通道/PG 段 + CodeQL OSS Gate 开关）、license 检查脚本
  - **M1 引擎集成**：三引擎并行调度 + 许可 Gate + §4.2 覆盖矩阵逐组合验证 + 统一 Finding 模型 + SARIF 导出
  - **M2 数据与 RAG**：pgvector 入库、AST 切块、Embedding 双通道、kb 导入、混合检索 API
  - **M3 多 agent 流水线**：LangGraph 全链路 + checkpointer + 预算守卫 + 人工复核中断 + **增量审计（diff 可达闭包）**
  - **M4 质量评测（已确认：自建 + 公开双轨）**：六语言自建样例漏洞仓做回归基线（每语言 5–10 个真实 CVE 模式用例）；公开基准（OWASP Benchmark、NIST Juliet 等，许可逐个核实）做能力对标；统计检出/误报/漏报与成本，迭代 prompt
  - **M5 基础 WebUI（v1 交付）**：FastAPI + React + AntD——扫描管理、finding 审阅、增量结果查看、报告展示；完整 WebUI 能力为 v2

## 10. 错误处理与测试要点

- 引擎子进程超时/崩溃 → 记录并以其余引擎结果继续；三引擎全失败 → 中止该扫描并落因
- LLM 调用失败 → 指数退避重试 3 次，仍失败则该 finding 标「未验证」保留引擎原始结论
- 测试：Finding 归一化单测；许可 Gate 单测（闭源声明时禁用 CodeQL）；diff 可达闭包单测；pgvector 检索集成测试（testcontainers）；六语言小型样例仓端到端测试；LLM 逻辑用录制回放（mock）测试

## 11. 风险

| 风险 | 缓解 |
|---|---|
| Joern 对 Go/PHP/Python 前端较新，解析质量待验证 | M1 逐组合实测（§4.2）；弱前端场景降级为 Semgrep + LLM，并在报告元数据标注 |
| CodeQL 许可 Gate 被绕过/误用（闭源仓库误开 CodeQL） | Gate 由 ScanAgent 强制执行（不依赖用户自觉）；声明与台账落库可审计；发行物不含 CodeQL |
| LLM 误报/漏报抖动 | 温度 0 + 确定性主链路 + 置信度阈值出报 + 人工复核开关 |
| 成本失控 | §7.3 硬预算熔断 |
| Semgrep 规则合规误用 | 规则仅经用户配置路径加载，发行物零内置（CI 检查） |
| 公开评测基准许可不一（Juliet 属 NIST 公有领域，OWASP Benchmark 为 MIT，需逐个核） | M4 引入前逐项做许可核验，核验记录入库 |

## 12. 决策记录（2026-10-18 与需求方逐项确认）

| # | 决策项 | 结论 |
|---|---|---|
| D1 | 引擎组合 | 三引擎全带：CodeQL（仅开源代码场景）+ Joern + Semgrep，平台内置许可分流 |
| D2 | v1 语言范围 | 六门：Python、Java、JS/TS、Go、C/C++、PHP |
| D3 | 产品形态 | 可分发展品（第三方规则不内置，用户自备；平台附少量自研规则） |
| D4 | 编排模式 | 混合：确定性主链路 + LLM Supervisor 异常点动态调度 |
| D5 | LLM 接入 | OpenAI 兼容抽象，用户自配厂商/本地 vLLM，平台不预置 |
| D6 | 平台自身协议 | Apache-2.0 |
| D7 | 历史约束 | CodeQL 许可场景限定为开源代码；先 CLI 后 WebUI；技术栈含 Python + RAG + PostgreSQL（Docker 挂载盘） |
| D8 | 引擎调度 | 并行双引擎（开源：CodeQL+Semgrep；闭源：Joern+Semgrep），交叉印证、互为降级 |
| D9 | RAG 切块粒度 | AST 函数/类粒度（tree-sitter） |
| D10 | Embedding | 双通道兼顾：OpenAI 兼容接口 + 本地部署 bge-m3（模型文件落挂载盘），按配置切换 |
| D11 | 增量审计 | **提入 v1**（FR-10）；范围外清单相应缩减 |
| D12 | 增量审计形态 | CLI 本地 diff + CI/CD 集成（退出码/SARIF 产物）+ 基础 WebUI 查看（M5 随 v1 交付） |
| D13 | CLI 命令集 | 七命令：init-db / scan / diff / report / kb import / engines check / agents list |
| D14 | 预算与开关默认值 | 预算四项按默认；HUMAN_REVIEW 默认关；LLM 温度默认 0（均环境变量可覆写） |
| D15 | Java 分析模式 | 源码级 + 可选构建（用户可配构建命令，CodeQL autobuild 可选） |
| D16 | WebUI 技术栈 | FastAPI + React + Ant Design（M5 基础版随 v1 交付） |
| D17 | 评测基线 | 自建六语言样例仓（回归基线）+ 公开基准（能力对标）双轨 |
| D18 | PostgreSQL 拓扑 | 单实例分 schema（业务与 checkpoint 分层），数据全部落挂载盘 |

## 13. 参考资料（调研来源）

- CodeQL CLI 许可条款（开源免费 / 闭源需商业授权）：https://github.com/github/codeql/blob/main/README.md
- Semgrep CLI（LGPL-2.1）：https://github.com/semgrep/semgrep
- Semgrep 规则许可（仅内部业务使用，禁竞争产品/SaaS）：https://docs.semgrep.dev/licensing
- Joern（Apache-2.0，CPG）：https://github.com/joernio/joern
- vulnhuntr（AGPL-3.0，LLM 迭代审计思路）：https://github.com/protectai/vulnhuntr
- RepoAgent（Apache-2.0，AST 切块）：https://github.com/OpenBMB/RepoAgent
- ZeroPath（商业产品流程参考）：https://zeropath.com/
- Team-Atlanta / Atlantis（AIxCC 获奖系统组件）：https://github.com/orgs/Team-Atlanta/repositories
