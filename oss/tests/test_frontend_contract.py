"""Contract test: every endpoint the frontend (app.js) calls must exist and work."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main() -> int:
    app = create_app(":memory:")
    c = app.test_client()

    # static + SPA fallback
    assert c.get("/").status_code == 200
    assert c.get("/app.js").status_code == 200
    assert c.get("/styles.css").status_code == 200
    assert c.get("/#/proxy").status_code == 200
    assert c.get("/api/nope").status_code == 404

    # reads used by every view
    for p in ("/api/status", "/api/health", "/api/nodes", "/api/groups",
              "/api/subscriptions", "/api/sitesets", "/api/rulesets",
              "/api/chains", "/api/settings", "/api/config"):
        r = c.get(p)
        assert r.status_code == 200, (p, r.status_code)

    # writes used by every view
    sub = (ROOT / "sample-sub.txt").read_text()
    sid = c.post("/api/subscriptions",
                 json={"name": "t", "content": sub, "format": "auto"}).get_json()["id"]
    ss = c.post("/api/sitesets", json={"name": "s1", "action": "proxy",
                                       "rules": {"domain_suffix": ["example.com"]}}).get_json()
    assert c.put(f"/api/sitesets/{ss['id']}",
                 json={"action": "direct"}).status_code == 200
    assert c.post("/api/route/preview", json={"target": "a.example.com"}).status_code == 200
    assert c.put("/api/settings", json={"dns_direct": "1.2.3.4"}).status_code == 200
    gid = c.post("/api/groups", json={"name": "g1", "type": "selector"}).get_json()["id"]
    cid = c.post("/api/chains", json={"name": "c1", "server": "1.2.3.4",
                                      "port": 1080, "front": "auto"}).get_json()["id"]
    rid = c.post("/api/rulesets", json={"name": "r1", "url": ""}).get_json()["id"]
    assert c.post("/api/health/check", json={"timeout": 1}).status_code == 200
    for p in (f"/api/subscriptions/{sid}", f"/api/sitesets/{ss['id']}",
              f"/api/groups/{gid}", f"/api/chains/{cid}", f"/api/rulesets/{rid}"):
        assert c.delete(p).status_code == 200, p

    print("OK: frontend API contract — all endpoints the SPA calls exist and work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
