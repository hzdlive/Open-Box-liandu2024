"""Config apply pipeline: build -> validate -> atomic write -> (re)start kernel.

The generated config is first validated with `sing-box check -c` before it
ever replaces the live config, so a bad generation cannot kill a running
kernel. Hot-swap note: stock sing-box applies route-rule changes only on
restart; the tcp23 patch series adds outbound hot-replacement, which this
pipeline will use automatically when the installed kernel reports a
tcp23-style version string (best effort, falls back to restart).
"""

from __future__ import annotations

import json
import os
import tempfile

from core.service import KernelManager
from core.singbox import build_config
from panel import db as dbmod


def _atomic_write_json(path: str, obj: dict) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        # 1:1 原版 v0.1.334：配置文件 0600 权限（仅所有者可读写）
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _sync_selection_before_build(conn) -> None:
    """Best-effort selection sync before building config.

    Native proxy-UI switches go straight to the kernel's Clash API, so the
    stored group defaults would otherwise lag behind. Syncing here means an
    apply never resets a live selector choice back to members[0]. Never
    raises and never blocks the apply (reconcile itself is failure-proof).
    """
    try:
        from core.selectionsync import reconcile
        reconcile(conn, dbmod.load_app_config(conn))
    except Exception:
        pass


def build_and_validate(conn, manager: KernelManager) -> tuple[dict, bool, str]:
    """Build the config from DB and validate it. Returns (config, ok, message)."""
    app_cfg = dbmod.load_app_config(conn, with_blocked_domains=True)
    # Local .srs rule-sets referenced by site sets: TTL-aware refresh now
    # (v6 #14 deploy-rulesets semantics: 24h TTL + URL match reuse, stale
    # files re-downloaded, failures keep the old file). Anything still
    # missing is skipped so a missing geodata file can never break
    # validation (degraded routing, warning in the message).
    from core import geodata as _gd
    names = _gd.referenced_rule_sets(app_cfg)
    try:
        _missing = _gd.refresh_names(conn, names)["missing"] if names else []
    except Exception:
        # Refresh must never break apply: fall back to missing-only ensure.
        _ok, _missing = _gd.ensure(names) if names else ([], [])
    missing = _missing
    cfg = build_config(app_cfg, set(missing))
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        ok, msg = manager.check_config(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if missing:
        msg = f"{msg} [geodata missing, skipped: {', '.join(missing)}]"
    return cfg, ok, msg


def apply_config(conn, manager: KernelManager,
                 restart: bool = True) -> dict:
    """Full pipeline. Returns a result dict; raises on validation failure."""
    _sync_selection_before_build(conn)
    cfg, ok, msg = build_and_validate(conn, manager)
    if not ok:
        from core.badnodes import ValidationError, locate_from_db
        raise ValidationError(f"config validation failed: {msg}",
                              bad=locate_from_db(msg, cfg, conn))
    _atomic_write_json(manager.config_path, cfg)
    svc = manager.to_dict()
    if manager.is_installed():
        running = manager.status().running
        if running and restart:
            manager.restart()
        elif not running:
            manager.start()
        svc = manager.to_dict()
    return {"applied": True, "validation": msg, "service": svc,
            "outbounds": len(cfg.get("outbounds", [])),
            "route_rules": len(cfg.get("route", {}).get("rules", []))}
