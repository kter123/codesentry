# A3/A4 + B1/B2 计划审计

## 1. 覆盖

| 规格项 | 任务 | 覆盖 |
|---|---|---|
| 默认部署 / POC_RUN 解耦 | 任务 1 | ✅ |
| Dockerfile / 嵌套根 / 端口 | 任务 2 | ✅ |
| host/internal / 清理 | 任务 3 | ✅ |
| canary 占位符 | 任务 4 | ✅ |
| max_iterations/budget/tool_trace | 任务 5 | ✅ |
| artifacts/WS/UI | 任务 6 | ✅ |
| 真实验收 | 任务 7 | ✅ |

## 2. 审计发现

1. **任务 3 的 host 模式安全**：计划只写“只绑 127.0.0.1”，需补充“容器仍有出网能力”的风险说明与 internal 选项。
2. **任务 2 的 Dockerfile 构建上下文**：未限制大小/`.dockerignore`，可能构建超大上下文；列入后续。
3. **任务 4 的 listener 在 internal 模式不可达**：计划应明确仅 host 模式验证 listener；internal 只用 cmd/fs。
4. **任务 6 的 WS 事件缓冲**：需要保证无订阅者时 drain，避免内存泄漏；已实现，需测试。
5. **任务 7 的真实部署依赖本机镜像**：Docker Hub 拉取超时，验收使用本地 `langgenius/dify-api:1.9.2` 作为 python 镜像；生产应配置私有镜像。
6. **测试隔离**：真实 612/613 会写 DB 与 Docker；需记录并清理；已完成清理。

## 3. 判定

计划可执行，覆盖规格；上述 1/2/3/5 作为已知限制写入文档，4 需补测试。进入实现（已完成）与两轮 review。
