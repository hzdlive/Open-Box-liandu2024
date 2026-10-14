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
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def build_and_validate(conn, manager: KernelManager) -> tuple[dict, bool, str]:
    """Build the config from DB and validate it. Returns (config, ok, message)."""
    cfg = build_config(dbmod.load_app_config(conn))
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
    return cfg, ok, msg


def apply_config(conn, manager: KernelManager,
                 restart: bool = True) -> dict:
    """Full pipeline. Returns a result dict; raises on validation failure."""
    cfg, ok, msg = build_and_validate(conn, manager)
    if not ok:
        raise RuntimeError(f"config validation failed: {msg}")
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
