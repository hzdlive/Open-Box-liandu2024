"""dnsmasq query-log parsing + DHCP hostname enrichment.

dnsmasq must run with ``log-queries`` (log to OBX_DNSMASQ_LOG, default
/var/log/dnsmasq.log). Lines look like::

    Oct 14 15:30:01 dnsmasq[1234]: query[A] example.com from 192.168.1.10
    Oct 14 15:30:01 dnsmasq[1234]: cached example.com is 1.2.3.4
    Oct 14 15:30:01 dnsmasq[1234]: reply example.com is 1.2.3.4
    Oct 14 15:30:01 dnsmasq[1234]: forwarded example.com to 8.8.8.8

Cache hits are marked so the UI can distinguish them (1:1 with original:
cached responses must also appear in the log).

On OpenWrt the same lines appear in ``logread`` output.
"""

from __future__ import annotations

import os
import re

_QUERY_RE = re.compile(
    r"query\[([A-Z]+)\]\s+(\S+)\s+from\s+(\d+\.\d+\.\d+\.\d+)")
_CACHED_RE = re.compile(r"cached\s+(\S+)\s+is\s+(\S+)")
_REPLY_RE = re.compile(r"reply\s+(\S+)\s+is\s+(\S+)")
_FORWARDED_RE = re.compile(r"forwarded\s+(\S+)\s+to\s+(\S+)")


def parse_dnsmasq_log(path: str, n: int = 200) -> tuple[list[dict], str]:
    """Returns (queries, note). queries newest-first.

    Each query dict has: qtype, domain, client, cached (bool), answer (str).
    Cached hits are explicitly marked.
    """
    if not path or not os.path.isfile(path):
        return [], "未找到 dnsmasq 查询日志（需开启 log-queries 并设置 OBX_DNSMASQ_LOG）"
    try:
        with open(path, "rb") as f:
            data = f.read().splitlines()[-max(n * 5, 500):]
    except OSError as e:
        return [], f"读取失败：{e}"
    # Two-pass: first collect all query events with their positions,
    # then match cached/reply lines that follow each query.
    # dnsmasq logs: query -> [cached|reply|forwarded]
    lines = [raw.decode("utf-8", "replace") for raw in data]
    # Pass 1: find all queries with their line indices
    query_events = []  # (line_idx, qtype, domain, client)
    for idx, line in enumerate(lines):
        m = _QUERY_RE.search(line)
        if m:
            query_events.append((idx, m.group(1), m.group(2), m.group(3)))
    # Pass 2: for each query, look ahead for cached/reply
    queries = []
    for q_idx, qtype, domain, client in query_events:
        cached = False
        answer = ""
        # Look at next few lines for the answer
        for j in range(q_idx + 1, min(q_idx + 5, len(lines))):
            line = lines[j]
            # Stop if we hit another query
            if _QUERY_RE.search(line):
                break
            m = _CACHED_RE.search(line)
            if m and m.group(1) == domain:
                cached = True
                answer = m.group(2)
                break
            m = _REPLY_RE.search(line)
            if m and m.group(1) == domain:
                cached = False
                answer = m.group(2)
                break
        queries.append({
            "qtype": qtype,
            "domain": domain,
            "client": client,
            "cached": cached,
            "answer": answer,
        })
    # Return newest-first, limited to n
    queries.reverse()
    return queries[:n], ""


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
