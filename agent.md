# CodeSentry — 需求与架构规格（唯一需求源文件）

> **本文件是 codesentry 项目的唯一需求与架构来源（SSOT）**。所有后续执行（脚手架、里程碑、代码评审）以本文件为准；修改需求先改本文件。
>
> - 状态：**v1.5（2026-10-18）**——v1.4 全部确认 + D39 GraphRAG 路线A；全量决策已与需求方逐项确认（见 §12 决策记录 D1–D39）
> - 位置：按需求方要求保存于仓库根目录 `agent.md`

---

## 0. 标准执行流水线（每个里程碑一轮，已确认）

后续每个里程碑（M0、M1、…）按以下 8 步执行，一轮一档产出、可验收：

1. **确认需求范围**：梳理本里程碑的需求范围与内容（以本文件为源），产出确认点清单并关跑
2. **写 spec 文档**：将本里程碑的执行内容写成 spec，保存至仓库根目录 `doc/`（`doc/` 为需求方指定的规格目录）
3. **spec 审计**：对 spec 做审计——逐项核对与 `agent.md` 需求无差异（含遗漏、越界、矛盾），审计结论记录进 spec 或独立审计记录
4. **多 agent 并发执行**：按 spec 拆分为可并行的任务，由多个子 agent 同时执行（无共享状态/有依赖的任务串行化）
5. **代码 code review**：对全部实现代码做评审（正确性、架构一致性、合规红线）
6. **修复 review 发现**：修复评审问题并回归验证
7. **全量功能测试**：按 §10 测试要点跑全量测试（单测 + 集成 + 端到端）
8. **归档上库（已确认）**：git commit 并 push 到远程仓库；每轮结束里程碑状态落 `agent.md` 里程碑表

---

## 1. 项目定位

**CodeSentry** 是基于 LLM 多智能体的代码安全审计平台：对目标仓库自动完成「三引擎静态扫描 → 数据流深挖 → RAG 上下文检索 → AI 验证降噪 → 中文审计报告」的端到端流程。

- **目标用户**：安全工程师、研发团队（本地 / 内网部署）
- **交付形态（已确认）**：v1 = **CLI（含增量审计）+ WebUI（M5，含 agent 管理控制台与 Skill 管理）**；v2 扩展完整 WebUI
- **核心差异化**：中心化多 agent 编排（LangGraph）+ 三引擎许可分流 + 引擎结果与 LLM 验证联动 + Skill 可插拔能力层 + **分级 PoC 生成与验证**，输出带完整证据链（污点源 → 传播路径 → 汇聚点）的低误报报告
- **成功标准（v1 验收）**：
  1. 六种语言各有至少一个样例漏洞仓库，`codesentry scan` 端到端跑通，产出 SARIF 2.1.0 + Markdown 双格式报告
  2. 报告中每条 finding 均附可复核证据（文件行号、调用链、引擎与 LLM 各自结论）
  3. 经 TriageAgent 过滤后误报显著下降（目标：原始 finding 数下降 ≥ 50%，已确认漏洞零漏报——按 M4 基线回测）
  4. 单仓扫描受预算硬约束（≤ $10 / ≤ 50 万 token / ≤ 500 次工具调用，超限熔断并降级输出）
  5. WebUI 可查看每次运行的 agent 拓扑与节点时间线，可完成人工复核、Prompt 版本管理与 Skill 上传/分配（M5 验收项）
  6. 高危 finding 附利用链路与 PoC；对 HTTP 类漏洞可在授权后自动试跑并回填 verified/plausible 判定（M5 验收项）

## 2. 基础要求

### 2.1 功能需求（v1）

| 编号 | 需求 | 说明 |
|---|---|---|
| FR-1 | 仓库扫描 | `codesentry scan <repo>`：识别语言/框架/构建方式，产出仓库画像与扫描计划 |
| FR-2 | 三引擎静态分析 | CodeQL（仅开源代码场景）+ Joern（CPG 数据流/污点）+ Semgrep（规则快扫），结果归一为统一 Finding 模型 |
| FR-3 | 许可分流（Gate） | 扫描时用户声明目标代码许可状态（`--oss` / 默认闭源处理）；仅声明为开源时启用 CodeQL，声明记录进扫描台账。平台**不代为分发 CodeQL CLI**，仅探测用户自装二进制 |
| FR-4 | AI 审计流水线 | 中心化多 agent 对引擎结果做验证、链路补全、置信度评级、去重合并 |
| FR-5 | RAG 检索（v1.3 扩展） | RAG 为**审计大脑**，四库角色（已确认）：① **代码库**（code_chunks）——AST 函数/类切块 + 签名/调用关系；② **安全知识库**（kb_chunks）——CWE/OWASP 公共资料 + 用户自有规范；③ **历史漏洞案例库**（vuln_cases，新增）——存历史扫描中经人工确认/verified 的漏洞案例（含利用链路、PoC、修复方案），新扫描检索相似案例直接指导 TriageAgent 判别与 **PoCGenAgent 生成**（经验复用，越用越准）；④ **漏洞模式/规则库**（audit_patterns，新增）——漏洞模式、引擎规则模板、自研 Joern/Semgrep 查询语料化，审计时按语言/框架检索对应检测模式反哺 agent 判断（主动）；⑤ **策略库**（scan_strategies，新增）——存相似项目的历史扫描策略与配置（引擎组合/规则集/参数），ReconAgent/Supervisor 检索相似项目策略指引扫描计划与编排决策。检索统一走 pgvector 向量 + 全文混合。**GraphRAG（v1.5 新增，已确认路线 A）**：切块时同步抽取代码图边（函数→函数调用、文件→import、函数→API/sink 节点），显式存 PostgreSQL `code_graph`（节点/边表，递归 CTE 查询，不另装图数据库）；TriageAgent 可达性验证与 PoCGenAgent 利用链路构造沿图 BFS 拉取沿链切片+边进上下文；增量审计的可达闭包（FR-10）升级为真调用图闭包（BFS from diff files） |
| FR-6 | 审计报告 | 中文 Markdown + SARIF 2.1.0 导出；含严重度、置信度、证据链、修复建议 |
| FR-7 | 预算与可观测 | token/成本/调用次数硬预算；节点级遥测（起止/耗时/token/工具调用/状态）直写 PostgreSQL 台账；全程落库可回放（LangGraph checkpoint） |
| FR-8 | 规则自管理 | 平台作为**可分发展品不内置任何第三方规则包**；提供规则配置机制（路径/目录/自研规则），随包附少量原创规则（Apache-2.0） |
| FR-9 | 人工复核（已确认入口） | `CODESENTRY_HUMAN_REVIEW=true` 时（默认关）流水线在 report 前 interrupt；复核入口为 **WebUI 待复核队列**：逐条查看证据链，通过/驳回/调整置信度，确认后流水线恢复出报（CLI 触发的扫描同样进队列） |
| FR-10 | 增量审计（已提入 v1） | `codesentry diff <base>...<head>`：基于本地 git diff 只审计变更代码及其可达链路；CLI 可直接嵌入 CI/CD 流水线（退出码 + SARIF 产物）；WebUI 提供增量结果查看（M5） |
| FR-11 | WebUI Agent 管理（已确认：全量） | WebUI 提供 agent 管理控制台：① 监控——agent 清单、健康状态、每次运行的节点时间线与拓扑图、token/成本/预算消耗；② 运行时配置——按 agent 调整模型分配（fast/deep）、启停、预算覆写；③ Prompt 管理——在线编辑、版本化入库、历史对比与回滚。扫描记录所用 Prompt 版本号（支撑 NFR-2 可复现） |
| FR-12 | Skill 装载与管理（已确认） | 以 **SKILL.md 目录包**（frontmatter 元信息 + 指令正文 + 附加参考文件）为 Skill 单元，上传后注入对应 agent 扩展其分析能力（如「Java SSRF 链路审计要点」「PHP 反序列化模式」）：① 分配——按 agent 指派并设默认启用集，单次扫描可临时增减（`scan --skills` / WebUI 勾选）；② 生效——agent 有效上下文 = 生效版 Prompt + 该 agent 已启用 Skills 正文；③ 管理——WebUI 上传/启停/版本管理与回滚，CLI 第 8 命令 `codesentry skills`（list/upload/enable）支持脚本化同步；④ 可复现——Skill 版本化入库，扫描记录所用 Skill 及版本快照 |
| FR-13 | PoC 生成与验证（已确认） | 审计产出的 finding 需附**利用链路**（污点源 → 传播 → 汇聚步骤）与**分级可执行 PoC**，CLI 与 WebUI 同等支持：① 分级——按 finding 类型选形态：HTTP 类接口洞出可直接发送的 HTTP 请求序列（curl/脚本）；本地类漏洞（如 SQL 注入）出 payload 与注入点及本地函数调用 PoC；② 试跑——`CODESENTRY_POC_RUN=off|sandbox|target`（默认 **off**：只生成不执行）；显式开启时仅允许对用户自备环境执行（sandbox 档：平台内置隔离验证容器——网络默认禁用、文件系统临时目录隔离；target 档：用户显式指定的自备环境），全程记录执行日志并回填结果；③ 判定——三档：**verified**（PoC 试跑成功）/ **plausible**（链路闭环但未执行或未能确认）/ **false_positive**（验证失败降级）；报告与 SARIF（property 承载级别与 PoC 路径）显著标注；④ 呈现——报告内嵌利用链路 + PoC 源码；PoC 脚本独立存扫描工作目录（挂载盘），WebUI finding 详情页展示链路与 PoC 并可下载/复制 |
| FR-14 | PoC 合规与安全（已确认） | PoC 仅用于**用户自有目标/授权靶场**的验证；平台产出物与文档明示授权边界；PoC 试执行仅在 `POC_RUN` 显式开启时发生（默认 off），sandbox 档出网默认禁用 |

### 2.2 非功能需求

- **NFR-1 语言支持（已确认）**：v1 覆盖 **Python、Java、JS/TS、Go、C/C++、PHP** 六门；各引擎覆盖度见 §4.2，弱组合在 M1 实测并标注降级策略
- **NFR-2 可复现**：同一仓库 + 同配置下路由路径可复现（LLM 温度默认 0，已确认）；复现要素含 Prompt 版本号 + Skill 版本快照 + agent 配置快照（随扫描落库）
- **NFR-3 数据本地化**：代码、向量、结果全部存本地 PostgreSQL（Docker 挂载盘）；代码不外发，仅 LLM 请求按需携带必要片段
- **NFR-4 部署**：`docker compose` 一键起数据库；应用可裸跑（Python venv）或容器化；Joern 需 JDK 17+
- **NFR-5 合规**：依赖引入前做许可证检查（脚本进 CI），红线见 §3

### 2.3 范围外（v1 不做，已确认）

SCA 依赖漏洞、容器/IaC 扫描、DAST、多租户 SaaS、IDE 插件、自动修复补丁、Skill 内可执行脚本（Skill 仅限声明式文本包，见 FR-12；可执行能力列为 v2+ 评估项，需先解决沙箱）、WebUI 多用户认证体系（v1 面向本地/内网单人使用，见 §11 风险；认证授权为 v2 首批候选）。~~PR 增量审计~~ 已提入 v1（FR-10）。

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
| React / Ant Design / FastAPI | MIT / MIT / BSD 等宽松协议 | WebUI 技术栈（D16），分发合规 |
| vulnhuntr | AGPL-3.0 | **仅借鉴思路**（迭代上下文扩展、两段式分析、置信度评分），不复制任何代码 |
| CodeSentry 自身 | **Apache-2.0（已确认）** | 自研查询/规则/代码均为原创；不移植 CodeQL 查询逻辑 |

**红线清单（CI 检查项）**：发行物中不含 CodeQL CLI 二进制；不含官方 semgrep 规则文件；依赖清单逐项记录 license 字段并阻塞不合许可的引入。随包附带的自研 Skill 全部原创（Apache-2.0）。

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
| **Claude Code Skills 机制**（行业实践参考） | — | SKILL.md 包形态（frontmatter + 渐进式披露：按需加载参考文件）作为 Skill 单元设计参照 | 仅借鉴包格式思想，非代码依赖 |

**相对上述项目的升级点**：中心化编排 + 统一预算熔断；三引擎许可分流（现有项目均无此问题域）；引擎 finding 与 RAG 证据双通道融合 triage；checkpointer 全程可回放；**agent 全量管理控制台 + Skill 可插拔能力层（含版本化，现有开源同类均缺）**。

## 6. 总体架构（第三步：中心化多 agent 设计）

```mermaid
flowchart TD
    CLI[CLI 层 Typer<br/>init-db / scan / diff / report / kb / engines / agents / skills] --> ORCH
    WEB[WebUI（M5）FastAPI + React + AntD<br/>扫描管理 · finding 审阅 · agent 控制台<br/>复核队列 · Prompt/Skill 版本管理] --> ORCH

    subgraph ORCH[LangGraph 中心编排：共享状态 AuditState + Supervisor + 预算守卫]
        SUP[Supervisor（中心决策点）]
        A1[ReconAgent 仓库画像]
        A2[ScanAgent 引擎调度+许可Gate]
        A3[RetrievalAgent RAG 检索]
        A4[TriageAgent 验证降噪]
        A5[ReportAgent 报告生成]
        A6[PoCGenAgent PoC 生成+验证]
        SUP <--> A1 & A2 & A3 & A4 & A5 & A6
    end

    A2 --> ENG[引擎层：CodeQL（仅OSS）· Joern CPG/数据流 · Semgrep 规则扫 · tree-sitter AST 切块]
    A2 --> DB
    A3 --> DB
    A4 --> DB
    A6[PoCGenAgent PoC 生成+验证] --> DB
    SUP --> DB
    A4 & A6 --> LLM[LLM API（OpenAI 兼容抽象 / 本地 vLLM）]
    A3 --> EMB[Embedding 双通道：OpenAI 兼容接口 / 本地 bge-m3（挂载盘）]
    SUP --> LLM

    subgraph DB[(PostgreSQL 16 + pgvector 单实例分 schema，Docker 挂载盘)]
        T1[scans / findings + PoC / budget_ledger / node_runs 遥测]
        T2[code_chunks 代码向量]
        T3[kb_chunks 知识库 + vuln_cases 历史案例 + audit_patterns 漏洞模式 + scan_strategies 策略库]
        T4[agent_configs / prompt_versions / skills]
        T5[LangGraph checkpoints]
    end
```

**中心化原则（已确认：混合编排）**：所有 agent 是无自主路由的「专家节点」，只接收 Supervisor 指令、只读写共享 `AuditState`，无 agent 间点对点 handoff。主链路为**确定性状态机**；仅在异常情形（证据不足需补查、引擎结论冲突）由 LLM Supervisor 介入动态调度，且始终受预算守卫约束。收益：预算单点管控、行为可审计、失败可回放。

**Agent 定义与 Prompt 加载（已确认）：** agent 注册表（清单/职责/可用工具/默认模型分配）以代码内常量维护并同步进 `agent_configs` 表；**数据库 `prompt_versions` 为生效源**（按 agent + 版本），代码内种子仅用于初始化，文件系统作备份导出（`codesentry skills`/`report` 同源读取）。WebUI 修改后下个扫描生效，进行中的扫描不中断。

**Skill 注入（已确认）：** Skill 生效集 = 「按 agent 指派的默认启用集」⊕「本次扫描覆写」；注入方式为拼接进 agent 的 system 上下文（生效 Prompt 之后、用户输入之前），参考文件采用渐进披露——Skill 正文引用的附加文件按需读入，避免无关内容占预算；**单个 Skill 正文上限 8K token、单 agent 单次注入总量上限 32K token**（超限告警并截断，环境变量可调）。Skill 启停/上传同 Prompt：下个扫描生效。

## 7. 多 Agent 详细设计

### 7.1 共享状态 `AuditState`（TypedDict）

`repo_path`、`license_declaration`（oss/proprietary + 声明时间戳）、`diff_scope`、`profile`、`engine_findings[]`、`triaged_findings[]`、`evidence{finding_id: 调用链+代码切片}`、`poc_results{finding_id: {exploit_chain, poc_file, verdict, execution_log}}`、`budget{…}`、`prompt_versions{…}`、`skills_snapshot{…}`、`phase`、`messages[]`。

### 7.2 Agent 职责表

| Agent | 职责 | 输入 → 输出 | 可用工具 |
|---|---|---|---|
| **ReconAgent** | 语言/框架/构建识别、目录结构、入口点（路由、反序列化点、外部输入面）；增量模式下先计算 diff 可达闭包；产出画像与扫描计划；检索**策略库**相似项目的历史扫描策略辅助定计划 | repo [diff_scope] → profile | 文件遍历、tree-sitter、启发式规则、scan_strategies 检索 |
| **ScanAgent** | 执行许可 Gate（FR-3）；按 §4.1 策略并行调度引擎；结果归一为统一 Finding（CWE、source/sink、置信度初值） | profile + license → engine_findings | codeql/joern/semgrep 子进程、SARIF 解析 |
| **RetrievalAgent** | 为候选 finding 拉取语义上下文：相关函数切片、相似历史漏洞、知识库条目 | findings + 问题 → evidence | pgvector 混合检索、代码读取 |
| **TriageAgent** | 可达性验证与误报判别（vulnhuntr 思路：按需迭代拉取调用链直到闭环）；检索**历史漏洞案例库**比对相似案例辅助判别；输出 保留/降级/否决 + 置信度 + 证据链。**Skill 主要消费者**（领域审计模式、误报特征库） | findings + evidence → triaged_findings | LLM（深度模型）、pgvector（code/kb/vuln_cases/audit_patterns 四库检索）、代码读取、链路追踪 |
| **PoCGenAgent**（新增） | 对保留的 finding（尤其 high/critical）生成**利用链路**与**分级可执行 PoC**（FR-13）；检索**历史漏洞案例库**相似案例的 PoC 作为模板；`POC_RUN` 开启时构造请求/调用并执行（sandbox/target 档），解析结果回填 verified/plausible/false_positive 判定与执行日志 | triaged_findings → findings + exploit_chain + poc{file, execution_log, verdict} | LLM（深度模型）、HTTP 客户端（仅在授权环境）、沙箱执行容器、vuln_cases 检索 |
| **ReportAgent** | 去重合并、严重度/置信度排序、生成中文 Markdown + SARIF | triaged_findings → 报告文件 | 模板渲染 |

### 7.3 路由策略（已确认：混合编排）

- **确定性主链路**：`recon → scan → (retrieval → triage → poc_gen[已保留 finding]) × N → report`
- **LLM Supervisor 介入点**：① TriageAgent 报告「证据不足需补查」；② 引擎间结论冲突（如同一点位 CodeQL 报/Joern 不报）；③ 主链路某 agent 失败需重规划
- **预算守卫（已确认默认值）**：`MAX_TOKENS=500000`、`MAX_TOOL_CALLS=500`、`MAX_COST_USD=10`、`MAX_FINDINGS=200`（环境变量可覆写，WebUI 亦可按 agent 覆写）；达 80% 预警、100% 熔断进入报告阶段（按已验证结果降级出报）；台账写 PostgreSQL `budget_ledger`
- **持久化**：LangGraph `PostgresSaver`（**单实例分 schema**，已确认；业务表与 checkpoint 分 schema 隔离）；`HUMAN_REVIEW=true` 时 report 节点前 interrupt，恢复由 WebUI 复核队列触发（FR-9）
- **遥测（已确认：台账直写 PG）**：节点起止时间、耗时、token 消耗、工具调用次数、状态与错误，每节点结束时写 `node_runs` 表；WebUI 轮询读取，不引入消息队列/时序库

## 8. 数据架构

- **部署（已确认）**：`pgvector/pgvector:pg16` 镜像**单实例**，业务 schema 与 LangGraph checkpoint schema 分层隔离；数据目录绑定挂载盘（`CODESENTRY_PGDATA_HOST`，如 `/mnt/data/codesentry/pgdata`）；Joern CPG 与扫描工作目录同落挂载盘（`CODESENTRY_WORK_DIR`）
- **核心表**：`projects`、`scans`（含 license 声明、扫描模式 full/diff、Prompt 与 Skill 版本快照）、`findings`（引擎原始 + triage 结论 + 置信度 + 证据 JSON + **PoC 字段**：exploit_chain JSON、poc_path、verdict、execution_log）、`code_chunks`、`kb_chunks`、**`vuln_cases`（历史漏洞案例：含利用链/PoC/修复，向量字段）**、**`audit_patterns`（漏洞模式与规则模板语料，向量字段）**、**`scan_strategies`（历史扫描策略与配置，向量字段）**、`budget_ledger`、`node_runs`、`agent_configs`、`prompt_versions`、`skills`/`skill_versions`/`skill_assignments`；checkpoint 表
- **RAG 切块（已确认）**：AST 函数/类粒度（tree-sitter，借鉴 RepoAgent）；向量 = 代码摘要 + 签名 + 调用关系
- **Embedding（已确认：双通道兼顾）**：提供统一 Embedding 接口层——① OpenAI 兼容远程接口（`CODESENTRY_EMBEDDING_MODEL` 可配）；② 本地部署 bge-m3（模型文件落挂载盘，经 vLLM/Ollama/自托管推理服务暴露，同样走 OpenAI 兼容协议）。二者按配置切换，维度入库时自动探测
- **知识库**：CWE/OWASP 官方公共资料 + 用户自有安全规范；`codesentry kb import <dir>` 导入
- **Skill 存储（已确认）**：正文与参考文本入库（`skill_versions`，含内容哈希）；二进制大文件（图片等）落挂载盘文件区，表存引用路径

## 9. 技术栈与里程碑

- **Python 3.11+**；uv 管理依赖；ruff + mypy；pytest
- **核心依赖**：langgraph、langchain-core、psycopg[binary]、pydantic v2、typer、rich、tree-sitter；外部二进制：JDK 17+（Joern）、用户自装 CodeQL；WebUI：FastAPI + React + Ant Design（已确认）
- **CLI 命令（已确认，第八命令随 FR-12 新增）**：`init-db` / `scan <repo> [--oss] [--out] [--skills <name>,…]` / `diff <base>...<head> [--oss]` / `report <scan-id>` / `kb import <dir>` / `engines check`（探测三引擎与 JDK）/ `agents list` / `skills list|upload|enable`
- **里程碑**：
  - **M0 脚手架**：目录结构、docker-compose（挂载盘卷、单实例分 schema）、配置加载、CLI 骨架（八命令占位）、`.env.example` 扩展（Joern/Semgrep/Embedding 双通道/PG 段 + CodeQL OSS Gate 开关）、license 检查脚本
  - **M1 引擎集成**：三引擎并行调度 + 许可 Gate + §4.2 覆盖矩阵逐组合验证 + 统一 Finding 模型 + SARIF 导出
  - **M2 数据与 RAG**：pgvector 入库、AST 切块、Embedding 双通道、kb 导入、混合检索 API
  - **M3 多 agent 流水线**：LangGraph 全链路 + checkpointer + 预算守卫 + 节点遥测直写 `node_runs` + Prompt/Skill 注入与版本快照 + 人工复核中断 + **增量审计（diff 可达闭包）** + **PoCGenAgent（生成 + sandbox 靶场 + 三档判定与执行日志回填）**
  - **M3.5 RAG 五库（已确认五库角色）**：`vuln_cases` 历史案例库积累机制（confirmed/verified finding 自动沉淀 + 人工导入）、`audit_patterns` 漏洞模式语料化、`scan_strategies` 策略库与 ReconAgent/Supervisor 接入；**GraphRAG code_graph（v1.5 新增）**：同步抽边入库 + 图 BFS 检索 API + 接入 TriageAgent/PoCGenAgent 增强证据链 + 增量审计可达闭包升级；M2 先行交付 code/kb 双库不影响 M3 启动
  - **M4 质量评测（已确认：自建 + 公开双轨）**：六语言自建样例漏洞仓做回归基线（每语言 5–10 个真实 CVE 模式用例）；公开基准（OWASP Benchmark、NIST Juliet 等，许可逐个核实）做能力对标；统计检出/误报/漏报与成本，迭代 prompt；**自研种子 Skill 2–3 个**（如污点链审计要点）作为随包 Apache-2.0 示例
  - **M5 WebUI（v1 交付，已确认全量 agent 管理 + Skill 管理）**：FastAPI + React + AntD——
    - 扫描管理：发起全量/增量扫描（含 Skill 临时勾选）、进度查看、报告展示（SARIF/Markdown）
    - finding 审阅：证据链查看、严重度/置信度标注、**利用链路与 PoC 查看/下载/复制、PoC 执行日志与三档判定展示**
    - **agent 控制台**：agent 清单与健康、运行拓扑图 + 节点时间线（轮询刷新）、token/成本/预算消耗统计、按 agent 模型分配与预算覆写、启停
    - **Prompt 管理**：在线编辑、版本列表与 diff 对比、一键回滚（版本入库，扫描记录所用版本）
    - **Skill 管理**：上传（SKILL.md 包解析校验）/启停/按 agent 指派默认启用集/版本列表与回滚
    - **人工复核队列**：interrupt 恢复、逐条通过/驳回/调整置信度
  - **v2 候选**：WebUI 认证与多用户、PR 平台集成（GitHub/GitLab App）、自动修复闭环、SCA/IaC、Skill 内可执行脚本（沙箱方案评估）

## 10. 错误处理与测试要点

- 引擎子进程超时/崩溃 → 记录并以其余引擎结果继续；三引擎全失败 → 中止该扫描并落因
- LLM 调用失败 → 指数退避重试 3 次，仍失败则该 finding 标「未验证」保留引擎原始结论
- PoC 生成失败 → finding 保留、verdict 标 plausible 并注明生成失败原因；试跑失败 ≠ false_positive（区分「PoC 无法构造」与「 PoC 执行后确认不可利用」）；`POC_RUN=off` 时所有 finding 最高只到 plausible
- 沙箱逃逸/危险 payload 防护：sandbox 档默认禁出网、临时文件系统；PoC 试跑前做危险模式静态检查（如 rm 类、反弹 shell 模板）并拒绝
- Prompt 版本校验：生效版本缺失/损坏时回退到代码内种子 Prompt 并告警（WebUI 标红）
- Skill 校验：SKILL.md frontmatter 缺失/格式非法/超限（8K 正文上限）→ 拒绝入库并明确报错；生效 Skill 集缺失时按无该 Skill 继续 + 扫描元数据标注
- 测试：Finding 归一化单测；许可 Gate 单测（闭源声明时禁用 CodeQL）；diff 可达闭包单测；Prompt/Skill 版本解析、注入与回退单测（含超限截断）；pgvector 检索集成测试（testcontainers）；六语言小型样例仓端到端测试；LLM 逻辑用录制回放（mock）测试；WebUI API 契约测试

## 11. 风险

| 风险 | 缓解 |
|---|---|
| Joern 对 Go/PHP/Python 前端较新，解析质量待验证 | M1 逐组合实测（§4.2）；弱前端场景降级为 Semgrep + LLM，并在报告元数据标注 |
| CodeQL 许可 Gate 被绕过/误用（闭源仓库误开 CodeQL） | Gate 由 ScanAgent 强制执行（不依赖用户自觉）；声明与台账落库可审计；发行物不含 CodeQL |
| LLM 误报/漏报抖动 | 温度 0 + 确定性主链路 + 置信度阈值出报 + 人工复核开关 |
| 成本失控 | §7.3 硬预算熔断（环境变量 + WebUI 覆写双通道，取更严者生效）；Skill 注入设 token 上限（§6） |
| Skill 内容质量参差/误导 agent（上传了低质量 Skill 反而抬高误报） | M4 评测基线可对比开/关 Skill 的指标变化；Skill 有版本回滚；扫描记录版本快照可归因 |
| Semgrep 规则合规误用 | 规则仅经用户配置路径加载，发行物零内置（CI 检查） |
| 公开评测基准许可不一（Juliet 属 NIST 公有领域，OWASP Benchmark 为 MIT，需逐个核） | M4 引入前逐项做许可核验，核验记录入库 |
| WebUI 无认证（v1 面向本地/内网） | **默认绑定 0.0.0.0（已确认）以兼容容器部署**，但文档/启动日志显式警示：无认证状态下暴露 0.0.0.0 的风险由部署者承担；认证体系列为 v2 首批 |
| PoC 被误用于未授权目标 | FR-14：默认不执行（POC_RUN=off）；sandbox/target 双重授权 + 执行日志审计；文档明示授权边界 |

## 12. 决策记录（2026-10-18 与需求方逐项确认）

| # | 决策项 | 结论 |
|---|---|---|
| D39 | GraphRAG 落地 | 路线 A（代码调用图）：tree-sitter 抽边 → PG `code_graph` 节点/边表（递归 CTE，不装图数据库）；Triage/PoC 沿图 BFS 取证据；增量闭包升级真调用图闭包（2026-10-18 确认，先 A 后议 B 知识图谱 v2） |
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
| D12 | 增量审计形态 | CLI 本地 diff + CI/CD 集成（退出码/SARIF 产物）+ WebUI 查看（M5 随 v1 交付） |
| D13 | CLI 命令集 | 七命令：init-db / scan / diff / report / kb import / engines check / agents list |
| D14 | 预算与开关默认值 | 预算四项按默认；HUMAN_REVIEW 默认关；LLM 温度默认 0（均环境变量可覆写） |
| D15 | Java 分析模式 | 源码级 + 可选构建（用户可配构建命令，CodeQL autobuild 可选） |
| D16 | WebUI 技术栈 | FastAPI + React + Ant Design（M5 随 v1 交付） |
| D17 | 评测基线 | 自建六语言样例仓（回归基线）+ 公开基准（能力对标）双轨 |
| D18 | PostgreSQL 拓扑 | 单实例分 schema（业务与 checkpoint 分层），数据全部落挂载盘 |
| D19 | WebUI Agent 管理深度 | **全量管理含 Prompt**：监控 + 运行时配置（模型分配/启停/预算）+ Prompt 在线编辑/版本化/回滚 |
| D20 | 人工复核入口 | 进 WebUI 待复核队列（逐条证据链查看，通过/驳回/调置信度，确认后恢复流水线） |
| D21 | 运行可视化 | LangGraph 拓扑图 + 节点时间线（状态/耗时/工具调用/预算，轮询刷新） |
| D22 | 遥测存储 | 台账直写 PostgreSQL（`node_runs` 表），不引入消息队列/时序库 |
| D23 | Skill 包形态 | SKILL.md 目录包：frontmatter 元信息 + 指令正文 + 附加参考文件（渐进披露）；不含可执行脚本（v1） |
| D24 | Skill 分配 | 按 agent 指派 + 默认启用集，单次扫描可临时增减（CLI `--skills` / WebUI 勾选） |
| D25 | Skill 管理入口 | WebUI（agent 控制台同区）+ CLI 第 8 命令 `codesentry skills`（list/upload/enable，供 CI/CD 脚本化） |
| D26 | Skill 版本化 | 版本化入库 + 扫描记录 Skill 版本快照（同 Prompt 机制，支撑 NFR-2 可复现），WebUI 支持回滚 |
| D27 | PoC 深度 | 分级可执行 PoC：HTTP 类出请求序列，本地类出 payload+注入点+本地调用 PoC；生成后由验证环节确认可用性 |
| D28 | PoC 执行策略 | `POC_RUN=off|sandbox|target`（默认 off）；开启后仅限平台内置隔离 sandbox（禁出网/临时文件系统）或用户显式指定自备环境；全程执行日志 |
| D29 | PoC 与报告关系 | 三档判定 verified/plausible/false_positive 进报告与 SARIF property；不强制所有 finding 带 PoC（无 PoC 的最多 plausible） |
| D30 | PoC 呈现 | 报告内嵌链路+PoC 源码；脚本独立存挂载盘工作目录；WebUI 详情页查看/下载/复制；CLI 与 WebUI 同源同权 |
| D31 | RAG 角色定位（修正） | RAG 为**审计大脑**五库：code_chunks + kb_chunks + **vuln_cases（历史案例复用：指导 triage 与 PoC 生成）** + **audit_patterns（漏洞模式/规则语料，主动反哺判断）** + **scan_strategies（策略库，指引 Recon/Supervisor 编排决策）** |
| D32 | PoC 合规 | FR-14：仅用于用户自有目标/授权靶场；默认 off；sandbox 禁出网；文档明示授权边界 |
| D33 | Prompt/Skill 生效源 | 数据库为生效源（版本化 + 回滚 + 扫描快照）；代码内种子仅初始化；文件系统作备份导出 |
| D34 | Skill 注入上限 | 单 Skill 正文 ≤ 8K token、单 agent 单次注入总量 ≤ 32K token，超限告警截断，环境变量可调 |
| D35 | Skill 大文件存储 | 文本入库 + 二进制大文件落挂载盘文件区（表存引用路径） |
| D36 | WebUI 默认监听 | 默认 0.0.0.0（容器部署开箱可用）；无认证风险由部署者承担，文档/启动日志显式警示；认证为 v2 首批 |
| D37 | 执行流程 | 8 步标准流水线（需求确认→spec→spec审计→多agent并发→codereview→修复→全量测试→归档），**每里程碑一轮** |
| D38 | 归档上库 | git commit + push 远程；远程地址待需求方提供 |

## 13. 参考资料（调研来源）

- CodeQL CLI 许可条款（开源免费 / 闭源需商业授权）：https://github.com/github/codeql/blob/main/README.md
- Semgrep CLI（LGPL-2.1）：https://github.com/semgrep/semgrep
- Semgrep 规则许可（仅内部业务使用，禁竞争产品/SaaS）：https://docs.semgrep.dev/licensing
- Joern（Apache-2.0，CPG）：https://github.com/joernio/joern
- vulnhuntr（AGPL-3.0，LLM 迭代审计思路）：https://github.com/protectai/vulnhuntr
- RepoAgent（Apache-2.0，AST 切块）：https://github.com/OpenBMB/RepoAgent
- ZeroPath（商业产品流程参考）：https://zeropath.com/
- Team-Atlanta / Atlantis（AIxCC 获奖系统组件）：https://github.com/orgs/Team-Atlanta/repositories

---

## 14. 里程碑状态表（§0 第 8 步回填区）

| 里程碑 | 状态 | spec/计划 | 实测验证 | commit |
|---|---|---|---|---|
| M0 脚手架 | ✅ 完成 | doc/2026-10-18-m0-scaffold-plan.md | compose 起库（挂载盘）/八命令/红线脚本/27 tests | e6fac5b…e16fed6 |
| M1 引擎集成 | ✅ 完成（含 M1.5 真实现升级） | doc/2026-10-18-m1-engines-plan.md | 覆盖矩阵 11 pass+1 xfail(php2cpg 实验性崩溃→降级 Semgrep)；Joern 六语言实测；双引擎交叉印证（line11 同点位双报）；SARIF/MD 双报告实产出 | da9b006…b1e301d |
| M2 数据与 RAG | ✅ 完成 | doc/2026-10-18-m2-data-rag-plan.md | pgvector 双库+混合检索（中文 FTS 命中实测）；kb import 幂等；Embedding 双通道 | c37b332…5432030 |
| M3 多 agent 流水线 | ✅ 完成 | doc/2026-10-18-m3-multiagent-plan.md | LangGraph 六节点全链 CLI 端到端（scan_id=32 全 node_runs ok、findings 落库、snapshot 落盘）；human_review interrupt+resume；diff 闭包；PoC 三档+POC_RUN gating+危险 payload 拒绝；120+ tests 绿 | 785edc6…4e339a5 |
| M3.5 RAG 五库+GraphRAG | ✅ 最小闭环（2026-10-22） | doc/2026-10-22-rag-experience-spec.md | vuln_cases/audit_patterns/scan_strategies + code_graph(BFS)；Retrieval→Triage/PoC/Recon 接入；复核沉淀；仅 Python 图/无向量重排 | 本轮提交 |
| M5 WebUI | ✅ 完成（v1 全面板） | docs/superpowers/specs/2026-10-19-webui-m5-design.md | FastAPI+React+AntD 三源上传（zip 防穿越/git https/粘贴diff）+后台 graph 全链+WS 时间线；图审阅页（G6 callgraph/源码切片/污点播放/CWE过滤）；agent 控制台+Prompt/Skill/规则管理（validate/版本化/回滚）+复核队列 resume+settings API key 管理（掩码+连通测试）；web 测试 37 绿（e2e+admin），全套 147 | （本 commit） |
| M4 质量评测 | ✅ 完成（v1 口径：semgrep+LLM triage denoise） | doc/m4-bench-report.md | 自建六语言 24 样例（15真/9净）引擎层+全链零漏报零误报；OWASP BenchmarkJava 抽样 106 例 recall 91%；真仓降噪 cryptography 86% / zaproxy 56% / DVWA 安全实现正确 REJECT；`codesentry bench`/`bench-top` 命令；LLM token 回流 budget_ledger；bge-m3 部署挂载盘（ollama 1024维实测） | c613025…（本 commit） |
| M6.0 基线收口 | ✅ 完成（2026-10-20） | doc/2026-10-20-m6.1-platform-foundation-spec.md | SPA 路由回归修复；硬编码密钥移除；pytest pythonpath / web_bind 回环默认 | 本轮提交 |
| M6.1 平台基座 | ✅ 完成（2026-10-21） | doc/2026-10-20-m6.1-platform-foundation-{spec,plan,architecture}.md + -agent-verification + 两轮 review 报告 | LLM Profile（加密/掩码/默认/fallback/OpenCode Go 双协议）+ Agent 绑定/能力矩阵 + Prompt/Skills 注入与扫描快照固定 + llm_usage（含失败记录）+ config_audit + 最小认证/JWT/API Token/RBAC/WS 4401 + LangGraph registry + Send 并行/checkpointer 恢复/interrupt-resume/state-history/artifacts 内核测试；真实 OpenCode Go 冒烟通过（triage keep/0.95，绑定→注入→用量）；最终回归全绿（含 8 项 Agent 基座专项 + 多层协同 e2e）| 本轮提交 |
| M6.2 沙箱部署 | ✅ 完成（默认部署；host/internal；Dockerfile/配方；嵌套根/端口；清理） | doc/2026-10-22-agent-flow-poc-verification-spec.md | scan 612/637 `ready`；637 端口仅 127.0.0.1；target 200；清理 | 本轮提交 |
| M6.3 PoC 实证 | ✅ 完成（PoC 自身 canary 占位符；cmd/fs/listener） | 同上 | 真实 scan 613 canary 回显命中 nonce，method=canary | 本轮提交 |
| M6.4 审查链/置信度 | ✅ 完成（artifacts 哈希链/校验 API、tool_trace、四层置信度/校准 API、审查链 UI） | 同上 | 真实扫描 594 7 节点链校验；篡改检测/置信度单测 | 本轮提交 |
| M6.5 Vue3 控制台 | ✅ 完成（17 视图/16 路由、审查链 tab、实时 Agent 事件、finding 工具轨迹/置信度） | web/frontend、src/codesentry/web/static | 静态路由/资产测试；npm build 通过 | 本轮提交 |
| M6.6 Prompt/编排/CI | 部分完成（Prompt eval 记录、graph_templates、SARIF、replay、webhook HMAC、工具循环） | 同上 | 控制面 API/工具循环/webhook 测试；A/B 自动评测与编排 UI 待续 | — |
| M6.7 P1/P2 | 部分完成（usage/audit/health/artifacts 页面；通知/多租户/AI 辅助待续） | requirements-v2 §5.2 | 按 P1/P2 排期 | — |
