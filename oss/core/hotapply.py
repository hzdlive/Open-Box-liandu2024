"""Hot-apply: change outbounds without restarting the kernel.

Clean-room reimplementation of the publicly observable behavior:
- node / group / selector changes are pushed live through the kernel's
  native ``PUT /openbox/outbounds`` endpoint (provided by our tcp23-patched
  sing-box builds; stock sing-box answers 404 and we fall back to restart);
- structural changes (inbounds, DNS, TUN, route rules, endpoints) still
  require a full restart;
- :func:`classify_changes` decides which path a config diff needs.

The native endpoint shape (list of outbound objects) is our best
reconstruction of the documented "online outbound replacement" behavior;
every call site treats 404/405 as "kernel too old" and falls back.
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
import urllib.error


def native_push_outbounds(api_base: str, secret: str,
                          outbounds: list[dict],
                          timeout: float = 15.0) -> tuple[bool, str]:
    """Replace the kernel's outbounds live. Returns (ok, detail)."""
    url = api_base.rstrip("/") + "/openbox/outbounds"
    data = json.dumps(outbounds).encode()
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Content-Type": "application/json"})
    if secret:
        req.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        if e.code in (404, 405):
            return False, "native hot-apply unsupported by this kernel (HTTP %d)" % e.code
        return False, f"HTTP {e.code}"
    except OSError as e:
        return False, str(e)


_HOT_SAFE_TOP_KEYS = {"outbounds"}  # everything else forces a restart


def classify_changes(old_cfg: dict, new_cfg: dict) -> str:
    """'hot' if only outbounds changed, else 'restart'."""
    if not old_cfg:
        return "restart"
    for key in set(old_cfg) | set(new_cfg):
        if key not in _HOT_SAFE_TOP_KEYS:
            if json.dumps(old_cfg.get(key), sort_keys=True) != \
               json.dumps(new_cfg.get(key), sort_keys=True):
                return "restart"
    if json.dumps(old_cfg.get("outbounds"), sort_keys=True) == \
       json.dumps(new_cfg.get("outbounds"), sort_keys=True):
        return "none"
    return "hot"


def _atomic_write_json(path: str, obj: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    import os
    os.replace(tmp, path)


def hot_apply_config(conn: sqlite3.Connection, manager,
                     api_base: str, secret: str,
                     force: str = "auto") -> dict:
    """Build + write config; push outbounds live when possible.

    force: 'auto' | 'hot' | 'full'. Returns a result dict with a 'mode'
    key ('hot' | 'full' | 'none').
    """
    from core.apply import build_and_validate, _sync_selection_before_build

    _sync_selection_before_build(conn)
    cfg, ok, msg = build_and_validate(conn, manager)
    if not ok:
        from core.badnodes import ValidationError, locate_from_db
        raise ValidationError(f"config validation failed: {msg}",
                              bad=locate_from_db(msg, cfg, conn))

    old_cfg: dict = {}
    try:
        with open(manager.config_path, encoding="utf-8") as f:
            old_cfg = json.load(f)
    except (OSError, ValueError):
        pass

    want = force if force in ("hot", "full") else classify_changes(old_cfg, cfg)
    _atomic_write_json(manager.config_path, cfg)

    result = {"applied": True, "validation": msg,
              "outbounds": len(cfg.get("outbounds", [])),
              "route_rules": len(cfg.get("route", {}).get("rules", [])),
              "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    svc = manager.to_dict()

    if want == "none":
        result["mode"] = "none"
        result["service"] = svc
        return result

    running = manager.status().running if manager.is_installed() else False
    hot_ok, hot_detail = False, ""
    if want == "hot" and running:
        hot_ok, hot_detail = native_push_outbounds(
            api_base, secret, cfg.get("outbounds", []))
    if hot_ok:
        result["mode"] = "hot"
        result["hot_detail"] = hot_detail
    else:
        relaunched = False
        before = None
        if manager.is_installed():
            from core import startverify as _sv
            before = _sv.snapshot_log(manager.log_path)
            if running:
                manager.restart()
            else:
                manager.start()
            relaunched = True
        result["mode"] = "full"
        if want == "hot":
            result["hot_fallback"] = hot_detail or "kernel not running"
        if relaunched:
            # Same rule as apply_config: a relaunched kernel that did not
            # come up is a failed apply, not a 200 with a dead kernel.
            from core import startverify as _sv
            from core.apply import ApplyVerifyError
            verify = _sv.verify_start(manager, before)
            result["verify"] = verify
            if verify["state"] == "failed":
                raise ApplyVerifyError(verify["message"], verify)
    result["service"] = manager.to_dict()
    return result
