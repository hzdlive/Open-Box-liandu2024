"""Data model: nodes, site sets (routing rule groups), DNS and app config."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    """A single proxy node parsed from a subscription link."""

    tag: str
    protocol: str  # vmess | vless | trojan | shadowsocks | tuic | hysteria2 | wireguard
    server: str
    server_port: int
    params: dict = field(default_factory=dict)
    # params carries protocol-specific fields, e.g.:
    #   uuid, password, method, security, sni, alpn, fingerprint,
    #   reality{public_key, short_id}, transport{type, path, host, service_name}


@dataclass
class SiteSet:
    """A named routing rule set. Matched top-down, first hit wins."""

    name: str
    action: str = "proxy"  # proxy | direct | reject
    domains: list = field(default_factory=list)        # exact domains
    domain_suffix: list = field(default_factory=list)  # domain suffixes
    domain_keyword: list = field(default_factory=list)
    ip_cidr: list = field(default_factory=list)
    rule_sets: list = field(default_factory=list)      # referenced rule set names
    group: str = "auto"  # outbound group tag used when action == "proxy"
    flip: str = ""  # hot-switch state: "" (= follow action) | "direct" | "proxy"
    sid: int = 0  # database id (used for the hot-switch selector tag)

    @classmethod
    def from_dict(cls, d: dict) -> "SiteSet":
        rules = d.get("rules", {}) if isinstance(d.get("rules"), dict) else {}

        def pick(key: str) -> list:
            v = rules.get(key, d.get(key, []))
            return list(v) if isinstance(v, list) else []

        return cls(
            name=d["name"],
            action=d.get("action", "proxy"),
            domains=pick("domains"),
            domain_suffix=pick("domain_suffix"),
            domain_keyword=pick("domain_keyword"),
            ip_cidr=pick("ip_cidr"),
            rule_sets=list(d.get("rule_sets", rules.get("rule_sets", []))),
            group=d.get("group", "auto"),
        )


@dataclass
class Group:
    """An outbound group. Members resolve at build time."""

    name: str
    type: str = "urltest"  # urltest | selector | failover
    members: list = field(default_factory=list)
    # member tags; "*nodes*" = all node tags, "*all*" = nodes + chains
    dynamic_keywords: list = field(default_factory=list)
    # node tags containing (case-insensitive) any keyword are auto-included
    position: int = 0


@dataclass
class Chain:
    """Chain proxy: exit (socks5/http) reached through a front node/group."""

    name: str
    exit_protocol: str = "socks"  # socks | http
    server: str = ""
    server_port: int = 0
    params: dict = field(default_factory=dict)  # username, password
    front: str = "auto"  # tag of the node/group to detour through


@dataclass
class RuleSet:
    """A remote/local rule list referenced by site sets."""

    name: str
    url: str = ""
    format: str = "auto"  # auto | clash-classical | domain-list
    content: str = ""
    updated_at: str = ""


@dataclass
class DnsConfig:
    direct_dns: str = "223.5.5.5"          # for direct domains
    proxy_dns: str = "tcp://1.1.1.1"       # for proxied domains
    enable_fakeip: bool = False
    mode: str = "dnsmasq"                  # dnsmasq | firewall | off (hijack mode)
    region: str = "auto"                   # auto | cn | outside
    region_detected: str = ""              # last auto-detected region ("cn"/"outside")


@dataclass
class DnsRewrite:
    domain: str
    target: str                            # fixed IP or another domain
    id: int = 0


@dataclass
class TerminalPolicy:
    ident: str                             # IP or CIDR of the terminal
    name: str = ""
    policy: str = "proxy"                  # direct | proxy | bypass (bypass = never enters kernel)
    id: int = 0


@dataclass
class AppConfig:
    nodes: list = field(default_factory=list)      # list[Node]
    site_sets: list = field(default_factory=list)  # list[SiteSet], top-down order
    groups: list = field(default_factory=list)     # list[Group]
    chains: list = field(default_factory=list)     # list[Chain]
    dns: DnsConfig = field(default_factory=DnsConfig)
    dns_rewrites: list = field(default_factory=list)  # list[DnsRewrite]
    terminals: list = field(default_factory=list)     # list[TerminalPolicy]
    final_outbound: str = "auto"  # fallback route
    tun_stack: str = "mixed"     # mixed | gvisor | system
    tun_mtu: int = 9000
    quic_block: bool = True      # reject UDP/443 for proxied traffic (default on)
    clash_api_port: int = 9090
