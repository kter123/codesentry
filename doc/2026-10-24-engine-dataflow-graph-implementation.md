# 引擎 Dataflow 入图 · 实现记录

- 日期：2026-10-24
- 规格：`doc/2026-10-24-engine-dataflow-graph-spec.md`
- 计划：`doc/2026-10-24-engine-dataflow-graph-plan.md`

## 已实现

| 能力 | 文件 |
|---|---|
| `dataflow` 边类型 + 图增量写入（幂等、20k 上限） | `rag/extractors/base.py`、`rag/graph_delta.py` |
| Joern CPG → calls/dataflow | `engines/joern_graph.py`、`engines/joern.py`（`cpg_path`） |
| CodeQL SARIF codeFlows → dataflow | `engines/codeql_graph.py` |
| scan 接入引擎图增量 | `agents/scan.py` |
| 路径构建消费 dataflow + entry-only | `rag/path_build.py` |
| 部署镜像策略（本地优先、显式配置、远程开关） | `config.py`、`sandbox/deploy.py`、`agents/deploy_agent.py` |
| 本地 bge-m3 embedding | `config.py`（`embedding_timeout_s`）、`rag/embedding.py` |

## kvf 实测

对最近一次 kvf CPG 运行 `run_joern_graph`：

| 指标 | 结果 |
|---|---|
| methods | 1,941 |
| calls | 364 |
| dataflow flows | 38 → 26 条去重 dataflow 边 |
| 图路径 | 189 |
| endpoint 覆盖 | **95 / 95**（含 entry-only 入口审计路径） |
| sink 覆盖 | 27 / 112 |
| dataflow 路径 | 27 |

说明：

- 没有可达 sink 的 controller 生成 `entry_only` 路径，审计入口鉴权/参数/越权，不再虚报 sink 覆盖。
- Joern `method.filename` 在 kvf CPG 上返回 `k`，已统一改用 `file.name`。

## 本地 bge-m3

- Ollama：`bge-m3:latest`，模型目录 `/Volumes/macOS/ollama-models`（5.9G）。
- CodeSentry embedding：`http://127.0.0.1:11434/v1`，model `bge-m3`，`is_local=True`。
- 实测：`dims=1024`；`index_repo` 写入 1 chunk，`embedding` 非空、维度 1024、`degraded=False`。
- 超时从 3s 调整为可配置 `CODESENTRY_EMBEDDING_TIMEOUT_S`（默认 60s），适配冷加载。

## 部署镜像

- 本机已有 `docker.m.daocloud.io/library/maven:3.8-openjdk-8`。
- `choose_java_image`：显式配置 > 本地镜像 > 远程（仅 `deploy_image_allow_remote=true`）。
- `deploy_image_pull` 支持 `never/missing/always`；`never` 不使用远程。
- DeployAgent 的 `java_images` 来自可用集合，禁止写未列出的 `openjdk:8-jre`。

## 测试

- `tests/test_engine_graph.py`：Joern 行解析、SARIF 解析、graph apply 幂等、dataflow proven。
- `tests/test_deploy_image.py`：镜像选择优先级、配置字段。
- `tests/test_embedding.py`：通道配置。
- 全量：**299 passed, 2 skipped, 1 xfailed**；ruff/mypy 绿。

## 剩余

- sink 覆盖 27/112：多数 sink 在静态 JS / ueditor 等非 controller 代码；需要更细的跨过程 dataflow 或按入口手工审计。
- 189 条路径全审成本高；当前按 batch/round 限流，优先 proven。
