"""Chain node-info (item 5): chains resolve through their front, cache
key carries front + exit identity. The probe itself (scratch sing-box)
is mocked here; live verification runs on the VPS."""

import json
import sqlite3
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import AppConfig, Node  # noqa: E402
from core import nodeinfo as ni  # noqa: E402
from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def _dbconn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


def _seed(app):
    conn = _dbconn(app)
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=")
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
        " VALUES (?, 'n1', 'vmess', 'example.com', 443, '{}')",
        (sid,))
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params, disabled)"
        " VALUES (?, 'off1', 'vmess', 'example.com', 443, '{}', 1)",
        (sid,))
    conn.execute(
        "INSERT INTO chains(name, exit_protocol, server, port, params, front, enabled)"
        " VALUES ('ch1', 'shadowsocks', '203.0.113.9', 8388, '{}', 'n1', 1)")
    conn.execute(
        "INSERT INTO chains(name, exit_protocol, server, port, params, front, enabled)"
        " VALUES ('ch-off', 'shadowsocks', '203.0.113.9', 8388, '{}', 'n1', 0)")
    conn.commit()
    conn.close()


def test_resolver_scope():
    app = _app()
    _seed(app)
    c = app.test_client()
    # Chain found (no cache yet) vs disabled chain not found.
    d = c.get("/api/node-info/ch1").get_json()
    assert d["ok"] is False and "暂无缓存" in d["message"]
    assert c.get("/api/node-info/ch-off").get_json() == {"error": "not found"}
    assert c.get("/api/node-info/off1").get_json() == {"error": "not found"}
    assert c.get("/api/node-info/nope").get_json() == {"error": "not found"}


def test_chain_cache_key():
    base = {"name": "ch1", "front": "n1", "exit_protocol": "shadowsocks",
            "server": "203.0.113.9", "port": 8388, "params": {}}
    k = ni.chain_cache_key(base)
    assert "n1" in k and "203.0.113.9" in k and "8388" in k
    assert ni.chain_cache_key({**base, "front": "n2"}) != k
    assert ni.chain_cache_key({**base, "server": "203.0.113.10"}) != k
    # Credential-only edits do not invalidate the measured exit.
    assert ni.chain_cache_key(
        {**base, "params": {"password": "changed"}}) == k


def _cfg_with_node():
    return AppConfig(
        nodes=[Node(tag="n1", protocol="vmess", server="example.com",
                    server_port=443, params={})],
        subscriptions=[], groups=[], chains=[],
        speedtest_url="http://www.gstatic.com/generate_204")


def _chain(front="n1", proto="shadowsocks"):
    return {"name": "ch1", "front": front, "exit_protocol": proto,
            "server": "203.0.113.9", "port": 8388, "params": {}}


def test_probe_chain_mapping_and_front_errors():
    canned = {"ok": True, "latency_ms": 123, "exit_ip": "1.2.3.4",
              "country": "Nowhere", "error": None}
    with mock.patch("os.path.isfile", return_value=True), \
            mock.patch("os.access", return_value=True), \
            mock.patch("core.chain_test.test_chain",
                       return_value=canned) as tc:
        r = ni.probe_chain(_chain(), _cfg_with_node())
    assert r == {"ok": True, "ip": "1.2.3.4", "country": "Nowhere",
                 "latency_ms": 123, "via": "chain",
                 "proxy_type": "shadowsocks"}
    assert tc.call_args[1]["front_outbound"]["tag"] == "n1"

    # Unresolvable front fails fast without calling test_chain.
    with mock.patch("os.path.isfile", return_value=True), \
            mock.patch("os.access", return_value=True), \
            mock.patch("core.chain_test.test_chain") as tc2:
        r = ni.probe_chain(_chain(front="nope"), _cfg_with_node())
    assert r == {"ok": False, "error": "chain front not found: nope"}
    tc2.assert_not_called()

    # Wireguard exit is an outbound error (400 at the endpoint).
    with mock.patch("os.path.isfile", return_value=True), \
            mock.patch("os.access", return_value=True):
        try:
            ni.probe_chain(_chain(proto="wireguard"), _cfg_with_node())
            raise AssertionError("expected OutboundError")
        except ni.OutboundError:
            pass


def test_chain_exit_endpoint_caches_and_throttles():
    app = _app()
    _seed(app)
    c = app.test_client()
    canned = {"ok": True, "latency_ms": 99, "exit_ip": "5.6.7.8",
              "country": "Somewhere", "error": None}
    with mock.patch("os.path.isfile", return_value=True), \
            mock.patch("os.access", return_value=True), \
            mock.patch("core.chain_test.test_chain",
                       return_value=canned):
        r = c.post("/api/node-info/ch1/exit")
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["ip"] == "5.6.7.8"
        d = c.get("/api/node-info/ch1").get_json()
        assert d["ip"] == "5.6.7.8" and d["cached"] is True
        assert c.post("/api/node-info/ch1/exit").status_code == 429


def test_chain_entry_country_uses_exit_server():
    app = _app()
    _seed(app)
    c = app.test_client()
    with mock.patch("core.nodeinfo.entry_country",
                    return_value={"ok": True, "country": "X"}) as ec:
        r = c.get("/api/node-info/ch1/entry-country")
    assert r.status_code == 200
    assert ec.call_args[0][0] == {"server": "203.0.113.9"}
