# P2 安全扩展 Review 2（安全/边界）

| # | 检查项 | 结论 |
|---|---|---|
| 1 | 反弹/交互 shell | **未实现**；`check_payload_safety` 继续拒绝 `bash -i`、`/dev/tcp`、`nc -e`；新增测试覆盖 |
| 2 | 远程 PoC | 默认关闭；仅 HTTPS/白名单/未过期/非私网；probe 只 GET `/`、5s、不跟随重定向、不执行 payload |
| 3 | CodeQL 自动下载 | 默认关闭；必须 `license_ack`；仅官方 GitHub release；拒绝重定向/路径穿越/链接；SHA 可选；安装后版本验证 |
| 4 | 依赖镜像 | 不走 `allow_remote` 绕过；`never` 缺失直接 degraded；依赖容器 cap_drop/no-new-privileges/不发布端口 |
| 5 | 自动修复 | 只返回 patch/写 finding 字段，不写源码；危险命令拒绝 |
| 6 | 密钥 | CodeQL SHA/安装目录不是密钥；远程 target 无凭据字段；无新增硬编码 secret |
| 7 | 权限 | `/api/poc-targets` admin；fix 接口归 analyst；install 归 `/api/engines` 写 admin |
| 8 | 审计 | CodeQL 安装写 config_audit；target 创建写 config_audit；fix 生成写 config_audit（失败不阻塞） |
| 9 | 清理 | 依赖容器/网络随 scan 清理；目标镜像清理沿用生命周期 |
| 10 | 资源 | 依赖 256MB 限制；health 最长 90s；probe 5s；fix 源码窗口 ±40 行 |

## 明确拒绝

- 交互式 shell
- 反弹 shell
- 远程任意利用/批量目标/持久化
- 静默绕过 CodeQL 许可
- 自动修改用户源码

## 结论

P2 安全边界通过；远程利用与 shell 能力不在实现范围。
