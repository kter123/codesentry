# P2 安全扩展 Review 1（正确性）

| # | 问题 | 修复 |
|---|---|---|
| 1 | 依赖容器若在目标之后启动/网络不同，目标连不上 | 目标启动前建 network；依赖先起并 health；目标同 network/env |
| 2 | 依赖拉镜像绕过 allow_remote | `DependencyManager` 在 `allow_remote=false` 时只接受本地镜像 |
| 3 | 依赖容器未清理 | `DockerDeployer.cleanup` + `cleanup_scan` 删除 `codesentry-dep-*` |
| 4 | Agent docker_run 不支持 env/network | 增加 network + dependency_env；`detect_dependencies/ensure_dependency` 工具 |
| 5 | JS 匿名回调无节点，路径 weak | `anon@L<n>` 合成节点；route owner 匹配下一行箭头函数 |
| 6 | CodeQL 同 line source/sink 被去重丢失 | flow 去重加入 column；同函数 dataflow 指向真实 sink |
| 7 | CodeQL 安装临时变量未初始化/解压目录不固定 | tmp_path 初始化；解压后查找可执行 `codeql` 再移动 |
| 8 | 安装配置只读 env，不读 DB | `_setting` 优先 app_settings；UI 保存后扫描生效 |
| 11 | 路径候选每批覆盖，早期高价值 finding 丢失 | `run_audit_collect` 按 rule/file/line 合并历史候选 |
| 9 | fix patch fence 可能带说明文字 | 只接受 `---/+++/@@`；否则 400 |
| 10 | 远程 probe 跟随重定向可能跳私网 | `follow_redirects=False` |

## 验证

- `tests/test_dependencies.py`、`test_js_anon.py`、`test_codeql_install.py`、`test_fix_agent.py`、`test_poc_targets.py`。
- JS 全链路出现 `anon@L5` proven 路径。
- kvf 真实依赖启动被安全分类器拦截（Production Deploy），未执行；MySQL 镜像已拉取。

## 结论

正确性问题已修复；真实部署验证需要在用户明确允许后执行。
