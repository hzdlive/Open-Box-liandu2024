"""Phase 3 tests: service lifecycle, apply pipeline, transparent gen,
failover election, share encoders, backup/restore, new panel APIs.

Uses a fake sing-box binary (shell script) and a stub clash API server;
nothing touches the real network or firewall.
"""

import base64
import io
import json
import os
import stat
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import backup as backupmod           # noqa: E402
from core import failover as fom                # noqa: E402
from core import share as sharemod              # noqa: E402
from core import transparent as tmod            # noqa: E402
from core.apply import apply_config, build_and_validate  # noqa: E402
from core.service import KernelManager          # noqa: E402
from core.subscription import parse_subscription  # noqa: E402
from panel import db as dbmod                   # noqa: E402
from panel.app import create_app                # noqa: E402

ROOT = Path(__file__).resolve().parent

FAKE_SINGBOX = """#!/bin/sh
case "$1" in
  version) echo "sing-box version 1.14.1-test";;
  check)
    shift; CFG=""
    while [ $# -gt 0 ]; do case "$1" in -c) CFG="$2"; shift 2;; *) shift;; esac; done
    python3 -c "import json; json.load(open('$CFG'))" && echo ok || { echo bad >&2; exit 1; };;
  run)
    shift
    while [ $# -gt 0 ]; do case "$1" in -c) CFG="$2"; shift 2;; *) shift;; esac; done
    echo "running $CFG" >&2
    trap "exit 0" TERM INT
    while true; do sleep 1; done;;
esac
"""


def make_fake_bin(tmp: str) -> str:
    p = os.path.join(tmp, "sing-box")
    with open(p, "w") as f:
        f.write(FAKE_SINGBOX)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


def make_db_with_nodes(tmp: str):
    import sqlite3
    conn = sqlite3.connect(os.path.join(tmp, "t.db"))
    dbmod.init_db(conn)
    dbmod.add_subscription(conn, "t", (ROOT / "sample-sub.txt").read_text())
    return conn


def test_service_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        fake = make_fake_bin(tmp)
        m = KernelManager(bin_path=fake, workdir=os.path.join(tmp, "wd"))
        assert m.is_installed()
        assert m.version() == "1.14.1-test"
        st = m.status()
        assert not st.running and st.pid is None

        # check_config ok / bad
        good = os.path.join(tmp, "good.json"); open(good, "w").write("{}")
        bad = os.path.join(tmp, "bad.json"); open(bad, "w").write("{nope")
        assert m.check_config(good)[0] is True
        assert m.check_config(bad)[0] is False

        # start without config -> error
        try:
            m.start()
            raise AssertionError("should have raised")
        except RuntimeError:
            pass

        open(m.config_path, "w").write("{}")
        st = m.start()
        assert st.running and st.pid
        assert m.status().running
        time_up = m.status().uptime_s
        assert time_up is not None and time_up >= 0

        assert "running" in m.log_tail()
        m.stop()
        assert not m.status().running
        # double stop is fine
        m.stop()
        st = m.restart()
        assert st.running
        m.stop()
    print("OK: service lifecycle (fake sing-box)")


def test_apply_pipeline():
    with tempfile.TemporaryDirectory() as tmp:
        fake = make_fake_bin(tmp)
        conn = make_db_with_nodes(tmp)
        m = KernelManager(bin_path=fake, workdir=os.path.join(tmp, "wd"))
        cfg, ok, msg = build_and_validate(conn, m)
        assert ok, msg
        assert len(cfg["outbounds"]) > 5
        res = apply_config(conn, m)
        assert res["applied"] and res["service"]["running"]
        assert os.path.isfile(m.config_path)
        # restart path: apply again while running
        res2 = apply_config(conn, m)
        assert res2["service"]["running"]
        m.stop()
        conn.close()
    print("OK: apply pipeline (validate -> atomic write -> start/restart)")


def test_transparent_gen():
    cfg = tmod.TransparentConfig(tproxy_port=7893, lan_iface="br-lan")
    nft = tmod.nft_script(cfg)
    assert "table inet openbox-oss" in nft
    assert "tproxy to 127.0.0.1:7893" in nft
    assert "192.168.0.0/16" in nft
    assert 'iifname != "br-lan"' in nft
    rules = tmod.ip_rules(cfg)
    assert "fwmark 0x1 table 100" in rules
    dns = tmod.dnsmasq_snippet(cfg)
    assert "server=127.0.0.1#1053" in dns
    print("OK: transparent artifacts generation (nft/iprules/dnsmasq)")


class ClashStub(BaseHTTPRequestHandler):
    calls: list = []

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        ClashStub.calls.append((self.path, json.loads(body)))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_failover():
    # election logic
    assert fom.elect_active(["a", "b"], {"a": True, "b": True}) == "a"
    assert fom.elect_active(["a", "b"], {"a": False, "b": True}) == "b"
    assert fom.elect_active(["a", "b"], {"a": None, "b": None}) == "a"
    assert fom.elect_active(["a", "b"], {"a": False, "b": None}) == "b"
    assert fom.elect_active(["a", "b"], {"a": False, "b": False}) == "a"  # fail open
    assert fom.elect_active([], {}) is None

    # watch_once against stub clash API
    ClashStub.calls = []
    srv = HTTPServer(("127.0.0.1", 0), ClashStub)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        groups = [{"name": "fo", "type": "failover", "members": ["n1", "n2"]},
                  {"name": "所有-自动", "type": "urltest", "members": ["n1"]}]
        health = [{"tag": "n1", "ok": False}, {"tag": "n2", "ok": True}]
        actions = fom.watch_once(groups, health, f"http://127.0.0.1:{port}", "")
        assert len(actions) == 1, actions
        assert actions[0]["target"] == "n2" and actions[0]["action"] == "switch"
        assert ClashStub.calls and ClashStub.calls[0][0] == "/proxies/fo"
        assert ClashStub.calls[0][1] == {"name": "n2"}
    finally:
        srv.shutdown()
    print("OK: failover election + clash API switch")


def test_share_roundtrip():
    links = [
        "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443"
        "?security=reality&sni=example.com&fp=chrome&pbk=PUBKEY&sid=abcd&type=ws&path=/w&host=h.example.com#tag-one",
        "trojan://secretpw@5.6.7.8:443?sni=s.example.com&alpn=h2,http/1.1#tag-two",
        "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@9.9.9.9:8388#tag-three",
    ]
    for link in links:
        nodes = parse_subscription(link)
        assert len(nodes) == 1, link
        n = nodes[0]
        d = {"tag": n.tag, "protocol": n.protocol, "server": n.server,
             "port": n.server_port, "params": n.params}
        back = sharemod.encode_node(d)
        n2 = parse_subscription(back)[0]
        assert n2.server == n.server and n2.server_port == n.server_port, back
        assert n2.params.get("uuid", n2.params.get("password")) == \
            n.params.get("uuid", n.params.get("password")), back
    # unsupported protocol reports error inline
    out = sharemod.encode_nodes([{"tag": "x", "protocol": "wireguard",
                                  "server": "s", "port": 1, "params": {}}])
    assert "error" in out[0]
    print("OK: share encoders round-trip (vless/trojan/ss)")


def test_backup_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        import sqlite3
        p = os.path.join(tmp, "t.db")
        conn = sqlite3.connect(p)
        dbmod.init_db(conn)
        dbmod.add_subscription(conn, "t", (ROOT / "sample-sub.txt").read_text())
        dbmod.create_site_set(conn, {"name": "s1", "action": "direct"})
        text = backupmod.backup_to_json(conn)
        data = json.loads(text)
        assert data["format"] == "openbox-oss-backup"
        n_nodes = len(dbmod.list_nodes(conn))
        n_sites = len(dbmod.list_site_sets(conn))  # 12 seeded defaults + s1
        conn.execute("DELETE FROM nodes")
        conn.execute("DELETE FROM site_sets")
        res = backupmod.backup_from_json(conn, text)
        assert res["counts"]["nodes"] == n_nodes
        assert len(dbmod.list_nodes(conn)) == n_nodes
        assert len(dbmod.list_site_sets(conn)) == n_sites
        try:
            backupmod.backup_from_json(conn, '{"format":"nope"}')
            raise AssertionError("should have raised")
        except ValueError:
            pass
        conn.close()
    print("OK: backup export/import round-trip")


def test_phase3_api():
    with tempfile.TemporaryDirectory() as tmp:
        import sqlite3
        dbfile = os.path.join(tmp, "t.db")
        app = create_app(dbfile)
        c = app.test_client()
        conn = sqlite3.connect(dbfile)
        dbmod.add_subscription(conn, "t", (ROOT / "sample-sub.txt").read_text())
        conn.close()

        # service (no binary here -> installed False, start -> 409)
        r = c.get("/api/service")
        assert r.status_code == 200 and r.get_json()["installed"] is False
        assert c.post("/api/service/start").status_code == 409
        assert c.get("/api/service/log").status_code == 200

        # transparent previews
        for p in ("/api/transparent/nft", "/api/transparent/iprules",
                  "/api/transparent/dnsmasq"):
            r = c.get(p)
            assert r.status_code == 200 and r.get_json()["script"], p

        # share
        nodes = c.get("/api/nodes").get_json()
        tags = [n["tag"] for n in nodes[:3]]
        r = c.post("/api/share", json={"node_tags": tags})
        assert r.status_code == 200 and len(r.get_json()) == 3
        assert all("link" in x for x in r.get_json()), r.get_json()
        r = c.get("/api/share/qr", query_string={"text": "vless://x"})
        assert r.status_code == 200 and r.mimetype == "image/png"

        # backup export/import
        r = c.get("/api/backup")
        assert r.status_code == 200
        blob = r.get_data(as_text=True)
        assert c.post("/api/backup", data=blob,
                      content_type="application/json").status_code == 200
        assert c.post("/api/backup", json={"format": "nope"}).status_code == 400

        # failover group type accepted + elect (no kernel -> actions report failed)
        gid = c.post("/api/groups", json={"name": "fo1", "type": "failover",
                                          "members": [tags[0]]}).get_json()["id"]
        r = c.post("/api/failover/elect", json={})
        assert r.status_code == 200
        acts = r.get_json()
        assert any(a["group"] == "fo1" for a in acts), acts
        assert c.delete(f"/api/groups/{gid}").status_code == 200

        # failover renders as selector in generated config
        c.post("/api/groups", json={"name": "fo2", "type": "failover",
                                    "members": [tags[0]]})
        conf = c.get("/api/config").get_json()
        fo = [o for o in conf["outbounds"] if o.get("tag") == "fo2"]
        assert fo and fo[0]["type"] == "selector", fo
    print("OK: phase3 panel APIs")


if __name__ == "__main__":
    test_service_lifecycle()
    test_apply_pipeline()
    test_transparent_gen()
    test_failover()
    test_share_roundtrip()
    test_backup_roundtrip()
    test_phase3_api()
    print("ALL PHASE3 TESTS PASSED")
