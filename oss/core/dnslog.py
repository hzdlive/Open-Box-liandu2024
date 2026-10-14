"""dnsmasq query-log parsing + DHCP hostname enrichment.

dnsmasq must run with ``log-queries`` (log to OBX_DNSMASQ_LOG, default
/var/log/dnsmasq.log). Lines look like::

    Oct 14 15:30:01 dnsmasq[1234]: query[A] example.com from 192.168.1.10

On OpenWrt the same lines appear in ``logread`` output.
"""

from __future__ import annotations

import os
import re

_QUERY_RE = re.compile(
    r"query\[([A-Z]+)\]\s+(\S+)\s+from\s+(\d+\.\d+\.\d+\.\d+)")


def parse_dnsmasq_log(path: str, n: int = 200) -> tuple[list[dict], str]:
    """Returns (queries, note). queries newest-first."""
    if not path or not os.path.isfile(path):
        return [], "未找到 dnsmasq 查询日志（需开启 log-queries 并设置 OBX_DNSMASQ_LOG）"
    try:
        with open(path, "rb") as f:
            data = f.read().splitlines()[-max(n * 3, 200):]
    except OSError as e:
        return [], f"读取失败：{e}"
    out = []
    for raw in reversed(data):
        line = raw.decode("utf-8", "replace")
        m = _QUERY_RE.search(line)
        if m:
            out.append({"qtype": m.group(1), "domain": m.group(2),
                        "client": m.group(3)})
            if len(out) >= n:
                break
    return out, ""


def dhcp_hostnames(leases_path: str | None = None) -> dict[str, str]:
    """Parse OpenWrt /tmp/dhcp.leases (expiry mac ip hostname)."""
    path = leases_path or os.environ.get("OBX_DHCP_LEASES", "/tmp/dhcp.leases")
    hosts: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[3] != "*":
                    hosts[parts[2]] = parts[3]
    except OSError:
        pass
    return hosts


def enrich(queries: list[dict], blocklist: set[str] | None = None,
           leases_path: str | None = None) -> list[dict]:
    from core.dnsfilter import match_domain
    hostnames = dhcp_hostnames(leases_path)
    for q in queries:
        q["hostname"] = hostnames.get(q["client"], "")
        q["blocked"] = bool(blocklist and match_domain(q["domain"], blocklist))
    return queries
