# 引擎 Dataflow 入图与部署镜像策略 · 设计规格

- 日期：2026-10-24
- 状态：待 spec 审计
- 关联：`doc/2026-10-24-agent-led-framework.md`、`doc/2026-10-24-path-centric-audit-spec.md`

## 0. 问题

1. **kvf 入口覆盖仅 20/95**：Joern/CodeQL 目前只把“命中的 sink”写成图节点，没有把 **调用边/数据流边** 写进图。路径构建只能依赖 tree-sitter 的调用边；Java 跨文件调用未解析时，endpoint 到 sink 无路径，覆盖上不去。
2. **部署镜像源**：本机已有 Java/Maven 镜像，但外部 registry 不可达。需要把“优先本地镜像、拉取策略、失败原因”变成明确配置与行为，而不是依赖 Agent 猜测。

## 1. 目标

- Joern CPG 的调用边、参数→sink 数据流边写入图，`provenance=joern`。
- CodeQL SARIF `codeFlows` 的路径写入图，`provenance=codeql`。
- 路径构建可沿 `dataflow` 边反向/正向 BFS，覆盖 endpoint→sink。
- 部署明确“镜像选择顺序 + 拉取策略 + 失败原因”，优先本地镜像。
- 覆盖率、引擎边数量、部署镜像来源可观测。

## 2. 图模型扩展

- 新增边类型 `dataflow`（普通数据流，不代表已确认污点）。
- `taints_to` 保留为“已确认污点”；引擎数据流统一写 `dataflow`。
- 每条引擎边必须带：`provenance`、`confidence`、`evidence`（sink/source 文件行号、引擎 query/规则）。
- 节点解析顺序：`path:line` → 最小包含 function/method → file → 新建 `source/sink` 节点。
- 边去重：`(project, src_key, dst_key, kind)` 唯一。

## 3. Joern 适配器

新增 `engines/joern_graph.py`：

1. 复用既有 CPG 文件（`run_joern` 已生成）。
2. 执行增量查询脚本，输出：
   - `JOERN_NODE|method|file|line|fullName`
   - `JOERN_EDGE|calls|callerFile|callerLine|calleeName|calleeFile?`
   - `JOERN_FLOW|sinkFile|sinkLine|sourceFile|sourceLine|sourceName|sinkName`
3. 限制：最多 20k 边、单查询超时 120s；失败只降级，不影响扫描。
4. 转换为 `GraphDelta`：
   - calls：caller function → callee function（按 name/qualified name 解析；歧义跳过）。
   - dataflow：source function → sink function；若 source 是入口参数，仍以函数节点连接，路径构建再向上找 route。
   - 同时补 source/sink 节点（若图中没有）。
5. provenance=`joern`，calls 置信度 0.8，dataflow 置信度 0.7。

## 4. CodeQL 适配器

新增 `engines/codeql_graph.py`：

- 解析 SARIF `runs[].results[].codeFlows[].threadFlows[].locations[]`。
- 每个 location 的 `physicalLocation.artifactLocation.uri` + `region.startLine` 映射到函数节点。
- 相邻 location 之间写 `dataflow` 边；首尾写 source→sink 边。
- provenance=`codeql`，置信度 0.9。
- 仅 OSS 且 CodeQL 实际运行时执行；无 codeFlows 时无输出。

## 5. 写入时机

```
recon → graph_build(tree-sitter) → scan(engines)
  scan:
    1) 运行引擎，得到 EngineResult
    2) hints → sink 节点（保留）
    3) Joern/CodeQL GraphDelta → apply_engine_graph()
    4) 返回 engine_hints + graph_delta 统计
→ path_build → audit...
```

- `apply_engine_graph(project, build_id, nodes, edges)` 幂等 upsert。
- `graph_delta` 统计：`engine_nodes/engine_edges/calls/dataflow/unresolved`。

## 6. 路径构建

- `EDGE_KINDS` 增加 `dataflow`。
- 反向 BFS：`dataflow` 边可作为路径边；`feasibility=proven` 若路径包含 `dataflow` 或 `taints_to`。
- 若 dataflow source 在 controller 方法，反向 `calls/routes_to` 找到 endpoint。
- 覆盖率统计新增 `dataflow_paths`。

## 7. 部署镜像策略

### 7.1 配置

| 配置 | 默认 | 说明 |
|---|---|---|
| `deploy_image_pull` | `missing` | `never/missing/always` |
| `deploy_java_image` | 空 | 显式指定 Java 基础镜像 |
| `deploy_maven_image` | 空 | 显式指定 Maven 构建镜像；空则自动选本地 |
| `deploy_image_allow_remote` | false | 是否允许拉取远程镜像 |

### 7.2 选择顺序

1. 显式配置镜像；
2. 本机已有镜像（匹配 maven/openjdk/temurin/jdk）；
3. 远程默认镜像（仅 `deploy_image_allow_remote=true` 且 pull 策略允许）。

### 7.3 行为

- `pull=missing`：本地无镜像时尝试拉取；失败则 `disabled`，`deploy_log` 写明镜像名与错误。
- `pull=never`：本地无镜像直接 `disabled`，不访问网络。
- DeployAgent 的 `java_images` 只能来自上述可用集合；不得写未列出的镜像。
- UI/部署日志展示：`image`、`image_source=local|remote|config`、失败原因。

## 8. 验收

1. kvf 扫描后图中有 `provenance=joern` 的 calls/dataflow 边；endpoint 覆盖从 20/95 提升到 **≥40/95（相对 +100%）**；若 Joern 查询不可用则明确标注降级，不虚报。
2. 路径构建产出 `dataflow` 路径，`feasibility=proven` 数量 > 0（有引擎 dataflow 时）。
3. CodeQL 合成 SARIF（含 codeFlows）→ 图出现 codeql dataflow 边。
4. 部署：本地 Java 镜像存在时使用本地；`pull=never` 且无镜像时 `disabled` 且日志含镜像名。
5. 单测覆盖 Joern 行解析、SARIF 解析、graph apply、dataflow 路径；全量测试绿。

## 9. 非目标

- 不做完整跨过程别名分析；引擎给什么边就入什么边。
- 不引入 Neo4j。
- 不保证所有 endpoint 都覆盖；未覆盖要在报告中标注原因。
