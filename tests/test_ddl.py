from codesentry.db.ddl import render_full_ddl
from codesentry.db.schema import BUSINESS_SCHEMA, CHECKPOINT_SCHEMA

EXPECTED_TABLES = [
    "scans",
    "findings",
    "code_chunks",
    "kb_chunks",
    "budget_ledger",
    "node_runs",
    "agent_configs",
    "prompt_versions",
    "skills",
    "skill_versions",
    "skill_assignments",
]


def test_ddl_contains_all_tables():
    ddl = render_full_ddl()
    for t in EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.{t} " in ddl, f"missing table {t}"


def test_ddl_schema_boundary():
    ddl = render_full_ddl()
    # checkpoint schema 不建业务表
    assert f"CREATE TABLE IF NOT EXISTS {CHECKPOINT_SCHEMA}." not in ddl
    # FK 都指向业务 schema
    assert f"REFERENCES {BUSINESS_SCHEMA}." in ddl


def test_ddl_vector_extension():
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in render_full_ddl()
