"""Wave6 item 1: the 17 partial-coverage endpoints, implemented batch.

Covers the well-defined fixes (small 6 + groups bulk PUT + subscriptions
PATCH + rulesets preview/import + content-filter source + rulesets
entries + bulk nodes latency). Deliberately NOT covered here (shapes or
semantics still unpinned, see panel-partial-17-verification.md):
- profile GET/PUT (inner profile schema unknown from the contract)
- nodes/latency/queue (needs an async job model first)
- policies/entries (contract keys empty)
"""

import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def _conn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


def test_config_preview_wraps_config():
    app = _app()
    r = app.test_client().get("/api/openbox/config/preview")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"config"}
    assert isinstance(body["config"], dict)


def test_defaults_endpoints():
    c = _app().test_client()
    r = c.get("/api/openbox/defaults/groups")
    assert r.status_code == 200
    names = [g["name"] for g in r.get_json()["groups"]]
    assert names == ["所有-自动", "所有-手动"]
    r = c.get("/api/openbox/defaults/routing")
    assert r.status_code == 200
    routing = r.get_json()["routing"]
    assert routing["final_outbound"] == "所有-自动"
    assert routing["routing_fallback"] == "direct"
    r = c.get("/api/openbox/profile/defaults")
    assert r.status_code == 200
    body = r.get_json()
    assert body["defaults"]["dns_direct"] == "223.5.5.5"
    assert body["dnsRewriteDefaults"] == []


def test_kernel_version_keys():
    r = _app().test_client().get("/api/openbox/kernel/version")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"ok", "raw", "version"}
    assert isinstance(body["ok"], bool)


def test_latency_history_version():
    app = _app()
    c = app.test_client()
    r = c.get("/api/openbox/latency-history/version")
    assert r.status_code == 200
    assert r.get_json() == {"updatedAt": None}
    conn = _conn(app)
    conn.execute("INSERT INTO latency_history(tag, ok, latency_ms, checked_at)"
                 " VALUES ('n1', 1, 42, '2026-10-31T10:00:00')")
    conn.commit()
    r = c.get("/api/openbox/latency-history/version")
    assert r.get_json() == {"updatedAt": "2026-10-31T10:00:00"}


def test_content_filter_source():
    app = _app()
    c = app.test_client()
    conn = _conn(app)
    conn.execute("INSERT INTO cf_rulesets(id, name, dialect, text)"
                 " VALUES ('t1', 'Test', 'surge', 'DOMAIN-SUFFIX,example.com,REJECT')")
    conn.commit()
    r = c.get("/api/openbox/content-filter/t1/source")
    assert r.status_code == 200
    assert r.get_json() == {"text": "DOMAIN-SUFFIX,example.com,REJECT"}
    r = c.get("/api/openbox/content-filter/nope/source")
    assert r.status_code == 404


def test_rulesets_entries_errors():
    c = _app().test_client()
    r = c.get("/api/openbox/rulesets/entries")
    assert r.status_code == 400
    assert r.get_json()["message"] == "tag is required"
    r = c.get("/api/openbox/rulesets/entries?tag=geosite-nope")
    assert r.status_code == 400
    assert r.get_json()["tag"] == "geosite-nope"


def test_rulesets_preview_errors():
    c = _app().test_client()
    r = c.get("/api/openbox/rulesets/preview")
    assert r.status_code == 400
    r = c.get("/api/openbox/rulesets/preview?url=http://127.0.0.1:1/x.list")
    assert r.status_code == 400
    assert "fetch failed" in r.get_json()["message"]


class _ListHandler(BaseHTTPRequestHandler):
    BODY = (b"DOMAIN-SUFFIX,example.com,REJECT\n"
            b"DOMAIN-SUFFIX,ads.example.org,REJECT\n")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(self.BODY)

    def log_message(self, *a):
        pass


def _local_server():
    srv = HTTPServer(("127.0.0.1", 0), _ListHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_rulesets_preview_and_import_success():
    srv = _local_server()
    url = f"http://127.0.0.1:{srv.server_address[1]}/x.list"
    try:
        app = _app()
        c = app.test_client()
        r = c.get(f"/api/openbox/rulesets/preview?url={url}")
        assert r.status_code == 200
        body = r.get_json()
        assert body["total"] == 2
        assert body["matched"] == 2
        assert body["url"] == url
        assert {e["value"] for e in body["entries"]} == {
            "example.com", "ads.example.org"}
        r = c.get(f"/api/openbox/rulesets/preview?url={url}&q=ads")
        assert r.get_json()["matched"] == 1
        r = c.post("/api/openbox/rulesets/import",
                   json={"url": url, "name": "preview-import"})
        assert r.status_code == 200
        assert r.get_json()["total"] == 2
        rows = c.get("/api/rulesets").get_json()
        assert any(g["name"] == "preview-import" for g in rows)
    finally:
        srv.shutdown()


def test_groups_bulk_put():
    app = _app()
    c = app.test_client()
    g1 = c.post("/api/groups", json={"name": "G1", "type": "selector",
                                     "members": []}).get_json()
    g2 = c.post("/api/groups", json={"name": "G2", "type": "selector",
                                     "members": []}).get_json()
    # Rename G1, drop G2, add G3; built-ins omitted but kept.
    r = c.put("/api/openbox/groups", json={"groups": [
        {"id": g1["id"], "name": "G1-renamed", "type": "selector",
         "members": []},
        {"name": "G3", "type": "selector", "members": ["ghost-node"]},
    ]})
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"applied", "dangling", "dropped", "groups",
                         "ok", "renamed"}
    assert body["ok"] is True
    assert body["applied"] == 2
    assert body["dropped"] == [g2["id"]]
    assert body["renamed"] == [g1["id"]]
    assert "ghost-node" in body["dangling"]
    names = [g["name"] for g in body["groups"]]
    assert "所有-自动" in names and "所有-手动" in names
    assert "G1-renamed" in names and "G3" in names
    assert "G2" not in names
    # Unknown id and bad type fail before any write.
    r = c.put("/api/openbox/groups",
              json={"groups": [{"id": 999999, "name": "X"}]})
    assert r.status_code == 400
    r = c.put("/api/openbox/groups",
              json={"groups": [{"name": "X", "type": "bogus"}]})
    assert r.status_code == 400


def test_subscriptions_patch_and_put_regression():
    app = _app()
    c = app.test_client()
    # Content mode (no network fetch): one ss node.
    sub = c.post("/api/subscriptions",
                 json={"name": "S1",
                       "content": "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@"
                                  "127.0.0.1:8388#testnode"}).get_json()
    assert "id" in sub, sub
    sid = sub["id"]
    assert sub["node_count"] == 1
    # PUT still works after the refactor.
    r = c.put(f"/api/subscriptions/{sid}", json={"name": "S1-put"})
    assert r.status_code == 200
    assert r.get_json()["name"] == "S1-put"
    # PATCH: change report, node count, skipped. Flip enabled from its
    # current value so the change is guaranteed.
    cur = c.get(f"/api/subscriptions/{sid}").get_json()
    flip = not cur["enabled"] if "enabled" in cur else False
    r = c.patch(f"/api/openbox/subscriptions/{sid}",
                json={"name": "S1-patch", "enabled": flip})
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"changed", "id", "name", "nodeCount", "skipped"}
    assert body["id"] == sid
    assert body["name"] == "S1-patch"
    assert "name" in body["changed"] and "enabled" in body["changed"]
    assert body["nodeCount"] == 1
    assert body["skipped"] == 0
    # No-op PATCH reports no changes.
    r = c.patch(f"/api/openbox/subscriptions/{sid}",
                json={"name": "S1-patch"})
    assert r.get_json()["changed"] == []
    r = c.patch("/api/openbox/subscriptions/999999", json={"name": "X"})
    assert r.status_code == 404
    r = c.patch(f"/api/openbox/subscriptions/{sid}",
                json={"auto_update": {"days": 0}})
    assert r.status_code == 200  # days clamped to >=1, not an error
    r = c.patch(f"/api/openbox/subscriptions/{sid}",
                json={"auto_update": {"days": "bad"}})
    assert r.status_code == 400


def test_nodes_latency_empty():
    r = _app().test_client().post("/api/openbox/nodes/latency", json={})
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"history", "results"}
    assert body["results"] == []
    assert body["history"] == {}
