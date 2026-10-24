# CodeSentry 图谱核心与管理面重建 · 设计规格

- 日期：2026-10-22
- 状态：已实现（2026-10-23，见 `doc/2026-10-23-graph-core-implementation.md`）
- 关联：`agent.md`、`doc/2026-10-22-rag-experience-spec.md`、`doc/2026-10-22-agent-flow-poc-verification-spec.md`

## 0. 结论先行

CodeSentry 的核心竞争力是「**把代码变成可检索的图**」，但当前实现是演示级：

1. **图在生产链路里从未被构建**。`db/repo.py:14 upsert_code_chunks()` 没有任何调用方；真实扫描结束后 `code_chunks` 为空。
2. **检索向量是假的**。`agents/retrieval.py:7 _fake_vec_for()` 返回 `[seed]*8`，混合检索的向量通道无效。
3. **图模型只有 Python 调用名**。`rag/chunker.py:23` 仅支持 Python；`rag/graphrag.py:31` 用 `ref.split(".")[-1]` 做同名匹配，边没有类型、没有去重、没有增量。
4. **存在两套互不相干的图**。`rag/graphrag.py` 的持久化图与 `web/graph_api.py` 按请求实时合成的图各算一套，UI 只把节点渲染成表格。
5. **Agent 不消费图**。`graph_context` 只被 `retrieval` 调用一次，triage/poc/report 都不走图。
6. **管理面是四列配置**。`agent_configs(name, enabled, model_role, budget_override)`；没有 per-agent LLM 绑定、提示词变量、工具可见性、运行上限。
7. **LLM 只有单个 fallback**。没有优先级链路、熔断、健康持久化、限流、上下文窗口判断、原始调用记录。

本规格的目标：把「图构建」升级为整条流水线的一等公民，并参照 CodeScan-Artex 的 Agent 提示词 / LLM 管理实现管理面落地产化。**不改多租户，不改静态/动态安全边界**。

## 1. 现状审计（证据）

| 能力 | 现状 | 证据 |
|---|---|---|
| 代码切块 | 仅 Python；类不拆方法；无 import/route/sink | `rag/chunker.py:23-29` |
| 切块入库 | 函数存在，无调用方 | `db/repo.py:14`；全仓 grep 无调用 |
| 向量检索 | 检索时用假向量 | `agents/retrieval.py:7-11` |
| 图节点 | 只有 function/class；`node_key=path:name` | `rag/graphrag.py:22-29` |
| 图边 | 仅 `calls`；同名首胜；重复插入 | `rag/graphrag.py:31-43` |
| 图增量 | 无；`ensure_graph` 只判断「非空即跳过」 | `rag/graphrag.py:50-62` |
| 图检索 | 无向 BFS 深度 2；无方向/边型/路径查询 | `rag/graphrag.py:65-102` |
| 图消费 | 仅 retrieval 附一个 `graph` 字段 | `agents/retrieval.py:48` |
| 图 UI | 表格；按请求现算 | `web/graph_api.py:44`、`ScanDetailView.vue:187` |
| Agent 管理 | 4 列 | `db/ddl.py:95-99` |
| Prompt | 版本/激活；无变量、无固定尾、无预览变量 | `db/ddl.py:102-110` |
| LLM | 单 fallback；无池/熔断/健康 | `db/ddl.py:153-181`、`control/profiles.py` |

## 2. 目标架构

```
recon → graph_build → scan → retrieval → triage → poc_gen → [human_review] → report
                     ↘ graph_query（agent 工具，任意节点可调用）
```

- `graph_build` 成为 LangGraph 的固定节点，位于 `recon` 之后、`scan` 之前。
- 图是**项目级快照**，扫描通过 `graph_build_id` 固定版本，保证可复现。
- 所有 Agent 通过统一只读图工具访问图，不再各自拼调用链。
- 管理面拆成三张核心表：`agents` / `prompt_templates` / `llm_profiles`（扩展），LLM 增加池化与熔断。

## 3. 代码图核心设计

### 3.1 图模型

节点类型（`node.kind`）：

| kind | 说明 | key 示例 |
|---|---|---|
| `repo` | 仓库根 | `repo:.` |
| `package` | 语言包/模块 | `package:src/main/java/com/x` |
| `file` | 文件 | `file:src/main/java/com/x/UserController.java` |
| `class` | 类/结构体/接口 | `class:.../UserController.java#UserController` |
| `function` | 顶层函数/方法 | `function:.../UserController.java#UserController.getUser` |
| `route` | 框架路由声明 | `route:.../UserController.java#GET:/api/user/{id}` |
| `endpoint` | 归一后的接口资产 | `endpoint:GET:/api/user/{id}` |
| `source` | 外部输入点 | `source:.../UserController.java#getUser.id` |
| `sink` | 危险操作点 | `sink:.../UserMapper.java#findById` |
| `dependency` | 第三方依赖 | `dependency:maven:org.x:y:1.2.3` |

边类型（`edge.kind`）：

`contains`（repo→package→file→class→function）、`imports`、`calls`、`inherits`、`implements`、`routes_to`（route→function）、`exposes`（function→endpoint）、`reads`/`writes`（函数→参数/字段）、`taints_to`（source→sink，带 `confidence` 与 `via`）、`depends_on`。

约束：

- `nodes(project, node_key)` 唯一；`edges(project, src_key, dst_key, kind)` 唯一。
- 每条边带 `provenance`（`tree_sitter` / `semgrep` / `joern` / `codeql` / `llm`）与 `confidence`。
- 行号区间必须来自 AST，不允许猜。

### 3.2 多语言抽取

统一接口：

```python
class CodeExtractor(Protocol):
    lang: str
    def extract(self, path: str, source: str, file_id: str) -> ExtractResult: ...
# ExtractResult: nodes, edges, routes, sources, sinks, imports, calls
```

实现顺序：Python（现有迁移）→ Java → JS/TS → Go → PHP → C/C++。使用 tree-sitter（`tree-sitter-language-pack` 或分语言包）。框架规则独立成 `rag/extractors/frameworks/`：

- Java：Spring `@RequestMapping/@GetMapping/@PreAuthorize`、Shiro、Servlet。
- Python：Flask/FastAPI/Django 路由与装饰器。
- JS/TS：Express/Koa/Nest 路由。
- Go：net/http、gin、echo。
- PHP：Laravel/Symfony 路由。
- C/C++：入口 `main`、危险函数表。

引擎结果作为补充而非替代：Semgrep 提供 source/sink 规则命中，Joern/CodeQL 提供数据流边；统一写入 `provenance` 字段。

#### 3.2.1 接口权限判定（Java 优先）

取值固定六档：`公开 / 注册用户 / 登录用户 / 管理员权限 / 内部接口 / 其他`。

判定优先级（首条命中）：

1. 网关白名单 / `permitAll()` → `公开`
2. 方法或类级 `@PreAuthorize` / `@Secured` / `@RequiresPermissions` / Shiro 注解 → 按表达式映射
3. 自研鉴权工具类或拦截器（按配置的实现类名匹配） → 映射
4. 路由分组 / 中间件注册范围 → 映射
5. 无任何鉴权且不在白名单 → `内部接口`

每条 endpoint 必须带 `evidence`（`file:line` + 命中的注解/配置原文）。「标注权限 ≠ 实际权限」单独标记 `mismatch=true`。其他语言先产出 endpoint 与 `permission=其他`，后续按框架补齐。

### 3.3 构建流程

```
graph_build(project, repo_path, mode=full|diff, changed_files=[]):
  1. 扫描文件清单 → 计算 file_sha256
  2. 与 graph_files 表比对 → 得到新增/修改/删除
  3. 只解析变更文件（diff 模式只解析 changed + 反向依赖闭包）
  4. 按文件替换节点/边（先删该文件旧节点与相关边，再写新）
  5. 重算跨文件边（imports/calls 目标在变更集合内）
  6. 写 graph_builds(build_id, project, git_sha, mode, stats) → 返回 build_id
```

- `graph_builds` 记录每次构建的统计：文件数、节点数、边数、未解析调用数、耗时。
- 增量基线：读取该项目**最近一次成功**的 `graph_builds`，用其 `graph_files` 比对；无基线则自动全量。
- 失败降级：`graph_build` 失败不阻塞扫描，节点写 `status=degraded`，`scans.graph_build_id` 置空；retrieval/triage 退回纯文本证据并在报告标注「图不可用」。
- 扫描的 `scans` 表新增 `graph_build_id`，产物与报告引用固定版本。
- 幂等验收：同一仓库连续构建两次，节点/边数完全一致；第二次 `parsed_files=0`。

### 3.4 存储

新增表（`db/ddl.py`）：

```
graph_builds(id, project, git_sha, mode, stats JSONB, created_at)
graph_files(build_id, path, sha256, lang, parsed_at)
graph_nodes(id, build_id, project, node_key, kind, name, path, start_line, end_line,
            qualified_name, lang, attrs JSONB)
graph_edges(id, build_id, project, src_key, dst_key, kind, provenance, confidence, attrs JSONB)
graph_endpoints(build_id, endpoint_key, method, path, permission, evidence JSONB)
```

索引：`(build_id, kind)`、`(build_id, path)`、`(build_id, src_key, kind)`、GIN(`attrs`)。热路径（可达闭包）用递归 CTE；节点数 > 50k 或单次 BFS 超过 200ms 时，构建期刷新物化闭包表 `graph_reach(build_id, src_key, dst_key, depth)`（深度上限 6，按项目可配）。

向量列：`code_chunks.embedding` / `kb_chunks.embedding` 改为带维度（如 `vector(1024)`），首次写入前校验 embedding 维度与列定义一致；不一致时拒绝写入并给出明确错误，禁止静默写入错误维度。

### 3.5 图检索 API

`rag/graph_query.py`，全部只读、带 `build_id`：

```python
node(build_id, key) -> dict
neighbors(build_id, key, depth=1, kinds=None, direction="both") -> subgraph
paths(build_id, src, dst, max_depth=6, kinds=None) -> list[path]
reachable(build_id, keys, depth=4) -> set[str]        # diff 闭包
entrypoints(build_id) -> list[endpoint]
findings_on_graph(build_id, scan_id) -> list[finding_with_path]
subgraph_for_finding(build_id, finding) -> {nodes, edges, slices}
```

REST：

- `GET /api/scans/{id}/graph?depth=&kinds=&node=`
- `GET /api/scans/{id}/graph/paths?src=&dst=`
- `GET /api/scans/{id}/graph/endpoints`
- `GET /api/scans/{id}/graph/node/{key}`（含源码切片）

### 3.6 Agent 接入

新增只读工具（沿用 `agents/tools.py` 的 tool loop）：

| 工具 | 用途 | 使用者 |
|---|---|---|
| `graph_search(q, kinds)` | 按名称/路径找节点 | 全部 |
| `graph_node(key)` | 节点详情 + 代码切片 | 全部 |
| `graph_neighbors(key, depth, kinds)` | 邻域 | triage/poc |
| `graph_paths(src, dst)` | 源→汇路径 | triage/poc |
| `graph_entrypoints()` | 接口清单 | recon/triage |
| `graph_reachable(files)` | diff 闭包 | recon |

消费约定：

- **recon**：用 `graph_entrypoints()` 产出入口清单；diff 模式用 `graph_reachable()`。
- **scan**：findings 落库后由 `graph_build` 映射到 `node_key`（`node_for_location` 改为精确匹配）。
- **retrieval**：以 `subgraph_for_finding` 为主证据，补代码切片；向量检索只作为补充。
- **triage**：必须检查 `source→sink` 路径是否可达；不可达直接降级，证据写入 `confidence_parts`。
- **poc_gen**：利用链路直接取 `paths()` 的边序列，禁止 LLM 自行编造调用链。
- **report**：报告附「图路径」段落，标注 provenance。

### 3.7 图 UI

新增 `GraphView.vue`（路由 `/scans/:id/graph`，ScanDetail 内嵌同组件）：

- ECharts `graph` 力导向布局；节点按 kind 着色，边按 kind 着色/线型。
- 左侧过滤：kind、语言、仅显示 finding 路径、仅显示未覆盖 endpoint。
- 点击节点：右侧抽屉显示源码切片、入/出边、相关 findings。
- finding 选中：高亮 `source→sink` 路径，其余节点淡出。
- 顶部统计：节点/边/未解析调用/endpoint 覆盖率。
- 大图分页/聚合：>2000 节点时按 package 折叠。

## 4. 管理面重建

### 4.1 Agent 注册表

`agents` 表替换 `agent_configs`：

```
agents(key PK, name, role, enabled, llm_profile_id, current_prompt_id,
       max_iterations, timeout_s, budget_override JSONB, tools_allow JSONB,
       skills_allow JSONB, wrapup_prompt, created_at, updated_at)
```

- `role ∈ {recon, scan, retrieval, triage, deploy, poc, report, assist}`。
- `tools_allow` 为空表示按角色默认白名单；`skills_allow` 为空表示全部已分配技能。
- 运行期 `prepare_agent()` 读该表，生成 `AgentRuntime`；扫描快照记录整行。

### 4.2 Prompt 体系（借鉴 Artex）

三段式：

```
[A] 可编辑正文   ← DB 版本化，模板变量
[B] 代码固定尾   ← 证据规约、输出 JSON 契约、安全边界；不可编辑
[C] 运行期注入   ← 技能正文、图上下文、扫描状态；按节点拼装
```

规则：

1. DB 模板与内置默认**都是模板**；渲染失败回退默认，绝不半渲染启动。
2. 变量目录 `prompt_vars(agent, name, description, example, source)`，渲染用 `missingkey=error`。
3. 种子只写一次；升级不覆盖用户编辑；版本历史含 `note/updated_by`，可回滚。
4. UI 提供变量插入、渲染预览（用真实扫描状态）、lint（长度/危险指令/JSON 契约）。
5. A/B 继续保留，`ab_arm` 写入快照。

### 4.3 LLM 池（借鉴 Artex）

`llm_profiles` 增列：`priority`、`pool_exclude`、`context_window_k`、`rate_per_second`、`rate_per_minute`、`retry_*`、`streaming`、`session_header_key`、`api_key_hint`。

新增：

- `llm_profile_health(profile_id, fails, trips, open_until, last_error, last_at)`
- `llm_calls(id, scan_id, agent, profile_id, model, request JSONB, response_preview, tokens, cost, latency_ms, ok, error)`

运行规则：

1. 链序：激活 profile 永远链首 → `priority DESC` → 同 priority 轮转。
2. `fallback_profile_id` 保留为兼容字段：非空时等价于在该 profile 之后追加一个 rank 更低的成员；池化配置优先，二者冲突以池为准并在 UI 提示。
3. 熔断：确定性错误（401/402/404）首次即熔断；瞬时错误（429/5xx/网络）连续 3 次熔断；退避 1m/5m/30m，落库跨重启。
4. **只在尚未向调用方输出任何 token 前切换**；已输出则原样上抛，避免重复内容。
5. 请求超出 profile 上下文窗口时跳过该 profile。
6. 每 profile 独立限流（令牌桶）与重试覆盖。
7. 扫描可绑定 LLM 链（`scan_llm_chain`），缺省用全局链。
8. UI：健康状态、最近错误、手动恢复、原始调用记录（脱敏后）。

### 4.4 任务与可观测

- 任务模型补齐：`scans` 增加 `goal/scope/status/paused_at/parent_scan_id`；支持暂停/恢复/取消/注入提示。
- 活动流：节点事件之外，增加 `agent_activity`（工具调用、图查询、LLM 调用摘要），SSE 推送，UI 可回放。
- 每次扫描固定：`graph_build_id`、agent 配置快照、prompt/skill 版本、LLM 链快照。

## 5. 迁移

1. 新表并存，不删旧表；`agent_configs` 数据回填到 `agents`，过渡期 `get_agent_config()` 先读 `agents`、缺失再读旧表，避免一次性改爆现有测试与调用点。
2. `chunker.py` 保留 `Chunk` 兼容层，内部改为 `extractors`；旧调用点（`recon.py`、`graph_api.py`）在 G2 一并切换。
3. `graphrag.py` 标记 deprecated，改由 `graph_build` 写入新表；旧表保留一个版本周期，`retrieval.py` 不再调用 `ensure_graph`。
4. `retrieval.py` 删除 `_fake_vec_for`，接真实 embedding；embedding 未配置时明确降级为 FTS，并在报告中标注；禁止用合成向量冒充语义检索。
5. 首次运行对现有项目做全量重建；`graph_builds` 记录基线。
6. 每个里程碑单独出实现计划（G1/G2/G3/G4/M1/M2），不合并为一份巨型计划。

## 6. 里程碑

| 里程碑 | 内容 | 验收 |
|---|---|---|
| G1 | 图 schema + Python/Java 抽取器 + 构建器 | 单仓构建出节点/边；重复构建幂等 |
| G2 | 六语言抽取器 + 增量 + LangGraph 接入 | 六语言样例各有节点/边；diff 只解析变更闭包 |
| G3 | 图检索 API + Agent 工具 + triage/poc 接入 | finding 证据含真实路径；poc 链路来自图 |
| G4 | 图 UI | 力导向图、过滤、切片、路径高亮 |
| M1 | Agent 注册表 + Prompt 三段式 | UI 编辑变量模板、预览、回滚 |
| M2 | LLM 池 + 熔断 + 原始记录 | 假 provider 故障转移测试；重启后冷却保留 |
| V1 | kvf-admin 全流程验证 | 清库后上传、扫描、图、复核、报告全通 |

## 7. 非目标

- 多租户/部门隔离。
- 把 CodeScan-Artex 作为 sidecar 接入（后续单独评估，注意 AGPL 边界）。
- 引入 Neo4j 等外部图数据库。
- 改变 PoC 安全边界（仍默认不执行、仅本地授权目标）。
- 重写报告排版与前端整体视觉。

## 8. 验收清单

- [ ] 真实扫描后 `code_chunks` / `graph_nodes` / `graph_edges` 非空，且 `graph_builds.stats` 合理。
- [ ] 同一仓库连续两次构建，节点/边数一致；第二次 `parsed_files=0`。
- [ ] 六语言样例均能产出函数节点与调用边。
- [ ] Java/Spring 样例能产出 endpoint 与权限判定（至少注解/路由分组两类依据）。
- [ ] triage 证据包含 source→sink 路径；不可达 finding 被降级。
- [ ] PoC 利用链路与图路径一致（抽样人工核对）。
- [ ] 图 UI 可加载、过滤、点击切片、路径高亮。
- [ ] Agent 页可编辑模板变量并预览；Prompt 固定尾不可被编辑删除。
- [ ] LLM 池故障转移、熔断、冷却持久化通过自动化测试。
- [ ] kvf-admin-master.zip 端到端验证通过。
