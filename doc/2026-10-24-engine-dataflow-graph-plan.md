# 引擎 Dataflow 入图 · 实现计划

- 规格：`doc/2026-10-24-engine-dataflow-graph-spec.md`（必读）
- 前置：路径中心审计已落地

## 全局约束

- 引擎 dataflow 只写 `dataflow` 边，不直接产生 finding。
- 所有 graph 写入幂等、参数化、带 provenance/confidence/evidence。
- 单次引擎图增量 ≤20k 边；失败只降级。
- 部署镜像优先本地；`pull=never` 不访问网络。

---

## 任务 1：图模型与 apply

**文件**
- 修改：`rag/extractors/base.py`（EDGE_KINDS 加 `dataflow`）
- 修改：`rag/graph_delta.py`
- 修改：`rag/graph_query.py`（可选边过滤）
- 测试：`tests/test_engine_graph.py`

**接口**
```python
def apply_engine_graph(project: str, build_id: int,
                       nodes: list[dict], edges: list[dict]) -> dict
```
- [ ] 节点/边 upsert；`(src,dst,kind)` 去重；上限 20k。
- [ ] 节点解析：`node_for_location` 最小包含 → file → 新建 source/sink。
- [ ] 返回 `{nodes,edges,calls,dataflow,truncated}`。
- [ ] 测试：重复 apply 幂等；超限 truncated。

## 任务 2：Joern 图适配器

**文件**
- 创建：`engines/joern_graph.py`
- 修改：`engines/joern.py`（暴露 CPG 路径）
- 测试：`tests/test_joern_graph.py`

**步骤**
- [ ] 查询脚本输出 `JOERN_NODE / JOERN_EDGE / JOERN_FLOW`。
- [ ] 行解析器 `parse_graph_lines()`（纯函数，先测）。
- [ ] `run_joern_graph(cpg_path, repo, timeout=120)` → `(nodes, edges, stats)`。
- [ ] 查询失败/超时返回空 + error，不抛。
- [ ] 测试：样例行 → calls/dataflow 边；异常行忽略。

## 任务 3：CodeQL SARIF 适配器

**文件**
- 创建：`engines/codeql_graph.py`
- 测试：`tests/test_codeql_graph.py`

**步骤**
- [ ] `normalize_sarif_uri(uri, repo)`。
- [ ] 遍历 `codeFlows[].threadFlows[].locations[]`，相邻写 dataflow。
- [ ] 首尾补 source→sink。
- [ ] 测试：合成 SARIF → 3 条边；无 codeFlows → 空。

## 任务 4：scan 接入

**文件**
- 修改：`agents/scan.py`
- 测试：`tests/test_scan_capabilities.py`

- [ ] 保留 hints → sink。
- [ ] Joern 运行后调用 `run_joern_graph`（有 CPG 时）。
- [ ] CodeQL 结果解析 codeFlows。
- [ ] 调用 `apply_engine_graph`，统计写 `graph_delta`。
- [ ] 测试：mock 适配器 → graph_delta 计数。

## 任务 5：路径构建消费 dataflow

**文件**
- 修改：`rag/path_build.py`
- 测试：`tests/test_path_audit.py`

- [ ] `EDGE_KINDS` 加 `dataflow`。
- [ ] `feasibility=proven` 若路径含 `dataflow`/`taints_to`。
- [ ] coverage 增加 `dataflow_paths`。
- [ ] 测试：source→sink dataflow 边 → 路径 proven。

## 任务 6：部署镜像策略

**文件**
- 修改：`config.py`、`sandbox/deploy.py`、`agents/deploy_agent.py`
- 测试：`tests/test_deploy_image.py`

- [ ] 配置：`deploy_image_pull`、`deploy_java_image`、`deploy_maven_image`、`deploy_image_allow_remote`。
- [ ] `choose_java_image()`：config → local → remote（allow）。
- [ ] `pull=never|missing|always` 行为；失败 `disabled` + 镜像名。
- [ ] Agent `java_images` 来自 choose 结果。
- [ ] 测试：config 优先；local；pull never 无镜像 disabled。

## 任务 7：验证

- [ ] 合成 Joern/SARIF 单测。
- [ ] 全量 pytest、ruff、mypy、前端 build。
- [ ] kvf 重跑：记录 `engine dataflow` 边数、endpoint 覆盖、路径 proven 数。
- [ ] 两轮 review + 文档。

## 审查重点

1. dataflow 边方向与路径反向 BFS 是否一致。
2. 节点解析到错误函数时是否有 evidence 行号可发现。
3. 大量边是否被截断且报告标注。
4. `pull=never` 是否真的不访问网络。
5. 部署失败原因是否包含镜像名与来源。
