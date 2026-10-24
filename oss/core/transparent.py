"""Transparent-proxy artifact generation (nftables + dnsmasq).

GENERATE-ONLY: these functions return file contents. Nothing here touches
the host firewall. Applying the generated nftables script requires root and
is an explicit, separate operator action (see panel API, which only serves
the preview unless explicitly confirmed).

Design (publicly documented TPROXY pattern):
- table inet openbox-oss
- set bypass4: RFC1918 + link-local + multicast + the router itself
- chain prerouting (mangle/PREROUTING): TCP/UDP -> tproxy to 127.0.0.1:TPROXY_PORT
- optional chain output for locally-generated traffic
"""

from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_BYPASS_V4 = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "224.0.0.0/4",
]

DEFAULT_BYPASS_V6 = [
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
]


@dataclass
class TransparentConfig:
    tproxy_port: int = 7893          # sing-box tproxy inbound listen port
    dns_port: int = 1053             # sing-box dns server listen port
    mark: int = 0x1                 # fwmark used by sing-box routing
    table_id: int = 100             # routing table id for marked packets
    bypass_v4: list = field(default_factory=lambda: list(DEFAULT_BYPASS_V4))
    bypass_v6: list = field(default_factory=lambda: list(DEFAULT_BYPASS_V6))
    lan_iface: str = "br-lan"       # interface whose traffic gets proxied
    enable_ipv6: bool = True
    proxy_output: bool = False      # also proxy router-locally-generated traffic
    quic_block: bool = True         # reject UDP/443 so browsers fall back to TCP
    mss_clamp: int = 0              # TCP MSS clamp value; 0 = off
    terminal_bypass: list = field(default_factory=list)  # idents (IP/CIDR) that never enter the kernel
    terminal_whitelist: list = field(default_factory=list)  # if non-empty, ONLY these enter kernel
    terminal_proxy: list = field(default_factory=list)  # idents that ALWAYS enter kernel (skip all bypass)
    dns_rewrites: list = field(default_factory=list)     # (domain, target) for dnsmasq address=
    dns_direct_ip: str = ""         # direct upstream, for per-domain server= lines
    dns_proxy_ip: str = ""          # proxy upstream, for per-domain server= lines
    site_domains: list = field(default_factory=list)  # (action, [domains/suffixes]) for server= lines
    dns_filter_conf: str = ""       # path to dnsmasq-blocklist.conf ("" = filter off)
    direct_ipset_domains: list = field(default_factory=list)  # direct domains -> ipset (bypass kernel)
    direct_ip_cidrs: list = field(default_factory=list)  # v0.1.341: direct ip_cidr bypass at ingress
    direct_ip_note: str = ""  # why some direct site sets yield no ip_cidr (v6 #15 fallback wording, ";"-joined)
    bypass_ports: str = ""          # e.g. "21114-21119, 2233"
    bypass_ports_mode: str = "black"  # black = these ports bypass; white = only these enter
    # Entry bypass mode (1:1 对标原版):
    # - "blacklist" (Default-release): everything bypasses EXCEPT entry_cidrs (proxy/reject sets)
    # - "whitelist" (Default-enter): only entry_cidrs (direct sets) bypass
    entry_mode: str = "whitelist"
    entry_cidrs: list = field(default_factory=list)  # CIDRs for entry_mode
    # Direct-answer release set: IPs from direct DNS answers, TTL 15min~1d
    direct_answer_enabled: bool = False


def _norm_idents(idents):
    """终端标识规范化（对标原版 Of/Pf/Tn/Co）：
    MAC 短横线转冒号+六组校验，IP/CIDR 裸地址补掩码+前缀越界拒绝。
    坏项直接丢弃，不让坏值进 nft 脚本（坏值会让整条脚本加载失败）。"""
    from core import arp as _arp
    macs, ips = _arp.split_mac_ip(idents or [])
    good_macs = [m for m in (_arp.normalize_mac(x) for x in macs) if m]
    good_ips = [c for c in (_arp.normalize_cidr(x) for x in ips) if c]
    return good_macs, good_ips


def classify_direct_ip_gaps(site_sets, expanded_names: set[str] | None = None) -> dict[str, int]:
    """Why some direct site sets contribute no ip_cidr to the ingress set.

    A set is skipped when it already has literal ip_cidr OR when its
    geoip rule_sets expanded into CIDRs (expanded_names). Remaining
    direct sets are classified by their strongest non-IP evidence:
    domain conditions, port conditions, unexpanded rule_sets (geosite
    domain lists can never yield CIDRs), or nothing at all.
    """
    expanded_names = expanded_names or set()
    causes = {"域名条件": 0, "port 等非 IP 条件": 0, "规则集未展开": 0, "没有 ip_cidr": 0}
    for s in site_sets:
        if s.action != "direct" or s.ip_cidr or s.name in expanded_names:
            continue
        if s.domains or s.domain_suffix or s.domain_keyword:
            causes["域名条件"] += 1
        elif s.ports:
            causes["port 等非 IP 条件"] += 1
        elif s.rule_sets:
            causes["规则集未展开"] += 1
        else:
            causes["没有 ip_cidr"] += 1
    return causes


def front_geoip_direct_cidrs(front_rules, expand_geoip) -> list[str]:
    """CIDRs from front rules that send geoip traffic direct.

    Mirrors the route generator's naming (geoip-<val>) and the ingress
    collection's target test (direct/直连). geosite rows are domains and
    can never yield CIDRs; group-targeted geoip rows stay in the kernel
    (they are not ingress bypasses). Disabled rows never reach here --
    load_app_config filters them.
    """
    out: list[str] = []
    for fr in front_rules or []:
        if not isinstance(fr, dict):
            continue
        if (fr.get("rtype") or "") != "geoip":
            continue
        target = (fr.get("target") or "").strip().lower()
        if target not in ("direct", "直连"):
            continue
        val = (fr.get("domain") or "").strip()
        if not val:
            continue
        out.extend(expand_geoip(f"geoip-{val}"))
    return out


def nft_script(cfg: TransparentConfig) -> str:
    b4 = ",\n        ".join(cfg.bypass_v4)
    b6 = ",\n        ".join(cfg.bypass_v6)
    v6_chain = ""
    if cfg.enable_ipv6:
        v6_chain = f"""
        set bypass6 {{
            type ipv6_addr
            flags interval
            elements = {{
                {b6}
            }}
        }}"""
    output_chain = ""
    if cfg.proxy_output:
        output_chain = f"""
    chain output {{
        type route hook output priority mangle; policy accept;
        meta mark {cfg.mark:#x} accept
        ip daddr @bypass4 accept
        tcp dport != 53 tproxy to 127.0.0.1:{cfg.tproxy_port} meta mark set {cfg.mark:#x} accept
        udp dport != 53 tproxy to 127.0.0.1:{cfg.tproxy_port} meta mark set {cfg.mark:#x} accept
    }}"""
    # Terminals configured as "bypass" never enter the kernel: accept early.
    # IP/CIDR idents go into an ipv4 set; MAC idents match directly on the
    # Ethernet source address (no ARP resolution needed, never goes stale).
    from core import arp as _arp
    _mac_terms, _ip_terms = _norm_idents(cfg.terminal_bypass or [])
    bypass_terminals = ""
    if _ip_terms:
        elts = ",\n        ".join(_ip_terms)
        bypass_terminals += f"""
        set tbypass {{
            type ipv4_addr
            flags interval
            elements = {{
                {elts}
            }}
        }}"""
    if _mac_terms:
        mel = ",\n        ".join(_mac_terms)
        bypass_terminals += f"""
        set macbypass {{
            type ether_addr
            elements = {{
                {mel}
            }}
        }}"""
    tbypass_rule = ""
    if _ip_terms:
        tbypass_rule += "\n        ip saddr @tbypass accept"
    if _mac_terms:
        tbypass_rule += "\n        ether saddr @macbypass accept"
    # Proxy terminals (v0.1.340): ALWAYS enter kernel, skip all bypass rules.
    # Placed BEFORE bypass rules so direct domains from these terminals
    # still go into the kernel (other terminals continue to enjoy bypass).
    _p_mac_terms, _p_ip_terms = _norm_idents(cfg.terminal_proxy or [])
    tproxy_terminals = ""
    tproxy_rule = ""
    if _p_ip_terms:
        pelts = ",\n        ".join(_p_ip_terms)
        tproxy_terminals += f"""
        set tproxy4 {{
            type ipv4_addr
            flags interval
            elements = {{
                {pelts}
            }}
        }}"""
        # Jump to tproxy directly, skipping all bypass accepts
        tproxy_rule += "\n        ip saddr @tproxy4 goto tproxy_direct"
    if _p_mac_terms:
        pmel = ",\n        ".join(_p_mac_terms)
        tproxy_terminals += f"""
        set mactproxy {{
            type ether_addr
            elements = {{
                {pmel}
            }}
        }}"""
        tproxy_rule += "\n        ether saddr @mactproxy goto tproxy_direct"
    # Whitelist mode: only listed terminals enter the kernel; all other
    # LAN traffic bypasses (like OpenClash whitelist). DNS also bypasses
    # for non-whitelisted (handled by placing before DNS accept).
    _wmac_terms, _wip_terms = _norm_idents(cfg.terminal_whitelist or [])
    whitelist_set = ""
    whitelist_rule = ""
    if _wip_terms or _wmac_terms:
        if _wip_terms:
            welts = ",\n        ".join(_wip_terms)
            whitelist_set += f"""
        set twhitelist {{
            type ipv4_addr
            flags interval
            elements = {{
                {welts}
            }}
        }}"""
        if _wmac_terms:
            wmel = ",\n        ".join(_wmac_terms)
            whitelist_set += f"""
        set macwhitelist {{
            type ether_addr
            elements = {{
                {wmel}
            }}
        }}"""
        # Bypass if NOT in whitelist (IP and MAC)
        conds = []
        if _wip_terms:
            conds.append("ip saddr != @twhitelist")
        if _wmac_terms:
            conds.append("ether saddr != @macwhitelist")
        # If both IP and MAC whitelists exist, bypass if NEITHER matches
        # (conservative: require at least one match to enter kernel)
        if len(conds) == 2:
            whitelist_rule = "\n        ip saddr != @twhitelist ether saddr != @macwhitelist accept"
        else:
            whitelist_rule = f"\n        {conds[0]} accept"
    # QUIC block: proxied UDP/443 is often poorly forwarded; rejecting it
    # makes browsers fall back to TCP. Placed before the tproxy rule.
    quic_rule = "\n        udp dport 443 reject" if cfg.quic_block else ""
    # TCP MSS clamp（对标原版 tunTcpMss）：0 关，合法域 536–65495；域外值直接关掉，
    # 不把坏值写进脚本（坏值会让整条脚本加载失败）。
    _mss = cfg.mss_clamp if (cfg.mss_clamp == 0 or 536 <= cfg.mss_clamp <= 65495) else 0
    mss_rule = f"\n        tcp flags syn tcp option maxseg size set {_mss}" if _mss else ""
    # Direct-bypass: dnsmasq puts resolved IPs of direct domains into this
    # dynamic set (see dnsmasq_conf ipset= lines); traffic to them is
    # accepted at ingress and never enters the kernel.
    direct_set = ""
    direct_rule = ""
    if cfg.direct_ipset_domains:
        direct_set = """
        set obx_direct4 {
            type ipv4_addr
            flags dynamic,timeout
            timeout 12h
        }"""
        direct_rule = "\n        ip daddr @obx_direct4 accept"
    # v0.1.341: Direct IP CIDRs bypass at ingress (from site_sets/front_rules)
    # v6 #15: three deductions in order (last address -> FakeIP pool ->
    # earlier sets), v4/v6 split; v6 is only reported, never written into
    # an ipv4_addr set (this script has no v6 prerouting chain).
    direct_ip_set = ""
    direct_ip_rule = ""
    direct_v4: list[str] = []
    deduct_notes: list[str] = []
    if cfg.direct_ip_note:
        deduct_notes.append(cfg.direct_ip_note)
    if cfg.direct_ip_cidrs:
        from core import cidr_deduct as _cd
        _dc_raw = [c for c in (_arp.normalize_cidr(x) for x in cfg.direct_ip_cidrs) if c]
        _dc = _cd.deduct(_dc_raw,
                         earlier=list(cfg.bypass_v4) + _ip_terms)
        direct_v4 = _dc["v4"]
        deduct_notes.append(_cd.note_line("direct_ip4", len(_dc_raw), _dc))
        if direct_v4:
            cidrs = ",\n        ".join(direct_v4)
            direct_ip_set = f"""
        set obx_direct_ip4 {{
            type ipv4_addr
            flags interval
            elements = {{
                {cidrs}
            }}
        }}"""
            direct_ip_rule = "\n        ip daddr @obx_direct_ip4 accept"
    # Entry bypass mode (1:1 对标原版):
    # - blacklist: everything bypasses EXCEPT entry_cidrs → create set, accept if NOT in set
    # - whitelist: only entry_cidrs bypass (handled by direct_set above)
    entry_set = ""
    entry_rule = ""
    if cfg.entry_mode == "blacklist" and cfg.entry_cidrs:
        from core import cidr_deduct as _cd
        _ec_raw = [c for c in (_arp.normalize_cidr(x) for x in cfg.entry_cidrs) if c]
        _ec = _cd.deduct(_ec_raw,
                         earlier=list(cfg.bypass_v4) + _ip_terms + direct_v4)
        deduct_notes.append(_cd.note_line("entry4", len(_ec_raw), _ec))
        if _ec["v4"]:
            ecidrs = ",\n        ".join(_ec["v4"])
            entry_set = """
        set obx_entry4 {
            type ipv4_addr
            flags interval
            elements = {
                %s
            }
        }""" % ecidrs
            # Blacklist: accept (bypass) if NOT in the enter-kernel set
            entry_rule = "\n        ip daddr != @obx_entry4 accept"
    
    # Direct-answer release set (blacklist mode only):
    # IPs from direct DNS answers, TTL 15min~1d, accepted at ingress
    da_set = ""
    da_rule = ""
    if cfg.direct_answer_enabled:
        da_set = """
        set obx_direct_answer4 {
            type ipv4_addr
            flags dynamic,timeout
            timeout 1d
        }"""
        da_rule = "\n        ip daddr @obx_direct_answer4 accept"
    
    # Port bypass: blacklist = listed ports bypass the kernel;
    # whitelist = only listed ports enter the kernel.
    # 对标原版 parsePortSpec：一条坏项否决整串（整条端口规则不生成，
    # 不把坏值写进脚本——坏值会让整条脚本加载失败）。
    port_rule = ""
    if cfg.bypass_ports.strip():
        _ports = _arp.parse_port_spec(cfg.bypass_ports)
        if _ports:
            ports = ", ".join(_ports)
            if cfg.bypass_ports_mode == "white":
                port_rule = (f"\n        tcp dport != {{{ports}}} accept"
                             f"\n        udp dport != {{{ports}}} accept")
            else:
                port_rule = f"\n        tcp dport {{{ports}}} accept\n        udp dport {{{ports}}} accept"
    notes_block = ""
    if deduct_notes:
        notes_block = "\n" + "\n".join(f"# {n}" for n in deduct_notes)
    return f"""#!/usr/sbin/nft -f
# Generated by openbox-oss. Review before applying. Requires root.{notes_block}
# Applies TPROXY transparent proxying for traffic arriving on {cfg.lan_iface}.

flush table inet openbox-oss

table inet openbox-oss {{
        set bypass4 {{
            type ipv4_addr
            flags interval
            elements = {{
                {b4}
            }}
        }}{v6_chain}{bypass_terminals}{tproxy_terminals}{whitelist_set}{direct_set}{direct_ip_set}{entry_set}{da_set}

    chain prerouting {{
        type filter hook prerouting priority mangle; policy accept;
        iifname != "{cfg.lan_iface}" accept{tproxy_rule}
        ip daddr @bypass4 accept{tbypass_rule}{whitelist_rule}{direct_rule}{direct_ip_rule}{da_rule}{entry_rule}
        tcp dport 53 accept
        udp dport 53 accept{port_rule}{quic_rule}{mss_rule}
        meta l4proto tcp tproxy to 127.0.0.1:{cfg.tproxy_port} meta mark set {cfg.mark:#x} accept
        meta l4proto udp tproxy to 127.0.0.1:{cfg.tproxy_port} meta mark set {cfg.mark:#x} accept
    }}

    # Proxy terminals jump here: skip all bypass, go directly to tproxy
    chain tproxy_direct {{
        meta l4proto tcp tproxy to 127.0.0.1:{cfg.tproxy_port} meta mark set {cfg.mark:#x} accept
        meta l4proto udp tproxy to 127.0.0.1:{cfg.tproxy_port} meta mark set {cfg.mark:#x} accept
    }}{output_chain}
}}
""".lstrip()


def ip_rules(cfg: TransparentConfig) -> str:
    """`ip rule`/`ip route` lines so marked packets use the TPROXY table."""
    lines = [
        f"# route marked packets via local table {cfg.table_id}",
        f"ip rule add fwmark {cfg.mark:#x} table {cfg.table_id}",
        f"ip route add local default dev lo table {cfg.table_id}",
    ]
    if cfg.enable_ipv6:
        lines += [
            f"ip -6 rule add fwmark {cfg.mark:#x} table {cfg.table_id}",
            f"ip -6 route add local default dev lo table {cfg.table_id}",
        ]
    return "\n".join(lines) + "\n"


def dnsmasq_snippet(cfg: TransparentConfig) -> str:
    """dnsmasq conf: hand DNS to the sing-box DNS server on localhost.

    Additionally emits per-domain `server=` lines so direct/proxy domains
    use their own upstream, and `address=` lines for DNS rewrites.
    """
    lines = ["# Generated by openbox-oss: forward all DNS to sing-box",
             "# Place in /etc/dnsmasq.d/ and restart dnsmasq. Port 53 on the router",
             f"# stays with dnsmasq; sing-box listens on 127.0.0.1:{cfg.dns_port}.",
             f"server=127.0.0.1#{cfg.dns_port}"]
    for action, domains in cfg.site_domains:
        upstream = cfg.dns_proxy_ip if action == "proxy" else cfg.dns_direct_ip
        if not upstream:
            continue
        for d in domains:
            lines.append(f"server=/{d}/{upstream}")
    for domain, target in cfg.dns_rewrites:
        lines.append(f"address=/{domain}/{target}")
    # Direct-bypass at ingress: resolved IPs of direct domains land in the
    # obx_direct4 nftables set, whose traffic is accepted before tproxy.
    for d in cfg.direct_ipset_domains:
        lines.append(f"ipset=/{d}/obx_direct4")
    if cfg.dns_filter_conf:
        lines.append(f"# DNS filter blocklist ({cfg.dns_filter_conf})")
        lines.append(f"conf-file={cfg.dns_filter_conf}")
    return "\n".join(lines) + "\n"
