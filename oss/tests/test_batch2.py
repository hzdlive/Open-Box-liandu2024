"""Batch 2 tests: hot-apply classify, deploy state/rollback, factory reset,
failover status/refresh/recheck."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def test_classify_changes():
    from core.hotapply import classify_changes
    old = {"outbounds": [{"tag": "a"}], "inbounds": [],
           "dns": {"servers": ["1.1.1.1"]}, "route": {"rules": []}}
    new = {"outbounds": [{"tag": "a"}, {"tag": "b"}], "inbounds": [],
           "dns": {"servers": ["1.1.1.1"]}, "route": {"rules": []}}
    assert classify_changes(old, new) == "hot"
    new2 = dict(new, dns={"servers": ["8.8.8.8"]})
    assert classify_changes(old, new2) == "restart"
    assert classify_changes(old, dict(old)) == "none"
    assert classify_changes({}, new) == "restart"
    print("ok classify_changes")


def test_native_push_unsupported_kernel():
    from core.hotapply import native_push_outbounds
    # nothing listening -> connection error, not a crash
    ok, detail = native_push_outbounds("http://127.0.0.1:1", "", [], timeout=1)
    assert ok is False and detail
    print("ok native_push fallback, detail:", detail[:40])


def test_deploy_state_and_rollback():
    app = _app()
    c = app.test_client()
    d = c.get("/api/deploy/state").get_json()
    assert d["ok"] is False  # never deployed
    # rollback writes a direct config; kernel not installed here -> still ok
    r = c.post("/api/deploy/rollback")
    assert r.status_code in (200, 409, 422), r.get_json()
    if r.status_code == 200:
        d = c.get("/api/deploy/state").get_json()
        assert d["mode"] == "rollback" and d["ok"] is True
    print("ok deploy state + rollback")


def test_factory_reset():
    import sqlite3
    app = _app()
    c = app.test_client()
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    dbmod.add_subscription(conn, "s", "vmess://e30=")
    conn.close()
    r = c.post("/api/factory-reset")
    assert r.status_code == 200
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    n = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
    groups = [x[0] for x in conn.execute("SELECT name FROM groups ORDER BY position")]
    conn.close()
    assert n == 0 and groups == ["auto", "manual"], (n, groups)
    print("ok factory reset")


def test_failover_status_flow():
    import sqlite3
    app = _app()
    c = app.test_client()
    # create a failover group with two members
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('fo1', 'failover', '[\"m1\", \"m2\"]', '[]', 5)")
    conn.execute(
        "INSERT INTO node_health(tag, ok, latency_ms, checked_at)"
        " VALUES ('m1', 0, 0, ''), ('m2', 1, 0, '')")
    conn.commit()
    conn.close()
    st = c.get("/api/failover/status").get_json()
    assert len(st) == 1 and st[0]["group"] == "fo1"
    assert st[0]["primary"] == "m1"
    assert st[0]["current"] == "m1"  # no state yet -> primary
    # refresh elects m2 (only healthy one); kernel clash API is down so the
    # switch call fails, but the election result is still recorded
    r = c.post("/api/failover/refresh").get_json()
    assert r[0]["group"] == "fo1" and r[0]["target"] == "m2"
    st = c.get("/api/failover/status").get_json()
    assert st[0]["current"] == "m2", st
    # unknown group recheck -> 404
    r = c.post("/api/failover/recheck", json={"group": "nope"})
    assert r.status_code == 404
    print("ok failover status/refresh/recheck")


def test_apply_modes():
    app = _app()
    c = app.test_client()
    r = c.post("/api/config/apply?mode=bogus")
    assert r.status_code == 400
    print("ok apply mode validation")


def main():
    test_classify_changes()
    test_native_push_unsupported_kernel()
    test_deploy_state_and_rollback()
    test_factory_reset()
    test_failover_status_flow()
    test_apply_modes()
    print("ALL BATCH2 TESTS PASSED")


if __name__ == "__main__":
    main()
