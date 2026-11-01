"""v0.1.361: TUIC/Hysteria2 certificate fingerprint, WireGuard link
import (pre-shared key + MTU), subscription mode tags, share encoders."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import clash as clashmod
from core import share as sharemod
from core import singbox as sbmod
from core import subscription as submod
from panel import db as dbmod
from panel.app import create_app


def _seed_conn():
    app = create_app(":memory:")
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    return conn


def test_tuic_link_keeps_fp():
    nodes = submod.parse_subscription(
        "tuic://11111111-2222-3333-4444-555555555555:pw@host.example:443"
        "?congestion_control=bbr&sni=s.example&alpn=h3&fp=chrome#tuic1")
    assert len(nodes) == 1
    tls = nodes[0].params["tls"]
    assert tls["fingerprint"] == "chrome"
    assert tls["server_name"] == "s.example"
    assert tls["alpn"] == ["h3"]


def test_hy2_link_keeps_fp_and_pin():
    nodes = submod.parse_subscription(
        "hysteria2://pw@host.example:443?obfs=salamander&obfs-password=ob"
        "&sni=s.example&fp=firefox&pinSHA256=DEADBEEF#hy1")
    assert len(nodes) == 1
    n = nodes[0]
    assert n.params["tls"]["fingerprint"] == "firefox"
    assert n.params["tls"]["pin_sha256"] == "DEADBEEF"
    assert n.params["obfs"] == {"type": "salamander", "password": "ob"}


def test_hy2_fingerprint_reaches_kernel_tls_block():
    nodes = submod.parse_subscription(
        "hysteria2://pw@host.example:443?sni=s.example&fp=chrome#hy1")
    ob = sbmod.node_to_outbound(nodes[0])
    assert ob["tls"]["utls"] == {"enabled": True, "fingerprint": "chrome"}


def test_wireguard_link_full():
    # Private key contains "/" raw: the manual parser must not split it.
    link = ("wireguard://ab%2Fcd%2Bef%3D%3D@wg.example:51820"
            "?publickey=PEERPUBKEY&presharedkey=PSK123"
            "&address=10.0.0.2%2F32%2Cfd00%3A%3A2%2F128&mtu=1400#wg1")
    nodes = submod.parse_subscription(link)
    assert len(nodes) == 1
    n = nodes[0]
    assert n.protocol == "wireguard"
    assert n.params["private_key"] == "ab/cd+ef=="
    assert n.params["peer_public_key"] == "PEERPUBKEY"
    assert n.params["pre_shared_key"] == "PSK123"
    assert n.params["local_address"] == ["10.0.0.2/32", "fd00::2/128"]
    assert n.params["mtu"] == 1400


def test_wireguard_link_alias_and_endpoint():
    nodes = submod.parse_subscription(
        "wireguard://PRIVKEY@wg.example:51820"
        "?public-key=PUB&pre-shared-key=PSK&address=10.0.0.3/32&mtu=1280#wg2")
    assert len(nodes) == 1
    n = nodes[0]
    assert n.params["pre_shared_key"] == "PSK"
    assert n.params["mtu"] == 1280
    ep = sbmod.node_to_endpoint(n)
    assert ep["peers"][0]["pre_shared_key"] == "PSK"
    assert ep["mtu"] == 1280
    assert ep["address"] == ["10.0.0.3/32"]


def test_clash_tuic_without_tls_key_keeps_fingerprint():
    text = """proxies:
  - name: tuic1
    type: tuic
    server: host.example
    port: 443
    uuid: 11111111-2222-3333-4444-555555555555
    password: pw
    sni: s.example
    fingerprint: chrome
    skip-cert-verify: true
"""
    nodes = clashmod.parse_clash_yaml(text)
    assert len(nodes) == 1
    tls = nodes[0].params["tls"]
    assert tls["fingerprint"] == "chrome"
    assert tls["insecure"] is True
    assert tls["server_name"] == "s.example"


def test_clash_vmess_tls_false_still_means_no_tls():
    text = """proxies:
  - name: v1
    type: vmess
    server: host.example
    port: 443
    uuid: 11111111-2222-3333-4444-555555555555
    cipher: auto
    fingerprint: chrome
"""
    nodes = clashmod.parse_clash_yaml(text)
    assert len(nodes) == 1
    assert "tls" not in nodes[0].params


def test_clash_wireguard_psk_mtu_regression():
    text = """proxies:
  - name: wg1
    type: wireguard
    server: wg.example
    port: 51820
    ip: 10.0.0.2/32
    private-key: PRIV
    public-key: PUB
    pre-shared-key: PSK
    mtu: 1400
"""
    nodes = clashmod.parse_clash_yaml(text)
    assert len(nodes) == 1
    assert nodes[0].params["pre_shared_key"] == "PSK"
    assert nodes[0].params["mtu"] == 1400


def test_share_roundtrip_new_protocols():
    cases = [
        ("tuic://11111111-2222-3333-4444-555555555555:pw@host.example:443"
         "?congestion_control=bbr&sni=s.example&fp=chrome#tuic1",
         lambda n: n.params["tls"]["fingerprint"] == "chrome"),
        ("hysteria2://pw@host.example:443?sni=s.example&fp=firefox"
         "&pinSHA256=DEADBEEF#hy1",
         lambda n: n.params["tls"]["pin_sha256"] == "DEADBEEF"
         and n.params["tls"]["fingerprint"] == "firefox"),
        ("anytls://pw@host.example:443?sni=s.example&fp=chrome#at1",
         lambda n: n.params["tls"]["fingerprint"] == "chrome"),
        ("wireguard://PRIV@wg.example:51820?publickey=PUB&presharedkey=PSK"
         "&address=10.0.0.2/32&mtu=1400#wg1",
         lambda n: n.params["pre_shared_key"] == "PSK"
         and n.params["mtu"] == 1400),
    ]
    for link, check in cases:
        nodes = submod.parse_subscription(link)
        assert len(nodes) == 1, link
        n = nodes[0]
        d = {"tag": n.tag, "protocol": n.protocol, "server": n.server,
             "port": n.server_port, "params": n.params}
        back = sharemod.encode_node(d)
        renodes = submod.parse_subscription(back)
        assert len(renodes) == 1, back
        assert check(renodes[0]), back


def test_subscription_mode_tags():
    conn = _seed_conn()
    conn.execute(
        "INSERT INTO subscriptions(name, source, url, urls, created_at) VALUES (?,?,?,?,?)",
        ("login-sub", "login", "http://x/token", '["http://x/token"]', "2026-11-01"))
    conn.execute(
        "INSERT INTO subscriptions(name, source, url, urls, created_at) VALUES (?,?,?,?,?)",
        ("url-sub", "manual", "http://x/sub", "[]", "2026-11-01"))
    conn.execute(
        "INSERT INTO subscriptions(name, source, url, urls, created_at) VALUES (?,?,?,?,?)",
        ("node-sub", "manual", "", "[]", "2026-11-01"))
    conn.execute(
        "INSERT INTO subscriptions(name, source, url, urls, created_at) VALUES (?,?,?,?,?)",
        ("content-url-sub", "manual", "", '["http://x/sub"]', "2026-11-01"))
    conn.commit()
    modes = {s["name"]: s["mode"] for s in dbmod.list_subscriptions(conn)}
    assert modes["login-sub"] == "login"
    assert modes["url-sub"] == "subscription"
    assert modes["node-sub"] == "node"
    assert modes["content-url-sub"] == "subscription"
