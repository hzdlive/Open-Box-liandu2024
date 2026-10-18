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
    # 兼容两种格式：内部格式 tls.fingerprint 和原始 sing-box 格式 tls.utls.fingerprint
    if isinstance(tls.get("utls"), dict) and tls["utls"].get("fingerprint"):
        # 已经是 sing-box 原生格式，直接返回（确保 enabled）
        out = dict(tls)
        out["enabled"] = True
        if isinstance(out.get("utls"), dict):
            out["utls"] = dict(out["utls"])
            out["utls"]["enabled"] = True
        if isinstance(out.get("reality"), dict):
            out["reality"] = dict(out["reality"])
            out["reality"]["enabled"] = True
        return out
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


def obflip_tag(site_set) -> str:
    """Rule-set tag for per-site-set QUIC blocking (1:1 with original).
    Format: obflip-<sha256(id|name)[0:12]>
    """
    import hashlib
    sid = str(getattr(site_set, 'sid', '') or '')
    name = str(getattr(site_set, 'name', '') or '')
    h = hashlib.sha256(f"{sid}|{name}".encode()).hexdigest()[:12]
    return f"obflip-{h}"


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
            # sing-box 没有原生 failover 类型，用 urltest 实现故障转移：
            # 内核级健康检测 + 自动选择最优可用节点，不依赖面板存活。
            # 1:1 with the original: lanes = 主用/备用1/备用2... tabs.
            # Each lane: single node -> used directly; multi-node ->
            # auto=urltest (by speed) or manual=selector (pick in proxy page).
            # 顶层用 urltest 覆盖所有 lane 成员，自动故障转移。
            fo_kwargs = {"url": g.test_url or cfg.speedtest_url,
                         "interval": f"{g.interval_s}s"}
            if g.expected_status:
                # urltest 不支持 expected_status，忽略（sing-box 限制）
                pass
            if g.lanes:
                # 收集所有 lane 的成员，顶层 urltest 统一健康检查
                all_members = []
                for i, ln in enumerate(g.lanes):
                    lane_name = ln.get("name") or (f"备用{i}" if i > 0 else "主用")
                    lane_tag = f"{g.name}#{lane_name}"
                    lane_members = [t for t in (ln.get("members") or [])
                                    if t in node_tags or t in chain_tags]
                    if not lane_members:
                        continue
                    if len(lane_members) == 1:
                        # 单节点页签直接使用
                        if lane_members[0] not in all_members:
                            all_members.append(lane_members[0])
                    elif (ln.get("mode") or "auto") == "manual":
                        outbounds.append({"type": "selector", "tag": lane_tag,
                                          "outbounds": lane_members,
                                          "default": lane_members[0]})
                        all_members.append(lane_tag)
                    else:
                        outbounds.append({"type": "urltest", "tag": lane_tag,
                                          "outbounds": lane_members,
                                          "url": g.test_url or cfg.speedtest_url,
                                          "interval": f"{g.interval_s}s",
                                          "tolerance": g.tolerance_ms,
                                          "idle_timeout": g.idle_timeout})
                        all_members.append(lane_tag)
                # 顶层用 selector（非 urltest），由面板故障转移状态机主动控制切换，
                # 实现“主通道优先、故障才切备用”的严格语义。default 指向主用 lane。
                _default_lane = all_members[0] if all_members else "direct"
                outbounds.append({"type": "selector", "tag": g.name,
                                  "outbounds": all_members or ["direct"],
                                  "default": _default_lane})
            else:
                outbounds.append({"type": "urltest", "tag": g.name,
                                  "outbounds": tags or ["direct"],
                                  "tolerance": g.tolerance_ms,
                                  **fo_kwargs})
        elif g.type in ("urltest", "smart", "loadbalance"):
            # urltest: 标准 URL 测试；smart: 按延迟智能选择（映射为 urltest）；
            # loadbalance: 负载均衡（映射为 urltest）
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
        # REA 27.4: __fo:reject 为故障转移 reject 回退（all-failed 时切换到此）
        {"type": "block", "tag": "__fo:reject"},
    ]
    # Hot-switch selectors, one per proxy/direct site set (see flip_outbound).
    group_names = {g.name for g in groups}
    for s in cfg.site_sets:
        fo = flip_outbound(s, group_names)
        if fo:
            outbounds.append(fo)
    return outbounds


def _front_url_tag(url: str) -> str:
    """Stable rule-set tag for a front ruleset_url rule."""
    import hashlib as _hashlib
    return "url-" + _hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def front_remote_rule_sets(cfg: AppConfig) -> list[tuple[str, str]]:
    """(tag, url) pairs for front ruleset_url rules pointing at .srs files.

    sing-box consumes these natively as remote binary rule-sets.
    """
    out: list[tuple[str, str]] = []
    for fr in cfg.front_rules or []:
        if not isinstance(fr, dict):
            continue
        if (fr.get("rtype") or "") == "ruleset_url":
            url = (fr.get("domain") or "").strip()
            if url.lower().endswith(".srs"):
                tag = _front_url_tag(url)
                if not any(t == tag for t, _ in out):
                    out.append((tag, url))
    return out


def front_rule_warnings(cfg: AppConfig) -> list[str]:
    """Human-readable warnings for front rules the generator cannot honor."""
    out: list[str] = []
    for fr in cfg.front_rules or []:
        if not isinstance(fr, dict):
            continue
        if (fr.get("rtype") or "") == "ruleset_url":
            url = (fr.get("domain") or "").strip()
            if url and not url.lower().endswith(".srs"):
                out.append(
                    f"前置规则: 规则集链接 {url} 非 .srs 格式, "
                    "sing-box 无法直接订阅, 已跳过")
    return out


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
    # Terminal rules (1:1): proxy policy -> source_ip_cidr to specified outbound.
    # Evaluated before site sets. MAC targets resolve to current ARP IPs.
    # direct/whitelist policies are handled at nftables level (see transparent.py).
    for tr in getattr(cfg, "terminal_rules", []) or []:
        if tr.policy != "proxy" or not tr.outbound:
            continue
        cidrs = []
        if tr.match_by == "mac":
            cidrs = _arp.expand_terminal_idents(tr.targets)
        else:
            for t in tr.targets:
                t = str(t).strip()
                if t:
                    # Normalize to CIDR if plain IP
                    cidrs.append(t if "/" in t else f"{t}/32")
        if cidrs:
            route_rules.append({"source_ip_cidr": cidrs, "outbound": tr.outbound})
    # Front custom routing: user domain -> target mappings, evaluated before
    # every site set. Target is a group name, node tag, "direct" or "reject".
    # Front custom routing: typed user rules, evaluated before every site
    # set. Target is a group name, node tag, "direct" or "reject".
    # 8 types: domain_suffix | domain | domain_keyword | ip_cidr |
    #          geosite | geoip | ruleset_url | port
    for fr in cfg.front_rules or []:
        if not isinstance(fr, dict):
            continue
        if not fr.get("enabled", True):
            continue
        rtype = (fr.get("rtype") or "domain_suffix").strip()
        val = (fr.get("domain") or "").strip()
        if not val:
            continue
        target = (fr.get("target") or "所有-自动").strip() or "所有-自动"
        rule: dict = {}
        dns_sel: dict | None = None  # selector for the companion dns rule
        if rtype == "domain":
            rule["domain"] = [val]
            dns_sel = {"domain": [val]}
        elif rtype == "domain_keyword":
            rule["domain_keyword"] = [val]
            dns_sel = {"domain_keyword": [val]}
        elif rtype == "ip_cidr":
            rule["ip_cidr"] = [val]
        elif rtype == "geosite":
            rule["rule_set"] = [f"geosite-{val}"]
            dns_sel = {"rule_set": [f"geosite-{val}"]}
        elif rtype == "geoip":
            rule["rule_set"] = [f"geoip-{val}"]
            dns_sel = {"rule_set": [f"geoip-{val}"]}
        elif rtype == "ruleset_url":
            if not val.lower().endswith(".srs"):
                continue  # surfaced via front_rule_warnings()
            tag = _front_url_tag(val)
            rule["rule_set"] = [tag]
            dns_sel = {"rule_set": [tag]}
            # register for declaration in build_config
            if not hasattr(cfg, "_front_remote_rs"):
                cfg._front_remote_rs = {}
            cfg._front_remote_rs[tag] = val
        elif rtype == "port":
            if "-" in val:
                rule["port_range"] = [val]
            else:
                try:
                    rule["port"] = [int(val)]
                except ValueError:
                    continue
        else:  # domain_suffix (covers legacy rows)
            rule["domain_suffix"] = [val.lstrip(".")]
            dns_sel = {"domain_suffix": [val.lstrip(".")]}
        dns_srv = "dns-proxy"
        if target == "direct":
            rule["outbound"] = "direct"; dns_srv = "dns-direct"
        elif target == "reject":
            rule["action"] = "reject"; dns_srv = "dns-direct"
        else:
            rule["outbound"] = target
            if cfg.dns.enable_fakeip:
                dns_srv = "dns-fakeip"
        route_rules.append(rule)
        if dns_sel is not None:
            dns_rules.append({**dns_sel, "server": dns_srv})
    # Subscription & node server domains go direct (keeps subscription updates
    # and node dialing off the proxy).
    # 对标原版：使用 obnode-direct / obnode-direct-ip rule_set（而非 inline 规则）。
    # 空集时用 sentinel 值（obnode-direct.invalid / 192.0.2.255/32）。
    if not hasattr(cfg, "_obnode_direct"):
        cfg._obnode_direct = {"domains": [], "cidrs": []}
    if cfg.sub_node_direct:
        snd = set(cfg.sub_domains or [])
        for n in cfg.nodes or []:
            srv = (n.server or "").strip().lower()
            if srv and not _is_ip_literal(srv):
                snd.add(srv)
        if snd:
            cfg._obnode_direct["domains"] = sorted(snd)
            # 路由规则引用 obnode-direct rule_set
            route_rules.append({"rule_set": ["obnode-direct", "obnode-direct-ip"],
                                "outbound": "direct"})
            dns_rules.append({"rule_set": ["obnode-direct"],
                              "server": "dns-direct"})
    # Collect remote ruleset URLs (side effect for build_config declarations)
    if not hasattr(cfg, "_remote_rulesets"):
        cfg._remote_rulesets = {}
    # Collect obflip inline rule_sets for per-site-set QUIC blocking (1:1 with original)
    if not hasattr(cfg, "_obflip_rulesets"):
        cfg._obflip_rulesets = {}
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
        if s.ports:
            # ports: list of ints or "start-end" strings -> sing-box port list
            rule["port"] = s.ports
        # Remote ruleset URLs -> generate tags and add to rule_set
        for url in (s.ruleset_urls or []):
            url = str(url).strip()
            if not url:
                continue
            # Find or create tag for this URL
            tag = None
            for t, u in cfg._remote_rulesets.items():
                if u == url:
                    tag = t
                    break
            if not tag:
                tag = f"url-{len(cfg._remote_rulesets)}"
                cfg._remote_rulesets[tag] = url
            rs = rule.get("rule_set", [])
            if tag not in rs:
                rs.append(tag)
            rule["rule_set"] = rs
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
        # 每个代理站点集独立 QUIC 拦截（对标原版 obflip 机制）：
        # 生成 obflip-<hash> inline rule_set，主规则前用 rule_set + udp/443 拦截。
        # 只对实际走代理的站点集生效（考虑 flip 状态）。
        _effective = (s.flip or s.action or "").strip()
        if getattr(cfg, 'quic_block', True) and _effective == "proxy":
            _ob_tag = obflip_tag(s)
            # obflip rule_set 内容：站点集的匹配条件（用于 QUIC 拦截）
            _ob_rules = []
            if rule.get("domain"):
                _ob_rules.append({"domain": rule["domain"]})
            if rule.get("domain_suffix"):
                _ob_rules.append({"domain_suffix": rule["domain_suffix"]})
            if rule.get("domain_keyword"):
                _ob_rules.append({"domain_keyword": rule["domain_keyword"]})
            if rule.get("ip_cidr"):
                _ob_rules.append({"ip_cidr": rule["ip_cidr"]})
            # 注意：inline rule_set 内不能嵌套 rule_set 引用，只纳入直接条件
            if _ob_rules:
                cfg._obflip_rulesets[_ob_tag] = _ob_rules
                # QUIC 拦截规则：引用 obflip rule_set
                route_rules.append({
                    "rule_set": [_ob_tag],
                    "network": "udp",
                    "port": 443,
                    "outbound": "block",
                })
            elif rule.get("rule_set"):
                # 纯 rule_set 引用的站点集：QUIC 规则直接引用（对标原版规则 6）
                route_rules.append({
                    "rule_set": rule["rule_set"],
                    "network": "udp",
                    "port": 443,
                    "outbound": "block",
                })
        route_rules.append({**rule, "outbound": target})
        # FakeIP: proxied domains resolve to placeholder addresses locally;
        # the real domain is handed to the node at connect time.
        dns_server = ("dns-fakeip" if (s.action == "proxy" and cfg.dns.enable_fakeip)
                      else "dns-proxy" if s.action == "proxy" else "dns-direct")
        dns_rules.append({**rule, "server": dns_server})
    # QUIC 拦截已改为每个站点集独立生成（见下方循环内），不再全局拦截
    # 内容过滤 (0.1.328): 拦截启用的过滤器中的域名
    _blocked = getattr(cfg, 'blocked_domains', []) or []
    if _blocked:
        route_rules.append({
            "domain_suffix": _blocked,
            "outbound": "block",
        })
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


def _share_server_inbound(s: dict) -> dict:
    """Build a sing-box inbound for a share server (1:1, 5 protocols)."""
    import json as _json
    proto = s.get("protocol", "shadowsocks")
    tag = f"share-{s['id']}"
    base = {
        "tag": tag,
        "listen": "0.0.0.0",
        "listen_port": int(s["port"]),
    }
    params = s.get("params") or {}
    if isinstance(params, str):
        try:
            params = _json.loads(params)
        except Exception:
            params = {}
    if proto == "shadowsocks":
        base.update({
            "type": "shadowsocks",
            "method": s.get("method", "aes-256-gcm"),
            "password": s.get("password", ""),
        })
    elif proto == "vless":
        # VLESS inbound with TLS (from params)
        base.update({
            "type": "vless",
            "users": [{"uuid": s.get("password", ""), "flow": params.get("flow", "")}],
            "tls": {
                "enabled": True,
                "server_name": params.get("sni", ""),
                "certificate_path": params.get("cert_path", ""),
                "key_path": params.get("key_path", ""),
            },
        })
        # Remove empty TLS fields
        tls = base["tls"]
        if not tls["server_name"]:
            tls.pop("server_name")
    elif proto == "tuic":
        base.update({
            "type": "tuic",
            "users": [{"uuid": s.get("password", ""), "password": s.get("password", "")}],
            "congestion_control": params.get("congestion_control", "bbr"),
            "tls": {
                "enabled": True,
                "server_name": params.get("sni", ""),
                "certificate_path": params.get("cert_path", ""),
                "key_path": params.get("key_path", ""),
            },
        })
    elif proto == "hysteria2":
        base.update({
            "type": "hysteria2",
            "users": [{"password": s.get("password", "")}],
            "tls": {
                "enabled": True,
                "server_name": params.get("sni", ""),
                "certificate_path": params.get("cert_path", ""),
                "key_path": params.get("key_path", ""),
            },
        })
        if params.get("obfs"):
            base["obfs"] = params["obfs"]
    elif proto == "socks5http":
        # SOCKS5 + HTTP combined (mixed)
        base.update({
            "type": "mixed",
            "users": [{"username": params.get("username", ""),
                       "password": s.get("password", "")}]
                       if params.get("username") else [],
        })
    else:
        # Fallback to shadowsocks
        base.update({
            "type": "shadowsocks",
            "method": s.get("method", "aes-256-gcm"),
            "password": s.get("password", ""),
        })
    return base


def build_config(cfg: AppConfig,
                 skip_rule_sets: set[str] | None = None) -> dict:
    """Build the full sing-box config dict.

    skip_rule_sets: rule-set names whose .srs is unavailable; their references
    are dropped so a missing geodata file can never break config validation.
    """
    outbounds = build_outbounds(cfg)
    route_rules, dns_rules, _ = build_route_rules(cfg, skip_rule_sets)
    # split=false: all DNS via the proxy upstream (no direct/proxy split).
    dns_final = "dns-direct"
    if not cfg.dns.split:
        dns_rules = [{**r, "server": "dns-proxy"} if r.get("server") == "dns-direct" else r
                     for r in dns_rules]
        dns_final = "dns-proxy"
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
    # Remote ruleset URLs from site sets: collected during build_route_rules
    # via cfg._remote_rulesets (populated as side effect). Declare them here.
    for tag, url in getattr(cfg, "_remote_rulesets", {}).items():
        rule_set_decls.append({
            "type": "remote",
            "tag": tag,
            "format": "binary",
            "url": url,
        })
    # Remote ruleset URLs from front rules (typed ruleset_url)
    for tag, url in front_remote_rule_sets(cfg):
        if not any(d.get("tag") == tag for d in rule_set_decls):
            rule_set_decls.append({
                "type": "remote",
                "tag": tag,
                "format": "binary",
                "url": url,
            })
    # Obflip inline rule_sets for per-site-set QUIC blocking (1:1 with original)
    for tag, rules in getattr(cfg, "_obflip_rulesets", {}).items():
        rule_set_decls.append({
            "type": "inline",
            "tag": tag,
            "rules": rules,
        })
    # obnode-direct / obnode-direct-ip: direct-host DOMAIN/CIDR sets (1:1 with original).
    # 空集时用 sentinel 值，保证 rule_set 非空。
    _obd = getattr(cfg, "_obnode_direct", None)
    if _obd is not None:
        _domains = _obd.get("domains") or ["obnode-direct.invalid"]
        _cidrs = _obd.get("cidrs") or ["192.0.2.255/32"]
        rule_set_decls.append({
            "type": "inline",
            "tag": "obnode-direct",
            "rules": [{"domain": _domains}],
        })
        rule_set_decls.append({
            "type": "inline",
            "tag": "obnode-direct-ip",
            "rules": [{"ip_cidr": _cidrs}],
        })

    return {
        "log": {"level": "warn"},
        "dns": {
            "servers": (
                [{"type": "fakeip", "tag": "dns-fakeip",
                  "inet4_range": "198.19.0.0/16", "inet6_range": "fc00::/18"}]
                if cfg.dns.enable_fakeip else []
            ) + (_dns_servers("dns-direct", cfg.dns.direct_dns, "direct",
                             cfg.dns.upstream_latency)
                 + _dns_servers("dns-proxy", cfg.dns.proxy_dns, _proxy_detour,
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
            _share_server_inbound(s)
            for s in (cfg.share_servers or [])
            if s.get("enabled", 1)
        ],
        "outbounds": outbounds,
        "route": {
            # sing-box >= 1.13: the "dns" outbound was removed; DNS protocol
            # traffic is handed to the DNS module via the hijack-dns action.
            # DNS 劫持紧随 sniff（对标原版规则 3）：DNS 协议流量优先交由 DNS 模块处理，
            # 避免被站点集规则误匹配。
            "rules": [{"action": "sniff"}, {"protocol": "dns", "action": "hijack-dns"}] + route_rules,
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
