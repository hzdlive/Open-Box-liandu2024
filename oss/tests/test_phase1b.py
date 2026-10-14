"""Phase 1b self-test: clash import, anytls, rulesets, chains, groups, health."""

import base64
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.clash import parse_clash_yaml  # noqa: E402
from core.ruleset import parse_ruleset_text  # noqa: E402
from core.subscription import parse_subscription  # noqa: E402
from panel.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def test_clash_direct():
    nodes = parse_clash_yaml((ROOT / "sample-clash.yaml").read_text())
    assert len(nodes) == 5, len(nodes)
    by_tag = {n.tag: n for n in nodes}
    vmess = by_tag["clash-vmess"]
    assert vmess.params["transport"]["type"] == "ws"
    assert vmess.params["transport"]["path"] == "/ws"
    assert vmess.params["tls"]["server_name"] == "example.com"
    vless = by_tag["clash-vless-reality"]
    assert vless.params["tls"]["reality"]["public_key"] == "pk123"
    assert vless.params["flow"] == "xtls-rprx-vision"
    wg = by_tag["clash-wg"]
    assert wg.protocol == "wireguard" and wg.params["mtu"] == 1280
    print("OK: clash yaml -> 5 nodes (ss/vmess/vless/trojan/wireguard)")


def test_anytls_link():
    nodes = parse_subscription("anytls://secret@203.0.113.40:443/?sni=example.com&alpn=h2#anytls-demo")
    assert len(nodes) == 1 and nodes[0].protocol == "anytls"
    assert nodes[0].params["tls"]["server_name"] == "example.com"
    print("OK: anytls link parsed")


def test_ruleset_parse():
    txt = "DOMAIN-SUFFIX,google.com\nDOMAIN,example.com\nDOMAIN-KEYWORD,ads\nIP-CIDR,1.1.1.0/24\n# comment\nDST-PORT,80\n"
    r = parse_ruleset_text(txt)
    assert r["domain_suffix"] == ["google.com"]
    assert r["domains"] == ["example.com"]
    assert r["domain_keyword"] == ["ads"]
    assert r["ip_cidr"] == ["1.1.1.0/24"]
    r2 = parse_ruleset_text("google.com\n+.example.org\n10.0.0.0/8\n", fmt="domain-list")
    assert r2["domain_suffix"] == ["google.com", "example.org"], r2
    assert r2["ip_cidr"] == ["10.0.0.0/8"]
    print("OK: ruleset formats parsed (clash-classical + domain-list)")


class _RuleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"DOMAIN-SUFFIX,google.com\nDOMAIN,example.com\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_api():
    app = create_app(":memory:")
    c = app.test_client()

    # default groups seeded (+ built-in direct/block)
    groups = c.get("/api/groups").get_json()
    assert {g["name"] for g in groups} == {"所有-自动", "所有-手动", "direct", "block"}, groups

    # clash subscription import via API (auto-detect)
    clash_text = (ROOT / "sample-clash.yaml").read_text()
    r = c.post("/api/subscriptions", json={"name": "clash", "content": clash_text})
    assert r.status_code == 201 and r.get_json()["node_count"] == 5, r.get_data(as_text=True)

    # node with keyword tag for dynamic group test
    link = f"trojan://pw@203.0.113.50:443#%E9%A6%99%E6%B8%AF%E8%8A%82%E7%82%B9"  # 香港节点
    r = c.post("/api/subscriptions", json={"name": "kw", "content": link})
    assert r.get_json()["node_count"] == 1

    # dynamic keyword group
    r = c.post("/api/groups", json={"name": "hk", "type": "urltest",
                                    "dynamic_keywords": ["香港"]})
    assert r.status_code == 201
    conf = c.get("/api/config").get_json()
    hk = [o for o in conf["outbounds"] if o["tag"] == "hk"][0]
    assert any("香港" in t for t in hk["outbounds"]), hk["outbounds"]

    # chain proxy
    r = c.post("/api/chains", json={"name": "chain1", "exit_protocol": "socks",
                                   "server": "203.0.113.60", "port": 1080,
                                   "params": {"username": "u", "password": "p"},
                                   "front": "所有-自动"})
    assert r.status_code == 201, r.get_data(as_text=True)
    conf = c.get("/api/config").get_json()
    chain_ob = [o for o in conf["outbounds"] if o["tag"] == "chain1"][0]
    assert chain_ob["detour"] == "所有-自动" and chain_ob["username"] == "u", chain_ob
    manual = [o for o in conf["outbounds"] if o["tag"] == "所有-手动"][0]
    assert "chain1" in manual["outbounds"]  # chains join the static selector
    auto = [o for o in conf["outbounds"] if o["tag"] == "所有-自动"][0]
    assert "chain1" not in auto["outbounds"]  # but not the dynamic urltest

    # ruleset: local HTTP stub -> refresh -> site set reference
    httpd = HTTPServer(("127.0.0.1", 0), _RuleHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/rules.txt"
    r = c.post("/api/rulesets", json={"name": "rs1", "url": url})
    assert r.status_code == 201
    rid = r.get_json()["id"]
    r = c.post(f"/api/rulesets/{rid}/refresh")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "google.com" in r.get_json()["content"]
    r = c.post("/api/sitesets", json={"name": "rs-site", "action": "proxy",
                                      "rules": {"rule_sets": ["rs1"]}})
    assert r.status_code == 201
    r = c.post("/api/route/preview", json={"target": "mail.google.com"})
    assert r.get_json()["site_set"] == "rs-site", r.get_json()
    httpd.shutdown()

    # health check against local TCP stubs
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    open_port = srv.getsockname()[1]

    def serve_once():
        try:
            conn, _ = srv.accept()
            conn.close()
        except Exception:
            pass

    threading.Thread(target=serve_once, daemon=True).start()
    links = (f"ss://{b64('aes-256-gcm:p')}@127.0.0.1:{open_port}#local-ok\n"
             f"ss://{b64('aes-256-gcm:p')}@127.0.0.1:1#local-bad\n")
    r = c.post("/api/subscriptions", json={"name": "health", "content": links})
    assert r.get_json()["node_count"] == 2
    r = c.post("/api/health/check", json={"timeout": 3})
    assert r.status_code == 200
    res = {x["tag"]: x for x in r.get_json()}
    assert res["local-ok"]["ok"] is True and res["local-ok"]["latency_ms"] is not None, res
    assert res["local-bad"]["ok"] is False, res
    r = c.get("/api/health")
    assert len(r.get_json()) >= 2
    srv.close()

    print("OK: api phase1b (groups/chains/rulesets/health) passed")


def main() -> int:
    test_clash_direct()
    test_anytls_link()
    test_ruleset_parse()
    test_api()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
