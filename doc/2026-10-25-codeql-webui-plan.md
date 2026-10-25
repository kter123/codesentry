# CodeQL WebUI / 系统接入 · 实现计划

- 规格：`doc/2026-10-25-codeql-webui-spec.md`
- 前置：P1 已完成

## 任务 1：设置分组扩展

**文件**
- 修改：`src/codesentry/web/server.py`
- 测试：`tests/test_control_api.py`

- [ ] `SETTING_KEYS` 增加 codeql 字段，映射到 `codeql` 组。
- [ ] `get/put settings/{group}` 允许 `codeql`。
- [ ] `_read_setting` 增加 codeql 字段的 env/config 默认。
- [ ] 测试：PUT/GET codeql 回读一致；未知 key 400。

## 任务 2：CodeQL 状态/探测

**文件**
- 修改：`src/codesentry/web/control_api.py`
- 修改：`src/codesentry/control/engine_config.py`（增加 `codeql_status()`）
- 测试：`tests/test_codeql_api.py`

- [ ] `GET /api/engines/codeql/status`：解析 binary/search_path/suite/build_mode/version/found。
- [ ] `POST /api/engines/codeql/test`：`version` + `resolve languages` + packs 目录；10s 超时。
- [ ] `/api/health` 增加 `engine_details.codeql`，保留 engines 字符串。
- [ ] 测试：mock subprocess；真实 CodeQL 可跳过。

## 任务 3：Settings UI

**文件**
- 修改：`web/frontend/src/views/SettingsView.vue`
- 修改：`web/frontend/src/api/types.ts`（如需）
- 测试：npm build

- [ ] 新增「CodeQL 引擎」面板：binary/search_path/suite/build_mode/build_command/timeout/cache。
- [ ] 保存、探测按钮；探测结果 alert。
- [ ] manual 才启用 build_command。
- [ ] 空值提示“自动探测”。

## 任务 4：Overview 状态

**文件**
- 修改：`web/frontend/src/views/OverviewView.vue`
- 修改：`web/frontend/src/api/types.ts`

- [ ] `engine_details.codeql` 展示版本/未检测到。
- [ ] 保持 engines 字符串兼容。

## 任务 5：扫描详情最小展示

**文件**
- 修改：`web/frontend/src/views/ScanDetailView.vue`

- [ ] 从 artifacts 中找 `graph_delta.engine_graph.codeql`，展示 SARIF/dataflow 边数；无则不显示。

## 任务 6：验证

- [ ] API 单测（真实 CodeQL test 可选）。
- [ ] 前端 build。
- [ ] 全量 pytest、ruff、mypy。
- [ ] 两轮 review + 文档。

## 审查重点

1. 设置空值是否仍走自动探测。
2. test 是否只执行允许的子命令。
3. `engine_details` 是否不破坏旧前端。
4. build_command 是否仅 manual 启用。
5. 扫描详情无 CodeQL 时是否安静隐藏。
