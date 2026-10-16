"""Build a sing-box configuration dict from an AppConfig.

Follows the sing-box configuration schema (open documentation).
Routing semantics: site sets are evaluated top-down, first hit wins;
unmatched traffic falls through to ``final_outbound``.
"""

from __future__ import annotations

import ipaddress

from .models import AppConfig, Chain, Group, Node


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


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
        Group(name="所有-自动", type="urltest", members=["*nodes*"], position=0),
        Group(name="所有-手动", type="selector", members=["*all*"], position=1),
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
    grp = site_set.group if site_set.group in group_names else "所有-自动"
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
        if not g.enabled:
            continue
        tags = resolve_group_members(g, node_tags, chain_tags)
        if g.type == "selector":
            outbounds.append({"type": "selector", "tag": g.name,
                              "outbounds": tags or ["direct"],
                              "default": tags[0] if tags else "direct"})
        elif g.type == "failover":
            # Native sing-box failover: kernel-level health checking and
            # automatic fallback, no panel-side watcher required.
            # 1:1 with the original: lanes = 主用/备用1/备用2... tabs.
            # Each lane: single node -> used directly; multi-node ->
            # auto=urltest (by speed) or manual=selector (pick in proxy page).
            # Top-level failover tries lanes in order.
            fo_kwargs = {"check_url": g.test_url or cfg.speedtest_url,
                         "check_interval": f"{g.interval_s}s"}
            if g.expected_status:
                fo_kwargs["expected_status"] = g.expected_status
            if g.lanes:
                lane_tags = []
                for i, ln in enumerate(g.lanes):
                    lane_name = ln.get("name") or (f"备用{i}" if i > 0 else "主用")
                    lane_tag = f"{g.name}#{lane_name}"
                    lane_members = [t for t in (ln.get("members") or [])
                                    if t in node_tags or t in chain_tags]
                    if not lane_members:
                        lane_members = ["direct"]
                    if len(lane_members) == 1:
                        # 单节点页签直接使用
                        lane_tags.append(lane_members[0])
                    elif (ln.get("mode") or "auto") == "manual":
                        outbounds.append({"type": "selector", "tag": lane_tag,
                                          "outbounds": lane_members,
                                          "default": lane_members[0]})
                        lane_tags.append(lane_tag)
                    else:
                        outbounds.append({"type": "urltest", "tag": lane_tag,
                                          "outbounds": lane_members,
                                          "url": g.test_url or cfg.speedtest_url,
                                          "interval": f"{g.interval_s}s",
                                          "tolerance": g.tolerance_ms,
                                          "idle_timeout": g.idle_timeout})
                        lane_tags.append(lane_tag)
                outbounds.append({"type": "failover", "tag": g.name,
                                  "outbounds": lane_tags or ["direct"],
                                  **fo_kwargs})
            else:
                outbounds.append({"type": "failover", "tag": g.name,
                                  "outbounds": tags or ["direct"],
                                  **fo_kwargs})
        else:  # urltest
            ob = {"type": "urltest", "tag": g.name,
                  "outbounds": tags or ["direct"],
                  "url": g.test_url or cfg.speedtest_url,
                  "interval": f"{g.interval_s}s",
                  "tolerance": g.tolerance_ms,
                  "idle_timeout": g.idle_timeout}
            if g.expected_status:
                ob["expected_status"] = g.expected_status
            outbounds.append(ob)
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


def build_route_rules(cfg: AppConfig,
                      skip_rule_sets: set[str] | None = None
                      ) -> tuple[list[dict], list[dict], set[str]]:
    """Build (route_rules, dns_rules, group_names) from site sets."""
    groups = cfg.groups or default_groups()
    group_names = {g.name for g in groups}

    dns_rules = []
    route_rules = []
    # Terminal policies: "direct" terminals bypass the proxy at the route
    # level (evaluated before any site set). "bypass" terminals never reach
    # the kernel at all (handled in nftables, see core/transparent.py).
    # MAC idents resolve to their current ARP IP (sing-box rules are L3).
    from core import arp as _arp
    direct_terms = _arp.expand_terminal_idents(
        [t.ident for t in cfg.terminals if t.policy == "direct"])
    if direct_terms:
        route_rules.append({"source_ip_cidr": direct_terms, "outbound": "direct"})
    # Front custom routing: user domain -> target mappings, evaluated before
    # every site set. Target is a group name, node tag, "direct" or "reject".
    for fr in cfg.front_rules or []:
        dom = (fr.get("domain") or "").strip()
        if not dom:
            continue
        target = (fr.get("target") or "所有-自动").strip() or "所有-自动"
        rule = {"domain_suffix": [dom.lstrip(".")]}
        dns_srv = "proxy-dns"
        if target == "direct":
            rule["outbound"] = "direct"; dns_srv = "direct-dns"
        elif target == "reject":
            rule["action"] = "reject"; dns_srv = "direct-dns"
        else:
            rule["outbound"] = target
            if cfg.dns.enable_fakeip:
                dns_srv = "fakeip"
        route_rules.append(rule)
        dns_rules.append({"domain_suffix": [dom.lstrip(".")], "server": dns_srv})
    # Subscription & node server domains go direct (keeps subscription updates
    # and node dialing off the proxy).
    if cfg.sub_node_direct:
        snd = set(cfg.sub_domains or [])
        for n in cfg.nodes or []:
            srv = (n.server or "").strip().lower()
            if srv and not _is_ip_literal(srv):
                snd.add(srv)
        if snd:
            route_rules.append({"domain_suffix": sorted(snd), "outbound": "direct"})
            dns_rules.append({"domain_suffix": sorted(snd), "server": "direct-dns"})
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
        from core.geodata import INLINE_RULE_SETS as _INLINE_RS
        rs = []
        for n in (s.rule_sets or []):
            if n in _INLINE_RS:
                # Fixed well-known ranges: expand inline, no download needed.
                rule["ip_cidr"] = (rule.get("ip_cidr") or []) + _INLINE_RS[n]
            elif not (skip_rule_sets and n in skip_rule_sets):
                rs.append(n)
        if rs:
            rule["rule_set"] = rs
        if not rule:
            continue
        if s.action == "reject":
            target = "block"
        else:
            target = flip_tag(s)  # hot-switch selector; default = action/flip state
        route_rules.append({**rule, "outbound": target})
        # FakeIP: proxied domains resolve to placeholder addresses locally;
        # the real domain is handed to the node at connect time.
        dns_server = ("fakeip" if (s.action == "proxy" and cfg.dns.enable_fakeip)
                      else "proxy-dns" if s.action == "proxy" else "direct-dns")
        dns_rules.append({**rule, "server": dns_server})
    return route_rules, dns_rules, group_names


def _dns_server(tag: str, addr: str, detour: str) -> dict:
    """Build one sing-box >= 1.12 DNS server entry.

    Legacy plain-"address" servers were deprecated in 1.12 and removed in
    1.14, so every server needs an explicit "type". Accepts the address forms
    our panel stores: bare IP/host (udp), tcp://, tls://, https://, quic://,
    dhcp://.

    A detour of "direct" is omitted: sing-box >= 1.14 rejects
    dns servers whose detour points at a plain direct outbound
    ("detour to an empty direct outbound makes no sense"), and direct
    is the default dial behavior anyway.
    """
    a = (addr or "").strip()
    low = a.lower()
    extra = {} if detour == "direct" else {"detour": detour}
    if low.startswith("https://"):
        return {"type": "https", "tag": tag, "server": a, **extra}
    for scheme, typ in (("tls://", "tls"), ("tcp://", "tcp"),
                        ("quic://", "quic"), ("dhcp://", "dhcp")):
        if low.startswith(scheme):
            return {"type": typ, "tag": tag, "server": a[len(scheme):], **extra}
    return {"type": "udp", "tag": tag, "server": a, **extra}


def _wan_dns_servers() -> list[str]:
    """System/WAN DNS servers for direct_dns='wan' (original panel parity)."""
    from core.dnstest import system_upstreams
    return system_upstreams()


def _strip_upstream_label(addr: str) -> str:
    """Strip the frontend display label "上游 DNS [addr]".

    The DNS UI shows system/upstream DNS as "上游 DNS" (alone) or
    "上游 DNS 1.2.3.4"; the backend only understands bare addresses
    or "wan". A bare label (no address after it) means system DNS.
    """
    a = (addr or "").strip()
    if "上游 DNS" in a:
        a = a.split("上游 DNS", 1)[1].strip()
        return a or "wan"
    return a


def _dns_servers(tag: str, addrs: str, detour: str,
                 latency: dict | None = None) -> list:
    """One entry per comma-separated upstream; the first keeps the canonical
    tag so dns rules / final keep working.

    addrs == "wan" resolves to the system/WAN DNS servers (original parity).
    Frontend display labels like "上游 DNS 1.2.3.4" are stripped to the bare
    address here (a bare "上游 DNS" label resolves to system DNS).

    Primary/backup: when latency measurements exist, the fastest upstream
    goes first (primary), the rest are backups.
    """
    raw = (addrs or "").strip()
    if raw.lower() == "wan":
        parts = _wan_dns_servers()
    else:
        parts = []
        for x in raw.split(","):
            x = _strip_upstream_label(x)
            if not x:
                continue
            if x.lower() == "wan":
                parts.extend(_wan_dns_servers())
            else:
                parts.append(x)
    if not parts:
        parts = ["223.5.5.5"]
    if latency:
        # Latency keys may be stored in labeled frontend form; normalize.
        latency = {_strip_upstream_label(k): v for k, v in latency.items()}
        parts = sorted(parts, key=lambda a: (latency.get(a, float("inf")), parts.index(a)))
    return [_dns_server(tag if i == 0 else f"{tag}-{i}", a, detour)
            for i, a in enumerate(parts)]


def build_config(cfg: AppConfig,
                 skip_rule_sets: set[str] | None = None) -> dict:
    """Build the full sing-box config dict.

    skip_rule_sets: rule-set names whose .srs is unavailable; their references
    are dropped so a missing geodata file can never break config validation.
    """
    outbounds = build_outbounds(cfg)
    route_rules, dns_rules, _ = build_route_rules(cfg, skip_rule_sets)
    # split=false: all DNS via the proxy upstream (no direct/proxy split).
    dns_final = "direct-dns"
    if not cfg.dns.split:
        dns_rules = [{**r, "server": "proxy-dns"} if r.get("server") == "direct-dns" else r
                     for r in dns_rules]
        dns_final = "proxy-dns"
    # Effective region (same formula as db.load_app_config). Outside mainland
    # there is no GFW, so proxy DNS goes direct instead of through the proxy.
    _eff_region = (cfg.dns.region if cfg.dns.region != "auto"
                   else (cfg.dns.region_detected or "cn"))
    _proxy_detour = "direct" if _eff_region == "outside" else "所有-自动"
    from core import geodata as _gd
    rule_set_decls = [
        {"type": "local", "tag": name, "format": "binary",
         "path": _gd.local_path(name)}
        for name in _gd.referenced_rule_sets(cfg)
        if not (skip_rule_sets and name in skip_rule_sets)]

    return {
        "log": {"level": "warn"},
        "dns": {
            "servers": (
                [{"type": "fakeip", "tag": "fakeip",
                  "inet4_range": "198.19.0.0/16", "inet6_range": "fc00::/18"}]
                if cfg.dns.enable_fakeip else []
            ) + (_dns_servers("direct-dns", cfg.dns.direct_dns, "direct",
                             cfg.dns.upstream_latency)
                 + _dns_servers("proxy-dns", cfg.dns.proxy_dns, _proxy_detour,
                                cfg.dns.upstream_latency)),
            "rules": dns_rules,
            "final": dns_final,
        },
        "inbounds": [
            {"type": "tun", "tag": "tun-in", "stack": cfg.tun_stack,
             "mtu": cfg.tun_mtu, "address": cfg.tun_address,
             "auto_route": True, "strict_route": False},
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080},
        ] + ([{"type": "mixed", "tag": "lan-share-in", "listen": "0.0.0.0",
               "listen_port": cfg.share_lan_port}]
             if cfg.share_lan_enabled else []) + [
            {"type": "shadowsocks", "tag": f"share-{s['id']}",
             "listen": "0.0.0.0", "listen_port": s["port"],
             "method": s["method"], "password": s["password"]}
            for s in (cfg.share_servers or [])
        ],
        "outbounds": outbounds,
        "route": {
            # sing-box >= 1.13: the "dns" outbound was removed; DNS protocol
            # traffic is handed to the DNS module via the hijack-dns action.
            "rules": [{"action": "sniff"}] + route_rules + [{"protocol": "dns", "action": "hijack-dns"}],
            **({"rule_set": rule_set_decls} if rule_set_decls else {}),
            "final": cfg.routing_fallback or cfg.final_outbound,
            "auto_detect_interface": True,
            # sing-box >= 1.12 requires an explicit resolver for outbound
            # server domain names (was implicit, removed in 1.14).
            "default_domain_resolver": dns_final,
        },
        "experimental": {
            "clash_api": {
                "external_controller": f"{cfg.clash_api_listen}:{cfg.clash_api_port}",
                **({"secret": cfg.clash_api_secret} if cfg.clash_api_secret else {}),
            },
            "cache_file": {"enabled": True},
        },
    }
