# RAG 经验层（五库 + GraphRAG）规格

> 日期：2026-10-22。目标：让 Triage/PoC/Recon 复用历史案例、漏洞模式、项目策略与调用图，提升分析效率与准确度。

## 1. 数据模型

| 表 | 角色 |
|---|---|
| `vuln_cases` | 历史漏洞案例：title/cwe/lang/pattern/exploit_chain/poc/fix/source |
| `audit_patterns` | 漏洞模式与审计要点：name/lang/cwe/pattern/guidance |
| `scan_strategies` | 项目扫描策略：project_profile/languages/strategy JSON |
| `code_graph_nodes` | 代码图节点：project/node_key/kind/name/path/start/end |
| `code_graph_edges` | 代码图边：project/src_key/dst_key/kind |

## 2. 采集与检索

- `seed_experience()`：首次写入内置 SSRF/命令注入/SQLi/路径穿越模式；幂等。
- `run_retrieval`：按 finding message/cwe 检索 `vuln_cases` 与 `audit_patterns`，写入 `evidence[key]`；构建 code_graph（若空）并附带 BFS 邻居。
- `build_profile`：按 languages/frameworks 检索 `scan_strategies`，写入 `profile["strategies"]`。
- `run_triage`：把 `vuln_cases/patterns/graph` 放入 LLM 用户上下文。
- `run_poc_gen`：证据中已含历史案例/PoC 模板，供生成参考。

## 3. GraphRAG

- `build_code_graph(project)`：由 `code_chunks` 建节点（`path:symbol`）与 calls 边（call_refs → 本地符号）。
- `neighbors(project, node_key, depth)`：双向 BFS。
- `graph_context(project, path, line)`：按位置找节点并返回邻居。
- 当前仅 Python chunker 产出 code_chunks；其他语言图能力随 chunker 扩展。

## 4. 反馈闭环

- `promote_findings(scan_id, verdicts)`：把 `verified/confirmed/keep` finding 沉淀为 `vuln_cases`，`source=scan:{id}:{rule}:{file}:{line}` 去重。
- 扫描结束自动沉淀 `verified`；人工复核后沉淀 `keep`。
- API：`POST /api/scans/{id}/promote`、`GET /api/experience/vuln-cases|patterns`。

## 5. 验收

1. `search_patterns/search_vuln_cases` 命中内置/新增数据。
2. `build_code_graph` + `neighbors` 能返回调用邻居。
3. `promote_findings` 去重沉淀案例。
4. `run_retrieval` 的 evidence 包含 vuln_cases/patterns/graph；Triage 用户上下文含这些字段。
5. 全量测试、ruff/mypy 通过。

## 6. 不在本轮

- embedding 向量回填/重排（当前文本检索可用，向量字段预留）。
- 六语言 AST 图（当前 Python）。
- 知识库运营 UI（导入/切块/重建）。
- 案例审核/质量评分。
