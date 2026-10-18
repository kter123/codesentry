import os

import pytest
from typer.testing import CliRunner

import codesentry.cli as cli_mod

runner = CliRunner()


@pytest.fixture()
def _db(monkeypatch):
    import subprocess

    if subprocess.run(
        ["docker", "ps", "--filter", "name=codesentry-db", "--filter", "status=running"],
        capture_output=True, check=False,
    ).returncode != 0:
        pytest.skip("codesentry-db not running")
    os.environ.setdefault(
        "CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry"
    )

    class _FakeClient:
        def embed(self, texts):
            return [[0.0] * 8 for _ in texts]

    monkeypatch.setattr(
        "codesentry.rag.embedding.EmbeddingClient", type("FC", (), {"from_config": staticmethod(lambda: _FakeClient())})
    )
    from codesentry.db.ddl import render_full_ddl
    from codesentry.db.pool import get_conn

    with get_conn() as conn:
        conn.execute(render_full_ddl())
        conn.execute("DELETE FROM kb_chunks WHERE embedding IS NOT NULL AND vector_dims(embedding) = 8")
        conn.commit()
    yield
    from codesentry.db.pool import close_pool

    close_pool()


def test_kb_import_and_idempotent(_db, tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ssrf.md").write_text(
        "# SSRF 防护\n服务端请求伪造：用户可控 URL 必须走白名单。", encoding="utf-8"
    )
    (kb / "notes.txt").write_text("内部规范：所有外部输入必须验证。", encoding="utf-8")
    r = runner.invoke(cli_mod.app, ["kb", "import", str(kb)])
    assert r.exit_code == 0, r.output
    assert "入库 2 条" in r.output
    # 幂等：再导一次 0 条
    r2 = runner.invoke(cli_mod.app, ["kb", "import", str(kb)])
    assert r2.exit_code == 0 and "入库 0 条" in r2.output


def test_kb_import_missing_dir():
    r = runner.invoke(cli_mod.app, ["kb", "import", "/nonexistent-kb-dir-xyz"])
    assert r.exit_code == 1
