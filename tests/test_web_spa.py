"""M5.1 SPA 路由回退回归测试（侧栏直链白屏 bug）。"""


import os
import re

os.environ.setdefault("CODESENTRY_DATABASE_URL", "postgresql://codesentry:devtest@127.0.0.1:5432/codesentry")
os.environ.setdefault("CODESENTRY_WORK_DIR", "/tmp/cs-spa-test")

from fastapi.testclient import TestClient

from codesentry.web.server import app

client = TestClient(app)


def test_spa_routes_return_index_html():
    for route in ("/ui/agents", "/ui/rules", "/ui/skills", "/ui/prompts", "/ui/reviews", "/ui/scans", "/ui/scans/1", "/ui/review/1"):
        r = client.get(route)
        assert r.status_code == 200, route
        assert re.search(r'assets/[^"]+\.js', r.text), route
        assert 'id="root"' in r.text


def test_assets_still_served():
    html = client.get("/ui/agents").text
    m = re.search(r'src="(/ui/assets/[^"]+\.js)"', html)
    assert m, html[:300]
    assert client.get(m.group(1)).status_code == 200
