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


def test_orig_parity_batch():
    # Original-panel parity: urltest expected_status/test_url, DNS "wan",
    # rewrite enabled flag, traffic month zero-fill + today.
    from core import singbox as _sb
    from core import dnstest as _dt
    app = _app()
    c = app.test_client()
    # 1. group expected_status + test_url round-trip
    r = c.post("/api/groups", json={"name": "g-parity", "type": "urltest",
                                    "expected_status": "204",
                                    "test_url": "http://example.com/ping"})
    assert r.status_code == 201, r.get_data(as_text=True)
    g = r.get_json()
    assert g["expected_status"] == "204" and g["test_url"] == "http://example.com/ping"
    gid = g["id"]
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    cfg = dbmod.load_app_config(conn)
    conn.close()
    obs = [o for o in _sb.build_config(cfg)["outbounds"] if o.get("tag") == "g-parity"]
    assert obs and obs[0]["expected_status"] == "204", obs
    assert obs[0]["url"] == "http://example.com/ping", obs
    # empty expected_status must not be emitted
    r = c.put(f"/api/groups/{gid}", json={"expected_status": "", "test_url": ""})
    assert r.status_code == 200 and r.get_json()["expected_status"] == ""
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    cfg = dbmod.load_app_config(conn)
    conn.close()
    obs = [o for o in _sb.build_config(cfg)["outbounds"] if o.get("tag") == "g-parity"]
    assert "expected_status" not in obs[0], obs
    # 2. DNS direct "wan" resolves to system upstreams
    orig = _dt.system_upstreams
    _dt.system_upstreams = lambda: ["9.9.9.9", "8.8.4.4"]
    try:
        servers = _sb._dns_servers("direct-dns", "wan", "direct")
        assert [s["server"] for s in servers] == ["9.9.9.9", "8.8.4.4"], servers
        assert servers[0]["tag"] == "direct-dns" and servers[0]["type"] == "udp"
    finally:
        _dt.system_upstreams = orig
    r = c.put("/api/dns", json={"direct_dns": "wan"})
    assert r.status_code == 200 and r.get_json()["direct_dns"] == "wan"
    # 3. rewrite enabled flag: disabled rewrites leave the generated config
    r = c.post("/api/dns/rewrite", json={"domain": "off.example", "target": "1.2.3.4"})
    assert r.status_code == 201, r.get_data(as_text=True)
    rid = r.get_json()["id"]
    assert r.get_json()["enabled"] is True
    r = c.put(f"/api/dns/rewrite/{rid}", json={"enabled": False})
    assert r.status_code == 200
    rows = c.get("/api/dns").get_json()["rewrites"]
    assert any(x["id"] == rid and x["enabled"] is False for x in rows), rows
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    cfg = dbmod.load_app_config(conn)
    conn.close()
    assert all(w.domain != "off.example" for w in cfg.dns_rewrites)
    # 4. traffic month: zero-filled + today
    m = c.get("/api/traffic/month?month=2026-02").get_json()
    assert m["today"] and len(m["days"]) == 28, (m["today"], len(m["days"]))
    assert all(d["up"] == 0 and d["down"] == 0 for d in m["days"])
    assert m["days"][0]["day"] == "2026-02-01" and m["days"][-1]["day"] == "2026-02-28"
    print("OK: original parity batch (expected_status/test_url, wan dns, rewrite enabled, month)")


def test_geodata_api():
    from core import geodata as _gd
    app = _app()
    c = app.test_client()
    r = c.get("/api/geodata").get_json()
    assert "dir" in r and "referenced" in r and "files" in r and "missing" in r, r
    # referenced rule-sets come from the 12 seeded site sets
    assert "geosite-youtube" in r["referenced"] and "geoip-cn" in r["referenced"]
    # ensure with mocked download writes a file and reports it
    orig_dl = _gd._download
    orig_dir = _gd.geodata_dir
    import tempfile
    tmpd = tempfile.mkdtemp()
    _gd.geodata_dir = lambda db_path=None: tmpd
    try:
        _gd._download = lambda url, dest, timeout=60: open(dest, "wb").write(b"srs")
        res = c.post("/api/geodata/ensure", json={"names": ["geosite-youtube"]}).get_json()
        assert res["downloaded"] == ["geosite-youtube"] and res["missing"] == [], res
        assert _gd.is_available("geosite-youtube")
        r2 = c.get("/api/geodata").get_json()
        assert any(f["name"] == "geosite-youtube" for f in r2["files"]), r2
    finally:
        _gd._download = orig_dl
        _gd.geodata_dir = orig_dir
    print("OK: geodata api (list/ensure)")


def test_terminal_mac():
    from core import arp as _arp
    from core import singbox as _sb
    from core import transparent as _tp
    # unit: mac detect / split / expand
    assert _arp.is_mac("AA:bb:CC:dd:EE:ff")
    assert not _arp.is_mac("192.168.1.1") and not _arp.is_mac("192.168.1.0/24")
    macs, ips = _arp.split_mac_ip(["aa:bb:cc:dd:ee:ff", "192.168.1.5", "10.0.0.0/8"])
    assert macs == ["aa:bb:cc:dd:ee:ff"] and ips == ["192.168.1.5", "10.0.0.0/8"]
    fake = {"192.168.1.50": "aa:bb:cc:dd:ee:ff"}
    assert _arp.expand_terminal_idents(
        ["aa:bb:cc:dd:ee:ff", "192.168.1.5", "aa:00:00:00:00:00"], fake) == [
        "192.168.1.50", "192.168.1.5"]
    # sing-box: MAC direct-terminal resolves to ARP IP, never leaks a MAC
    # into source_ip_cidr
    orig = _arp.arp_table
    _arp.arp_table = lambda: dict(fake)
    try:
        app = _app()
        c = app.test_client()
        r = c.post("/api/terminals", json={"ident": "aa:bb:cc:dd:ee:ff",
                                           "name": "macbook", "policy": "direct"})
        assert r.status_code == 201, r.get_data(as_text=True)
        conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
        cfg = dbmod.load_app_config(conn)
        conn.close()
        conf = _sb.build_config(cfg)
        rules = [x for x in conf["route"]["rules"] if "source_ip_cidr" in x]
        assert rules, "no source_ip_cidr rule generated"
        assert rules[0]["source_ip_cidr"] == ["192.168.1.50"], rules[0]
        assert rules[0]["outbound"] == "direct"
        # nftables: MAC bypass matches ether saddr directly
        tcfg = _tp.TransparentConfig(terminal_bypass=["aa:bb:cc:dd:ee:ff",
                                                     "192.168.1.60"])
        script = _tp.nft_script(tcfg)
        assert "type ether_addr" in script and "aa:bb:cc:dd:ee:ff" in script
        assert "ether saddr @macbypass accept" in script
        assert "192.168.1.60" in script and "ip saddr @tbypass accept" in script
        # API: arp table endpoint
        r = c.get("/api/arp")
        assert r.status_code == 200 and "entries" in r.get_json()
    finally:
        _arp.arp_table = orig
    print("OK: terminal MAC ident (arp resolve + nft ether match)")


def main():
    test_dns_api()
    test_terminals_api()
    test_terminal_mac()
    test_orig_parity_batch()
    test_geodata_api()
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
