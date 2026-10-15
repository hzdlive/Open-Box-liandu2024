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
    dns_rewrites: list = field(default_factory=list)     # (domain, target) for dnsmasq address=
    dns_direct_ip: str = ""         # direct upstream, for per-domain server= lines
    dns_proxy_ip: str = ""          # proxy upstream, for per-domain server= lines
    site_domains: list = field(default_factory=list)  # (action, [domains/suffixes]) for server= lines
    dns_filter_conf: str = ""       # path to dnsmasq-blocklist.conf ("" = filter off)
    direct_ipset_domains: list = field(default_factory=list)  # direct domains -> ipset (bypass kernel)
    bypass_ports: str = ""          # e.g. "21114-21119, 2233"
    bypass_ports_mode: str = "black"  # black = these ports bypass; white = only these enter


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
    _mac_terms, _ip_terms = _arp.split_mac_ip(cfg.terminal_bypass or [])
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
    # QUIC block: proxied UDP/443 is often poorly forwarded; rejecting it
    # makes browsers fall back to TCP. Placed before the tproxy rule.
    quic_rule = "\n        udp dport 443 reject" if cfg.quic_block else ""
    # TCP MSS clamp (helps MTU-blackhole paths, e.g. hardware offload NICs).
    mss_rule = f"\n        tcp flags syn tcp option maxseg size set {cfg.mss_clamp}" if cfg.mss_clamp else ""
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
    # Port bypass: blacklist = listed ports bypass the kernel;
    # whitelist = only listed ports enter the kernel.
    port_rule = ""
    if cfg.bypass_ports.strip():
        ports = cfg.bypass_ports.strip()
        if cfg.bypass_ports_mode == "white":
            port_rule = (f"\n        tcp dport != {{{ports}}} accept"
                         f"\n        udp dport != {{{ports}}} accept")
        else:
            port_rule = f"\n        tcp dport {{{ports}}} accept\n        udp dport {{{ports}}} accept"
    return f"""#!/usr/sbin/nft -f
# Generated by openbox-oss. Review before applying. Requires root.
# Applies TPROXY transparent proxying for traffic arriving on {cfg.lan_iface}.

flush table inet openbox-oss

table inet openbox-oss {{
        set bypass4 {{
            type ipv4_addr
            flags interval
            elements = {{
                {b4}
            }}
        }}{v6_chain}{bypass_terminals}{direct_set}

    chain prerouting {{
        type filter hook prerouting priority mangle; policy accept;
        iifname != "{cfg.lan_iface}" accept
        ip daddr @bypass4 accept{tbypass_rule}{direct_rule}
        tcp dport 53 accept
        udp dport 53 accept{port_rule}{quic_rule}{mss_rule}
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
