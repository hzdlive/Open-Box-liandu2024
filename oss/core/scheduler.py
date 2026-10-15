"""Background scheduler for periodic panel jobs.

Runs as a daemon thread inside the Flask process:
- subscription auto-update (per-subscription interval in hours)
- DNS filter list auto-update (daily at a configured time)

Jobs are best-effort and never raise out of the loop. The thread is started
once per panel process via start_scheduler().
"""

from __future__ import annotations

import sqlite3
import threading
import time
import traceback

_started = False
_lock = threading.Lock()


def _open_db(dsn: str, uri: bool) -> sqlite3.Connection:
    c = sqlite3.connect(dsn, uri=uri, timeout=30)
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _due_subscriptions(conn: sqlite3.Connection) -> list[int]:
    now = time.time()
    out = []
    for sid, auh, updated in conn.execute(
            "SELECT id, auto_update_hours, updated_at FROM subscriptions"
            " WHERE enabled=1 AND url IS NOT NULL AND url != ''"
            " AND auto_update_hours > 0"):
        due = True
        if updated:
            try:
                ts = time.mktime(time.strptime(updated, "%Y-%m-%dT%H:%M:%S"))
                due = (now - ts) >= auh * 3600
            except ValueError:
                due = True
        if due:
            out.append(sid)
    return out


def _tick(dsn: str, uri: bool) -> None:
    from panel import db as dbmod
    conn = _open_db(dsn, uri)
    try:
        for sid in _due_subscriptions(conn):
            try:
                dbmod.refresh_subscription(conn, sid)
                print(f"[scheduler] auto-updated subscription {sid}", flush=True)
            except Exception as e:
                print(f"[scheduler] subscription {sid} update failed: {e}", flush=True)
        _maybe_update_dns_filter(conn)
        _maybe_panel_self_update(conn)
    except Exception:
        traceback.print_exc()
    finally:
        conn.close()


def _maybe_update_dns_filter(conn: sqlite3.Connection) -> None:
    """Daily DNS filter list refresh at the configured time (default 04:00)."""
    from panel.db import get_setting
    if get_setting(conn, "dns_filter_enabled", "0") != "1":
        return
    if get_setting(conn, "dns_filter_auto_update", "0") != "1":
        return
    at = get_setting(conn, "dns_filter_update_time", "04:00")
    try:
        hh, mm = at.split(":")
        hh, mm = int(hh), int(mm)
    except ValueError:
        return
    now = time.localtime()
    # run once per day: only within the first check window after the time
    last = get_setting(conn, "dns_filter_auto_updated_at", "")
    today = time.strftime("%Y-%m-%d")
    if last == today:
        return
    if (now.tm_hour, now.tm_min) < (hh, mm):
        return
    try:
        from core import dnsfilter as _df
        from core.service import manager_from_env
        from panel.db import set_setting
        import json as _json
        lists = _json.loads(get_setting(conn, "dns_filter_lists", "[]"))
        result = _df.apply_lists(manager_from_env().workdir, lists)
        set_setting(conn, "dns_filter_applied_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
        set_setting(conn, "dns_filter_auto_updated_at", today)
        conn.commit()
        print(f"[scheduler] dns filter auto-updated: {result}", flush=True)
    except Exception as e:
        print(f"[scheduler] dns filter update failed: {e}", flush=True)


def _maybe_panel_self_update(conn: sqlite3.Connection) -> None:
    """Scheduled panel self-update check (update_auto=1).

    Runs at most once per update_days, at/after update_hour. On an available
    update with update_auto enabled, the check is followed by a detached
    fast-forward pull + panel restart.
    """
    from panel.db import get_setting
    from core import selfupdate as _su
    if get_setting(conn, "update_auto", "0") != "1":
        return
    if not _su.due_for_check(conn):
        return
    try:
        result = _su.check_for_update(conn)
        print(f"[scheduler] panel update check: {result}", flush=True)
        if result.get("available"):
            ref = result.get("ref") or "refs/heads/oss"
            logf = _su.apply_update_async(ref)
            print(f"[scheduler] panel update applying, log: {logf}", flush=True)
    except Exception as e:
        print(f"[scheduler] panel self-update failed: {e}", flush=True)


def _loop(dsn: str, uri: bool, interval: float = 60.0) -> None:
    while True:
        time.sleep(interval)
        try:
            _tick(dsn, uri)
        except Exception:
            traceback.print_exc()


def start_scheduler(dsn: str, uri: bool) -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, args=(dsn, uri), daemon=True,
                         name="openbox-scheduler")
    t.start()
