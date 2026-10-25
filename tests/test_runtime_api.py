from fastapi.testclient import TestClient

from codesentry.web.server import app

client = TestClient(app)


def test_dashboard_contract():
    body = client.get("/api/dashboard").json()
    assert "scans" in body and "by_verdict" in body and "paths" in body


def test_knowledge_packs_contract():
    body = client.get("/api/knowledge-packs").json()
    assert isinstance(body.get("packs"), list)
    assert any(p.get("name") for p in body["packs"])


def test_events_and_tree_empty_contract():
    assert client.get("/api/scans/999999/events").status_code == 200
    assert client.get("/api/scans/999999/agent-tree").status_code == 200
    assert client.get("/api/scans/999999/tools").status_code == 200


def test_control_contract():
    assert client.get("/api/scans/999999/control").status_code == 200
