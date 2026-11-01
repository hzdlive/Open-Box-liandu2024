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


def parse_status_pattern(pattern):
    """Parse a test_expected pattern into a status predicate.

    "" or "*" -> any status. Otherwise comma-separated codes ("200,204")
    and ranges ("200-299"). Raises ValueError on an invalid token.
    """
    p = (pattern or "").strip()
    if p in ("", "*"):
        return lambda status: True
    allowed = set()
    ranges = []
    for tok in p.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, b = tok.split("-", 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise ValueError(f"invalid status pattern token: {tok!r}")
            if not (100 <= lo <= hi <= 599):
                raise ValueError(f"invalid status range: {tok!r}")
            ranges.append((lo, hi))
        else:
            try:
                code = int(tok)
            except ValueError:
                raise ValueError(f"invalid status pattern token: {tok!r}")
            if not (100 <= code <= 599):
                raise ValueError(f"invalid status code: {tok!r}")
            allowed.add(code)
    if not allowed and not ranges:
        raise ValueError(f"empty status pattern: {pattern!r}")

    def _match(status):
        if status is None:
            return False
        if status in allowed:
            return True
        return any(lo <= status <= hi for lo, hi in ranges)

    return _match


def direct_test(url, expected_pattern, timeout: float = 8.0) -> dict:
    """Panel-side direct fetch (no proxy) judged by a status pattern.

    Returns {ok, status, latency_ms, via: "direct", error?}. An invalid
    pattern falls back to unlimited with a warning (the stored pattern
    must never break the test; body-provided patterns are validated
    by the caller instead).
    """
    import time as _time
    import urllib.request as _url
    try:
        match = parse_status_pattern(expected_pattern)
        warning = None
    except ValueError:
        match = lambda status: True  # noqa: E731
        warning = (f"invalid status pattern {expected_pattern!r}, "
                   "treated as unlimited")
    opener = _url.build_opener(_url.ProxyHandler({}))
    started = _time.monotonic()
    try:
        req = _url.Request(url, headers={
            "User-Agent": "openbox-oss-direct-test/1.0"})
        with opener.open(req, timeout=timeout) as resp:
            resp.read(65536)
            status = resp.status
        ms = round((_time.monotonic() - started) * 1000, 1)
        out = {"ok": bool(match(status)), "status": status,
               "latency_ms": ms, "via": "direct"}
    except Exception as e:
        out = {"ok": False, "status": None, "latency_ms": None,
               "via": "direct", "error": str(e)[:200]}
    if warning:
        out["warning"] = warning
    return out
