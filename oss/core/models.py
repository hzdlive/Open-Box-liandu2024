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
    sub_id: int | None = None  # 所属订阅 ID
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
    ports: list = field(default_factory=list)          # port numbers/ranges
    rule_sets: list = field(default_factory=list)      # referenced rule set names
    ruleset_urls: list = field(default_factory=list)   # remote ruleset URLs
    group: str = "所有-自动"  # outbound group tag used when action == "proxy"
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
            group=d.get("group", "所有-自动"),
        )


@dataclass
class Group:
    """An outbound group. Members resolve at build time."""

    name: str
    type: str = "urltest"  # urltest | selector | failover | smart | loadbalance
    members: list = field(default_factory=list)
    # member tags; "*nodes*" = all node tags, "*all*" = nodes + chains
    dynamic_keywords: list = field(default_factory=list)
    # node tags containing (case-insensitive) any keyword are auto-included
    position: int = 0
    enabled: bool = True
    interval_s: int = 300      # urltest check interval
    tolerance_ms: int = 100    # urltest tolerance
    idle_timeout: str = "12h"  # urltest idle timeout (sing-box duration)
    expected_status: str = ""  # urltest expected HTTP status ("" = kernel default)
    test_url: str = ""         # per-group test URL ("" = global speedtest_url)
    lanes: list = field(default_factory=list)
    # failover lanes: [{name, members[]}] — primary/backup tabs (1:1 original).
    # Empty = single flat member list (legacy behavior).


@dataclass
class Chain:
    """Chain proxy: exit reached through a front node/group.

    exit_protocol supports: socks, http, shadowsocks, vmess, vless,
    trojan, tuic, hysteria2, anytls (1:1 with node protocols).
    """

    name: str
    exit_protocol: str = "socks"  # socks | http | shadowsocks | vmess | vless | trojan | tuic | hysteria2 | anytls
    server: str = ""
    server_port: int = 0
    params: dict = field(default_factory=dict)  # protocol-specific params
    front: str = "所有-自动"  # tag of the node/group to detour through


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
    split: bool = True                     # split direct/proxy upstreams; False = all via proxy
    region: str = "auto"                   # auto | cn | outside
    region_detected: str = ""              # last auto-detected region ("cn"/"outside")
    upstream_latency: dict = field(default_factory=dict)  # {upstream: ms}


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
class TerminalRule:
    id: int = 0
    name: str = ""
    match_by: str = "ip"                  # ip | mac
    targets: list = field(default_factory=list)
    policy: str = "proxy"                 # proxy | direct | whitelist
    outbound: str = ""
    enabled: bool = True
    position: int = 0


@dataclass
class AppConfig:
    nodes: list = field(default_factory=list)      # list[Node]
    site_sets: list = field(default_factory=list)  # list[SiteSet], top-down order
    groups: list = field(default_factory=list)     # list[Group]
    chains: list = field(default_factory=list)     # list[Chain]
    dns: DnsConfig = field(default_factory=DnsConfig)
    dns_rewrites: list = field(default_factory=list)  # list[DnsRewrite]
    terminals: list = field(default_factory=list)     # list[TerminalPolicy]
    terminal_rules: list = field(default_factory=list)  # list[TerminalRule]
    final_outbound: str = "所有-自动"  # fallback route
    routing_fallback: str = "direct"  # 1:1 original: unmatched -> direct
    tun_stack: str = "mixed"     # mixed | gvisor | system
    tun_mtu: int = 9000
    tun_address: str = "172.19.0.1/30"  # TUN interface address (sing-box >= 1.14 requires it)
    quic_block: bool = True      # reject UDP/443 for proxied traffic (default on)
    blocked_domains: list = None  # content filtering (0.1.328): domains to block
    clash_api_port: int = 9090
    clash_api_listen: str = "127.0.0.1"  # dashboard 二开分支：浏览器直连 clash API 时需改为 0.0.0.0
    clash_api_secret: str = ""           # clash API secret，为空表示不设密码
    share_lan_enabled: bool = False  # legacy: expose mixed inbound on LAN
    share_lan_port: int = 8088
    share_servers: list = field(default_factory=list)
    # 1:1 original: LAN shadowsocks inbounds [{name, address, port, method, password, enabled}]
    front_rules: list = field(default_factory=list)  # list[dict], before site sets
    subscriptions: list = field(default_factory=list)  # list[dict] {id, name, enabled}
    speedtest_url: str = "http://www.gstatic.com/generate_204"
    sub_node_direct: bool = False  # subscription/node server domains go direct
    sub_domains: list = field(default_factory=list)  # subscription URL hostnames
