import uuid

from codesentry.control import knowledge_packs as kp
from codesentry.db.pool import get_conn


def _cleanup(pid):
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM knowledge_packs WHERE id=%s", (pid,))
        c.commit()


def test_seed_and_search():
    n = kp.seed_builtins()
    assert n >= 0
    rows = kp.search("命令注入", cwe=78)
    assert rows and rows[0]["cwe"] == 78
    assert any("pack:" in r.get("source_ref", "") for r in rows)


def test_pack_crud_and_weighting():
    name = f"test-pack-{uuid.uuid4().hex[:8]}"
    pack = kp.create_pack(name, "python fastapi sql injection parameterized query",
                          kind="vuln", lang="python", framework="fastapi", cwe=89)
    try:
        assert kp.search("sql", lang="python", framework="fastapi", cwe=89)[0]["id"] == pack["id"]
        updated = kp.update_pack(pack["id"], {"content": "updated", "enabled": False})
        assert updated["enabled"] is False and updated["version"] == pack["version"] + 1
        assert all(p["id"] != pack["id"] for p in kp.list_packs(enabled=True))
    finally:
        _cleanup(pack["id"])
