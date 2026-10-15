"""Tests for panel self-update: scheduler gating, check logic, API."""

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402
from core import selfupdate as su  # noqa: E402
from core import scheduler  # noqa: E402

LOCAL = "a" * 40
REMOTE = "b" * 40


def _conn():
    c = sqlite3.connect(":memory:")
    dbmod.init_db(c)
    return c


class _R:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_git(local_sha, remote_sha, fail=False):
    def fake(args, cwd, timeout=30):
        if args[:2] == ["rev-parse", "HEAD"]:
            return _R(0, local_sha + "\n")
        if args[0] == "ls-remote":
            if fail:
                return _R(128, "", "fatal: unable to access")
            return _R(0, f"{remote_sha}\trefs/heads/oss\n")
        return _R(0, "")
    return fake


def _ts(s):
    return time.mktime(time.strptime(s, su.TS_FMT))


def test_due_never_checked():
    c = _conn()
    dbmod.set_setting(c, "update_days", "1")
    dbmod.set_setting(c, "update_hour", "4")
    assert su.due_for_check(c, now=_ts("2026-10-15T05:00:00")) is True
    assert su.due_for_check(c, now=_ts("2026-10-15T03:59:00")) is False


def test_due_interval_and_daily():
    c = _conn()
    dbmod.set_setting(c, "update_days", "1")
    dbmod.set_setting(c, "update_hour", "4")
    # checked this morning already -> not due again today
    dbmod.set_setting(c, "update_last_check", "2026-10-15T05:00:00")
    assert su.due_for_check(c, now=_ts("2026-10-15T06:00:00")) is False
    # checked yesterday evening (< 24h ago) -> interval not reached
    dbmod.set_setting(c, "update_last_check", "2026-10-14T18:00:00")
    assert su.due_for_check(c, now=_ts("2026-10-15T06:00:00")) is False
    # checked 2 days ago, after the hour -> due
    dbmod.set_setting(c, "update_last_check", "2026-10-13T05:00:00")
    assert su.due_for_check(c, now=_ts("2026-10-15T05:00:00")) is True
    # days=7, checked 3 days ago -> not due
    dbmod.set_setting(c, "update_days", "7")
    dbmod.set_setting(c, "update_last_check", "2026-10-12T05:00:00")
    assert su.due_for_check(c, now=_ts("2026-10-15T05:00:00")) is False


def test_check_update_available():
    c = _conn()
    orig = su._run_git
    su._run_git = _fake_git(LOCAL, REMOTE)
    try:
        r = su.check_for_update(c)
    finally:
        su._run_git = orig
    assert r["available"] is True, r
    assert r["local"] == LOCAL and r["remote"] == REMOTE
    assert dbmod.get_setting(c, "update_last_check") != ""
    saved = json.loads(dbmod.get_setting(c, "update_last_result"))
    assert saved["available"] is True


def test_check_update_current():
    c = _conn()
    orig = su._run_git
    su._run_git = _fake_git(LOCAL, LOCAL)
    try:
        r = su.check_for_update(c)
    finally:
        su._run_git = orig
    assert r["available"] is False, r


def test_check_update_error_recorded():
    c = _conn()
    orig = su._run_git
    su._run_git = _fake_git(LOCAL, REMOTE, fail=True)
    try:
        r = su.check_for_update(c)
    finally:
        su._run_git = orig
    assert r["available"] is False and "error" in r, r


def test_scheduler_triggers_check_and_apply():
    c = _conn()
    dbmod.set_setting(c, "update_auto", "1")
    dbmod.set_setting(c, "update_days", "1")
    dbmod.set_setting(c, "update_hour", "0")
    orig_git, orig_apply = su._run_git, su.apply_update_async
    called = {}
    su._run_git = _fake_git(LOCAL, REMOTE)

    def _fake_apply(ref="refs/heads/oss"):
        called["ref"] = ref
        return "/tmp/x.log"
    su.apply_update_async = _fake_apply
    try:
        # force due by clearing last check and using hour 0
        scheduler._maybe_panel_self_update(c)
    finally:
        su._run_git, su.apply_update_async = orig_git, orig_apply
    assert called.get("ref") == "refs/heads/oss", called
    assert dbmod.get_setting(c, "update_last_check") != ""


def test_scheduler_skipped_when_auto_off():
    c = _conn()
    dbmod.set_setting(c, "update_auto", "0")
    orig = su._run_git
    su._run_git = _fake_git(LOCAL, REMOTE)
    try:
        scheduler._maybe_panel_self_update(c)
    finally:
        su._run_git = orig
    assert dbmod.get_setting(c, "update_last_check") == ""


def test_api_endpoints():
    app = create_app(":memory:")
    cl = app.test_client()
    r = cl.get("/api/panel/update/status")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    for k in ("update_auto", "update_hour", "update_channel",
              "update_check_channel", "update_days", "local_commit"):
        assert k in body, k
    # apply with nothing available -> 409
    r = cl.post("/api/panel/update/apply")
    assert r.status_code == 409, r.status_code
    # mocked check -> available, then apply ok (apply itself mocked)
    orig_git, orig_apply = su._run_git, su.apply_update_async
    su._run_git = _fake_git(LOCAL, REMOTE)
    su.apply_update_async = lambda ref="refs/heads/oss": "/tmp/x.log"
    try:
        r = cl.post("/api/panel/update/check")
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["available"] is True
        r = cl.post("/api/panel/update/apply")
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["ok"] is True
    finally:
        su._run_git, su.apply_update_async = orig_git, orig_apply


def main() -> int:
    test_due_never_checked()
    test_due_interval_and_daily()
    test_check_update_available()
    test_check_update_current()
    test_check_update_error_recorded()
    test_scheduler_triggers_check_and_apply()
    test_scheduler_skipped_when_auto_off()
    test_api_endpoints()
    print("test_selfupdate: all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
