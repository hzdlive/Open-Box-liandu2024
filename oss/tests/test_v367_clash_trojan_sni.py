"""v0.1.367 (#743): Clash-imported Trojan must keep its SNI.

Clash trojan entries carry no tls: key (the format puts sni/alpn/
skip-cert-verify at top level) and trojan is TLS by definition, so
the import must force TLS like tuic/hy2/anytls. Before this fix the
tls dict was dropped entirely: the kernel outbound lost TLS/SNI and
a later share link lost the original sni as well.
"""
import sys

sys.path.insert(0, "oss")

from core.clash import parse_clash_yaml
from core.share import encode_node


def _trojan_doc(extra: str = "") -> str:
    return (
        "proxies:\n"
        "  - name: trojan-sni\n"
        "    type: trojan\n"
        "    server: 203.0.113.7\n"
        "    port: 443\n"
        "    password: secret\n"
        "    sni: cdn.example.com\n"
        "    alpn: [h2, http/1.1]\n"
        "    skip-cert-verify: true\n"
        + extra
    )


def test_trojan_sni_kept_without_tls_key():
    nodes = parse_clash_yaml(_trojan_doc())
    assert len(nodes) == 1
    tls = nodes[0].params.get("tls")
    assert tls, "trojan import dropped tls entirely"
    assert tls["enabled"] is True
    assert tls["server_name"] == "cdn.example.com"
    assert tls["insecure"] is True
    assert tls["alpn"] == ["h2", "http/1.1"]


def test_trojan_share_link_keeps_original_sni():
    nodes = parse_clash_yaml(_trojan_doc())
    n = nodes[0]
    # encode_node takes the DB node shape (tag/protocol/server/port/
    # params), as subshare_public/share_links pass it.
    link = encode_node({"tag": n.tag, "protocol": n.protocol, "server": n.server,
                        "port": n.server_port, "params": n.params})
    assert link is not None and "sni=cdn.example.com" in link


def test_trojan_ws_transport_and_sni_coexist():
    doc = _trojan_doc("    network: ws\n    ws-opts:\n      path: /ws\n")
    nodes = parse_clash_yaml(doc)
    assert len(nodes) == 1
    assert nodes[0].params["tls"]["server_name"] == "cdn.example.com"
    assert nodes[0].params["transport"]["type"] == "ws"


def test_vmess_without_tls_still_means_no_tls():
    doc = (
        "proxies:\n"
        "  - name: vmess-plain\n"
        "    type: vmess\n"
        "    server: 203.0.113.8\n"
        "    port: 8080\n"
        "    uuid: 11111111-2222-3333-4444-555555555555\n"
        "    cipher: auto\n"
    )
    nodes = parse_clash_yaml(doc)
    assert len(nodes) == 1
    assert "tls" not in nodes[0].params


def test_vless_tls_servername_unchanged():
    doc = (
        "proxies:\n"
        "  - name: vless-tls\n"
        "    type: vless\n"
        "    server: 203.0.113.9\n"
        "    port: 443\n"
        "    uuid: 11111111-2222-3333-4444-555555555555\n"
        "    tls: true\n"
        "    servername: vless.example.com\n"
    )
    nodes = parse_clash_yaml(doc)
    assert len(nodes) == 1
    assert nodes[0].params["tls"]["server_name"] == "vless.example.com"
