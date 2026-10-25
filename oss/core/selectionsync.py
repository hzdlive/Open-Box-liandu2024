"""Selection sync (v6 clash-selection + selection-sync 对照，Debian 适配).

The panel's proxy UI switches selectors straight against the kernel's
Clash API (``PUT /proxies/{group}``), bypassing the panel backend. Without
a sync step, the panel profile never learns about those switches, and the
next apply rebuilds every selector group with ``default = members[0]``,
silently resetting the user's live choice.

This module closes that loop (v6 #16 ``reconcileSelection`` + #20 ``hD``,
adapted: no profile file, no sidecar — the panel DB is the profile):

- Only ``selector``-type, enabled groups are reconciled. ``urltest`` and
  ``failover`` groups compute ``now`` themselves (latency / failover state
  machine); writing their ``now`` back as a default would be wrong.
- Only entries with a string ``now`` are read (v6: sparse by design —
  leaf nodes have no ``now``).
- A ``now`` value is written back only when it is still a member of the
  group (resolved members, wildcards included) — never introduce an
  unknown tag, and never touch groups whose members changed.
- Nothing is written when nothing changed (v6: don't bump revision for a
  no-op). No ``bump_rev`` here at all: syncing aligns the stored default
  with the already-running config, so the running config is not stale.
- Never raises: an unreachable kernel (or any other failure) yields
  ``ok: False`` and the caller carries on. Sync must never block an apply.
"""

from __future__ import annotations

import sqlite3
import threading

from core.clashapi import get_proxies
from core.singbox import resolve_group_members

# Trailing-debounce scheduler for the controller-proxy trigger (v7 #23 hD
# equivalent). Repeated schedule() calls reset the timer; only the final
# state runs, once. The timer fires in its own daemon thread and opens a
# fresh connection (the requesting thread's connection is long gone).
_schedule_lock = threading.Lock()
_schedule_timer = None


def schedule(dsn: str, uri: bool = False, delay: float = 0.6,
             run=None) -> None:
    """Arm (or re-arm) a trailing-debounced selection sync.

    run: injected worker for tests; default loads the config from dsn and
    reconciles. Never raises; a failed run is simply swallowed (the sync
    runs on a timer with no request to answer, and apply reconciles again).
    """
    global _schedule_timer

    def _fire():
        try:
            if run is not None:
                run()
            else:
                c = sqlite3.connect(dsn, uri=uri, timeout=30)
                try:
                    from panel import db as dbmod
                    cfg = dbmod.load_app_config(c)
                    reconcile(c, cfg)
                finally:
                    c.close()
        except Exception:
            pass

    with _schedule_lock:
        if _schedule_timer is not None:
            _schedule_timer.cancel()
        _schedule_timer = threading.Timer(delay, _fire)
        _schedule_timer.daemon = True
        _schedule_timer.start()


def reconcile(conn: sqlite3.Connection, cfg, proxies: dict | None = None,
              port: int | None = None) -> dict:
    """Write kernel selector ``now`` values back to group defaults.

    cfg: AppConfig (groups, nodes, chains, clash_api_port).
    proxies: Clash ``/proxies`` response body (``{"proxies": {...}}``);
        fetched from the kernel when omitted.
    Returns {"ok", "updated": [{group, from, to}], "skipped": [{group, reason}],
    "error"}.
    """
    updated: list[dict] = []
    skipped: list[dict] = []
    if proxies is None:
        ok, data = get_proxies(port if port is not None
                               else getattr(cfg, "clash_api_port", None))
        if not ok:
            return {"ok": False, "updated": [], "skipped": [],
                    "error": "无法读取内核选择（Clash API 不可达）"}
        proxies = data
    entries = (proxies or {}).get("proxies") or {}
    node_tags = [n.tag for n in getattr(cfg, "nodes", [])]
    chain_tags = [c.name for c in getattr(cfg, "chains", [])]
    try:
        for g in getattr(cfg, "groups", []):
            if g.type != "selector" or not g.enabled:
                continue
            entry = entries.get(g.name)
            now = entry.get("now") if isinstance(entry, dict) else None
            if not isinstance(now, str) or not now:
                skipped.append({"group": g.name, "reason": "no-now"})
                continue
            members = resolve_group_members(g, node_tags, chain_tags)
            if now not in members:
                skipped.append({"group": g.name, "reason": "not-member"})
                continue
            if (g.default_outbound or "") == now:
                continue
            conn.execute("UPDATE groups SET default_outbound=? WHERE name=?",
                         (now, g.name))
            updated.append({"group": g.name,
                            "from": g.default_outbound or "",
                            "to": now})
        if updated:
            conn.commit()
    except Exception as e:  # sync never breaks the caller
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "updated": [], "skipped": skipped,
                "error": f"选择同步失败：{e}"}
    return {"ok": True, "updated": updated, "skipped": skipped, "error": ""}
