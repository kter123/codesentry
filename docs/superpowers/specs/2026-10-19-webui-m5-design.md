# CodeSentry WebUI（M5）设计规格

> 日期：2026-10-19。上游：agent.md v1.5（M5 验收项已确认）。决策记录：图库 AntV G6 v5；天马行空拓展（污点 replay / 问AI / 图diff）全入 v1；上传三源全支持（zip/tar.gz、git URL、粘贴 diff）；规则管理 UI 纳入；Skill 指派到 agent 节点运行时加载纳入。

## 一、需求（Requirements）

### R1 总体
v1 WebUI 是 LLM 多 agent 代码审计**工作台**，CLI 并存不动。六个功能面板 + 规则管理 + Skill 指派（agent.md M5 验收全项覆盖）：
1. 扫描管理：三源上传（zip/tar.gz ≤500MB 流式落 work/、git URL（https 白名单）、粘贴 diff/文本）、Skill/规则集临时勾选、发起全量/增量、进度查看（WS 时间线）、报告展示（SARIF/Markdown 下载）
2. Finding 审阅：列表（severity/cwe/verdict/confidence 过滤）、证据链、源码切片高亮、triage rationale/fix_advice、PoC 三档展示与下载
3. 调用图审阅（核心页）：GraphRAG 建图结果可视化——G6 v5 画 CALLS/CONTAINS/IMPORTS 图，节点=文件/函数/入口，finding 挂 sink 节点，污点链=source→sink BFS 路径；点节点看源码切片；点边/链看污点流
4. Agent 控制台：拓扑图+节点时间线（node_runs）、token/cost 统计、per-agent 启停与预算覆写、生效 skills 展示
5. Prompt 管理：在线编辑/版本 diff/回滚（MC Monaco diff）
6. Skill 管理：上传解析（SKILL.md 包校验）、版本回滚、**指派到指定 agent 节点、运行时注入**（UI 发扫后 prompts 拼接 skill body，扫描记录 skills_snapshot；rationale 引用 skill 内容可量化对比）
7. 规则管理：规则列表（命中统计）、YAML 编辑+`semgrep --validate` 代理、单规则试跑 preview、规则集版本化与回滚、扫描记录 rule_set_version
8. 复核队列：interrupted 扫描列表 → 逐条通过/驳回/调置信度 → resume 闭环
9. 拓展（全入 v1）：污点链 replay 动画、节点右键「问AI」（RAG+LLM 流式）、双扫描图 diff（新增红闪/修复绿闪）

### R2 非功能
- 单机模式无登录（v2）；上传大小/类型校验；切片接口防路径穿越（仅 work/{scan}/ 白名单内）；PoC 执行仍受 POC_RUN gating（UI 只展示日志不新增执行入口）；全部数据复用现有表+两处例外（rule_sets 新表、scans.rule_set_version 字段）。

### R3 依赖与退化
- 图质量依赖 M2 code_graph：语言缺抽边时退化「findings-only 图」（finding 节点+文件级边，UI 明示降级徽标），不阻塞。
- LLM 未配置时：审阅页 rationale 标「未验证」，问AI 按钮禁用。

## 二、前端页面架构

技术栈：React 18 + Vite + TypeScript + Ant Design 5 + AntV G6 v5 + zustand（状态）+ monaco-react（编辑器）。目录：`web/frontend/`；FastAPI `src/codesentry/web/`。

```
App
├─ Layout（AntD Pro 侧栏；WS 全局连接管理）
│  ├─ /scans        扫描管理页（Upload Dropzone / GitURL Tab / Diff Tab；历史卡片网格）
│  ├─ /scans/:id    扫描详情（节点时间线 Step、token/cost Summary、报告下载）
│  ├─ /review/:scanId   ★图审阅三栏页
│  │   ├─ 左：FindingList（过滤联动图）
│  │   ├─ 中：GraphCanvas（G6；污点 replay 播放条；图 difftoggle）
│  │   └─ 右：NodeDrawer（源码高亮 / rationale / fix / PoC链 / 问AI）
│  ├─ /reviews      复核队列（interrupted 列表→进 /review resume 模式）
│  ├─ /agents       Agent 控制台（SVG 拓扑 + node 时间线 + 预算表）
│  ├─ /prompts      Prompt 管理（列表+Monaco diff）
│  ├─ /rules        规则管理（列表/详情/试跑/规则集版本）
│  └─ /skills       Skill 管理（列表/上传/指派弹窗/版本回滚）
└─ components：GraphCanvas(G6 封装)、FindingTable、SourceView(切片高亮)、TaintPlayer、AgentChatDrawer、DiffViewer
```

核心组件状态流：图审阅页 store = {graphData, findings, selectedNodeId, filter{cwe,severity,verdict}, replayState}——过滤器变化触发图 highlight（不重绘），选中节点拉 `/source` 切片与 `/findings/:id` 详情。

## 三、API（FastAPI）

核心端点（实现于 `src/codesentry/web/api.py`，挂 `/api`）：
```
POST /api/scans            GET /api/scans  GET /api/scans/{id}
GET  /api/scans/{id}/graph  /findings  /findings/{id}  /findings/{id}/source?start&end
GET  /api/agents   POST /api/agents/{name}/budget
GET  /api/scans/{id}/agents/timeline
GET/POST /api/prompts, /api/prompts/{id}/rollback
GET /api/skills, POST /api/skills/upload, /api/skills/{name}/assign, /api/skills/{name}/versions, GET /api/scans/{id}/skills
GET /api/rules, /api/rules/{id}, POST /api/rules/validate, /api/rules/preview
GET/POST /api/rulesets, /api/rulesets/{id}/rollback
GET /api/reviews, POST /api/scans/{id}/resume
POST /api/agent-chat
WS  /ws/scans/{id}
```

## 四、Schema 例外

- 新表 `rule_sets(name, version, body, body_sha256, created_at)`（复用 skill_versions 同构）
- `scans` 加列 `rule_set_version TEXT DEFAULT ''`

## 五、里程碑

- **M5.1 骨架+扫描管理**：FastAPI 起、三源上传、后台 GraphRunner、WS 时间线、扫描列表/详情。验收：UI 上传 zip 全链可跑通并看时间线。
- **M5.2 图审阅页**：graph 合成 API、G6 画布、findings 联动、源码切片、污点 replay、问AI。验收：点 sink 节点见高亮源码+rationale，污点链可播放。
- **M5.3 管理面板**：agent 控制台、复核队列、Prompt/Skill/规则管理、PoC 展示、Skill 运行时注入闭环。验收：UI 一轮 编辑规则→试跑→存版本→扫描记录版本；上传 skill→指派 triage→扫描 rationale 引用→复核→resume。
