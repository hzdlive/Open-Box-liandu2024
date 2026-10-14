"""Build a sing-box configuration dict from an AppConfig.

Follows the sing-box configuration schema (open documentation).
Routing semantics: site sets are evaluated top-down, first hit wins;
unmatched traffic falls through to ``final_outbound``.
"""

from __future__ import annotations

from .models import AppConfig, Chain, Group, Node


def _tls_block(params: dict) -> dict | None:
    tls = params.get("tls")
    if not tls:
        return None
    out = {"enabled": True}
    if tls.get("server_name"):
        out["server_name"] = tls["server_name"]
    if tls.get("insecure"):
        out["insecure"] = True
    if tls.get("alpn"):
        out["alpn"] = tls["alpn"]
    if tls.get("fingerprint"):
        out["utls"] = {"enabled": True, "fingerprint": tls["fingerprint"]}
    reality = tls.get("reality")
    if reality:
        out["reality"] = {"enabled": True, **{k: v for k, v in reality.items() if k != "enabled"}}
    return out


def _transport_block(params: dict) -> dict | None:
    t = params.get("transport")
    if not t or t.get("type") in (None, "tcp", "none"):
        return None
    out = {"type": t["type"]}
    if t.get("path"):
        out["path"] = t["path"]
    if t.get("headers"):
        out["headers"] = t["headers"]
    if t.get("service_name"):
        out["service_name"] = t["service_name"]
    return out


def node_to_outbound(node: Node) -> dict:
    """Map a Node to a sing-box outbound object."""
    p, ob = node.params, {
        "type": node.protocol,
        "tag": node.tag,
        "server": node.server,
        "server_port": node.server_port,
    }
    if node.protocol == "vmess":
        ob.update(uuid=p.get("uuid", ""), alter_id=p.get("alter_id", 0), security=p.get("security", "auto"))
    elif node.protocol == "vless":
        ob["uuid"] = p.get("uuid", "")
        if p.get("flow"):
            ob["flow"] = p["flow"]
    elif node.protocol == "trojan":
        ob["password"] = p.get("password", "")
    elif node.protocol == "shadowsocks":
        ob.update(method=p.get("method", ""), password=p.get("password", ""))
    elif node.protocol == "tuic":
        ob.update(uuid=p.get("uuid", ""), password=p.get("password", ""),
                   congestion_control=p.get("congestion_control", "bbr"))
    elif node.protocol == "hysteria2":
        ob["password"] = p.get("password", "")
        if p.get("obfs"):
            ob["obfs"] = p["obfs"]
    elif node.protocol == "anytls":
        ob["password"] = p.get("password", "")
    elif node.protocol == "wireguard":
        ob["system_interface"] = False
        if p.get("local_address"):
            ob["local_address"] = p["local_address"]
        ob["private_key"] = p.get("private_key", "")
        ob["peer_public_key"] = p.get("peer_public_key", "")
        if p.get("pre_shared_key"):
            ob["pre_shared_key"] = p["pre_shared_key"]
        if p.get("mtu"):
            ob["mtu"] = p["mtu"]
    tls = _tls_block(p)
    if tls:
        ob["tls"] = tls
    transport = _transport_block(p)
    if transport:
        ob["transport"] = transport
    return ob


def chain_to_outbound(chain: Chain) -> dict:
    """A chain proxy is an exit outbound (socks5/http) dialing through a front."""
    ob: dict = {
        "type": chain.exit_protocol,
        "tag": chain.name,
        "server": chain.server,
        "server_port": chain.server_port,
        "detour": chain.front,
    }
    if chain.params.get("username"):
        ob["username"] = chain.params["username"]
    if chain.params.get("password"):
        ob["password"] = chain.params["password"]
    return ob


def default_groups() -> list[Group]:
    return [
        Group(name="auto", type="urltest", members=["*nodes*"], position=0),
        Group(name="manual", type="selector", members=["*all*"], position=1),
    ]


def resolve_group_members(group: Group, node_tags: list[str],
                          chain_tags: list[str]) -> list[str]:
    tags: list[str] = []
    for m in group.members:
        if m == "*nodes*":
            tags.extend(node_tags)
        elif m == "*all*":
            tags.extend(node_tags + chain_tags)
        elif (m in node_tags or m in chain_tags) and m not in tags:
            tags.append(m)
    for kw in group.dynamic_keywords:
        kl = kw.lower()
        for t in node_tags:
            if kl in t.lower() and t not in tags:
                tags.append(t)
    return tags


def build_config(cfg: AppConfig) -> dict:
    """Build the full sing-box config dict."""
    node_tags = [n.tag for n in cfg.nodes]
    chain_tags = [c.name for c in cfg.chains]
    groups = cfg.groups or default_groups()
    group_names = {g.name for g in groups}

    outbounds = [node_to_outbound(n) for n in cfg.nodes]
    outbounds += [chain_to_outbound(c) for c in cfg.chains]
    for g in groups:
        tags = resolve_group_members(g, node_tags, chain_tags)
        if g.type == "selector":
            outbounds.append({"type": "selector", "tag": g.name,
                              "outbounds": tags or ["direct"],
                              "default": tags[0] if tags else "direct"})
        elif g.type == "failover":
            # Priority-ordered members; the runtime election (core/failover.py)
            # switches this selector's active proxy via the clash API.
            outbounds.append({"type": "selector", "tag": g.name,
                              "outbounds": tags or ["direct"],
                              "default": tags[0] if tags else "direct"})
        else:  # urltest
            outbounds.append({"type": "urltest", "tag": g.name,
                              "outbounds": tags or ["direct"],
                              "url": "http://www.gstatic.com/generate_204",
                              "interval": "5m", "tolerance": 50})
    outbounds += [
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"},
        {"type": "dns", "tag": "dns-out"},
    ]

    def target_of(action: str, group: str) -> str:
        if action == "direct":
            return "direct"
        if action == "reject":
            return "block"
        return group if group in group_names else "auto"

    dns_rules = []
    route_rules = []
    for s in cfg.site_sets:
        rule: dict = {}
        if s.domains:
            rule["domain"] = s.domains
        if s.domain_suffix:
            rule["domain_suffix"] = s.domain_suffix
        if s.domain_keyword:
            rule["domain_keyword"] = s.domain_keyword
        if s.ip_cidr:
            rule["ip_cidr"] = s.ip_cidr
        if not rule:
            continue
        target = target_of(s.action, s.group)
        route_rules.append({**rule, "outbound": target})
        dns_rules.append({**rule, "server": "proxy-dns" if s.action == "proxy" else "direct-dns"})

    return {
        "log": {"level": "warn"},
        "dns": {
            "servers": [
                {"tag": "direct-dns", "address": cfg.dns.direct_dns, "detour": "direct"},
                {"tag": "proxy-dns", "address": cfg.dns.proxy_dns, "detour": "auto"},
            ],
            "rules": dns_rules,
            "final": "direct-dns",
        },
        "inbounds": [
            {"type": "tun", "tag": "tun-in", "stack": cfg.tun_stack,
             "auto_route": True, "strict_route": False, "sniff": True},
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080, "sniff": True},
        ],
        "outbounds": outbounds,
        "route": {
            "rules": route_rules + [{"protocol": "dns", "outbound": "dns-out"}],
            "final": cfg.final_outbound,
            "auto_detect_interface": True,
        },
        "experimental": {
            "clash_api": {"external_controller": f"127.0.0.1:{cfg.clash_api_port}"},
            "cache_file": {"enabled": True},
        },
    }
