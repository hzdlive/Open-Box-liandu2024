"""Parse subscription content into Node objects.

Supports base64-encoded subscription bodies as well as plain link lists.
Protocols: vmess, vless, trojan, shadowsocks, tuic, hysteria2/hy2.
Link formats follow the widely documented open conventions (SIP002 etc.).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from urllib.parse import parse_qsl, unquote, urlparse

from .models import Node


def _b64decode(s: str) -> bytes:
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def _maybe_b64_body(text: str) -> str:
    """If the whole body looks like base64 without '://', decode it."""
    t = text.strip()
    if "://" not in t and re.fullmatch(r"[A-Za-z0-9+/=_\-\s]+", t):
        try:
            return _b64decode(re.sub(r"\s+", "", t)).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            return text
    return text


def _unique_tag(base: str, seen: set) -> str:
    tag = base or "node"
    i, cand = 2, tag
    while cand in seen:
        cand = f"{tag} #{i}"
        i += 1
    seen.add(cand)
    return cand


def _hostport(host: str | None, port: int) -> str:
    """Tag fallback when a link carries no name (golden vless-no-tag):
    the panel uses host:port, not the protocol name."""
    return f"{host or 'node'}:{port}"


def _parse_vmess(link: str, seen: set) -> Node | None:
    try:
        data = json.loads(_b64decode(link[len("vmess://"):]).decode("utf-8"))
    except Exception:
        return None
    params: dict = {
        "uuid": data.get("id", ""),
        "alter_id": int(data.get("aid") or 0),
        "security": "auto",
    }
    net = (data.get("net") or "tcp").lower()
    if net == "h2":
        net = "http"
    elif net not in ("tcp", "ws", "grpc", "http"):
        return None
    transport: dict = {"type": net}
    if net == "ws":
        transport["path"] = data.get("path") or "/"
        if data.get("host"):
            transport["headers"] = {"Host": data["host"]}
    elif net == "grpc":
        transport["service_name"] = data.get("path") or ""
    params["transport"] = transport
    if str(data.get("tls", "")).lower() == "tls":
        params["tls"] = {"enabled": True, "server_name": data.get("sni") or data.get("host") or data.get("add")}
    try:
        port = int(data.get("port", 0))
    except (TypeError, ValueError):
        return None
    return Node(
        tag=_unique_tag(unquote(data.get("ps") or "") or _hostport(data.get("add"), port), seen),
        protocol="vmess", server=data.get("add", ""), server_port=port, params=params,
    )


def _parse_vless_trojan(link: str, seen: set) -> Node | None:
    proto = "vless" if link.startswith("vless://") else "trojan"
    u = urlparse(link)
    q = dict(parse_qsl(u.query))
    try:
        port = int(u.port or 0)
    except (TypeError, ValueError):
        return None
    params: dict = {}
    if proto == "vless":
        params["uuid"] = unquote(u.username or "")
        if q.get("flow"):
            params["flow"] = q["flow"]
    else:
        params["password"] = unquote(u.username or "")
    sec = q.get("security", "tls" if proto == "trojan" else "none").lower()
    if sec in ("tls", "reality"):
        tls: dict = {"enabled": True, "server_name": q.get("sni") or u.hostname}
        if q.get("alpn"):
            tls["alpn"] = q["alpn"].split(",")
        if q.get("fp"):
            tls["fingerprint"] = q["fp"]
        if q.get("allowInsecure") in ("1", "true"):
            tls["insecure"] = True
        if sec == "reality":
            # An enabled reality block with no public_key is rejected by
            # the panel (golden invalid-reality-no-pbk); the desktop
            # parser emits it unvalidated.
            if not q.get("pbk"):
                return None
            tls["reality"] = {
                "enabled": True,
                "public_key": q.get("pbk", ""),
                "short_id": q.get("sid", ""),
            }
        params["tls"] = tls
    # Transport allowlist (golden invalid-transport): sing-box has no kcp
    # transport for vless/trojan; h2 is the panel's alias for http.
    ttype = q.get("type", "tcp").lower()
    if ttype == "h2":
        ttype = "http"
    elif ttype not in ("tcp", "ws", "grpc", "http"):
        return None
    transport: dict = {"type": ttype}
    if ttype == "ws":
        transport["path"] = q.get("path") or "/"
        if q.get("host"):
            transport["headers"] = {"Host": q["host"]}
    elif ttype == "http":
        # h2 (and explicit http): same path/host shape as ws; the
        # generator passes path/headers through for any non-tcp type.
        if q.get("path"):
            transport["path"] = q["path"]
        if q.get("host"):
            transport["headers"] = {"Host": q["host"]}
    elif ttype == "grpc":
        transport["service_name"] = q.get("serviceName") or ""
    params["transport"] = transport
    return Node(
        tag=_unique_tag(unquote(u.fragment) or _hostport(u.hostname, port), seen),
        protocol=proto, server=u.hostname or "", server_port=port, params=params,
    )


def _parse_ss(link: str, seen: set) -> Node | None:
    # SIP002: ss://base64(method:password)@host:port?plugin=...#tag
    # or the legacy full-base64 form. The plugin table (golden
    # ss-plugin-*): obfs-local and its alias simple-obfs map to
    # obfs-local; v2ray-plugin passes through; anything else (kcptun)
    # rejects the link instead of silently dropping the plugin.
    _PLUGIN_TABLE = {"obfs-local": "obfs-local", "simple-obfs": "obfs-local",
                     "v2ray-plugin": "v2ray-plugin"}
    body = link[len("ss://"):]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    query = ""
    if "?" in body:
        body, query = body.split("?", 1)
    plugin = None
    plugin_opts = ""
    if query:
        q = dict(parse_qsl(query))
        raw = q.get("plugin", "")
        if raw:
            parts = unquote(raw).split(";")
            mapped = _PLUGIN_TABLE.get(parts[0].strip())
            if mapped is None:
                return None
            plugin, plugin_opts = mapped, ";".join(parts[1:])
    try:
        if "@" in body:  # ss://base64(method:password)@host:port
            userinfo_b64, hostport = body.rsplit("@", 1)
            method, password = _b64decode(userinfo_b64).decode("utf-8").split(":", 1)
        else:  # ss://base64(method:password@host:port[?plugin=...])
            decoded = _b64decode(body).decode("utf-8")
            if "?" in decoded:
                decoded, dquery = decoded.split("?", 1)
                dq = dict(parse_qsl(dquery))
                if dq.get("plugin") and plugin is None:
                    parts = unquote(dq["plugin"]).split(";")
                    mapped = _PLUGIN_TABLE.get(parts[0].strip())
                    if mapped is None:
                        return None
                    plugin, plugin_opts = mapped, ";".join(parts[1:])
            m = re.match(r"(.+?):(.+)@(.+):(\d+)", decoded)
            if not m:
                return None
            method, password, hostport = m.group(1), m.group(2), f"{m.group(3)}:{m.group(4)}"
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)
    except Exception:
        return None
    params = {"method": method, "password": password}
    if plugin:
        params["plugin"] = plugin
        if plugin_opts:
            params["plugin_opts"] = plugin_opts
    return Node(
        tag=_unique_tag(unquote(frag) or _hostport(host.strip("[]"), port), seen),
        protocol="shadowsocks", server=host.strip("[]"), server_port=port,
        params=params,
    )


def _parse_tuic_hysteria2(link: str, seen: set) -> Node | None:
    proto = "tuic" if link.startswith("tuic://") else "hysteria2"
    # Inline port range (golden hy2-inline-range): host:2000-3000 is
    # lifted out before parsing -- first port becomes server_port and
    # the range is kept as mport (the generator ignores unknown params,
    # same as the query-form mport the golden ignores).
    mport = None
    if proto == "hysteria2":
        m = re.match(r"^([a-z0-9+.-]+://[^?#]*?):(\d+)-(\d+)([?#].*)?$", link, re.I)
        if m:
            link = f"{m.group(1)}:{m.group(2)}{m.group(4) or ''}"
            mport = f"{m.group(2)}-{m.group(3)}"
    u = urlparse(link)
    q = dict(parse_qsl(u.query))
    try:
        port = int(u.port or 0)
    except (TypeError, ValueError):
        return None
    if proto == "tuic":
        params = {
            "uuid": unquote(u.username or ""),
            "password": unquote(u.password or ""),
            "congestion_control": q.get("congestion_control", "bbr"),
        }
    else:
        params = {"password": unquote(u.username or "")}
        if q.get("obfs"):
            params["obfs"] = {"type": q["obfs"], "password": q.get("obfs-password", "")}
        if mport:
            params["mport"] = mport
    tls: dict = {
        "enabled": True,
        "server_name": q.get("sni") or u.hostname,
        "insecure": q.get("insecure") in ("1", "true"),
    }
    if q.get("alpn"):
        tls["alpn"] = q["alpn"].split(",")
    params["tls"] = tls
    return Node(
        tag=_unique_tag(unquote(u.fragment) or _hostport(u.hostname, port), seen),
        protocol=proto, server=u.hostname or "", server_port=port, params=params,
    )


def _parse_anytls(link: str, seen: set) -> Node | None:
    # anytls://password@host:port/?sni=..&alpn=..&insecure=..&fp=..
    u = urlparse(link)
    q = dict(parse_qsl(u.query))
    try:
        port = int(u.port or 0)
    except (TypeError, ValueError):
        return None
    tls: dict = {"enabled": True, "server_name": q.get("sni") or u.hostname}
    if q.get("alpn"):
        tls["alpn"] = q["alpn"].split(",")
    if q.get("insecure") in ("1", "true"):
        tls["insecure"] = True
    if q.get("fp"):
        tls["fingerprint"] = q["fp"]
    return Node(
        tag=_unique_tag(unquote(u.fragment) or _hostport(u.hostname, port), seen),
        protocol="anytls", server=u.hostname or "", server_port=port,
        params={"password": unquote(u.username or ""), "tls": tls},
    )


def _parse_socks(link: str, seen: set) -> Node | None:
    # socks5://user:pass@host:port | socks5://host:port (anon)
    # | socks4a://host:port | socks4://host:port | socks://host:port
    # (generic defaults to version 5, per the golden's socks-generic case).
    scheme = link.split("://", 1)[0].lower()
    version = {"socks5": "5", "socks": "5", "socks4": "4", "socks4a": "4a"}.get(scheme)
    if version is None:
        return None
    u = urlparse(link)
    q = dict(parse_qsl(u.query))
    try:
        port = int(u.port or 0)
    except (TypeError, ValueError):
        return None
    params: dict = {"version": version}
    if u.username is not None:
        params["username"] = unquote(u.username)
    if u.password is not None:
        params["password"] = unquote(u.password)
    return Node(
        tag=_unique_tag(unquote(u.fragment) or _hostport(u.hostname, port), seen),
        protocol="socks", server=u.hostname or "", server_port=port,
        params=params,
    )


def looks_like_singbox_json(text: str) -> bool:
    """Detect sing-box JSON config (has outbounds array)."""
    head = text.lstrip()[:500]
    if not head.startswith("{"):
        return False
    try:
        import json
        d = json.loads(text[:50000])
        return isinstance(d.get("outbounds"), list)
    except Exception:
        return False


def parse_singbox_json(text: str) -> list[Node]:
    """Parse sing-box JSON config outbounds into Nodes. Skips selector/urltest/direct/block."""
    import json
    try:
        d = json.loads(text)
    except Exception:
        return []
    nodes: list[Node] = []
    seen: set = set()
    skip_types = {"selector", "urltest", "direct", "block", "dns", "wireguard"}
    # wireguard 需要私钥等复杂配置，暂跳过
    for ob in d.get("outbounds", []):
        if not isinstance(ob, dict):
            continue
        t = str(ob.get("type", "")).lower()
        if t in skip_types or not t:
            continue
        tag = str(ob.get("tag", "") or t)
        server = str(ob.get("server", "") or "")
        try:
            port = int(ob.get("server_port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not server or not 1 <= port <= 65535:
            continue
        # 协议名映射到内部协议
        proto_map = {
            "vless": "vless", "vmess": "vmess", "trojan": "trojan",
            "shadowsocks": "shadowsocks", "ss": "shadowsocks",
            "tuic": "tuic", "hysteria2": "hysteria2", "hy2": "hysteria2",
            "anytls": "anytls", "socks": "socks", "http": "http",
        }
        protocol = proto_map.get(t, t)
        # 提取 params（保留原始 outbound 字段供配置生成用）
        params = {k: v for k, v in ob.items() if k not in ("type", "tag", "server", "server_port")}
        node = Node(
            tag=_unique_tag(tag, seen),
            protocol=protocol, server=server, server_port=port,
            params=params,
        )
        nodes.append(node)
    return nodes


# 订阅信息节点（非真实节点）的名称特征，1:1 过滤
# 订阅商常把流量/到期信息做成假节点，名称如"剩余流量：1012.99 GB"
_INFO_NODE_PATTERNS = (
    "剩余流量", "距离下次重置", "套餐到期", "流量", "到期时间",
    "剩余", "已用流量", "总流量",
)


def is_info_node(name: str) -> bool:
    """Check if a node name is subscription metadata, not a real node."""
    if not name:
        return False
    return any(p in name for p in _INFO_NODE_PATTERNS)


def parse_subscription(text: str) -> list[Node]:
    """Parse subscription text into a list of Nodes. Unknown lines are skipped."""
    # sing-box JSON 配置
    if looks_like_singbox_json(text):
        nodes = parse_singbox_json(text)
        return [n for n in nodes if not is_info_node(getattr(n, "tag", ""))]
    nodes: list[Node] = []
    seen: set = set()
    for raw in _maybe_b64_body(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        node = None
        try:
            if line.startswith("vmess://"):
                node = _parse_vmess(line, seen)
            elif line.startswith(("vless://", "trojan://")):
                node = _parse_vless_trojan(line, seen)
            elif line.startswith("ss://"):
                node = _parse_ss(line, seen)
            elif line.startswith(("tuic://", "hysteria2://", "hy2://")):
                node = _parse_tuic_hysteria2(line, seen)
            elif line.startswith("anytls://"):
                node = _parse_anytls(line, seen)
            elif line.startswith(("socks5://", "socks4a://", "socks4://", "socks://")):
                node = _parse_socks(line, seen)
        except Exception:
            node = None
        # Port range is validated here, centrally: urlparse already
        # rejects out-of-range ports for URL links, but vmess (JSON int)
        # and ss (split int) do not -- sing-box would reject them later.
        if node and node.server and 1 <= node.server_port <= 65535:
            # 过滤订阅信息假节点
            if is_info_node(getattr(node, "tag", "")):
                continue
            nodes.append(node)
    return nodes
