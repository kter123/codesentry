# P2 安全扩展 Plan 审计

- 日期：2026-10-25
- 结论：通过，补 6 项执行细节。

| # | 问题 | 修订 |
|---|---|---|
| 1 | 依赖容器与目标网络如果不存在，需先创建且避免 `internal=true` 阻断镜像拉取 | 网络在目标启动前创建；依赖镜像先 pull 再 `containers.run`；internal 只影响容器外联，不影响已拉取镜像。 |
| 2 | `docker_run` 需允许 env，且 Agent 工具签名变化不能破坏旧调用 | `docker_run(port=8080, env: dict|None=None)`；旧调用兼容。 |
| 3 | `ensure_dependency` 需幂等 | 同名容器存在且 running 直接复用。 |
| 4 | CodeQL 安装包解压后顶层目录名不固定 | 解压到 temp，找包含 `codeql` 可执行文件的目录，再移动。 |
| 5 | 修复建议 LLM 输出可能含 markdown fence | 提取 ```diff/unified diff，统一校验以 `---`/`+++` 开头。 |
| 6 | 远程 probe 重定向可能跳到私网 | `follow_redirects=False`；只接受 2xx/3xx，不跟随。 |

## 安全复核

- 反弹/交互 shell：不实现；现有危险模式测试补充 `/dev/tcp`、`bash -i`、`nc -e`。
- CodeQL 自动安装：默认关闭，必须 license_ack + OSS；URL 白名单 + sha。
- 远程 target：默认关闭，仅 probe，不执行 finding payload。
- 修复建议：只返回 patch，不写源码。

## 结论

按此执行；任务 1/2/3 优先，任务 4/5 随后。
