# 图谱核心与管理面 · 实现记录

- 日期：2026-10-23
- 规格：`doc/2026-10-22-graph-core-and-agent-platform-spec.md`
- 审计：`doc/2026-10-22-graph-core-and-agent-platform-spec-audit.md`

## 已交付

### 图谱核心（G1–G4）

| 能力 | 实现 |
|---|---|
| 六语言抽取 | `rag/extractors/`：Python / Java / JS / TS / Go / PHP / C / C++（tree-sitter） |
| 图模型 | `graph_nodes` / `graph_edges` / `graph_endpoints` / `graph_builds` / `graph_files` |
| 增量构建 | 按文件 sha256 比对；变更文件重解析；跨文件调用与导入重算 |
| LangGraph 接入 | `recon → graph_build → scan → …`；失败降级不阻塞扫描 |
| 真实检索 | 删除 `_fake_vec_for`；`code_chunks` 由 `rag/indexer.py` 写入；embedding 不可用时 FTS 降级并按维度隔离；`rerank()` 按同文件/符号/词命中加权 |
| 图查询 | `rag/graph_query.py`：邻域、路径、可达、入口、finding 子图 |
| Agent 工具 | `graph_search` / `graph_node` / `graph_neighbors` / `graph_paths` / `graph_entrypoints` |
| 图 UI | `GraphView.vue` 力导向图、类型过滤、finding 过滤、节点详情与源码切片 |

### 管理面（M1–M2）

| 能力 | 实现 |
|---|---|
| Prompt 三段式 | 可编辑正文 + 代码固定尾（`INVARIANT_MARKER`）+ 运行期变量 `{{var}}`；渲染失败回退种子 |
| Prompt 版本 | `note` / `updated_by`；`/api/prompts/{name}/vars` 与 `/preview` |
| Agent 配置 | `tools_allow` / `skills_allow` / `wrapup_prompt`；按 agent 预算覆写（总额 1.2M token / $30） |
| LLM 池 | `control/llm_pool.py`：激活链首 → priority 降序；`pool_exclude`；进程级熔断 + 落库 |
| 原始调用 | `llm_calls` 表（脱敏截断）；`/api/llm-calls` |
| 健康 UI | LLM 配置页新增「池与健康」「最近调用」，支持手动恢复 |
| Agent 白名单 UI | Agent 详情页可配置 `tools_allow` / `skills_allow` / `wrapup_prompt` |
| A/B 对比图 | Prompt 页新增 `EvalCompareChart`（Recall/Precision/FP/ECE 分组柱+线） |
| 知识库运营 | 新增 `/kb` 页面：来源列表、切块预览、重建索引、导入、检索、删除 |
| 报告修复建议 | `Finding.fix_advice` 落库并渲染到 Markdown 明细 |

## 验证证据

- 后端：`282 passed, 2 skipped, 1 xfailed`；`ruff` 与 `mypy` 全绿。
- 前端：`npm run build` 通过（Vue 3 + vue-tsc）。
- kvf-admin（Java/Spring，311 个源码文件）真实构建：
  - 21.3s；节点 5,782；边 12,087；接口 95；解析失败 0。
  - 权限分布：内部接口 56，管理员权限 39。
  - 图查询可按接口定位函数、拉取二跳邻域与调用边。
- 真实扫描（`POC_RUN=off`）：recon → graph_build → scan → retrieval → triage → deploy → poc_gen → report 全节点 ok；Joern 产出 8 条高危 sink（CWE-78/22），文件路径已相对化。
- 合成漏洞样例（Spring `@RequestParam` → `Runtime.exec`）：图含 source/sink/taints_to；Triage `keep` 0.80；PoCGen 输出 3 步利用链与可执行 bash PoC（canary 占位符），落盘路径写入 findings。
- kvf-admin 的 Joern sink（`getInputStream`/`readString`）被 Triage 判定为误报，符合降噪预期。
- 降级策略：Triage 在缺少污点路径/证据时把 LLM 的 `reject` 降为 `demote`（低置信保留），避免检索不可用时整批丢失；报告标注未验证。
- 页面冒烟：16 个 SPA 路由全部 200，首屏 JS/CSS 全部 200；18 个核心 API 全部 200；KB 导入/预览/重建/删除、Agent 白名单保存、Prompt 预览均实测通过。
- 浏览器渲染验证未完成：Playwright Chromium 下载在本机网络下 11 分钟无进度，已停止；未做截图级校验。

## 已知限制

1. 图按项目增量演进，`graph_builds` 保留统计历史但节点表不是逐版本不可变快照；扫描记录 `graph_build_id` 与统计。
2. Java 权限判定覆盖 Spring Security / Shiro / 注解；网关 YAML 与自定义拦截器尚未解析，未识别时归「内部接口」。
3. source/sink 为启发式；调用未解析数较高（Java 标准库调用），当前只计数不建外部边。
4. embedding 索引异步执行；检索在索引未完成时以图证据与 FTS 为主。
5. 六语言中 Java/Python 的路由与权限最完整；其余语言以端点与调用边为主。

## 待办

- 清理历史分析数据：`PYTHONPATH=src uv run python scripts/purge_analysis_data.py --yes`（需人工执行，安全分类器拦截自动批量删除）。
- 验证库：`codesentry_validate`（独立数据库，避免影响历史数据）。
- OpenCode Go 密钥轮换与历史清理仍需在外部控制台 / 显式授权下完成。
