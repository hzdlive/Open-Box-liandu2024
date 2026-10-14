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


def flip_tag(site_set) -> str:
    """Outbound tag of the hot-switch selector for a site set."""
    import re
    key = site_set.sid or re.sub(r"\W+", "-", site_set.name).strip("-") or "x"
    return f"flip-{key}"


def flip_outbound(site_set, group_names: set[str]) -> dict | None:
    """A selector holding [primary, secondary] so the panel can flip a site
    set between direct and proxy at runtime via the clash API (no restart).

    primary = the action's target; secondary = the other side.
    default = persisted flip state, else the action.
    Only for proxy/direct actions; reject stays a static block."""
    if site_set.action == "reject":
        return None
    grp = site_set.group if site_set.group in group_names else "auto"
    if site_set.action == "direct":
        primary, secondary = "direct", grp
    else:
        primary, secondary = grp, "direct"
    members = [primary] + ([secondary] if secondary != primary else [])
    default = site_set.flip if site_set.flip in members else primary
    return {"type": "selector", "tag": flip_tag(site_set),
            "outbounds": members, "default": default}


def build_outbounds(cfg: AppConfig) -> list[dict]:
    """Build the outbound list (nodes + chains + groups + builtins)."""
    node_tags = [n.tag for n in cfg.nodes]
    chain_tags = [c.name for c in cfg.chains]
    groups = cfg.groups or default_groups()

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
    ]
    # Hot-switch selectors, one per proxy/direct site set (see flip_outbound).
    group_names = {g.name for g in groups}
    for s in cfg.site_sets:
        fo = flip_outbound(s, group_names)
        if fo:
            outbounds.append(fo)
    return outbounds


def build_route_rules(cfg: AppConfig) -> tuple[list[dict], list[dict], set[str]]:
    """Build (route_rules, dns_rules, group_names) from site sets."""
    groups = cfg.groups or default_groups()
    group_names = {g.name for g in groups}

    dns_rules = []
    route_rules = []
    # Terminal policies: "direct" terminals bypass the proxy at the route
    # level (evaluated before any site set). "bypass" terminals never reach
    # the kernel at all (handled in nftables, see core/transparent.py).
    direct_terms = [t.ident for t in cfg.terminals if t.policy == "direct"]
    if direct_terms:
        route_rules.append({"source_ip_cidr": direct_terms, "outbound": "direct"})
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
        if s.action == "reject":
            target = "block"
        else:
            target = flip_tag(s)  # hot-switch selector; default = action/flip state
        route_rules.append({**rule, "outbound": target})
        dns_rules.append({**rule, "server": "proxy-dns" if s.action == "proxy" else "direct-dns"})
    return route_rules, dns_rules, group_names


def _dns_server(tag: str, addr: str, detour: str) -> dict:
    """Build one sing-box >= 1.12 DNS server entry.

    Legacy plain-"address" servers were deprecated in 1.12 and removed in
    1.14, so every server needs an explicit "type". Accepts the address forms
    our panel stores: bare IP/host (udp), tcp://, tls://, https://, quic://,
    dhcp://.
    """
    a = (addr or "").strip()
    low = a.lower()
    if low.startswith("https://"):
        return {"type": "https", "tag": tag, "server": a, "detour": detour}
    for scheme, typ in (("tls://", "tls"), ("tcp://", "tcp"),
                        ("quic://", "quic"), ("dhcp://", "dhcp")):
        if low.startswith(scheme):
            return {"type": typ, "tag": tag, "server": a[len(scheme):], "detour": detour}
    return {"type": "udp", "tag": tag, "server": a, "detour": detour}


def _dns_servers(tag: str, addrs: str, detour: str) -> list:
    """One entry per comma-separated upstream; the first keeps the canonical
    tag so dns rules / final keep working."""
    parts = [x.strip() for x in (addrs or "").split(",") if x.strip()]
    if not parts:
        parts = ["223.5.5.5"]
    return [_dns_server(tag if i == 0 else f"{tag}-{i}", a, detour)
            for i, a in enumerate(parts)]


def build_config(cfg: AppConfig) -> dict:
    """Build the full sing-box config dict."""
    outbounds = build_outbounds(cfg)
    route_rules, dns_rules, _ = build_route_rules(cfg)

    return {
        "log": {"level": "warn"},
        "dns": {
            "servers": (_dns_servers("direct-dns", cfg.dns.direct_dns, "direct")
                        + _dns_servers("proxy-dns", cfg.dns.proxy_dns, "auto")),
            "rules": dns_rules,
            "final": "direct-dns",
        },
        "inbounds": [
            {"type": "tun", "tag": "tun-in", "stack": cfg.tun_stack,
             "mtu": cfg.tun_mtu,
             "auto_route": True, "strict_route": False},
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080},
        ] + ([{"type": "mixed", "tag": "lan-share-in", "listen": "0.0.0.0",
               "listen_port": cfg.share_lan_port}]
             if cfg.share_lan_enabled else []),
        "outbounds": outbounds,
        "route": {
            # sing-box >= 1.13: the "dns" outbound was removed; DNS protocol
            # traffic is handed to the DNS module via the hijack-dns action.
            "rules": [{"action": "sniff"}] + route_rules + [{"protocol": "dns", "action": "hijack-dns"}],
            "final": cfg.final_outbound,
            "auto_detect_interface": True,
            # sing-box >= 1.12 requires an explicit resolver for outbound
            # server domain names (was implicit, removed in 1.14).
            "default_domain_resolver": "direct-dns",
        },
        "experimental": {
            "clash_api": {"external_controller": f"127.0.0.1:{cfg.clash_api_port}"},
            "cache_file": {"enabled": True},
        },
    }
