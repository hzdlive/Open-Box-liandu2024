"""Parse Clash YAML subscriptions into Node objects.

Covers the proxy types relevant to sing-box:
ss, vmess, vless, trojan, tuic, hysteria2, wireguard.
Unknown types are skipped.
"""

from __future__ import annotations

import yaml

from .models import Node


def _tls_from_clash(p: dict, default_sni: str = "", force: bool = False) -> dict | None:
    # v0.1.361: TUIC/Hysteria2/AnyTLS always run over TLS, but their
    # Clash entries often omit the tls: key and carry fingerprint/sni/
    # alpn/skip-cert-verify at top level. Without force those fields
    # were dropped (the caller fell back to a bare {enabled,
    # server_name} dict). For vmess/vless force stays False: an
    # absent/false tls: there means no TLS and must be honored.
    # v0.1.367 (#743): trojan joins the forced set — Clash trojan
    # entries never carry a tls: key (sni/alpn/skip-cert-verify live
    # at top level) and trojan is TLS by definition, so requiring the
    # key dropped the original SNI on import (and again on share).
    if not p.get("tls") and not force:
        return None
    tls: dict = {"enabled": True, "server_name": p.get("servername") or p.get("sni") or default_sni}
    if p.get("skip-cert-verify"):
        tls["insecure"] = True
    if p.get("alpn"):
        alpn = p["alpn"]
        tls["alpn"] = alpn if isinstance(alpn, list) else [alpn]
    if p.get("fingerprint") or p.get("client-fingerprint"):
        tls["fingerprint"] = p.get("fingerprint") or p.get("client-fingerprint")
    return tls


def _transport_from_clash(p: dict) -> dict | None:
    net = str(p.get("network", "tcp")).lower()
    if net in ("tcp", "none"):
        return None
    t: dict = {"type": net}
    if net == "ws":
        opts = p.get("ws-opts") or {}
        t["path"] = opts.get("path", "/")
        headers = opts.get("headers")
        if headers:
            t["headers"] = dict(headers)
    elif net == "grpc":
        opts = p.get("grpc-opts") or {}
        t["service_name"] = opts.get("grpc-service-name", "")
    elif net in ("h2", "http"):
        opts = p.get("h2-opts") or p.get("http-opts") or {}
        t["path"] = opts.get("path", "/")
        if opts.get("host"):
            host = opts["host"]
            t["headers"] = {"Host": host[0] if isinstance(host, list) else host}
    return t


def _clash_proxy_to_node(p: dict, seen: set) -> Node | None:
    ptype = str(p.get("type", "")).lower()
    base_tag = str(p.get("name") or ptype)
    i, tag = 2, base_tag
    while tag in seen:
        tag = f"{base_tag} #{i}"
        i += 1
    seen.add(tag)
    try:
        port = int(p.get("port", 0))
    except (TypeError, ValueError):
        return None
    server = str(p.get("server", ""))
    if not server or not port:
        return None
    params: dict = {}
    proto: str | None = None

    if ptype == "ss":
        proto, params = "shadowsocks", {"method": p.get("cipher", ""), "password": str(p.get("password", ""))}
    elif ptype == "vmess":
        proto = "vmess"
        params = {"uuid": str(p.get("uuid", "")), "alter_id": int(p.get("alterId", 0)),
                  "security": p.get("cipher", "auto")}
    elif ptype == "vless":
        proto = "vless"
        params = {"uuid": str(p.get("uuid", ""))}
        if p.get("flow"):
            params["flow"] = p["flow"]
    elif ptype == "trojan":
        proto, params = "trojan", {"password": str(p.get("password", ""))}
    elif ptype == "tuic":
        proto = "tuic"
        params = {"uuid": str(p.get("uuid", "")), "password": str(p.get("password", "")),
                  "congestion_control": p.get("congestion-controller", "bbr")}
    elif ptype == "hysteria2":
        proto = "hysteria2"
        params = {"password": str(p.get("password", ""))}
        if p.get("obfs"):
            params["obfs"] = {"type": p["obfs"], "password": str(p.get("obfs-password", ""))}
    elif ptype == "anytls":
        proto = "anytls"
        params = {"password": str(p.get("password", ""))}
    elif ptype == "wireguard":
        proto = "wireguard"
        local = []
        if p.get("ip"):
            local.append(str(p["ip"]))
        if p.get("ipv6"):
            local.append(str(p["ipv6"]))
        params = {"local_address": local, "private_key": str(p.get("private-key", "")),
                  "peer_public_key": str(p.get("public-key", ""))}
        if p.get("pre-shared-key"):
            params["pre_shared_key"] = str(p["pre-shared-key"])
        if p.get("mtu"):
            params["mtu"] = int(p["mtu"])
    else:
        return None

    if ptype in ("vmess", "vless", "trojan"):
        tls = _tls_from_clash(p, server, force=(ptype == "trojan"))
        if tls:
            if ptype == "vless" and isinstance(p.get("reality-opts"), dict):
                ro = p["reality-opts"]
                tls["reality"] = {"enabled": True,
                                  "public_key": str(ro.get("public-key", "")),
                                  "short_id": str(ro.get("short-id", ""))}
            params["tls"] = tls
        transport = _transport_from_clash(p)
        if transport:
            params["transport"] = transport
    elif ptype in ("tuic", "hysteria2", "anytls"):
        tls = _tls_from_clash(p, server, force=True)
        if p.get("sni"):
            tls["server_name"] = p["sni"]
        params["tls"] = tls
        if ptype == "anytls":
            # v0.1.376 (#663)：Clash 侧同名字段（kebab-case）一并保留
            for clash_key, param_key in (
                    ("idle-session-check-interval", "idle_session_check_interval"),
                    ("idle-session-timeout", "idle_session_timeout"),
                    ("min-idle-session", "min_idle_session"),
                    ("client-metadata", "client_metadata")):
                if p.get(clash_key) is not None:
                    if param_key == "min_idle_session":
                        try:
                            params[param_key] = int(p[clash_key])
                        except (TypeError, ValueError):
                            pass
                    else:
                        params[param_key] = str(p[clash_key])

    return Node(tag=tag, protocol=proto, server=server, server_port=port, params=params)


def parse_clash_yaml(text: str) -> list[Node]:
    """Parse a Clash YAML subscription/config into Nodes."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        return []
    nodes, seen = [], set()
    for p in data["proxies"]:
        if not isinstance(p, dict):
            continue
        try:
            node = _clash_proxy_to_node(p, seen)
        except Exception:
            node = None
        if node:
            nodes.append(node)
    return nodes


def looks_like_clash(text: str) -> bool:
    head = text.lstrip()[:2000]
    return head.startswith("proxies:") or "\nproxies:" in head
