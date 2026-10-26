"""Background scheduler for periodic panel jobs.

Runs as a daemon thread inside the Flask process:
- subscription auto-update (per-subscription: every N days at H:00)
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
    try:
        c.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return c


def _due_subscriptions(conn: sqlite3.Connection) -> list[int]:
    # 1:1 with the original panel: each subscription refreshes every N days
    # at H:00 (auto_update {enabled, days, hour}).
    now = time.time()
    now_lt = time.localtime(now)
    out = []
    cols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)")}
    if "auto_update_enabled" in cols:
        q = ("SELECT id, auto_update_enabled, auto_update_days, auto_update_hour,"
             " updated_at FROM subscriptions"
             " WHERE enabled=1 AND url IS NOT NULL AND url != ''"
             " AND auto_update_enabled = 1")
        rows = [(sid, 1, days or 1, hour if hour is not None else 4, updated)
                for sid, _en, days, hour, updated in conn.execute(q)]
    else:  # legacy DB without the migration: fall back to hours column
        rows = [(sid, 1, max(1, round((auh or 0) / 24)), 4, updated)
                for sid, auh, updated in conn.execute(
                    "SELECT id, auto_update_hours, updated_at FROM subscriptions"
                    " WHERE enabled=1 AND url IS NOT NULL AND url != ''"
                    " AND auto_update_hours > 0")]
    for sid, _en, days, hour, updated in rows:
        due = True
        if updated:
            try:
                ts = time.mktime(time.strptime(updated, "%Y-%m-%dT%H:%M:%S"))
                # must be at/after the scheduled hour and N days past last run
                due = (now - ts) >= (days or 1) * 86400 and now_lt.tm_hour >= (hour or 0)
            except ValueError:
                due = True
        if due:
            out.append(sid)
    return out


def _maybe_run_failover(conn: sqlite3.Connection) -> None:
    """Run due failover probe rounds (REA §24.5: scheduler-driven pipeline)."""
    from core import failover_sm as _fsm
    from panel import db as dbmod
    import json as _json
    try:
        groups = dbmod.list_groups(conn)
    except Exception:
        return
    for g in groups:
        if g.get("type") != "failover":
            continue
        # 加载状态，检查是否到探测时间
        try:
            row = conn.execute(
                "SELECT state_json FROM failover_state WHERE group_name=?",
                (g["name"],)).fetchone()
            st = None
            if row and row[0] and row[0] != '{}':
                try:
                    st = _fsm.FailoverState.from_dict(_json.loads(row[0]))
                except Exception:
                    st = None
            if st is None:
                lanes_cfg = g.get("lanes") or []
                st = _fsm.failover_init(g["name"], lanes_cfg, {
                    "probe_interval_s": g.get("interval_s", 300),
                    "tolerance_ms": g.get("tolerance_ms", 100),
                })
            # 检查是否到期
            now = time.time()
            next_at = st.next_round_at
            due = False
            if not next_at:
                due = True  # 从未跑过
            else:
                try:
                    next_ts = time.mktime(time.strptime(next_at, "%Y-%m-%dT%H:%M:%S"))
                    due = now >= next_ts
                except ValueError:
                    due = True
            if not due:
                continue
            # 运行一轮
            cfg = dbmod.load_app_config(conn)
            api_base = f"http://127.0.0.1:{cfg.clash_api_port}"
            secret = getattr(cfg, "clash_api_secret", "") or ""
            result = _fsm.run_round(st, api_base, secret)
            # 持久化
            conn.execute(
                "INSERT INTO failover_state(group_name, current_tag, updated_at, last_switch_at, state_json)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(group_name) DO UPDATE SET current_tag=excluded.current_tag,"
                " updated_at=excluded.updated_at, last_switch_at=excluded.last_switch_at,"
                " state_json=excluded.state_json",
                (g["name"], st.current_id, _fsm._now_iso(),
                 st.last_switch, _json.dumps(st.to_dict(), ensure_ascii=False)))
            conn.commit()
            if result.get("switched"):
                print(f"[scheduler] failover {g['name']}: switched to {result['currentTag']} "
                      f"({result['reason']})", flush=True)
                _fsm.apply_switch(api_base, secret, g["name"], result["currentTag"])
            else:
                print(f"[scheduler] failover {g['name']}: round done ({result['reason']})",
                      flush=True)
        except Exception as e:
            print(f"[scheduler] failover {g.get('name')} failed: {e}", flush=True)


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
        _maybe_update_content_filter(conn)
        _maybe_panel_self_update(conn)
        _maybe_prune_traffic(conn)
        _maybe_run_failover(conn)
        _maybe_observe_direct_answers(conn)
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
        before = _df.blocklist_hash(manager_from_env().workdir)
        result = _df.apply_lists(manager_from_env().workdir, lists)
        after = _df.blocklist_hash(manager_from_env().workdir)
        set_setting(conn, "dns_filter_applied_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
        set_setting(conn, "dns_filter_auto_updated_at", today)
        conn.commit()
        print(f"[scheduler] dns filter auto-updated: {result}", flush=True)
        if before != after:
            # Same gap as the manual apply path: the drop-in only
            # references the blocklist by path, so without this the
            # refreshed list would wait for the next restart. Lazy
            # import: the scheduler runs inside the panel process and
            # panel.app imports the scheduler lazily, so this cannot
            # cycle at module load.
            from panel.app import sync_dnsmasq_panel_conf
            sync = sync_dnsmasq_panel_conf(conn, force_restart=True)
            print(f"[scheduler] dns filter dnsmasq sync: {sync}", flush=True)
    except Exception as e:
        print(f"[scheduler] dns filter update failed: {e}", flush=True)


def _maybe_update_content_filter(conn: sqlite3.Connection) -> None:
    """Daily content-filter list refresh at the configured time (default
    04:00), mirroring the DNS filter's schedule. Refreshes only lists
    that have a source: enabled cf_rulesets with source_url (via
    cfrefresh, which keeps old rules on failure and respects its 600s
    failure cooldown) and enabled legacy content_filters with
    snapshot_url. No-URL lists are manual and skipped. One attempt per
    day (cf_auto_updated_at), even if individual items fail -- same
    stamp semantics as the DNS filter run.

    Refresh updates the stored lists only; the kernel's block rule
    picks them up on the next apply/deploy, exactly like the manual
    refresh buttons (refresh != apply). No kernel restart is triggered
    from the scheduler.
    """
    from panel.db import get_setting, set_setting
    if get_setting(conn, "cf_auto_update", "0") != "1":
        return
    at = get_setting(conn, "cf_update_time", "04:00")
    try:
        hh, mm = at.split(":")
        hh, mm = int(hh), int(mm)
    except ValueError:
        return
    now = time.localtime()
    today = time.strftime("%Y-%m-%d")
    if get_setting(conn, "cf_auto_updated_at", "") == today:
        return
    if (now.tm_hour, now.tm_min) < (hh, mm):
        return
    results = []
    try:
        from core import cfrefresh as _cfr
        rows = conn.execute(
            "SELECT id FROM cf_rulesets WHERE enabled = 1 "
            "AND source_url IS NOT NULL AND source_url != ''").fetchall()
        for (rid,) in rows:
            try:
                results.append((rid, _cfr.refresh_ruleset(conn, rid)))
            except Exception as e:
                results.append((rid, {"status": "failed",
                                     "error": str(e)}))
    except Exception as e:
        print(f"[scheduler] content filter ruleset refresh failed: {e}",
              flush=True)
    try:
        from panel import db as dbmod
        rows = conn.execute(
            "SELECT id FROM content_filters WHERE enabled = 1 "
            "AND snapshot_url IS NOT NULL AND snapshot_url != ''").fetchall()
        for (fid,) in rows:
            try:
                r = dbmod.refresh_content_filter_from_snapshot(conn, fid)
                results.append((fid, {"status": "updated" if r else "skipped"}))
            except Exception as e:
                results.append((fid, {"status": "failed",
                                     "error": str(e)}))
    except Exception as e:
        print(f"[scheduler] content filter legacy refresh failed: {e}",
              flush=True)
    set_setting(conn, "cf_auto_updated_at", today)
    conn.commit()
    print(f"[scheduler] content filter auto-updated: {results}", flush=True)


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


def _maybe_observe_direct_answers(conn: sqlite3.Connection) -> None:
    """扫描 DNS 日志，将直连域名的解析 IP 写入 direct-answer 集合。

    简化实现：每 60s 扫描一次 dnsmasq 日志，提取直连应答。
    完整实现需在 DNS 路径内钩子写入（原版 Go 核心行为）。
    """
    try:
        from core import direct_answer as _da
        from core import dnslog as _dl
        import os
        # 检查入口绕过是否启用
        from panel.db import get_setting
        if get_setting(conn, "direct_bypass_kernel", "0") != "1":
            return
        log_path = "/var/log/dnsmasq.log"  # 常见路径
        if not os.path.isfile(log_path):
            return
        # 解析最近的 DNS 应答（简化：只处理 A 记录应答）
        # 实际需结合站点集判断是否为直连域名
        # 此处为框架占位，完整逻辑需 DNS 上下文
        pass
    except Exception as e:
        print(f"[scheduler] direct-answer observe failed: {e}", flush=True)


def _maybe_prune_traffic(conn: sqlite3.Connection) -> None:
    """Delete traffic_daily rows older than traffic_keep_months, once a day."""
    from panel import db as dbmod
    from panel.db import get_setting, set_setting
    today = time.strftime("%Y-%m-%d")
    if get_setting(conn, "traffic_pruned_on", "") == today:
        return
    try:
        n = dbmod.prune_old_traffic(conn)
        set_setting(conn, "traffic_pruned_on", today)
        print(f"[scheduler] pruned {n} old traffic rows", flush=True)
    except Exception as e:
        print(f"[scheduler] traffic prune failed: {e}", flush=True)


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
