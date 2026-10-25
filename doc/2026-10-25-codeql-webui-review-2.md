# CodeQL WebUI 接入 · Code Review 第 2 轮（安全/可靠性）

| # | 等级 | 问题 | 修复/确认 |
|---|---|---|---|
| 1 | 必须 | test 接口可能执行任意命令 | 只跑配置 binary 的 `version` / `resolve languages`，不含 shell |
| 2 | 必须 | build_command 可能被误执行 | 仅 `build_mode=manual` 且扫描时才传给 CodeQL；UI 仅 manual 可编辑 |
| 3 | 必须 | 探测超时可能拖住请求 | 10s 子进程超时；异常返回 `{ok:false,error}` |
| 4 | 建议 | settings 写接口权限 | 沿用 admin 控制面；无密钥字段 |
| 5 | 建议 | 空 binary 时 status 500 | `found=false` 正常返回 |

## 安全

- 平台不分发 CodeQL/packs；只读本机。
- 不通过 API 读任意文件；packs 只列目录名。
- CodeQL 仍受 OSS Gate 限制。

## 可靠性

- 设置保存失败有错误 alert；探测失败不阻塞保存。
- `engine_details` 为可选字段，旧后端/旧前端不崩。

## 验证

- 305 passed；ruff/mypy 绿；前端 build 通过。
- 真实 CodeQL status/test 返回 2.27.2。
