"""Basic node connectivity checks: TCP connect + TLS handshake latency.

This is a lightweight reachability signal, NOT a full URL test
(no HTTP request is made). UDP-only protocols (tuic, hysteria2, wireguard)
are reported as skipped rather than failed.
"""

from __future__ import annotations

import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

TCP_PROTOCOLS = {"vmess", "vless", "trojan", "shadowsocks", "socks", "socks5", "http", "https", "anytls"}


@dataclass
class HealthResult:
    tag: str
    ok: bool | None  # None = skipped (protocol not TCP-testable)
    latency_ms: float | None
    error: str
    checked_at: str


def check_node(node, timeout: float = 5.0) -> HealthResult:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if node.protocol not in TCP_PROTOCOLS:
        return HealthResult(node.tag, None, None,
                            f"udp-only protocol ({node.protocol}), skipped", now)
    start = time.monotonic()
    try:
        sock = socket.create_connection((node.server, node.server_port), timeout=timeout)
    except Exception as e:
        return HealthResult(node.tag, False, None, f"tcp: {e.__class__.__name__}: {e}", now)
    try:
        tls = node.params.get("tls") or {}
        if tls.get("enabled"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=tls.get("server_name") or node.server)
            sock.do_handshake()
        latency = round((time.monotonic() - start) * 1000, 1)
        return HealthResult(node.tag, True, latency, "", now)
    except Exception as e:
        return HealthResult(node.tag, False, None, f"tls: {e.__class__.__name__}: {e}", now)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def check_nodes(nodes, timeout: float = 5.0, max_workers: int = 20) -> list[HealthResult]:
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(lambda n: check_node(n, timeout), nodes))
