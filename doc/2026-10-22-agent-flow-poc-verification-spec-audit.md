# A3/A4 + B1/B2 规格审计

> 基准：用户设计意图（LangGraph 多 Agent、PoC 实证、本地服务 + Web 包 Docker 部署）与 `2026-10-22-requirements-understanding-audit.md`。

## 1. 覆盖检查

| 意图/需求 | 规格覆盖 | 结论 |
|---|---|---|
| 看见多个 Agent 工作 | A3 artifacts + tool_trace + 审查链 UI | ✅ |
| 实时过程 | A4 node.start/end + WS + 时间线 | ✅（节点级，token 级不在本轮） |
| 上传 Web 包默认部署 | B1 默认部署、`POC_RUN` 解耦 | ✅ |
| 本地可访问 target | 默认 host 127.0.0.1 + 随机端口 | ✅ |
| 严格沙箱 | internal 模式可选 | ✅ |
| 项目自带 Dockerfile | 构建优先级 Dockerfile → 配方 | ✅ |
| zip 嵌套根/端口 | resolve_project_root + detect_port | ✅ |
| 扫描后清理 | 默认清理，`DEPLOY_KEEP` 保留 | ✅ |
| PoC 自身产生证据 | canary 占位符 + nonce | ✅ |
| 真实 Docker/canary | 验收 612/613 | ✅ |

## 2. 审计发现

1. **compose 不支持**：规格明确列为不在本轮，但用户上传 Web 包可能是 compose 项目；需要 UI/日志明确提示，避免误以为部署失败。
2. **internal 模式 listener canary 不可达**：规格已注明；host 模式为默认，listener 可用。
3. **`DEPLOY_KEEP=false` 时 target 扫描结束即关闭**：用户若想手工浏览，需要设置 keep；UI 应提示“扫描结束后 target 可能已关闭”。
4. **Dockerfile 构建上下文可能很大**：未设置 `.dockerignore`/大小上限；需要后续限制。
5. **host 模式容器仍有出网能力**：默认 host 为可用性取舍；严格安全场景应切 internal。
6. **工具循环依赖 LLM 输出 `tool_calls`**：Prompt 已指示，但模型可能不调用；没有工具调用时退化为单轮，不阻塞。
7. **无 token 级流式**：当前 LLM 调用非 stream；节点级事件已满足“看见 agent 在做什么”的第一层。
8. **`max_iterations`/`budget_override` 真实 LLM 长链验证不足**：本轮有单测；需在下一批用真实扫描观察。

## 3. 判定

规格与用户意图一致，可进入计划与实现；上述 1/2/3 作为已知限制写入文档与 UI 提示，4/8 列入后续增强。实现完成后需用真实扫描 612/613 作为验收证据（已完成）。
