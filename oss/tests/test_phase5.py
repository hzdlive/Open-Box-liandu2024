"""Phase 5 tests: DNS management, terminals, hot-switch flip, connections,
traffic accounting, transparent artifacts (quic/bypass/dnsmasq).
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    app = create_app(":memory:")
    return app


def test_dns_api():
    app = _app()
    c = app.test_client()
    d = c.get("/api/dns").get_json()
    assert d["mode"] == "dnsmasq" and d["region"] == "auto", d
    assert d["direct_dns"] == "223.5.5.5" and d["proxy_dns"] == "tcp://1.1.1.1"

    r = c.put("/api/dns", json={"mode": "firewall", "region": "cn",
                                "direct_dns": "114.114.114.114"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["mode"] == "firewall" and d["direct_dns"] == "114.114.114.114", d
    assert c.put("/api/dns", json={"mode": "bogus"}).status_code == 400
    assert c.put("/api/dns", json={"region": "bogus"}).status_code == 400

    # rewrites (2 defaults are seeded to match the original panel)
    n0 = len(c.get("/api/dns").get_json()["rewrites"])
    r = c.post("/api/dns/rewrite", json={"domain": "Example.COM ", "target": "1.2.3.4"})
    assert r.status_code == 201
    rw = r.get_json()
    assert rw["domain"] == "example.com" and rw["target"] == "1.2.3.4", rw
    assert len(c.get("/api/dns").get_json()["rewrites"]) == n0 + 1
    assert c.delete(f"/api/dns/rewrite/{rw['id']}").status_code == 200
    assert len(c.get("/api/dns").get_json()["rewrites"]) == n0
    assert c.post("/api/dns/rewrite", json={"domain": "", "target": "x"}).status_code == 400
    print("OK: DNS api (mode/region/upstreams/rewrites)")


def test_terminals_api():
    app = _app()
    c = app.test_client()
    assert c.get("/api/terminals").get_json() == {"terminals": []}
    r = c.post("/api/terminals", json={"ident": "192.168.1.50", "name": "电视", "policy": "direct"})
    assert r.status_code == 201, r.get_data(as_text=True)
    t = r.get_json()
    assert t["policy"] == "direct"
    # upsert same ident
    r = c.post("/api/terminals", json={"ident": "192.168.1.50", "policy": "bypass"})
    assert r.get_json()["policy"] == "bypass"
    assert c.post("/api/terminals", json={"ident": "x", "policy": "bogus"}).status_code == 400
    tid = c.get("/api/terminals").get_json()["terminals"][0]["id"]
    assert c.delete(f"/api/terminals/{tid}").status_code == 200
    assert c.get("/api/terminals").get_json() == {"terminals": []}
    print("OK: terminals api")


def test_flip():
    from core.singbox import build_config, flip_tag
    app = _app()
    c = app.test_client()
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    s1 = dbmod.create_site_set(conn, {"name": "翻转测试国外", "action": "proxy", "group": "所有-自动",
                                      "rules": {"domain_suffix": ["example.com"]}})
    s2 = dbmod.create_site_set(conn, {"name": "翻转测试国内", "action": "direct",
                                      "rules": {"domain_suffix": ["cn.example"]}})
    conn.close()

    # config has a flip selector per site set
    cfg = dbmod.load_app_config(
        sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"]))
    conf = build_config(cfg)
    tags = {o["tag"] for o in conf["outbounds"]}
    assert f"flip-{s1['id']}" in tags and f"flip-{s2['id']}" in tags, tags
    sel = next(o for o in conf["outbounds"] if o["tag"] == f"flip-{s1['id']}")
    assert sel["type"] == "selector" and sel["outbounds"] == ["所有-自动", "direct"], sel
    assert sel["default"] == "所有-自动"  # follows action=proxy
    sel2 = next(o for o in conf["outbounds"] if o["tag"] == f"flip-{s2['id']}")
    assert sel2["outbounds"] == ["direct", "所有-自动"] and sel2["default"] == "direct"

    # route rules go through the flip selectors (12 defaults are seeded first)
    rrules = conf["route"]["rules"]
    flips = [r for r in rrules if r.get("outbound", "").startswith("flip-")]
    assert flips and f"flip-{s1['id']}" in {r["outbound"] for r in flips}, rrules

    # flip endpoint persists (kernel down -> hot=false but persisted)
    r = c.post(f"/api/sitesets/{s1['id']}/flip", json={"to": "direct"})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["ok"] and body["hot"] is False  # no kernel in test env
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    cfg2 = dbmod.load_app_config(conn)
    conn.close()
    conf2 = build_config(cfg2)
    sel = next(o for o in conf2["outbounds"] if o["tag"] == f"flip-{s1['id']}")
    assert sel["default"] == "direct", sel
    # preview resolves through flip state
    r = c.post("/api/route/preview", json={"target": "www.example.com"}).get_json()
    assert r["outbound"] == "direct" and r["flip"] == "direct", r
    assert c.post(f"/api/sitesets/{s1['id']}/flip", json={"to": "sideways"}).status_code == 400
    print("OK: hot-switch flip (selector + persist + preview)")


def test_connections_no_kernel():
    app = _app()
    c = app.test_client()
    # no kernel running in CI -> 502, not a crash
    assert c.get("/api/connections").status_code == 502
    assert c.delete("/api/connections/abc").status_code == 502
    t = c.get("/api/traffic/now").get_json()
    assert t["kernel"] is False and t["connections"] == 0
    assert c.get("/api/traffic/daily").get_json() == {"rows": []}
    print("OK: connections/traffic degrade gracefully without kernel")


def test_traffic_record():
    app = _app()
    c = app.test_client()
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    dbmod.record_traffic(conn, "2026-10-14", "192.168.1.2", "node-a", "example.com", 100, 200)
    dbmod.record_traffic(conn, "2026-10-14", "192.168.1.2", "node-a", "example.com", 50, 25)
    conn.close()
    rows = c.get("/api/traffic/daily?days=3650").get_json()["rows"]
    assert len(rows) == 1 and rows[0]["up"] == 150 and rows[0]["down"] == 225, rows
    print("OK: traffic daily accounting")


def test_transparent_new_bits():
    from core.transparent import TransparentConfig, nft_script, dnsmasq_snippet
    cfg = TransparentConfig(quic_block=True, mss_clamp=1400,
                            terminal_bypass=["192.168.1.50"],
                            dns_rewrites=[("example.com", "1.2.3.4")],
                            dns_direct_ip="223.5.5.5", dns_proxy_ip="1.1.1.1",
                            site_domains=[("proxy", ["example.com"])])
    nft = nft_script(cfg)
    assert "udp dport 443 reject" in nft, "quic block missing"
    assert "@tbypass" in nft and "192.168.1.50" in nft, "terminal bypass missing"
    assert "maxseg size set 1400" in nft, "mss clamp missing"
    dm = dnsmasq_snippet(cfg)
    assert "address=/example.com/1.2.3.4" in dm, dm
    assert "server=/example.com/1.1.1.1" in dm, dm
    print("OK: transparent artifacts (quic/bypass/mss/dnsmasq)")


def test_tun_mtu_and_quic_settings():
    app = _app()
    c = app.test_client()
    r = c.put("/api/settings", json={"tun_mtu": "1400", "quic_block": "0"})
    assert r.get_json()["tun_mtu"] == "1400" and r.get_json()["quic_block"] == "0"
    from core.singbox import build_config
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    cfg = dbmod.load_app_config(conn)
    conn.close()
    assert cfg.tun_mtu == 1400 and cfg.quic_block is False
    tun = next(i for i in build_config(cfg)["inbounds"] if i["type"] == "tun")
    assert tun["mtu"] == 1400, tun
    print("OK: tun mtu + quic block settings")


def test_route_penetrate_and_test():
    app = _app()
    c = app.test_client()
    r = c.post("/api/route/penetrate", json={"target": "www.example.com"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["chain"][0]["level"] == "site_set", body
    assert body["kernel"] is False  # no kernel in test env
    assert c.post("/api/route/penetrate", json={}).status_code == 400
    # route test against unreachable proxy -> 502, not a crash
    r = c.post("/api/route/test", json={"url": "http://127.0.0.1:9/"})
    assert r.status_code in (200, 502), r.status_code
    assert c.post("/api/route/test", json={"url": "ftp://x"}).status_code == 400
    print("OK: route penetrate + test")


def test_upgrade_endpoints():
    app = _app()
    c = app.test_client()
    st = c.get("/api/upgrade/status").get_json()
    assert st["panel"] and "singbox" in st, st
    assert c.get("/api/upgrade/log").get_json() == {"log": ""}
    print("OK: upgrade status/log endpoints")


def main():
    test_dns_api()
    test_terminals_api()
    test_flip()
    test_connections_no_kernel()
    test_traffic_record()
    test_transparent_new_bits()
    test_tun_mtu_and_quic_settings()
    test_route_penetrate_and_test()
    test_upgrade_endpoints()
    print("ALL PHASE5 TESTS PASSED")


if __name__ == "__main__":
    main()
