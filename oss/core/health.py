"""Basic node connectivity checks: TCP connect + TLS handshake latency.

This is a lightweight reachability signal, NOT a full URL test
(no HTTP request is made) for TCP protocols. UDP-only protocols that
exist as kernel outbounds (tuic, hysteria2) cannot be TCP-probed, so
they are measured through the kernel's clash delay API instead -- a
real request through the outbound. Wireguard has no kernel outbound
(it is generated as endpoints), so it is still reported as skipped
rather than failed.
"""

from __future__ import annotations

import socket
import ssl
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from core import clashapi

TCP_PROTOCOLS = {"vmess", "vless", "trojan", "shadowsocks", "socks", "socks5", "http", "https", "anytls"}

# UDP protocols measurable through the kernel's clash delay API.
KERNEL_TESTABLE = {"tuic", "hysteria2"}

DEFAULT_TEST_URL = "http://www.gstatic.com/generate_204"


@dataclass
class HealthResult:
    tag: str
    ok: bool | None  # None = skipped (protocol not testable)
    latency_ms: float | None
    error: str
    checked_at: str


def kernel_delay(tag: str, timeout_s: float, test_url: str):
    """Measure one UDP-only outbound via the kernel's clash delay API.

    Returns (ok, latency_ms, error). A definitive delay failure
    (timeout / HTTP error body) maps to ok=False. If the kernel itself
    cannot be reached, returns ok=None (skipped) so a down kernel does
    not mark working nodes as failed.
    """
    ms = max(1, int(timeout_s * 1000))
    path = (f"/proxies/{urllib.parse.quote(tag, safe='')}/delay"
            f"?url={urllib.parse.quote(test_url, safe='')}&timeout={ms}")
    ok, data = clashapi.clash_get(path, timeout=timeout_s + 2.0)
    if ok and isinstance(data, dict) and isinstance(data.get("delay"), (int, float)):
        return True, float(data["delay"]), ""
    if isinstance(data, dict):
        err = str(data.get("error") or "")
        msg = str(data.get("message") or "")
        if "Connection refused" in err or "Name or service not known" in err:
            return None, None, "kernel unreachable, skipped"
        if msg or err:
            return False, None, f"kernel delay: {msg or err}"
    return False, None, "kernel delay: unknown error"


def check_node(node, timeout: float = 5.0,
               test_url: str = DEFAULT_TEST_URL,
               kernel_delay_fn=None) -> HealthResult:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if node.protocol in KERNEL_TESTABLE:
        fn = kernel_delay_fn or kernel_delay
        ok, latency, error = fn(node.tag, timeout, test_url)
        return HealthResult(node.tag, ok, latency, error, now)
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


def check_nodes(nodes, timeout: float = 5.0, max_workers: int = 20,
                test_url: str | None = None, kernel_delay_fn=None) -> list[HealthResult]:
    url = test_url or DEFAULT_TEST_URL
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(
            lambda n: check_node(n, timeout, url, kernel_delay_fn), nodes))
