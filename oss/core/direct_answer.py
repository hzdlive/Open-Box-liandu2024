"""Direct-answer release set manager.

Clean-room implementation of publicly observable behavior:
- IPs from direct DNS answers are written to nftables set BEFORE
  handing the answer to the device (approximate: panel-side async)
- TTL = DNS cache time, clamped 15min ~ 1 day
- Restart persistence: rebuild set on panel start from DB
- Clear on: direct→proxy/reject, routing changes
- Precise delete on: proxy→direct (only related entries)

Note: This is an approximate implementation. The original writes
from within the DNS path (Go core has a hook). We write async from
the panel after observing DNS answers via logs.
"""

from __future__ import annotations

import sqlite3
import time

# TTL bounds (1:1 with original)
MIN_TTL_S = 15 * 60  # 15 minutes
MAX_TTL_S = 24 * 3600  # 1 day


def clamp_ttl(ttl_s: int) -> int:
    """Clamp TTL to [15min, 1d] (1:1 with original)."""
    return max(MIN_TTL_S, min(MAX_TTL_S, ttl_s))


def add_direct_answer(conn: sqlite3.Connection, ip: str, source: str = "",
                      ttl_s: int = 3600) -> None:
    """Add an IP to the direct-answer release set.
    
    Args:
        ip: IPv4 address
        source: DNS domain that resolved to this IP
        ttl_s: TTL in seconds (will be clamped to 15min~1d)
    """
    ttl_s = clamp_ttl(ttl_s)
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.localtime(time.time() + ttl_s))
    conn.execute(
        "INSERT OR REPLACE INTO direct_answer_ips (ip, expires_at, source) VALUES (?, ?, ?)",
        (ip, expires_at, source))
    conn.commit()


def get_active_direct_answers(conn: sqlite3.Connection) -> list[dict]:
    """Get non-expired direct-answer IPs (for nftables set rebuild)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    # Clean expired first
    conn.execute("DELETE FROM direct_answer_ips WHERE expires_at <= ?", (now,))
    conn.commit()
    cur = conn.execute("SELECT ip, expires_at, source FROM direct_answer_ips")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def clear_direct_answers(conn: sqlite3.Connection) -> int:
    """Clear all direct-answer IPs (on direct→proxy/reject or routing change).
    
    Returns number of cleared entries.
    """
    cur = conn.execute("DELETE FROM direct_answer_ips")
    conn.commit()
    return cur.rowcount


def remove_direct_answers_for_domain(conn: sqlite3.Connection, domain: str) -> int:
    """Remove entries for a specific domain (on proxy→direct, precise delete).
    
    Returns number of removed entries.
    """
    cur = conn.execute("DELETE FROM direct_answer_ips WHERE source = ?", (domain,))
    conn.commit()
    return cur.rowcount
