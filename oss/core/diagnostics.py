"""Diagnostic bundle export (desensitized).

Mirrors the publicly observable behavior of a "one-click diagnostics"
feature: versions, platform, memory, kernel state, configuration
*summary* (counts only, never secrets), deploy state and log tails —
as one JSON document suitable for bug reports.

Desensitization rules (hard):
- never include passwords, tokens, or their hashes;
- never include node server addresses / ports / credentials;
- subscription URLs are reduced to their host only.
"""

from __future__ import annotations

import datetime
import os
import platform as _platform
import sqlite3
import sys
import time
from urllib.parse import urlparse

from core.service import (
    PANEL_VERSION,
    detect_autostart,
    detect_platform,
    os_pretty_name,
)


def _meminfo() -> dict:
    info: dict = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition(":")
                k = k.strip()
                if k in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    num = v.strip().split()[0]
                    info[k] = int(num) * 1024  # kB -> bytes
    except (OSError, ValueError):
        pass
    return info


def _table_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        return None


def _setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    except sqlite3.Error:
        return default


def _tail(path: str | None, n: int = 100) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            step, data = 8192, b""
            while len(data.splitlines()) <= n and size > 0:
                step = min(step, size)
                size -= step
                f.seek(size)
                data = f.read() + data
        return [l.decode("utf-8", "replace") for l in data.splitlines()[-n:]]
    except OSError:
        return []


def _sub_hosts(conn: sqlite3.Connection) -> list[str]:
    """Subscription URL hosts only — never the full URL (may embed tokens)."""
    hosts = []
    try:
        for (url,) in conn.execute(
                "SELECT url FROM subscriptions WHERE url IS NOT NULL"):
            try:
                h = urlparse(url).hostname
                if h:
                    hosts.append(h)
            except ValueError:
                pass
    except sqlite3.Error:
        pass
    return sorted(set(hosts))


def collect(conn: sqlite3.Connection, manager) -> dict:
    """Build the desensitized diagnostic bundle."""
    svc = manager.to_dict()
    state_rev = _setting(conn, "state_rev", "0")
    applied_rev = _setting(conn, "applied_rev", "")
    return {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "panel": {
            "version": PANEL_VERSION,
            "python": _platform.python_version(),
        },
        "system": {
            "platform": detect_platform(),
            "arch": _platform.machine(),
            "os": os_pretty_name(),
            "memory": _meminfo(),
        },
        "kernel": {
            "installed": svc["installed"],
            "running": svc["running"],
            "version": svc["version"],
            "uptime_s": svc["uptime_s"],
            "bin_path": svc["bin_path"],
            "autostart": svc["autostart"],
        },
        "config_summary": {
            "subscriptions": _table_count(conn, "subscriptions"),
            "nodes": _table_count(conn, "nodes"),
            "site_sets": _table_count(conn, "site_sets"),
            "groups": _table_count(conn, "groups"),
            "chains": _table_count(conn, "chains"),
            "rulesets": _table_count(conn, "rulesets"),
            "terminals": _table_count(conn, "terminal_policies"),
            "dns_rewrites": _table_count(conn, "dns_rewrite"),
            "subscription_hosts": _sub_hosts(conn),
            "tun_stack": _setting(conn, "tun_stack"),
            "tun_mtu": _setting(conn, "tun_mtu"),
            "quic_block": _setting(conn, "quic_block"),
            "dns_mode": _setting(conn, "dns_mode"),
        },
        "deploy": {
            "state_rev": state_rev,
            "applied_rev": applied_rev or None,
            "config_stale": (applied_rev != "" and applied_rev != state_rev),
        },
        "logs": {
            "sing_box": _tail(manager.log_path, 120),
        },
    }
