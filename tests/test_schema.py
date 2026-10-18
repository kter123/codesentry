from codesentry.db.schema import BUSINESS_SCHEMA, CHECKPOINT_SCHEMA, render_ddl


def test_schema_names():
    assert BUSINESS_SCHEMA == "codesentry"
    assert CHECKPOINT_SCHEMA == "langgraph"
    assert BUSINESS_SCHEMA != CHECKPOINT_SCHEMA


def test_render_ddl_contains_schemas_and_extension():
    ddl = render_ddl()
    assert "CREATE SCHEMA IF NOT EXISTS codesentry;" in ddl
    assert "CREATE SCHEMA IF NOT EXISTS langgraph;" in ddl
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in ddl
