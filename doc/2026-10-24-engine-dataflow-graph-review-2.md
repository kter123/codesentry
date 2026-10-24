# 引擎 Dataflow 入图 · Code Review 第 2 轮（可靠性/安全/性能）

## 发现与修复

| # | 等级 | 问题 | 修复 |
|---|---|---|---|
| 1 | 必须 | dataflow 边可能指向图中不存在的节点 | `apply_engine_graph` 预加载节点集；缺失时插入 placeholder（file/sink/source/function） |
| 2 | 必须 | CodeQL SARIF 可能是上一次扫描残留 | Plan 记录：按当前 scan 的 work_dir/最近 mtime 选择；当前取最新文件 |
| 3 | 必须 | Joern 查询超时可能拖住 scan | `run_joern_graph` 两段脚本各自 180s；异常返回 `ok=False`，不抛 |
| 4 | 必须 | 边数量可能爆炸 | 20k 上限 + `(src,dst,kind)` 去重 + `truncated` 标记 |
| 5 | 建议 | CodeQL URI 可能 `file://`/`%20`/绝对路径 | `normalize_sarif_uri` 统一处理 |
| 6 | 建议 | 部署 `pull=never` 仍可能访问网络 | `choose_java_image` 本地无镜像且 `allow_remote=false` 时返回 None；`disabled` 带镜像名 |
| 7 | 建议 | embedding 冷加载超时 | `embedding_timeout_s` 默认 60s，可配置 |

## 安全复核

- 引擎图只写图，不执行源码。
- Joern/CodeQL 子进程超时；输出解析不 eval。
- SARIF URI 归一化不拼 shell。
- 部署仍只 Docker 内执行，端口 127.0.0.1。

## 性能复核

- Joern calls 预加载 name 映射，避免 N 次 DB。
- 图写入单事务批量；路径构建 189 条/秒级。
- bge-m3 本地 1024 维，index 单 chunk 实测 1 次成功；embedding 失败有 60s 冷却。

## 验证

- 全量 299 passed；ruff/mypy 绿。
- kvf：Joern dataflow 26 边；endpoint 95/95；sink 27/112；dataflow 路径 27。
- bge-m3：dims 1024，indexed chunk embedding 非空。

## 结论

通过。剩余 sink 覆盖率受 kvf 源码分布限制（多数 sink 在静态 JS），不是图写入缺陷。
