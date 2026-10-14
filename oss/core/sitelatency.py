"""Site latency cards: HEAD a URL twice through the kernel's loopback
mixed inbound (HTTP proxy) and report the round trip.

Falls back to a direct connection when the kernel is not running; the
result is labelled accordingly so the UI never misattributes it.
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.request


def _head_once(url: str, proxy: str | None, timeout: float) -> float:
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "openbox-oss/1.0"})
    t0 = time.monotonic()
    with opener.open(req, timeout=timeout) as r:
        r.read(0)
    return (time.monotonic() - t0) * 1000


def check_site(url: str, proxy: str | None = None,
               timeout: float = 8.0) -> dict:
    """Two HEADs; returns {ok, latency_ms, via}."""
    latencies = []
    for _ in range(2):
        try:
            latencies.append(_head_once(url, proxy, timeout))
        except Exception as e:
            return {"ok": False, "latency_ms": None,
                    "via": "proxy" if proxy else "direct",
                    "error": str(e)[:120]}
    ms = sum(latencies) / len(latencies)
    return {"ok": True, "latency_ms": round(ms, 1),
            "via": "proxy" if proxy else "direct"}
