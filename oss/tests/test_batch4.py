"""Batch 4 tests: subscription shares + public link, subscription refresh,
share network, terminal probe, node-info cache, timezone."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def _dbconn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


def test_sub_shares():
    app = _app()
    c = app.test_client()
    assert c.get("/api/subscription-shares").get_json() == []
    r = c.post("/api/subscription-shares", json={})
    assert r.status_code == 400
    s = c.post("/api/subscription-shares",
               json={"name": "s1", "node_filter": ""}).get_json()
    assert len(s["token"]) > 16
    tok1 = s["token"]
    # public link serves a (possibly empty) subscription file, no login needed
    r = c.get(f"/sub/{tok1}")
    assert r.status_code == 200 and "text/plain" in r.content_type
    assert c.get("/sub/badtoken").status_code == 404
    # patch + regenerate
    r = c.patch(f"/api/subscription-shares/{s['id']}",
                json={"name": "s1b"})
    assert r.get_json()["name"] == "s1b"
    r = c.post(f"/api/subscription-shares/{s['id']}/regenerate").get_json()
    assert r["token"] != tok1
    assert c.get(f"/sub/{tok1}").status_code == 404  # old token dead
    assert c.delete(f"/api/subscription-shares/{s['id']}").get_json()["ok"]
    assert c.delete("/api/subscription-shares/999").status_code == 404
    print("ok subscription shares")


def test_sub_refresh_validation():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=")
    conn.close()
    assert c.post(f"/api/subscriptions/{sid}/refresh").status_code == 400  # no url
    assert c.post("/api/subscriptions/999/refresh").status_code == 404
    print("ok subscription refresh validation")


def test_share_network():
    app = _app()
    c = app.test_client()
    d = c.get("/api/share-network").get_json()
    assert d == {"enabled": False, "port": 8088}
    assert c.put("/api/share-network", json={"port": 80}).status_code == 400
    r = c.put("/api/share-network",
              json={"enabled": True, "port": 8088}).get_json()
    assert r["enabled"] is True
    r = c.get("/api/share-network/port-check?port=8080").get_json()
    assert r["port"] == 8080 and "conflicts" in r
    r = c.get("/api/share-network/port-check?port=8080").get_json()
    assert any("8080" in x for x in r["conflicts"])  # panel port conflict
    print("ok share network")


def test_share_network_config():
    # enabled LAN share adds an inbound to the generated config
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.singbox import build_config
    from core.models import AppConfig
    cfg = AppConfig(share_lan_enabled=True, share_lan_port=18088)
    inbounds = build_config(cfg)["inbounds"]
    lan = [i for i in inbounds if i["tag"] == "lan-share-in"]
    assert lan and lan[0]["listen_port"] == 18088 and lan[0]["listen"] == "0.0.0.0"
    cfg2 = AppConfig()
    assert not [i for i in build_config(cfg2)["inbounds"] if i["tag"] == "lan-share-in"]
    print("ok share network config")


def test_terminal_probe():
    app = _app()
    c = app.test_client()
    cap = c.get("/api/terminal-test/capability").get_json()
    assert cap["tcp"] is True and "ping" in cap
    assert c.post("/api/terminal-test", json={}).status_code == 400
    r = c.post("/api/terminal-test",
               json={"target": "127.0.0.1", "timeout": 2}).get_json()
    assert r["target"] == "127.0.0.1" and "ping" in r and "tcp" in r
    # candidates: empty traffic + no leases file -> {"candidates": [...]}
    body = c.get("/api/terminal-candidates").get_json()
    assert isinstance(body.get("candidates"), list)
    print("ok terminal probe")


def test_node_info_cache():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=")
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
        " VALUES (?, 'n1', 'vmess', 'example.com', 443, '{}')", (sid,))
    conn.commit()
    conn.close()
    assert c.get("/api/node-info/n1").status_code == 404  # no cache yet
    assert c.get("/api/node-info/nope").status_code == 404
    # cache write/read path
    conn = _dbconn(app)
    dbmod.set_node_info_cache(conn, "n1", {"ok": True, "ip": "1.2.3.4",
                                           "country": "Nowhere"})
    conn.close()
    d = c.get("/api/node-info/n1").get_json()
    assert d["ip"] == "1.2.3.4" and d["cached"] is True
    # exit refresh without binary -> 409 honest error (use a node with no cache)
    conn = _dbconn(app)
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
        " VALUES (1, 'n2', 'vmess', 'example.com', 443, '{}')")
    conn.commit()
    conn.close()
    r = c.post("/api/node-info/n2/exit")
    assert r.status_code == 409, r.get_json()
    # throttle: n1 has a fresh cache -> 429
    assert c.post("/api/node-info/n1/exit").status_code == 429
    print("ok node info cache + throttle")


def test_timezone():
    app = _app()
    c = app.test_client()
    d = c.get("/api/system/timezone").get_json()
    assert "timezone" in d and "options" in d and "Asia/Shanghai" in d["options"]
    assert c.put("/api/system/timezone", json={}).status_code == 400
    assert c.put("/api/system/timezone",
                 json={"timezone": "bogus"}).status_code in (400, 409)
    print("ok timezone (read-only on non-OpenWrt)")


def main():
    test_sub_shares()
    test_sub_refresh_validation()
    test_share_network()
    test_share_network_config()
    test_terminal_probe()
    test_node_info_cache()
    test_timezone()
    print("ALL BATCH4 TESTS PASSED")


if __name__ == "__main__":
    main()
