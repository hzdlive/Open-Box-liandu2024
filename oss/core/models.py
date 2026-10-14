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
    group: str = "auto"  # outbound group tag used when action == "proxy"

    @classmethod
    def from_dict(cls, d: dict) -> "SiteSet":
        return cls(
            name=d["name"],
            action=d.get("action", "proxy"),
            domains=list(d.get("domains", [])),
            domain_suffix=list(d.get("domain_suffix", [])),
            domain_keyword=list(d.get("domain_keyword", [])),
            ip_cidr=list(d.get("ip_cidr", [])),
            group=d.get("group", "auto"),
        )


@dataclass
class DnsConfig:
    direct_dns: str = "223.5.5.5"          # for direct domains
    proxy_dns: str = "tcp://1.1.1.1"       # for proxied domains
    enable_fakeip: bool = False


@dataclass
class AppConfig:
    nodes: list = field(default_factory=list)      # list[Node]
    site_sets: list = field(default_factory=list)  # list[SiteSet], top-down order
    dns: DnsConfig = field(default_factory=DnsConfig)
    final_outbound: str = "auto"  # fallback route
    tun_stack: str = "mixed"     # mixed | gvisor | system
    clash_api_port: int = 9090
