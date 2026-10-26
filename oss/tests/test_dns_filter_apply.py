"""Tests for POST /api/dns/filter/apply semantics (v7 #24 alignment).

Covers: update must be exactly `true` (a truthy string takes the full
path); listId validated before the busy check and must name an enabled
list; a second apply while one holds the lock answers 400 and PUT
answers 409; all-enabled-failed keeps the old blocklist and answers 400
(fail closed); partial failure still answers 200; a write failure
answers 400, never 500.
"""

import os
import sqlite3
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import dnsfilter as dfmod  # noqa: E402
from panel import app as appmod  # noqa: E402
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


def _client(monkeypatch, workdir):
    monkeypatch.setenv("OPENBOX_WORKDIR", workdir)
    monkeypatch.setattr(appmod, "sync_dnsmasq_panel_conf",
                        lambda c, **kw: {"ok": True, "mock": True})
    return create_app(":memory:").test_client()


def _put_lists(c, lists, enabled=True):
    r = c.put("/api/dns/filter", json={"enabled": enabled, "lists": lists})
    assert r.status_code == 200, r.get_json()
    return r


def _get(c):
    return c.get("/api/dns/filter").get_json()


def test_update_strict_true_vs_string_vs_query(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        c = _client(monkeypatch, wd)
        lists = [{"name": "good", "url": url, "enabled": True}]
        # boolean true -> refresh-only path, enabled flag untouched
        _put_lists(c, lists, enabled=False)
        r = c.post("/api/dns/filter/apply", json={"update": True})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["stage"] == "updated"
        assert _get(c)["enabled"] is False
        # truthy string -> full path, enabled flag set
        _put_lists(c, lists, enabled=False)
        r = c.post("/api/dns/filter/apply", json={"update": "true"})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["stage"] == "applied"
        assert _get(c)["enabled"] is True
        # legacy query spelling, no body key -> refresh-only path
        _put_lists(c, lists, enabled=False)
        r = c.post("/api/dns/filter/apply?update=1")
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["stage"] == "updated"
        assert _get(c)["enabled"] is False
        # neither -> full path
        r = c.post("/api/dns/filter/apply", json={})
        assert r.get_json()["stage"] == "applied"
        assert _get(c)["enabled"] is True


def test_list_id_validation(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        c = _client(monkeypatch, wd)
        _put_lists(c, [{"name": "good", "url": url, "enabled": True},
                       {"name": "off", "url": url, "enabled": False}])
        r = c.post("/api/dns/filter/apply", json={"listId": "nope"})
        assert r.status_code == 400
        assert r.get_json()["error"] == "只能更新已启用的过滤名单"
        # a disabled list's name is equally unknown for update purposes
        r = c.post("/api/dns/filter/apply", json={"listId": "off"})
        assert r.status_code == 400
        r = c.post("/api/dns/filter/apply", json={"listId": "good"})
        assert r.status_code == 200, r.get_json()


def test_list_id_before_busy_and_put_409(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        c = _client(monkeypatch, wd)
        _put_lists(c, [{"name": "good", "url": url, "enabled": True}])
        assert _get(c)["busy"] is False
        dfmod._APPLY_LOCK.acquire()
        try:
            assert _get(c)["busy"] is True
            # stale id still answers 400 with the id message, not busy
            r = c.post("/api/dns/filter/apply", json={"listId": "nope"})
            assert r.status_code == 400
            assert r.get_json()["error"] == "只能更新已启用的过滤名单"
            # a valid apply while busy answers 400 with the busy message
            r = c.post("/api/dns/filter/apply", json={})
            assert r.status_code == 400
            assert r.get_json()["error"] == "DNS 设置正在应用,请稍后重试"
            # settings refuse with 409 while busy
            r = c.put("/api/dns/filter", json={"enabled": True, "lists": []})
            assert r.status_code == 409
            assert r.get_json()["error"] == "名单正在更新,请稍后保存"
        finally:
            dfmod._APPLY_LOCK.release()
        assert _get(c)["busy"] is False


def test_all_failed_keeps_old_blocklist(monkeypatch):
    with tempfile.TemporaryDirectory() as wd:
        c = _client(monkeypatch, wd)
        path = dfmod.blocklist_path(wd)
        sentinel = b"# sentinel - old blocklist\naddress=/old.example.com/#\n"
        with open(path, "wb") as f:
            f.write(sentinel)
        _put_lists(c, [{"name": "down", "url": "http://127.0.0.1:1/x",
                        "enabled": True}])
        r = c.post("/api/dns/filter/apply", json={})
        assert r.status_code == 400, r.get_json()
        body = r.get_json()
        assert "旧拦截文件未动" in body["error"]
        assert body["total_domains"] == 0
        assert body["lists"][0]["error"]
        with open(path, "rb") as f:
            assert f.read() == sentinel
        assert _get(c)["applied_at"] == ""


def test_partial_failure_still_200(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        c = _client(monkeypatch, wd)
        _put_lists(c, [{"name": "good", "url": url, "enabled": True},
                       {"name": "down", "url": "http://127.0.0.1:1/x",
                        "enabled": True}])
        r = c.post("/api/dns/filter/apply", json={})
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body["total_domains"] == 2
        by_name = {s["name"]: s for s in body["lists"]}
        assert by_name["good"]["domains"] == 2
        assert by_name["down"]["error"]


def test_write_failure_is_400_not_500(monkeypatch):
    with tempfile.TemporaryDirectory() as wd, _StubServer() as url:
        c = _client(monkeypatch, wd)
        _put_lists(c, [{"name": "good", "url": url, "enabled": True}])

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(dfmod, "write_blocklist", _boom)
        r = c.post("/api/dns/filter/apply", json={})
        assert r.status_code == 400
        assert "写入拦截文件失败" in r.get_json()["error"]
