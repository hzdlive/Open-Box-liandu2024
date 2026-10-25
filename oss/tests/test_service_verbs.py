"""Self-test for the service verbs completion (v7 #25 alignment).

- enable/disable flip only the autostart flag: no kernel start/stop,
  no pipeline, no timing.
- stop keeps its wait-for-real-exit (manager.stop) and adds the third
  step: clear the autostart flag; a clear failure keeps ok True and
  appends stderr instead.
- maybe_autostart_kernel: flag 0 -> no start; flag 1 -> start attempted;
  unreadable DB -> no raise, no start.
"""
import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panel import app as appmod  # noqa: E402
from panel import db as dbmod  # noqa: E402


def _client(tmp_path):
    dbfile = str(tmp_path / "panel.db")
    app = appmod.create_app(dbfile)
    return app.test_client(), dbfile


def _flag(dbfile):
    c = sqlite3.connect(dbfile)
    try:
        row = c.execute(
            "SELECT value FROM settings WHERE key = 'autostart'").fetchone()
    finally:
        c.close()
    return row[0] if row else None


def _db_with_flag(tmp_path, value):
    dbfile = str(tmp_path / "panel.db")
    c = sqlite3.connect(dbfile)
    dbmod.init_db(c)
    dbmod.set_setting(c, "autostart", value)
    c.close()
    return dbfile


def test_enable_disable_flip_flag_only(tmp_path):
    client, dbfile = _client(tmp_path)
    assert _flag(dbfile) == "0"  # seeded default: current behavior preserved
    r = client.post("/api/service/enable")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "autostart": True}
    assert _flag(dbfile) == "1"
    r = client.post("/api/service/disable")
    assert r.get_json() == {"ok": True, "autostart": False}
    assert _flag(dbfile) == "0"


def test_stop_clears_flag_and_keeps_service_fields(tmp_path):
    client, dbfile = _client(tmp_path)
    client.post("/api/service/enable")
    assert _flag(dbfile) == "1"
    r = client.post("/api/service/stop")
    body = r.get_json()
    assert r.status_code == 200
    assert body["ok"] is True
    assert body["autostart_cleared"] is True and body["stderr"] == ""
    assert body["running"] is False  # no kernel in this env; fields kept
    assert _flag(dbfile) == "0"


def test_maybe_autostart_flag_off_no_start(tmp_path):
    dbfile = _db_with_flag(tmp_path, "0")
    called = []
    assert appmod.maybe_autostart_kernel(
        dbfile, start_fn=lambda: called.append(1)) is False
    assert called == []


def test_maybe_autostart_flag_on_starts(tmp_path):
    dbfile = _db_with_flag(tmp_path, "1")
    event = threading.Event()
    assert appmod.maybe_autostart_kernel(
        dbfile, start_fn=event.set) is True
    assert event.wait(5)


def test_maybe_autostart_unreadable_db_no_raise(tmp_path):
    assert appmod.maybe_autostart_kernel(
        str(tmp_path / "no-such-dir" / "x.db")) is False
