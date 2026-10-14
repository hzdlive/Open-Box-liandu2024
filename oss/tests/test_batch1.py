"""Batch 1 tests: kernel page API, logs, diagnostics (desensitized)."""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def _dbconn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


def test_service_status_extended():
    c = _app().test_client()
    s = c.get("/api/service").get_json()
    for k in ("installed", "running", "version", "platform", "arch",
              "os_version", "autostart", "panel_version", "config_stale"):
        assert k in s, k
    assert s["config_stale"] is False  # nothing applied yet -> not stale
    assert isinstance(s["platform"], str) and s["platform"]
    print("ok service status extended fields")


def test_config_stale_flag():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    # simulate a config change without apply
    dbmod.create_site_set(conn, {"name": "s", "action": "proxy",
                                 "rules": {"domain_suffix": ["x.com"]}})
    conn.close()
    s = c.get("/api/service").get_json()
    # applied_rev empty -> not stale (nothing to compare against)
    assert s["config_stale"] is False
    print("ok config_stale flag")


def test_diagnostics_desensitized():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    secret_url = "https://sub.example.com/abc?token=SECRET123"
    secret_server = "203.0.113.9"
    sid, _ = dbmod.add_subscription(conn, "s1", "vmess://e30=", url=secret_url)
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
        " VALUES (?, 'n1', 'vmess', ?, 443, '{}')",
        (sid, secret_server))
    conn.commit()
    conn.close()
    # set a panel password and pair a device (more secrets)
    c.post("/api/auth/setup", json={"password": "pw123456"})
    c.post("/api/auth/login", json={"password": "pw123456"})
    d = c.get("/api/diagnostics").get_json()
    blob = json.dumps(d)
    assert "SECRET123" not in blob, "subscription token leaked"
    assert secret_server not in blob, "node server leaked"
    assert "pw123456" not in blob, "password leaked"
    # but structure is there
    assert d["config_summary"]["subscriptions"] == 1
    assert d["config_summary"]["nodes"] == 1
    assert d["config_summary"]["subscription_hosts"] == ["sub.example.com"]
    assert "panel" in d and "system" in d and "kernel" in d
    assert "deploy" in d and "logs" in d
    print("ok diagnostics desensitized")


def test_logs_endpoints():
    app = _app()
    c = app.test_client()
    r = c.get("/api/service/log?source=kernel&n=10").get_json()
    assert r["source"] == "kernel" and isinstance(r["log"], list)
    r = c.get("/api/service/log?source=panel").get_json()
    assert r["source"] == "panel" and isinstance(r["log"], list)
    # panel log file honored via env
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("line1\nline2\n")
        path = f.name
    old = os.environ.get("OBX_PANEL_LOG")
    os.environ["OBX_PANEL_LOG"] = path
    try:
        r = c.get("/api/service/log?source=panel").get_json()
        assert r["log"] == ["line1", "line2"], r["log"]
    finally:
        if old is None:
            del os.environ["OBX_PANEL_LOG"]
        else:
            os.environ["OBX_PANEL_LOG"] = old
        os.unlink(path)
    print("ok logs endpoints")


def main():
    test_service_status_extended()
    test_config_stale_flag()
    test_diagnostics_desensitized()
    test_logs_endpoints()
    print("ALL BATCH1 TESTS PASSED")


if __name__ == "__main__":
    main()
