"""Self-test for the Clash controller proxy (v7 #23 bD + hD wiring).

A stub kernel serves /proxies; the panel proxy must forward method,
path, query and body, return the upstream status/body, and schedule a
trailing-debounced selection sync only for successful PUT|DELETE whose
path contains /proxies/. WebSocket upgrades are refused, oversized
bodies are refused, and an unreachable kernel yields 502, never a crash.
"""
import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panel import app as appmod  # noqa: E402
from panel import db as dbmod  # noqa: E402
from core import selectionsync as selectionsync  # noqa: E402


class Stub:
    """Minimal kernel stub: records requests, serves /proxies state."""

    def __init__(self):
        self.seen = []
        self.now = {"G1": "node-b"}
        self.fail_paths = set()
        handler = self._make_handler()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def _make_handler(self):
        stub = self

        class H(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                stub.seen.append((self.command, self.path, body))
                if self.path.split("?")[0] in stub.fail_paths:
                    self._send(500, b'{"error":"boom"}')
                    return
                if self.command == "GET" and self.path.startswith("/proxies"):
                    proxies = {g: {"now": n, "type": "Selector"}
                               for g, n in stub.now.items()}
                    self._send(200, json.dumps({"proxies": proxies}).encode())
                    return
                self._send(200, b'{"ok":true}')

            def _send(self, code, payload):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _handle
            do_PUT = _handle
            do_POST = _handle
            do_DELETE = _handle
            do_PATCH = _handle

            def log_message(self, *a):
                pass

        return H

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _client_with_kernel(tmp_path, stub):
    dbfile = str(tmp_path / "panel.db")
    c = sqlite3.connect(dbfile)
    dbmod.init_db(c)
    dbmod.set_setting(c, "clash_api_port", str(stub.port))
    c.execute("INSERT INTO subscriptions(name, created_at, enabled)"
              " VALUES ('t', '2026-01-01', 1)")
    sid = c.execute("SELECT id FROM subscriptions").fetchone()[0]
    for tag in ("node-a", "node-b"):
        c.execute("INSERT INTO nodes(sub_id, tag, protocol, server, port)"
                  " VALUES (?, ?, 'vless', '1.2.3.4', 443)", (sid, tag))
    dbmod.create_group(c, {"name": "G1", "type": "selector",
                           "members": ["node-a", "node-b"]})
    c.execute("UPDATE groups SET default_outbound='node-a' WHERE name='G1'")
    c.commit()
    c.close()
    app = appmod.create_app(dbfile)
    return app.test_client(), dbfile


def _default(dbfile):
    c = sqlite3.connect(dbfile)
    try:
        row = c.execute("SELECT default_outbound FROM groups"
                        " WHERE name='G1'").fetchone()
    finally:
        c.close()
    return row[0] if row else None


def test_put_proxies_forwards_and_syncs(tmp_path):
    stub = Stub()
    try:
        client, dbfile = _client_with_kernel(tmp_path, stub)
        assert _default(dbfile) == "node-a"
        r = client.put("/api/controller/proxies/G1", json={"name": "node-b"})
        assert r.status_code == 200
        assert ("PUT", "/proxies/G1", b'{"name": "node-b"}') in [
            (m, p, b) for m, p, b in stub.seen]
        time.sleep(1.5)  # trailing debounce (0.6s) + reconcile
        assert _default(dbfile) == "node-b"
    finally:
        stub.stop()


def test_get_and_non_proxies_and_failed_put_do_not_sync(tmp_path):
    stub = Stub()
    try:
        client, dbfile = _client_with_kernel(tmp_path, stub)
        assert client.get("/api/controller/proxies").status_code == 200
        assert client.put("/api/controller/configs", json={}).status_code == 200
        stub.fail_paths.add("/proxies/G1")
        r = client.put("/api/controller/proxies/G1", json={"name": "node-b"})
        assert r.status_code == 500
        time.sleep(1.5)
        assert _default(dbfile) == "node-a"  # untouched by all three
    finally:
        stub.stop()


def test_unreachable_kernel_is_502_and_ws_refused(tmp_path):
    dbfile = str(tmp_path / "panel.db")
    c = sqlite3.connect(dbfile)
    dbmod.init_db(c)
    dbmod.set_setting(c, "clash_api_port", "59999")  # nothing listens
    c.close()
    app = appmod.create_app(dbfile)
    client = app.test_client()
    r = client.get("/api/controller/version")
    assert r.status_code == 502
    # NOTE: sending both Connection: Upgrade and Upgrade: websocket makes
    # the Werkzeug test client itself answer 400 on every endpoint (harness
    # quirk, not the handler); Upgrade alone reaches the handler fine.
    r = client.get("/api/controller/version",
                   headers={"Upgrade": "websocket"})
    assert r.status_code == 501


def test_oversized_body_is_413(tmp_path):
    dbfile = str(tmp_path / "panel.db")
    c = sqlite3.connect(dbfile)
    dbmod.init_db(c)
    c.close()
    app = appmod.create_app(dbfile)
    client = app.test_client()
    r = client.post("/api/controller/proxies/G1", data=b"x",
                    environ_overrides={
                        "CONTENT_LENGTH": str(26 * 1024 * 1024)})
    assert r.status_code == 413


def test_schedule_burst_runs_once():
    calls = []
    selectionsync.schedule(":memory:", delay=0.05,
                           run=lambda: calls.append(1))
    selectionsync.schedule(":memory:", delay=0.05,
                           run=lambda: calls.append(1))
    selectionsync.schedule(":memory:", delay=0.05,
                           run=lambda: calls.append(1))
    time.sleep(0.5)
    assert calls == [1]
