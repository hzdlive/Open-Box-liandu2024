"""Node -> share-link encoders (subscription sharing).

Inverse of core/subscription.py parsing for the protocols that round-trip
cleanly: vmess, vless, trojan, shadowsocks. tuic / hysteria2 / wireguard /
anytls raise a clear error (their link formats carry QUIC-only options we
don't want to half-encode).
"""

from __future__ import annotations

import base64
import json
from urllib.parse import quote, urlencode


def _b64e(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode().rstrip("=")


def _tls_of(params: dict) -> dict:
    return params.get("tls") or {}


def _transport_of(params: dict) -> dict:
    return params.get("transport") or {"type": "tcp"}


def encode_vmess(node: dict) -> str:
    p, t, tls = node["params"], _transport_of(node["params"]), _tls_of(node["params"])
    headers = t.get("headers") or {}
    data = {
        "v": "2", "ps": node["tag"], "add": node["server"],
        "port": str(node["port"]), "id": p.get("uuid", ""),
        "aid": str(p.get("alter_id", 0)), "net": t.get("type", "tcp"),
        "type": "none", "host": headers.get("Host", ""),
        "path": t.get("path", "") or t.get("service_name", ""),
        "tls": "tls" if tls.get("enabled") else "",
    }
    if tls.get("server_name"):
        data["sni"] = tls["server_name"]
    return "vmess://" + _b64e(json.dumps(data, ensure_ascii=False))


def encode_vless(node: dict) -> str:
    p, t, tls = node["params"], _transport_of(node["params"]), _tls_of(node["params"])
    q: dict = {}
    reality = tls.get("reality") or {}
    if reality.get("enabled"):
        q["security"] = "reality"
        q["pbk"] = reality.get("public_key", "")
        q["sid"] = reality.get("short_id", "")
    elif tls.get("enabled"):
        q["security"] = "tls"
    else:
        q["security"] = "none"
    if tls.get("server_name"):
        q["sni"] = tls["server_name"]
    if tls.get("alpn"):
        q["alpn"] = ",".join(tls["alpn"])
    if tls.get("fingerprint"):
        q["fp"] = tls["fingerprint"]
    if p.get("flow"):
        q["flow"] = p["flow"]
    ttype = t.get("type", "tcp")
    q["type"] = ttype
    if ttype == "ws":
        q["path"] = t.get("path", "/")
        headers = t.get("headers") or {}
        if headers.get("Host"):
            q["host"] = headers["Host"]
    elif ttype == "grpc":
        q["serviceName"] = t.get("service_name", "")
    return (f"vless://{quote(p.get('uuid', ''), safe='')}@{node['server']}:{node['port']}"
            f"?{urlencode(q)}#{quote(node['tag'], safe='')}")


def encode_trojan(node: dict) -> str:
    p, tls = node["params"], _tls_of(node["params"])
    q: dict = {}
    if tls.get("server_name"):
        q["sni"] = tls["server_name"]
    if tls.get("alpn"):
        q["alpn"] = ",".join(tls["alpn"])
    if tls.get("fingerprint"):
        q["fp"] = tls["fingerprint"]
    qs = f"?{urlencode(q)}" if q else ""
    return (f"trojan://{quote(p.get('password', ''), safe='')}@{node['server']}:{node['port']}"
            f"{qs}#{quote(node['tag'], safe='')}")


def encode_ss(node: dict) -> str:
    p = node["params"]
    userinfo = _b64e(f"{p.get('method', '')}:{p.get('password', '')}")
    return (f"ss://{userinfo}@{node['server']}:{node['port']}"
            f"#{quote(node['tag'], safe='')}")


_ENCODERS = {
    "vmess": encode_vmess,
    "vless": encode_vless,
    "trojan": encode_trojan,
    "shadowsocks": encode_ss,
}


def encode_node(node: dict) -> str:
    """Encode one node dict (tag/protocol/server/port/params) to a share link."""
    enc = _ENCODERS.get(node.get("protocol"))
    if enc is None:
        raise ValueError(f"sharing not supported for protocol: {node.get('protocol')}")
    return enc(node)


def encode_nodes(nodes: list[dict]) -> list[dict]:
    """Encode many; per-node errors are reported inline, not raised."""
    out = []
    for n in nodes:
        try:
            out.append({"tag": n.get("tag"), "link": encode_node(n)})
        except ValueError as e:
            out.append({"tag": n.get("tag"), "error": str(e)})
    return out
