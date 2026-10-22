# A3/A4 + B1/B2 双轮 Code Review

> 日期：2026-10-22。范围：Agent 过程可见（artifacts/tool_trace/WS）+ 默认 Docker 部署 + PoC canary。真实证据：scan 612/637（deploy ready、127.0.0.1 端口、target 200、清理）；scan 613（canary 回显命中 nonce）。

## 第一轮：安全 / 生命周期 / canary 语义

| ID | 发现 | 处置 |
|---|---|---|
| R1-1 | host 模式端口发布到 0.0.0.0 | **已修**：`ports={port: ("127.0.0.1", None)}`；637 实测 `127.0.0.1:57255->8080/tcp` |
| R1-2 | 部署被 `POC_RUN=off` 阻断，默认只 built | **已修**：`DEPLOY_ENABLED` 独立控制；`POC_RUN` 只管 PoC 执行 |
| R1-3 | internal 网络不发布端口，宿主健康探测失败 | **已修**：host 默认；internal 模式容器内 `exec_run` 健康探测 |
| R1-4 | canary 可由“容器能执行命令”冒充 | **已修**：PoC 必须自身包含 `{CANARY_CMD}/{CANARY_FILE}/{CANARY_URL}`；613 用含占位符的 PoC 验证 |
| R1-5 | 扫描结束不清理容器/网络 | **已修**：runner finally `cleanup_scan`；`DEPLOY_KEEP=true` 可保留；612 target 结束即关闭 |
| R1-6 | 上传源只读导致 JS 构建失败 | **已修**：语言配方复制到可写工作区；Dockerfile 用构建产物 |
| R1-7 | Docker client 默认 60s 超时 | **已修**：`from_env(timeout=max(180, timeout+90))` |

## 第二轮：兼容 / 回归 / UI / 事件

| ID | 发现 | 处置 |
|---|---|---|
| R2-1 | zip 常见单层/双层根目录识别失败 | **已修**：`resolve_project_root` 深度 1–2 |
| R2-2 | 端口写死 8080/3000 | **已修**：Dockerfile EXPOSE、app.py port 探测、`DEPLOY_PORT` |
| R2-3 | 项目自带 Dockerfile 被忽略 | **已修**：Dockerfile 优先构建 |
| R2-4 | A/B 分流拿不到 scan_id | **已修**：`_insert_scan` 先落 id，再 `build_scan_snapshot(scan_id)` 写回 |
| R2-5 | 事件总线无订阅者时泄漏 | **已修**：pump 对 `room_ids()` 全量 drain，无 room 直接丢弃 |
| R2-6 | WS 未在页面卸载时关闭 | **已修**：`onUnmounted` close + clearPoll |
| R2-7 | 审查链/tool_trace 不在 UI | **已修**：ScanDetail 审查链 tab、finding 抽屉置信度/工具轨迹/验证字段 |
| R2-8 | 旧图/旧测试被 database 变更影响 | 全量 268 passed；ruff/mypy clean；Vue build 通过 |

## 仍存在的限制（不阻塞本批）

1. `docker-compose` 多服务未支持；检测不到 Dockerfile/配方时返回 disabled + 原因。
2. Dockerfile 构建上下文未限制大小/`.dockerignore`。
3. host 模式容器仍有出网能力；严格场景用 `CODESENTRY_DEPLOY_NETWORK_MODE=internal`。
4. internal 模式 HTTP listener canary 不可达；cmd/fs 可用，host 模式全协议可用。
5. `DEPLOY_KEEP=false` 时扫描结束 target 会关闭；UI 应提示，需人工查看时设 true。
6. token 级 LLM 流式未实现，本轮是节点级事件。
7. 真实 Docker 验证使用本机镜像 `langgenius/dify-api:1.9.2`；生产应配置私有/本地镜像，避免 Docker Hub 超时。

## 验证命令

```bash
uv run pytest -q                 # 268 passed（本批全量）
uv run ruff check src tests
uv run mypy src
cd web/frontend && npm run build
```

真实联调：

- scan 612/637：`deploy_status=ready`，`target_url` 200，637 端口仅 127.0.0.1，结束后容器/网络清理。
- scan 613：`verification_method=canary`，`execution_log` 命中 `CODESENTRY-<nonce>`。
