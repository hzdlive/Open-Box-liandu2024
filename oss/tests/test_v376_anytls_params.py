"""v0.1.376 (#663): AnyTLS session params + client metadata survive
import (link + Clash), config generation and share round-trip.

Field names/types were probed against the sing-box 1.14.1 binary
(check rejects unknown fields): idle_session_check_interval and
idle_session_timeout take duration strings, min_idle_session an int,
client_metadata a string.
"""
import sys
from types import SimpleNamespace

sys.path.insert(0, "oss")

from core import singbox
from core.clash import parse_clash_yaml
from core.share import encode_node
from core.subscription import parse_subscription

LINK = ("anytls://pw@203.0.113.7:443/?sni=any.example.com"
        "&idle_session_check_interval=30s&idle_session_timeout=60s"
        "&min_idle_session=2&client_metadata=ios-1.2#any-node")


def test_link_import_keeps_params():
    nodes = parse_subscription(LINK)
    assert len(nodes) == 1
    p = nodes[0].params
    assert p["idle_session_check_interval"] == "30s"
    assert p["idle_session_timeout"] == "60s"
    assert p["min_idle_session"] == 2
    assert p["client_metadata"] == "ios-1.2"


def test_config_generation_emits_params():
    nodes = parse_subscription(LINK)
    ob = singbox.node_to_outbound(nodes[0])
    assert ob["type"] == "anytls"
    assert ob["idle_session_check_interval"] == "30s"
    assert ob["idle_session_timeout"] == "60s"
    assert ob["min_idle_session"] == 2
    assert ob["client_metadata"] == "ios-1.2"


def test_share_roundtrip_keeps_params():
    nodes = parse_subscription(LINK)
    n = nodes[0]
    link = encode_node({"tag": n.tag, "protocol": n.protocol, "server": n.server,
                        "port": n.server_port, "params": n.params})
    back = parse_subscription(link)
    assert len(back) == 1
    p = back[0].params
    assert p["idle_session_check_interval"] == "30s"
    assert p["idle_session_timeout"] == "60s"
    assert p["min_idle_session"] == 2
    assert p["client_metadata"] == "ios-1.2"


def test_clash_import_keeps_params():
    doc = (
        "proxies:\n"
        "  - name: any-clash\n"
        "    type: anytls\n"
        "    server: 203.0.113.8\n"
        "    port: 443\n"
        "    password: pw\n"
        "    sni: any.example.com\n"
        "    idle-session-check-interval: 30s\n"
        "    idle-session-timeout: 60s\n"
        "    min-idle-session: 3\n"
        "    client-metadata: android-2.0\n"
    )
    nodes = parse_clash_yaml(doc)
    assert len(nodes) == 1
    p = nodes[0].params
    assert p["idle_session_check_interval"] == "30s"
    assert p["idle_session_timeout"] == "60s"
    assert p["min_idle_session"] == 3
    assert p["client_metadata"] == "android-2.0"


def test_plain_anytls_unchanged():
    nodes = parse_subscription("anytls://pw@203.0.113.7:443/?sni=a.com#x")
    ob = singbox.node_to_outbound(nodes[0])
    for key in ("idle_session_check_interval", "idle_session_timeout",
                "min_idle_session", "client_metadata"):
        assert key not in ob
