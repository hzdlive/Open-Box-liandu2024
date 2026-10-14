"""Build a sing-box configuration dict from an AppConfig.

Follows the sing-box configuration schema (open documentation).
Routing semantics: site sets are evaluated top-down, first hit wins;
unmatched traffic falls through to ``final_outbound``.
"""

from __future__ import annotations

from .models import AppConfig, Node


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
    tls = _tls_block(p)
    if tls:
        ob["tls"] = tls
    transport = _transport_block(p)
    if transport:
        ob["transport"] = transport
    return ob


def build_config(cfg: AppConfig) -> dict:
    """Build the full sing-box config dict."""
    node_tags = [n.tag for n in cfg.nodes]
    outbounds = [node_to_outbound(n) for n in cfg.nodes]
    outbounds += [
        {"type": "urltest", "tag": "auto", "outbounds": node_tags,
         "url": "http://www.gstatic.com/generate_204", "interval": "5m", "tolerance": 50},
        {"type": "selector", "tag": "manual", "outbounds": node_tags, "default": node_tags[0] if node_tags else "direct"},
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"},
        {"type": "dns", "tag": "dns-out"},
    ]

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
        target = {"proxy": s.group, "direct": "direct", "reject": "block"}.get(s.action, s.group)
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
