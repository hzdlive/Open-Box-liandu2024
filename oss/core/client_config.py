"""Client-side sing-box config generation.

Served via GET /api/client/config. Reuses the router's outbound/rule
building blocks (core/singbox.py) but with client-local inbounds and a
mode-dependent final outbound:

- mode=global: everything through the proxy group ("所有-自动").
- mode=rule:    site-set rules apply, unmatched -> final_outbound.
- mode=direct:  everything direct (rules still emitted for DNS only).

ruleset=follow (default): include the router's site-set rules.
ruleset=local:  omit site-set rules (client manages its own rules).
"""

from __future__ import annotations

from core.singbox import build_outbounds, build_route_rules, _dns_servers

VALID_MODES = ("global", "rule", "direct")


def build_client_config(cfg, mode: str = "rule", ruleset: str = "follow",
                        mixed_port: int = 7890) -> dict:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}")
    outbounds = build_outbounds(cfg)
    route_rules, dns_rules, _ = build_route_rules(cfg)

    if ruleset == "local":
        route_rules, dns_rules = [], []
    elif ruleset != "follow":
        raise ValueError("ruleset must be follow|local")

    if mode == "global":
        final = "所有-自动"
    elif mode == "direct":
        final = "direct"
    else:
        final = cfg.final_outbound

    return {
        "log": {"level": "warn"},
        "dns": {
            "servers": (_dns_servers("dns-direct", cfg.dns.direct_dns, "direct")
                        + _dns_servers("dns-proxy", cfg.dns.proxy_dns, "所有-自动")),
            "rules": dns_rules,
            "final": "dns-direct",
        },
        "inbounds": [
            # Client-local: no auto_route here; the client app (VpnService /
            # utun / wintun) owns routing and points at this tun.
            {"type": "tun", "tag": "tun-in", "stack": cfg.tun_stack,
             "auto_route": False},
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1",
             "listen_port": mixed_port},
        ],
        "outbounds": outbounds,
        "route": {
            "rules": ([{"action": "sniff"}] + route_rules
                      + [{"protocol": "dns", "action": "hijack-dns"}]),
            "final": final,
            "auto_detect_interface": True,
            "default_domain_resolver": "dns-direct",
        },
    }
