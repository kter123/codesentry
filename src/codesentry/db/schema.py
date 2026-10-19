BUSINESS_SCHEMA = "codesentry"
CHECKPOINT_SCHEMA = "langgraph"


def render_ddl() -> str:
    """业务/checkpoint 双 schema + pgvector 扩展 + 全部表 DDL（db.ddl.render_full_ddl）。"""
    from codesentry.db.ddl import render_full_ddl

    return (
        "\n".join(
            [
                f"CREATE SCHEMA IF NOT EXISTS {BUSINESS_SCHEMA};",
                f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA};",
                "CREATE EXTENSION IF NOT EXISTS vector;",
            ]
        )
        + "\n"
        + render_full_ddl()
    )
