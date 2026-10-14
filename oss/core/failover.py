"""True failover for `failover`-type groups.

How it works (clean-room design, public sing-box APIs only):
- A failover group is rendered into the config as a `selector` whose members
  are ordered by priority (position 0 = primary).
- This module elects the active member: the first member whose last health
  check passed; if none passed, it fails open to the primary (position 0).
- The election is enforced at runtime through sing-box's public clash API:
  `PUT /proxies/{selector}` with `{"name": "<tag>"}` switches the selector
  without restarting the kernel.
- `watch_loop` runs the election periodically; run it as a background task
  (or a cron-style job) wherever the panel runs.

This is panel-side failover, not a kernel outbound type. It is honest about
what it is: health-driven selector switching with hysteresis-free election.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error


def elect_active(members: list[str], health: dict[str, bool | None]) -> str | None:
    """Return the tag that should be active.

    members: priority-ordered tags (index 0 = primary).
    health: tag -> True (ok) / False (failed) / None (unknown/skipped).
    Unknown counts as "not proven bad", but a proven-good member earlier in
    the list always wins over an unknown one later.
    """
    if not members:
        return None
    for tag in members:
        if health.get(tag) is True:
            return tag
    # No proven-good member: prefer an unknown over a proven-bad one,
    # still respecting priority order.
    for tag in members:
        if health.get(tag) is not False:
            return tag
    # Everything proven bad: fail open to the primary.
    return members[0]


def clash_api_put(api_base: str, secret: str, path: str, body: dict,
                  timeout: float = 5.0) -> tuple[bool, str]:
    """PUT JSON to the sing-box clash API. Returns (ok, message)."""
    url = api_base.rstrip("/") + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Content-Type": "application/json"})
    if secret:
        req.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except OSError as e:
        return False, str(e)


def switch_selector(api_base: str, secret: str, selector: str,
                   target: str) -> tuple[bool, str]:
    """Switch a selector's active outbound via the clash API."""
    return clash_api_put(api_base, secret, f"/proxies/{selector}", {"name": target})


def watch_once(groups: list, health_rows: list,
               api_base: str, secret: str) -> list[dict]:
    """Run one election pass over failover groups.

    groups: iterable of objects/dicts with .name/.type/.members (priority order).
    health_rows: iterable of objects/dicts with .tag/.ok.
    Returns a list of action dicts describing what was done.
    """
    health = {}
    for h in health_rows:
        tag = h.tag if hasattr(h, "tag") else h["tag"]
        ok = h.ok if hasattr(h, "ok") else h["ok"]
        health[tag] = ok
    actions = []
    for g in groups:
        gtype = g.type if hasattr(g, "type") else g["type"]
        if gtype != "failover":
            continue
        name = g.name if hasattr(g, "name") else g["name"]
        members = list(g.members if hasattr(g, "members") else g["members"])
        want = elect_active(members, health)
        if want is None:
            actions.append({"group": name, "action": "skip", "reason": "no members"})
            continue
        ok, msg = switch_selector(api_base, secret, name, want)
        actions.append({"group": name, "action": "switch" if ok else "failed",
                        "target": want, "message": msg})
    return actions


def watch_loop(get_groups, get_health, api_base: str, secret: str,
               interval: float = 60.0, stop_after: float | None = None) -> None:
    """Periodically run elections. get_groups/get_health are zero-arg callables."""
    t0 = time.time()
    while True:
        try:
            actions = watch_once(get_groups(), get_health(), api_base, secret)
            for a in actions:
                print(f"[failover] {a['group']}: {a['action']} -> "
                      f"{a.get('target')} ({a.get('message', a.get('reason'))})",
                      flush=True)
        except Exception as e:  # keep the loop alive; log and retry
            print(f"[failover] election error: {e}", flush=True)
        if stop_after is not None and time.time() - t0 >= stop_after:
            break
        time.sleep(interval)
