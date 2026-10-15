"""DNS upstream test + trace. Minimal dependency-free DNS client.

Supports udp://, tcp://, tls:// (853), https:// (DoH, RFC 8484) and bare
IPs (UDP/53). Measures round-trip latency for one A query.
"""

from __future__ import annotations

import base64
import os
import socket
import ssl
import struct
import time
import urllib.parse
import urllib.request


def _build_query(domain: str, qid: int = 0x1234) -> bytes:
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode()
                     for p in domain.strip(".").split(".")) + b"\x00"
    return header + qname + struct.pack(">HH", 1, 1)  # A IN


def _parse_answers(resp: bytes) -> int:
    if len(resp) < 12:
        return 0
    qd, an = struct.unpack(">HH", resp[4:8])
    off = 12
    for _ in range(qd):  # skip questions
        while off < len(resp) and resp[off] != 0:
            off += 1 + resp[off]
        off += 5
    return an


def _split_upstream(upstream: str) -> tuple[str, str, int, str]:
    """-> (scheme, host, port, path)."""
    u = upstream.strip()
    if "://" not in u:
        return "udp", u, 53, ""
    p = urllib.parse.urlparse(u)
    scheme = p.scheme.lower()
    host = p.hostname or ""
    port = p.port or {"udp": 53, "tcp": 53, "tls": 853, "https": 443,
                      "http": 80}.get(scheme, 53)
    path = p.path if scheme not in ("https", "http") else (p.path or "/dns-query")
    return scheme, host, port, path


def _query_udp_tcp(host: str, port: int, packet: bytes,
                   use_tcp: bool, timeout: float) -> bytes:
    if use_tcp:
        s = socket.create_connection((host, port), timeout=timeout)
        with s:
            s.sendall(struct.pack(">H", len(packet)) + packet)
            ln = struct.unpack(">H", _recvall(s, 2))[0]
            return _recvall(s, ln)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    with s:
        s.sendto(packet, (host, port))
        return s.recv(4096)


def _recvall(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _query_tls(host: str, port: int, packet: bytes, timeout: float) -> bytes:
    ctx = ssl.create_default_context()
    raw = socket.create_connection((host, port), timeout=timeout)
    with ctx.wrap_socket(raw, server_hostname=host) as s:
        s.settimeout(timeout)
        s.sendall(struct.pack(">H", len(packet)) + packet)
        ln = struct.unpack(">H", _recvall(s, 2))[0]
        return _recvall(s, ln)


def _query_doh(url: str, packet: bytes, timeout: float) -> bytes:
    body = base64.urlsafe_b64encode(packet).rstrip(b"=").decode()
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + "dns=" + body,
                                 headers={"Accept": "application/dns-message",
                                          "User-Agent": "openbox-oss/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def test_upstream(upstream: str, domain: str = "www.google.com",
                  timeout: float = 5.0) -> dict:
    """Run one A query through *upstream*. Returns a result dict."""
    scheme, host, port, path = _split_upstream(upstream)
    packet = _build_query(domain)
    t0 = time.monotonic()
    try:
        if scheme in ("udp", ""):
            resp = _query_udp_tcp(host, port, packet, False, timeout)
        elif scheme == "tcp":
            resp = _query_udp_tcp(host, port, packet, True, timeout)
        elif scheme == "tls":
            resp = _query_tls(host, port, packet, timeout)
        elif scheme in ("https", "http"):
            url = f"{scheme}://{host}:{port}{path}"
            resp = _query_doh(url, packet, timeout)
        else:
            return {"upstream": upstream, "ok": False,
                    "error": f"不支持的协议: {scheme}"}
        ms = (time.monotonic() - t0) * 1000
        return {"upstream": upstream, "ok": True,
                "latency_ms": round(ms, 1),
                "answers": _parse_answers(resp),
                "via": "direct", "domain": domain}
    except Exception as e:
        return {"upstream": upstream, "ok": False,
                "error": str(e)[:160], "via": "direct", "domain": domain}


def system_upstreams() -> list[str]:
    """System/WAN DNS servers (the box's current upstream DNS).

    OpenWrt: the wan interface's DHCP-provided servers first; generic Linux:
    /etc/resolv.conf. Localhost entries are filtered out to avoid loops.
    """
    import re as _re
    for path in ("/tmp/resolv.conf.d/resolv.conf.auto", "/etc/resolv.conf"):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        servers = _re.findall(r"^\s*nameserver\s+(\S+)", text, _re.M)
        servers = [s for s in servers
                   if not s.startswith(("127.", "0.0.0.0", "::1", "fe80:"))]
        if servers:
            return servers
    return []


def trace(domain: str, direct_upstream: str, proxy_upstream: str,
          route: str = "direct", timeout: float = 5.0) -> dict:
    """Trace which upstream a domain would use and time it.

    *route* is the panel's routing decision for the domain
    (direct|proxy); the query itself always goes out directly from the
    panel (honest 'via' labelling — kernel-side proxy DNS needs the
    kernel's DNS inbound, see /api/dns/trace docs).
    """
    upstream = proxy_upstream if route == "proxy" else direct_upstream
    r = test_upstream(upstream, domain, timeout=timeout)
    r["route"] = route
    return r
