"""Fill the obnode-direct-ip set (sentinel 192.0.2.255/32 until now).

The logical bypass rule (rule 0) matches rule_set=obnode-direct-ip, but
that set was never populated, so the rule could never fire. The fill
mirrors the reference (behavior对照, not reversed code):
- IP-literal node servers go straight into cidrs (no resolving);
- direct-host domains (subscription + node hostnames) are resolved
  through the host's own resolvers at build time;
- unresolved hosts contribute nothing; an empty set keeps the sentinel
  and rule 0 stays inert, exactly as today.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import route_oracle as orc  # noqa: E402
from core import singbox as sbmod  # noqa: E402
from core.models import AppConfig, DnsConfig, Node  # noqa: E402
from core.singbox import build_config  # noqa: E402


def _node(tag, server):
    return Node(tag=tag, protocol="vless", server=server, server_port=443)


def _decls(conf):
    return {d["tag"]: d for d in conf["route"].get("rule_set", [])}


def _obnode_ip_cidrs(conf):
    d = _decls(conf).get("obnode-direct-ip", {})
    rules = d.get("rules", [])
    if not rules:
        return []
    return rules[0].get("ip_cidr", [])


def test_ip_literal_nodes_fill_cidrs():
    cfg = AppConfig(nodes=[_node("n1", "203.0.113.7"),
                           _node("n2", "2001:db8::1")],
                    dns=DnsConfig(), sub_node_direct=True)
    conf = build_config(cfg)
    assert set(_obnode_ip_cidrs(conf)) == {"203.0.113.7/32",
                                           "2001:db8::1/128"}
    # The obnode route rule is emitted even with no domains: the rule
    # OR-matches the two sets, so the IP half alone is enough.
    assert any(r.get("rule_set") == ["obnode-direct", "obnode-direct-ip"]
               for r in conf["route"]["rules"])
    # No domains -> no DNS rule (it references the domain set only).
    assert not [r for r in conf["dns"]["rules"]
                if r.get("rule_set") == ["obnode-direct"]]


def test_resolved_domains_fill_cidrs(monkeypatch):
    monkeypatch.setattr(sbmod, "resolve_host_ips",
                        lambda hosts, budget_s=5.0: ["198.51.100.9"])
    cfg = AppConfig(nodes=[_node("n1", "node.example.com")],
                    dns=DnsConfig(), sub_node_direct=True,
                    sub_domains=["sub.example.com"])
    conf = build_config(cfg)
    assert set(_obnode_ip_cidrs(conf)) == {"198.51.100.9/32"}
    d = _decls(conf).get("obnode-direct", {})
    assert d.get("rules", [{}])[0].get("domain") == ["node.example.com",
                                                     "sub.example.com"]


def test_unresolved_keeps_sentinel(monkeypatch):
    monkeypatch.setattr(sbmod, "resolve_host_ips",
                        lambda hosts, budget_s=5.0: [])
    cfg = AppConfig(nodes=[_node("n1", "node.example.com")],
                    dns=DnsConfig(), sub_node_direct=True)
    conf = build_config(cfg)
    assert _obnode_ip_cidrs(conf) == ["192.0.2.255/32"]


def test_switch_off_no_fill():
    cfg = AppConfig(nodes=[_node("n1", "203.0.113.7")],
                    dns=DnsConfig(), sub_node_direct=False,
                    sub_domains=["sub.example.com"])
    conf = build_config(cfg)
    assert _obnode_ip_cidrs(conf) == ["192.0.2.255/32"]
    assert not [r for r in conf["route"]["rules"]
                if r.get("rule_set") == ["obnode-direct", "obnode-direct-ip"]]


def test_oracle_node_ip_hits_bypass_rule():
    cfg = AppConfig(nodes=[_node("n1", "203.0.113.7")],
                    dns=DnsConfig(), sub_node_direct=True)
    # A port is required: without one the rule's `!port=53` leg is
    # unknown, so the logical AND cannot hit and evaluation falls
    # through to the later obnode rule instead.
    r = orc.predict(cfg, "203.0.113.7", port=443,
                    geosite_split=lambda n: ([], []),
                    geoip_expand=lambda n: [])
    assert r["matched"]["source"] == "bypass"
    assert r["matched"]["target"] == "direct"
    assert r["matched"]["rule_index"] == 0
    # Control: an unrelated IP must not hit rule 0.
    r2 = orc.predict(cfg, "198.51.100.99", port=443,
                     geosite_split=lambda n: ([], []),
                     geoip_expand=lambda n: [])
    assert r2["matched"]["rule_index"] != 0


def test_resolve_host_ips_dedup_and_bad(monkeypatch):
    import socket
    real = socket.getaddrinfo

    def _fake(host, port, *a, **kw):
        if host == "dup.example.com":
            return [(socket.AF_INET, None, None, None, ("198.51.100.9", 0)),
                    (socket.AF_INET, None, None, None, ("198.51.100.9", 0))]
        if host == "bad.example.com":
            raise OSError("no such host")
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", _fake)
    ips = sbmod.resolve_host_ips(["dup.example.com", "bad.example.com"],
                                 budget_s=5.0)
    assert ips == ["198.51.100.9"]
