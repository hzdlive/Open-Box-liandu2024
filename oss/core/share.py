"""Node -> share-link encoders (subscription sharing).

Inverse of core/subscription.py parsing. v0.1.361 added the four
protocols that used to raise a clear error: tuic, hysteria2, anytls,
wireguard. Their link formats carry QUIC/WG-only options, now encoded
field-for-field (fp, pinSHA256, obfs, mport, presharedkey, mtu).
Note: tuic/hysteria2/wireguard/anytls certificate pins (pinSHA256)
round-trip through the link but have no sing-box equivalent -- see
subscription.py -- so a shared link preserves them without the kernel
enforcing them.
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
    qs = ""
    if p.get("plugin"):
        # Parser reads ?plugin= before # and splits opts on ";"; urlencode
        # escapes both separators so the value survives the query round-trip.
        plugin_val = p["plugin"] + (";" + p["plugin_opts"] if p.get("plugin_opts") else "")
        qs = f"?{urlencode({'plugin': plugin_val})}"
    return (f"ss://{userinfo}@{node['server']}:{node['port']}"
            f"{qs}#{quote(node['tag'], safe='')}")


def encode_socks(node: dict) -> str:
    p = node["params"]
    scheme = {"4": "socks4", "4a": "socks4a"}.get(str(p.get("version", "5")), "socks5")
    userinfo = ""
    if p.get("username") is not None:
        userinfo = quote(str(p["username"]), safe="")
        if p.get("password") is not None:
            userinfo += ":" + quote(str(p["password"]), safe="")
        userinfo += "@"
    return (f"{scheme}://{userinfo}{node['server']}:{node['port']}"
            f"#{quote(node['tag'], safe='')}")


def _tls_query(tls: dict) -> dict:
    q: dict = {}
    if tls.get("server_name"):
        q["sni"] = tls["server_name"]
    if tls.get("alpn"):
        q["alpn"] = ",".join(tls["alpn"])
    if tls.get("insecure"):
        q["insecure"] = "1"
    if tls.get("fingerprint"):
        q["fp"] = tls["fingerprint"]
    return q


def encode_tuic(node: dict) -> str:
    p, tls = node["params"], _tls_of(node["params"])
    q = {"congestion_control": p.get("congestion_control", "bbr")}
    q.update(_tls_query(tls))
    return (f"tuic://{quote(p.get('uuid', ''), safe='')}:{quote(p.get('password', ''), safe='')}"
            f"@{node['server']}:{node['port']}?{urlencode(q)}#{quote(node['tag'], safe='')}")


def encode_hysteria2(node: dict) -> str:
    p, tls = node["params"], _tls_of(node["params"])
    q: dict = {}
    obfs = p.get("obfs") or {}
    if obfs.get("type"):
        q["obfs"] = obfs["type"]
    if obfs.get("password"):
        q["obfs-password"] = obfs["password"]
    q.update(_tls_query(tls))
    if tls.get("pin_sha256"):
        q["pinSHA256"] = tls["pin_sha256"]
    if p.get("mport"):
        q["mport"] = p["mport"]
    qs = f"?{urlencode(q)}" if q else ""
    return (f"hysteria2://{quote(p.get('password', ''), safe='')}"
            f"@{node['server']}:{node['port']}{qs}#{quote(node['tag'], safe='')}")


def encode_anytls(node: dict) -> str:
    p, tls = node["params"], _tls_of(node["params"])
    q = _tls_query(tls)
    qs = f"?{urlencode(q)}" if q else ""
    return (f"anytls://{quote(p.get('password', ''), safe='')}"
            f"@{node['server']}:{node['port']}{qs}#{quote(node['tag'], safe='')}")


def encode_wireguard(node: dict) -> str:
    p = node["params"]
    q: dict = {}
    if p.get("peer_public_key"):
        q["publickey"] = p["peer_public_key"]
    if p.get("pre_shared_key"):
        q["presharedkey"] = p["pre_shared_key"]
    addr = p.get("local_address")
    if addr:
        q["address"] = ",".join(addr) if isinstance(addr, list) else str(addr)
    if p.get("mtu") is not None:
        q["mtu"] = str(p["mtu"])
    qs = f"?{urlencode(q)}" if q else ""
    return (f"wireguard://{quote(p.get('private_key', ''), safe='')}"
            f"@{node['server']}:{node['port']}{qs}#{quote(node['tag'], safe='')}")


_ENCODERS = {
    "vmess": encode_vmess,
    "vless": encode_vless,
    "trojan": encode_trojan,
    "shadowsocks": encode_ss,
    "socks": encode_socks,
    "tuic": encode_tuic,
    "hysteria2": encode_hysteria2,
    "anytls": encode_anytls,
    "wireguard": encode_wireguard,
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
