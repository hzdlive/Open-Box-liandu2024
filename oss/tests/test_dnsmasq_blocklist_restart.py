"""Blocklist-change restart (follow-up to the 2026-10-26 DNS filter gap).

The panel drop-in references the filter blocklist only by path, so when
an apply rewrites the blocklist file itself the drop-in is unchanged and
the old sync skipped the restart — dnsmasq kept serving the old list
(SIGHUP does not reload config files, verified live 2026-10-25).

Covers: forced restart on an unchanged drop-in; no forced restart when
dnsmasq is down; the apply endpoint forces a restart only when the file
actually changed AND the filter ends up enabled; the scheduler refresh
path forces one too; apply_lists no longer fakes a reload via HUP.
"""

import sqlite3
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import dnsfilter as dfmod  # noqa: E402
from core import scheduler as schedmod  # noqa: E402
from panel import app as appmod  # noqa: E402
from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


class _StubLists(BaseHTTPRequestHandler):
    body = b"0.0.0.0 ads.example.com\n0.0.0.0 tracker.example.org\n"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


class _StubServer:
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StubLists)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/list.txt"

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        return False


def _db():
    c = sqlite3.connect(":memory:")
    dbmod.init_db(c)
    return c


def _seed_rewrites(c):
    dbmod.add_dns_rewrite(c, "x.example.com", "1.2.3.4")


class Runner:
    def __init__(self, running=True, systemctl_rc=0):
        self.running = running
        self.systemctl_rc = systemctl_rc
        self.cmds = []

    def __call__(self, cmd):
        self.cmds.append(list(cmd))
        if "--test" in cmd:
            return SimpleNamespace(returncode=0)
        if cmd[0].endswith("pgrep"):
            return SimpleNamespace(returncode=0 if self.running else 1)
        if cmd[0] == "systemctl":
            return SimpleNamespace(returncode=self.systemctl_rc)
        return SimpleNamespace(returncode=0)


def test_sync_forced_restart_on_unchanged_dropin(tmp_path):
    c = _db()
    _seed_rewrites(c)
    path = str(tmp_path / "openbox-panel.conf")
    runner = Runner()
    r1 = appmod.sync_dnsmasq_panel_conf(c, conf_path=path, run=runner,
                                        wait_ready=lambda: True)
    assert r1["restarted"] is True
    ncmds = len(runner.cmds)
    r2 = appmod.sync_dnsmasq_panel_conf(c, conf_path=path, run=runner,
                                        wait_ready=lambda: True,
                                        force_restart=True)
    assert r2["changed"] is False  # drop-in itself did not change
    assert r2["restarted"] is True
    assert r2["forced"] is True
    assert len(runner.cmds) > ncmds
    assert any(cmd[0] == "systemctl" for cmd in runner.cmds[ncmds:])


def test_sync_forced_no_restart_when_dnsmasq_down(tmp_path):
    c = _db()
    _seed_rewrites(c)
    runner = Runner(running=False)
    r = appmod.sync_dnsmasq_panel_conf(
        c, conf_path=str(tmp_path / "openbox-panel.conf"), run=runner,
        wait_ready=lambda: True, force_restart=True)
    assert r["restarted"] is False
    assert not any(cmd[0] == "systemctl" for cmd in runner.cmds)


def _client(monkeypatch, workdir, recorder):
    monkeypatch.setenv("OPENBOX_WORKDIR", workdir)

    def _sync(c, **kw):
        recorder.append(kw)
        return {"ok": True, "mock": True}

    monkeypatch.setattr(appmod, "sync_dnsmasq_panel_conf", _sync)
    return create_app(":memory:").test_client()


def test_endpoint_apply_forces_restart_when_changed(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        recorder = []
        c = _client(monkeypatch, wd, recorder)
        r = c.put("/api/dns/filter",
                  json={"enabled": True,
                        "lists": [{"name": "good", "url": url,
                                   "enabled": True}]})
        assert r.status_code == 200, r.get_json()
        r = c.post("/api/dns/filter/apply", json={})
        body = r.get_json()
        assert r.status_code == 200, body
        assert body["blocklist_changed"] is True
        assert body["dnsmasq_sync"] == {"ok": True, "mock": True}
        assert recorder and recorder[-1].get("force_restart") is True


def test_endpoint_apply_no_force_when_content_identical(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        recorder = []
        c = _client(monkeypatch, wd, recorder)
        c.put("/api/dns/filter",
              json={"enabled": True,
                    "lists": [{"name": "good", "url": url,
                               "enabled": True}]})
        assert c.post("/api/dns/filter/apply", json={}).status_code == 200
        r = c.post("/api/dns/filter/apply", json={})
        body = r.get_json()
        assert body["blocklist_changed"] is False
        assert recorder[-1].get("force_restart") is False


def test_endpoint_apply_no_force_when_filter_off(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        recorder = []
        c = _client(monkeypatch, wd, recorder)
        c.put("/api/dns/filter",
              json={"enabled": False,
                    "lists": [{"name": "good", "url": url,
                               "enabled": True}]})
        # refresh-only path leaves the flag off: the drop-in does not
        # reference the file, so restarting would be a pointless blip.
        r = c.post("/api/dns/filter/apply", json={"update": True})
        body = r.get_json()
        assert r.status_code == 200, body
        assert body["blocklist_changed"] is True
        assert recorder[-1].get("force_restart") is False


def test_apply_lists_reports_no_reload(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        result = dfmod.apply_lists(
            wd, [{"name": "good", "url": url, "enabled": True}])
        assert result["all_failed"] is False
        assert result["dnsmasq_reloaded"] is False


def _scheduler_conn(monkeypatch, wd, url):
    import core.service as _svc
    monkeypatch.setattr(_svc, "manager_from_env",
                        lambda: SimpleNamespace(workdir=wd))
    conn = sqlite3.connect(":memory:")
    dbmod.init_db(conn)
    dbmod.set_setting(conn, "dns_filter_enabled", "1")
    dbmod.set_setting(conn, "dns_filter_auto_update", "1")
    dbmod.set_setting(conn, "dns_filter_update_time", "00:00")
    dbmod.set_setting(conn, "dns_filter_auto_updated_at", "")
    import json as _json
    dbmod.set_setting(conn, "dns_filter_lists", _json.dumps(
        [{"name": "good", "url": url, "enabled": True}]))
    conn.commit()
    return conn


def test_scheduler_refresh_forces_restart_when_changed(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        recorder = []
        monkeypatch.setattr(
            appmod, "sync_dnsmasq_panel_conf",
            lambda c, **kw: recorder.append(kw) or {"mock": True})
        conn = _scheduler_conn(monkeypatch, wd, url)
        schedmod._maybe_update_dns_filter(conn)
        assert recorder and recorder[-1].get("force_restart") is True


def test_scheduler_no_sync_when_unchanged(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        recorder = []
        monkeypatch.setattr(
            appmod, "sync_dnsmasq_panel_conf",
            lambda c, **kw: recorder.append(kw) or {"mock": True})
        # Pre-seed exactly what the fetch would write.
        path = dfmod.blocklist_path(wd)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Generated by openbox-oss DNS filter — do not edit\n")
            f.write("address=/ads.example.com/#\n")
            f.write("address=/tracker.example.org/#\n")
        conn = _scheduler_conn(monkeypatch, wd, url)
        schedmod._maybe_update_dns_filter(conn)
        assert recorder == []
