"""API self-test for the panel backend (Flask test client)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main() -> int:
    app = create_app(":memory:")
    c = app.test_client()

    # subscriptions
    sub_text = (ROOT / "sample-sub.txt").read_text(encoding="utf-8")
    r = c.post("/api/subscriptions", json={"name": "demo", "content": sub_text})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json()["node_count"] == 5
    r = c.get("/api/subscriptions")
    assert len(r.get_json()) == 1
    r = c.get("/api/nodes")
    nodes = r.get_json()
    assert len(nodes) == 5, len(nodes)

    # site sets
    for d in json.loads((ROOT / "sample-sites.json").read_text()):
        r = c.post("/api/sitesets", json=d)
        assert r.status_code == 201, r.get_data(as_text=True)
    r = c.get("/api/sitesets")
    assert len(r.get_json()) == 3

    # route preview: domain -> first match wins, top-down
    r = c.post("/api/route/preview", json={"target": "www.youtube.com"})
    assert r.get_json() == {"site_set": "国外", "action": "proxy", "outbound": "auto", "flip": None}, r.get_json()
    r = c.post("/api/route/preview", json={"target": "www.baidu.com"})
    assert r.get_json()["outbound"] == "direct", r.get_json()
    r = c.post("/api/route/preview", json={"target": "ads.example.com"})
    assert r.get_json()["outbound"] == "block", r.get_json()
    # IP targets only match ip_cidr
    r = c.post("/api/route/preview", json={"target": "114.114.114.114"})
    assert r.get_json() == {"site_set": "国内", "action": "direct", "outbound": "direct", "flip": None}, r.get_json()
    r = c.post("/api/route/preview", json={"target": "8.8.8.8"})
    assert r.get_json() == {"site_set": None, "action": "final", "outbound": "auto"}, r.get_json()
    # domain must not match ip_cidr and vice versa
    r = c.post("/api/route/preview", json={"target": "114.114.114.114.example.com"})
    assert r.get_json()["site_set"] is None, r.get_json()

    # generated config reflects DB state (10 base + 2 flip selectors for the 2 site sets)
    r = c.get("/api/config")
    conf = r.get_json()
    assert len(conf["outbounds"]) == 12, len(conf["outbounds"])
    flips = [o for o in conf["outbounds"] if o["tag"].startswith("flip-")]
    assert len(flips) == 2 and all(o["type"] == "selector" for o in flips), flips
    assert conf["route"]["final"] == "auto"

    # settings round-trip
    r = c.put("/api/settings", json={"dns_direct": "114.114.114.114"})
    assert r.get_json()["dns_direct"] == "114.114.114.114"

    # status
    r = c.get("/api/status")
    st = r.get_json()
    assert st["nodes"] == 5 and st["site_sets"] == 3, st

    # delete flows
    r = c.delete("/api/sitesets/1")
    assert r.get_json() == {"ok": True}
    r = c.delete("/api/subscriptions/1")
    assert r.get_json() == {"ok": True}
    assert c.get("/api/nodes").get_json() == []

    print("OK: panel API self-test passed "
          "(subscriptions/nodes/sitesets/route-preview/config/settings/status)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
