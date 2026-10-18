BUSINESS_SCHEMA = "codesentry"
CHECKPOINT_SCHEMA = "langgraph"


def render_ddl() -> str:
    """M0 DDL 骨架：业务/checkpoint 双 schema + pgvector 扩展。表 DDL 由 M1+ 增量追加。"""
    return (
        "\n".join(
            [
                f"CREATE SCHEMA IF NOT EXISTS {BUSINESS_SCHEMA};",
                f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA};",
                "CREATE EXTENSION IF NOT EXISTS vector;",
            ]
        )
        + "\n"
    )
