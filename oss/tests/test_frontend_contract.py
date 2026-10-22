"""Contract test: every endpoint the Vue frontend calls must exist and work."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main() -> int:
    app = create_app(":memory:")
    c = app.test_client()

    # static + SPA fallback (Vue build output in panel/frontend/dist)
    r = c.get("/")
    assert r.status_code == 200
    assert b'<div id="app">' in r.data, "Vue mount point missing"
    assert b"assets/" in r.data, "built asset reference missing"
    assert c.get("/#/proxies").status_code == 200  # SPA fallback
    assert c.get("/api/nope").status_code == 404

    # reads used by every view
    for p in ("/api/status", "/api/health", "/api/nodes", "/api/groups",
              "/api/subscriptions", "/api/sitesets", "/api/rulesets",
              "/api/chains", "/api/settings", "/api/config",
              "/api/dns", "/api/terminals", "/api/traffic/daily"):
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
    assert c.post("/api/route/penetrate", json={"target": "a.example.com"}).status_code == 200
    assert c.put("/api/settings", json={"dns_direct": "1.2.3.4"}).status_code == 200
    # site-set hot-switch flip (no kernel -> persisted, hot=false)
    r = c.post(f"/api/sitesets/{ss['id']}/flip", json={"to": "direct"})
    assert r.status_code == 200 and r.get_json()["ok"], r.get_data(as_text=True)
    # policy-card select (frontend calls this; it 404'd before it existed):
    # group -> action=proxy + group set + flip cleared; direct/block mapped;
    # unknown outbound rejected.
    r = c.post(f"/api/sitesets/{ss['id']}/select", json={"outbound": "所有-自动"})
    assert r.status_code == 200 and r.get_json()["ok"], r.get_data(as_text=True)
    row = r.get_json()["site_set"]
    assert row["action"] == "proxy" and row["group"] == "所有-自动", row
    r = c.post(f"/api/sitesets/{ss['id']}/select", json={"outbound": "direct"})
    assert r.status_code == 200 and r.get_json()["site_set"]["action"] == "direct"
    r = c.post(f"/api/sitesets/{ss['id']}/select", json={"outbound": "block"})
    assert r.status_code == 200 and r.get_json()["site_set"]["action"] == "reject"
    r = c.post(f"/api/sitesets/{ss['id']}/select", json={"outbound": "no-such-group"})
    assert r.status_code == 400, r.status_code
    # fallback policy card (其他) select: persists to both final settings
    r = c.post("/api/openbox/final-select", json={"outbound": "所有-自动"})
    assert r.status_code == 200 and r.get_json()["final"] == "所有-自动", r.get_data(as_text=True)
    settings = c.get("/api/settings").get_json()
    assert settings["routing_fallback"] == "所有-自动", settings["routing_fallback"]
    assert settings["final_outbound"] == "所有-自动", settings["final_outbound"]
    r = c.post("/api/openbox/final-select", json={"outbound": "direct"})
    assert r.status_code == 200 and r.get_json()["final"] == "direct"
    r = c.post("/api/openbox/final-select", json={"outbound": "no-such-group"})
    assert r.status_code == 400, r.status_code
    # terminals + dns rewrite round-trip
    tid = c.post("/api/terminals", json={"ident": "192.168.1.9", "policy": "direct"}).get_json()["id"]
    rwid = c.post("/api/dns/rewrite", json={"domain": "x.test", "target": "1.1.1.1"}).get_json()["id"]
    assert c.get("/api/upgrade/status").status_code == 200
    gid = c.post("/api/groups", json={"name": "g1", "type": "selector"}).get_json()["id"]
    cid = c.post("/api/chains", json={"name": "c1", "server": "1.2.3.4",
                                      "port": 1080, "front": "auto"}).get_json()["id"]
    rid = c.post("/api/rulesets", json={"name": "r1", "url": ""}).get_json()["id"]
    assert c.post("/api/health/check", json={"timeout": 1}).status_code == 200
    for p in (f"/api/subscriptions/{sid}", f"/api/sitesets/{ss['id']}",
              f"/api/groups/{gid}", f"/api/chains/{cid}", f"/api/rulesets/{rid}",
              f"/api/terminals/{tid}", f"/api/dns/rewrite/{rwid}"):
        assert c.delete(p).status_code == 200, p

    print("OK: frontend API contract — all endpoints the SPA calls exist and work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
