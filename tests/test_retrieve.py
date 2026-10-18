"""混合检索/入库集成测试——连本机 compose 库（skip-if-no-db）。"""

import os

import pytest

from codesentry.db import repo as db_repo
from codesentry.db.pool import close_pool, get_conn

pytestmark = pytest.mark.skipif(
    not os.environ.get("CODESENTRY_TEST_DB", "")
    and not os.access("/var/run/docker.sock", os.W_OK)
    and os.system("docker ps >/dev/null 2>&1") != 0,
    reason="local codesentry-db not reachable",
)


def _db_up() -> bool:
    import subprocess

    return (
        subprocess.run(
            ["docker", "ps", "--filter", "name=codesentry-db", "--filter", "status=running"],
            capture_output=True,
        ).returncode
        == 0
    )


pytestmark = pytest.mark.skipif(
    not _db_up(), reason="codesentry-db container not running"
)

SAMPLE_FUNC_1 = "def fetch_url(u):\n    return requests.get(u)\n"
SAMPLE_FUNC_2 = "def calc_hash(data):\n    return hashlib.sha256(data)\n"


@pytest.fixture()
def _clean_chunks():
    os.environ.setdefault(
        "CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry"
    )
    if _db_up():
        os.environ.setdefault(
            "CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry"
        )
        from codesentry.db.ddl import render_full_ddl

        with get_conn() as conn:
            conn.execute(render_full_ddl())
            conn.execute(
                "DELETE FROM code_chunks WHERE project LIKE 'test-m2-%'"
            )
            conn.execute("DELETE FROM kb_chunks WHERE source LIKE 'test-m2-%'")
            conn.commit()
    yield
    close_pool()


def _fake_vec(seed: float, dims: int = 8) -> list[float]:
    return [seed] * dims


def test_code_upsert_and_hybrid_search(_clean_chunks):
    from codesentry.rag.chunker import chunk_code
    from codesentry.rag.retrieve import hybrid_search

    chunks = chunk_code("svc.py", "python", SAMPLE_FUNC_1 + "\n" + SAMPLE_FUNC_2)
    chunks = [c for c in chunks if c.symbol_kind == "function"]
    n_inserted = db_repo.upsert_code_chunks(
        project="test-m2-code",
        chunks=chunks,
        embeddings=[_fake_vec(0.5) for _ in chunks],
    )
    assert n_inserted == len(chunks) == 2
    # 幂等：二次导入 skip
    n2 = db_repo.upsert_code_chunks(
        project="test-m2-code",
        chunks=chunks,
        embeddings=[_fake_vec(0.5) for _ in chunks],
    )
    assert n2 == 0

    rows = hybrid_search("code", "fetch_url", _fake_vec(0.5), top_k=5)
    assert rows, "vector 检索应有命中"


def test_kb_chinese_fts(_clean_chunks):
    from codesentry.rag.retrieve import hybrid_search

    items = [
        {"source": "test-m2-kb", "title": "SSRF 防护要点", "content": "服务端请求伪造：用户可控 URL 必须走白名单校验，禁止直接请求内网地址。"},
        {"source": "test-m2-kb", "title": "SQL 注入防护", "content": "SQL 注入：使用参数化查询，禁止字符串拼接。"},
    ]
    n = db_repo.upsert_kb_chunks(items, [_fake_vec(0.3), _fake_vec(0.7)])
    assert n == 2
    rows = hybrid_search("kb", "SSRF 白名单", _fake_vec(0.3))
    assert rows, "中文全文+向量混合应有命中"
    assert any("SSRF" in r.get("title", "") or "SSRF" in r.get("content", "") for r in rows)
