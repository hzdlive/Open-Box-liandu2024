"""Minimal client for sing-box's clash API (public, documented endpoints).

Used by the panel for: live connections, closing a connection, reading
selector state / switching selectors (hot-switch, failover election),
and per-proxy traffic. All calls fail soft (ok=False) when the kernel
isn't running.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


def api_base(port: int | None = None) -> str:
    p = port or int(os.environ.get("OBX_CLASH_PORT", "9090"))
    return f"http://127.0.0.1:{p}"


def _req(base: str, secret: str, method: str, path: str,
         body: dict | None = None, timeout: float = 5.0):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if secret:
        req.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return True, (json.loads(raw) if raw else None)
            except ValueError:
                return True, raw
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode("utf-8", "replace") or "{}")
        except ValueError:
            return False, {"error": f"HTTP {e.code}"}
    except Exception as e:  # kernel down / refused
        return False, {"error": str(e)}


def clash_get(path: str, port: int | None = None, secret: str = "",
              timeout: float = 5.0) -> tuple[bool, object]:
    return _req(api_base(port), secret, "GET", path, None, timeout)


def clash_put(path: str, body: dict, port: int | None = None, secret: str = "",
              timeout: float = 5.0) -> tuple[bool, object]:
    return _req(api_base(port), secret, "PUT", path, body, timeout)


def clash_delete(path: str, port: int | None = None, secret: str = "",
                 timeout: float = 5.0) -> tuple[bool, object]:
    return _req(api_base(port), secret, "DELETE", path, None, timeout)


def list_connections(port: int | None = None) -> tuple[bool, list]:
    ok, data = clash_get("/connections", port)
    if not ok or not isinstance(data, dict):
        return False, []
    return True, data.get("connections", []) or []


def close_connection(conn_id: str, port: int | None = None) -> tuple[bool, object]:
    return clash_delete(f"/connections/{conn_id}", port)


def get_proxies(port: int | None = None) -> tuple[bool, dict]:
    ok, data = clash_get("/proxies", port)
    return (ok, data) if ok and isinstance(data, dict) else (False, {})


def switch_selector(selector: str, target: str,
                    port: int | None = None) -> tuple[bool, object]:
    """Switch a selector's active outbound without restarting the kernel."""
    from urllib.parse import quote
    return clash_put(f"/proxies/{quote(selector, safe='')}", {"name": target}, port)
