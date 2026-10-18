# M2 依赖 license 清单（agent.md §3：逐项记录，阻塞不合许可引入）

| 依赖 | 版本 | 许可证 | 用途 | 备注 |
|---|---|---|---|---|
| typer | >=0.12 | MIT | CLI | M0 |
| rich | >=13 | MIT | CLI 输出 | M0 |
| pydantic / pydantic-settings | >=2.2 | MIT | 模型/配置 | M0 |
| psycopg[binary] | >=3.2 | LGPL-3.0 | PG 驱动（进程外调用 CLI，无链接问题） | M0 |
| psycopg-pool | >=3.3 | LGPL-3.0 | 连接池 | M2 |
| tree-sitter | 0.26 | MIT | AST 切块 | M2 |
| tree-sitter-python | 0.25 | MIT | python grammar | M2 |
| openai | （cli 客户端） | Apache-2.0 | Embedding/LLM 兼容协议客户端 | M2 |

**红线核对**：无 CodeQL 相关依赖；无 semgrep 官方规则；semgrep CLI 本体为用户环境工具（LGPL-2.1，子进程隔离）；bge-m3（MIT）为用户自部署推理服务，不随包分发。
