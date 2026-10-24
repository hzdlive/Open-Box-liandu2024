"""Wireguard-as-endpoint tests (sing-box 1.13+).

The wireguard OUTBOUND type was removed in sing-box 1.13: every legacy
field (server, system_interface, ...) fails check with "unknown field".
WG nodes must render as endpoints and are referenced by tag from
selectors/urltest/route rules exactly like outbounds.
"""
import sys
from types import SimpleNamespace

sys.path.insert(0, "oss")

from core.models import Node
from core.singbox import (build_endpoints, build_outbounds, node_to_endpoint,
                          node_to_outbound)
from core.subscription import parse_singbox_json

WG = Node(
    tag="wg-1", protocol="wireguard", server="203.0.113.1", server_port=51820,
    params={"private_key": "PRIV", "peer_public_key": "PUB",
            "local_address": ["10.0.0.2/32"], "mtu": 1400,
            "pre_shared_key": "PSK"},
)
VLESS = Node(tag="v-1", protocol="vless", server="example.com", server_port=443,
             params={"uuid": "u"})


def test_endpoint_shape():
    ep = node_to_endpoint(WG)
    assert ep["type"] == "wireguard" and ep["tag"] == "wg-1"
    assert ep["private_key"] == "PRIV" and ep["address"] == ["10.0.0.2/32"]
    assert ep["mtu"] == 1400
    # Legacy outbound fields must NOT appear (check rejects them).
    for banned in ("server", "server_port", "system_interface", "interface_name"):
        assert banned not in ep, banned
    peer = ep["peers"][0]
    assert peer == {"public_key": "PUB", "address": "203.0.113.1",
                    "port": 51820, "allowed_ips": ["0.0.0.0/0", "::/0"],
                    "pre_shared_key": "PSK"}, peer


def test_outbound_raises():
    try:
        node_to_outbound(WG)
    except RuntimeError as e:
        assert "endpoint" in str(e)
    else:
        raise AssertionError("wireguard outbound must raise")


def test_build_partition():
    cfg = SimpleNamespace(nodes=[VLESS, WG], chains=[], groups=[],
                          subscriptions=[], speedtest_url="https://example.com",
                          site_sets=[], front_rules=[], routing_fallback="",
                          final_outbound="direct")
    obs = build_outbounds(cfg)
    assert not any(o.get("type") == "wireguard" for o in obs)
    assert any(o.get("tag") == "v-1" for o in obs)
    # WG tag stays reachable from groups (urltest/selector accept endpoints).
    auto = [o for o in obs if o.get("tag") == "所有-自动"][0]
    manual = [o for o in obs if o.get("tag") == "所有-手动"][0]
    assert "wg-1" in auto["outbounds"] and "wg-1" in manual["outbounds"]
    eps = build_endpoints(cfg)
    assert len(eps) == 1 and eps[0]["tag"] == "wg-1"


def test_parse_endpoints():
    import json
    cfg = {
        "endpoints": [{
            "type": "wireguard", "tag": "wg-ep", "private_key": "PRIV",
            "address": ["10.0.0.2/32"], "mtu": 1280,
            "peers": [
                {"public_key": "PUB1", "address": "203.0.113.1", "port": 51820,
                 "pre_shared_key": "PSK1"},
                {"public_key": "PUB2", "address": "198.51.100.1", "port": 51821},
            ],
        }],
        "outbounds": [
            # Legacy wireguard outbounds are skipped (invalid on 1.14).
            {"type": "wireguard", "tag": "wg-old", "server": "203.0.113.9",
             "server_port": 51820},
        ],
    }
    nodes = parse_singbox_json(json.dumps(cfg))
    assert [n.tag for n in nodes] == ["wg-ep", "wg-ep #2"], [n.tag for n in nodes]
    n0, n1 = nodes
    assert (n0.server, n0.server_port) == ("203.0.113.1", 51820)
    assert (n1.server, n1.server_port) == ("198.51.100.1", 51821)
    assert n0.params["peer_public_key"] == "PUB1"
    assert n0.params["pre_shared_key"] == "PSK1"
    assert n0.params["local_address"] == ["10.0.0.2/32"]
    assert n0.params["mtu"] == 1280
    assert "pre_shared_key" not in n1.params
    # Round-trip: parsed nodes regenerate the endpoint shape.
    assert node_to_endpoint(n0)["peers"][0]["public_key"] == "PUB1"


if __name__ == "__main__":
    test_endpoint_shape()
    test_outbound_raises()
    test_build_partition()
    test_parse_endpoints()
    print("OK: wireguard endpoints — all cases pass")
