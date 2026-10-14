"""Daily traffic accounting collector.

Polls the kernel's clash API (/connections), attributes each connection's
cumulative upload/download to (day, client IP, proxy, host), and stores
deltas in the panel DB (traffic_daily). Run as a background thread next to
the panel (see panel/run.py); it exits silently when the kernel is down.
"""

from __future__ import annotations

import sqlite3
import threading
import time

from . import clashapi as clashmod


def _snapshot(port: int | None) -> list[dict]:
    ok, conns = clashmod.list_connections(port)
    return conns if ok else []


def collect_once(db_path: str, port: int | None = None,
                 state: dict | None = None) -> int:
    """One poll cycle. Returns number of connections accounted."""
    state = state if state is not None else {}
    conns = _snapshot(port)
    if not conns:
        return 0
    day = time.strftime("%Y-%m-%d")
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        from panel import db as dbmod
        for c in conns:
            cid = str(c.get("id", ""))
            up, down = int(c.get("upload", 0)), int(c.get("download", 0))
            prev_up, prev_down = state.get(cid, (0, 0))
            # counters reset (kernel restart) -> treat current as delta
            d_up = up - prev_up if up >= prev_up else up
            d_down = down - prev_down if down >= prev_down else down
            state[cid] = (up, down)
            if d_up <= 0 and d_down <= 0:
                continue
            meta = c.get("metadata", {}) or {}
            chains = c.get("chains", []) or []
            dbmod.record_traffic(
                conn, day,
                client=str(meta.get("sourceIP", "")),
                proxy=str(chains[-1] if chains else ""),
                host=str(meta.get("host", "") or meta.get("destinationIP", "")),
                up=d_up, down=d_down)
    finally:
        conn.close()
    # drop state for connections that vanished
    alive = {str(c.get("id", "")) for c in conns}
    for cid in [k for k in state if k not in alive]:
        del state[cid]
    return len(conns)


def watch_loop(db_path: str, port: int | None = None,
               interval: float = 60.0,
               stop: threading.Event | None = None) -> None:
    state: dict = {}
    while True:
        if stop is not None and stop.is_set():
            return
        try:
            collect_once(db_path, port, state)
        except Exception:
            pass
        if stop is not None and stop.wait(interval):
            return
        time.sleep(interval)
