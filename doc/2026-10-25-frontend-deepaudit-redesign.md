# 前端 DeepAudit 风格重构记录

- 日期：2026-10-25
- 框架：Vue3 + Element Plus + ECharts（保持现有技术栈）
- 参考：DeepAudit 的终端信息密度、网格背景、等宽信息流；采用白色终端 + 蓝色主色，不复制其代码/视觉资源

## 已完成

### 全局设计系统

- 白色终端主题：白色/浅蓝面板、蓝色主色 `#2563eb`、青色辅助色；深色作为可切换备选。
- Element Plus CSS 变量覆盖：主色、背景、表格、输入、抽屉、Tabs、Tag、按钮。
- 全局网格背景、面板角标、发光/悬停、等宽日志字体。
- 支持深/浅主题切换（localStorage 记忆，默认白色终端）。

### 布局

- 白色 Sidebar 分组：Workspace / Control Plane / System；蓝色激活条。
- 信息架构对齐 DeepAudit：Agent 审计 / 仪表盘 / 项目管理 / 即时分析 / 审计任务 / 复核队列 / 审计规则 / Prompt / Agent 控制面。
- 品牌区、折叠、蓝色激活边、终端式菜单字体。
- 顶栏：面包屑、CONNECTED 状态灯、主题切换、本地模式、用户菜单。
- 页面标题改为 `// 标题` 终端风格。

### Agent 审计首页（新 `/`）

- DeepAudit 风格入口：导入项目、上传源码、Git/Diff、即时分析、项目管理。
- Agent 战队状态、最近审计任务、实时事件流、运行中/verified 统计。
- 原有概览迁移到 `/dashboard`「仪表盘」。

### 概览 / 仪表盘

- 新增 Graph Audit Console Hero：
  - “把代码变成可审路径，让 Agent 沿着图去验证”
  - 即时分析/新建扫描/最近工作台 CTA
  - 右侧终端状态：graph/engines/runtime/verification/queue
- 审计质量卡片：verified / plausible / rejected / 已审路径 / Harness。

### 审计工作台

- 三栏 cyber 面板：Agent 树 / 审计事件流 / 上下文。
- Agent 树按 `scan → group → node` 缩进，并新增「Agent 分析拓扑」阶段流（Recon→GraphBuild→Scan→PathBuild→Supervisor→PathAudit→Harness→Triage→Deploy→PoC→Report），点击阶段过滤事件。
- Agent 管理卡片显示 Prompt 版本；Agent 详情页内置 Prompt 编辑器，可直接保存并激活新版本，与当前 Agent 对齐。
- 事件流按类型着色：finding 红、tool 青、verification 绿、path 蓝、supervisor 紫、error 红。
- 终端等宽字体、自动滚动、过滤。
- 底部 tabs：路径 / Findings / 验证 / 工具证据 / 报告。

### 兼容

- 所有业务 API/路由不变。
- 现有测试、Playwright 21/21 通过。
- 深色/浅色 token 都保留，组件硬编码浅色背景已替换为变量。

## 验证

- `npm run build` 通过。
- Playwright 21/21 路由通过。
- 截图检查：概览、审计工作台。

## 后续可选

- 登录页/复核页的进一步终端拟态。
- 事件流虚拟滚动（当前最多 1000 条）。
- 图表色板统一到设计 token。
