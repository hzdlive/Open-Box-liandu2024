"""Tests for chain front resolution (core/chain_front).

Covers what the old app.py resolver missed: failover groups (members
live in lanes, not group.members), sub-<id> groups, chain fronts
(recursive), and cycles/unknown/disabled fronts.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.chain_front import resolve_chain_front  # noqa: E402
from core.models import AppConfig, Chain, Group, Node  # noqa: E402


def _node(tag, protocol="vless"):
    return Node(tag=tag, protocol=protocol, server="h.example.com",
                server_port=1234, params={"uuid": "u"})


def _cfg():
    nodes = [_node("n1"), _node("n2"), _node("n3", "trojan")]
    nodes[0].sub_id = 7
    nodes[1].sub_id = 7
    groups = [
        Group(name="sel", type="selector", members=["n1", "n2"]),
        Group(name="ut", type="urltest", members=["n1", "n2"],
              test_url="http://x/generate_204", interval_s=60),
        Group(name="fo", type="failover", members=[], lanes=[
            {"name": "primary", "mode": "auto", "members": ["n1", "n2"]},
            # Multi-member manual lane -> selector lane outbound.
            {"name": "backup", "mode": "manual", "members": ["n3", "n2"]},
        ]),
        Group(name="fo-single", type="failover", members=[], lanes=[
            {"name": "primary", "mode": "auto", "members": ["n1"]},
        ]),
        Group(name="off", type="urltest", members=["n1"], enabled=False),
    ]
    chains = [
        Chain(name="c-front", exit_protocol="shadowsocks",
              server="e.example.com", server_port=9999,
              params={"method": "aes-256-gcm", "password": "p"},
              front="n1"),
        Chain(name="c-cycle-a", exit_protocol="socks", server="a",
              server_port=1, params={}, front="c-cycle-b"),
        Chain(name="c-cycle-b", exit_protocol="socks", server="b",
              server_port=1, params={}, front="c-cycle-a"),
    ]
    return AppConfig(nodes=nodes, groups=groups, chains=chains,
                     subscriptions=[{"id": 7, "enabled": True},
                                    {"id": 8, "enabled": False}],
                     speedtest_url="http://www.gstatic.com/generate_204")


def test_node_front():
    ob, deps, gate, grp = resolve_chain_front(_cfg(), "n1")
    assert ob["type"] == "vless" and ob["tag"] == "n1"
    assert deps == [] and gate == [] and grp is None


def test_selector_front_uses_persisted_default():
    cfg = _cfg()
    cfg.groups[0].default_outbound = "n2"
    ob, deps, gate, grp = resolve_chain_front(cfg, "sel")
    assert ob["type"] == "selector" and ob["default"] == "n2"
    assert {d["tag"] for d in deps} == {"n1", "n2"}
    assert gate == [] and grp is None  # selectors: no convergence gate


def test_urltest_front_gate_members():
    ob, deps, gate, grp = resolve_chain_front(_cfg(), "ut")
    assert ob["type"] == "urltest" and ob["outbounds"] == ["n1", "n2"]
    assert ob["url"] == "http://x/generate_204"
    assert gate == ["n1", "n2"] and grp == "ut"


def test_failover_front_mirrors_lanes():
    ob, deps, gate, grp = resolve_chain_front(_cfg(), "fo")
    assert ob["type"] == "selector" and ob["tag"] == "fo"
    # Primary auto lane -> urltest lane outbound; backup manual lane ->
    # selector lane outbound; top selector defaults to the primary lane.
    by_tag = {d["tag"]: d for d in deps}
    assert by_tag["fo#primary"]["type"] == "urltest"
    assert by_tag["fo#backup"]["type"] == "selector"
    assert ob["outbounds"] == ["fo#primary", "fo#backup"]
    assert ob["default"] == "fo#primary"
    assert gate == ["n1", "n2"]  # primary auto lane's members
    assert grp == "fo#primary"  # gate waits for the lane's selection


def test_failover_single_node_primary_needs_no_gate():
    ob, deps, gate, grp = resolve_chain_front(_cfg(), "fo-single")
    assert ob["type"] == "selector"
    assert ob["outbounds"] == ["n1"] and ob["default"] == "n1"
    assert gate == [] and grp is None


def test_sub_front():
    ob, deps, gate, grp = resolve_chain_front(_cfg(), "sub-7")
    assert ob["type"] == "urltest" and ob["tag"] == "sub-7"
    assert ob["outbounds"] == ["n1", "n2"]
    assert gate == ["n1", "n2"] and grp == "sub-7"
    # Disabled subscription: unresolvable.
    assert resolve_chain_front(_cfg(), "sub-8") == (None, None, [], None)


def test_chain_front_recursive():
    ob, deps, gate, grp = resolve_chain_front(_cfg(), "c-front")
    assert ob["type"] == "shadowsocks" and ob["tag"] == "c-front"
    assert ob["detour"] == "n1"  # its own front, resolved
    assert [d["tag"] for d in deps] == ["n1"]
    assert gate == [] and grp is None  # inner front is a node


def test_cycle_unknown_disabled_unresolvable():
    cfg = _cfg()
    assert resolve_chain_front(cfg, "c-cycle-a") == (None, None, [], None)
    assert resolve_chain_front(cfg, "no-such-thing") == (None, None, [], None)
    assert resolve_chain_front(cfg, "off") == (None, None, [], None)
    assert resolve_chain_front(cfg, "direct") == (None, None, [], None)
    assert resolve_chain_front(cfg, "block") == (None, None, [], None)
