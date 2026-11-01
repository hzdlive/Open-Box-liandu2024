"""Wave6 settings wiring (2026-11-01): ipv6 / test_expected / tun_only.

- The three keys persist via PUT /api/settings (they used to be dropped
  and pinned as KNOWN_DEAD).
- ipv6: the transparent config reads the stored setting when no
  ?ipv6= query param is given; the default is off (UI hint), and an
  explicit query param still wins.
- test_expected: status-pattern parsing + the direct test judged by it.
- tun_only: persists only (no behavior consumer yet -- its original
  semantics are still unpinned, so nothing else is asserted for it).
"""

import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.health import direct_test, parse_status_pattern  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def test_three_keys_persist():
    c = _app().test_client()
    r = c.put("/api/settings", json={
        "ipv6": "1", "test_expected": "200-299", "tun_only": "1"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ipv6"] == "1"
    assert body["test_expected"] == "200-299"
    assert body["tun_only"] == "1"
    r = c.get("/api/settings")
    assert r.get_json()["ipv6"] == "1"
    assert r.get_json()["test_expected"] == "200-299"
    assert r.get_json()["tun_only"] == "1"


def test_ipv6_nft_script_default_off_and_param_wins():
    c = _app().test_client()
    # Fresh DB: no stored value, no param -> off (no bypass6 set).
    # (The "ip -6 rule" lines live in a different output, not this
    # script, so only bypass6 is asserted here.)
    r = c.get("/api/transparent/nft")
    assert r.status_code == 200
    script = r.get_json()["script"]
    assert "bypass6" not in script
    # Explicit query param still wins.
    r = c.get("/api/transparent/nft?ipv6=1")
    script = r.get_json()["script"]
    assert "bypass6" in script
    # Stored setting is consulted when no param is given.
    c.put("/api/settings", json={"ipv6": "1"})
    r = c.get("/api/transparent/nft")
    assert "bypass6" in r.get_json()["script"]
    c.put("/api/settings", json={"ipv6": "0"})
    r = c.get("/api/transparent/nft")
    assert "bypass6" not in r.get_json()["script"]
    # Stored on + explicit param off -> param wins.
    c.put("/api/settings", json={"ipv6": "1"})
    r = c.get("/api/transparent/nft?ipv6=0")
    assert "bypass6" not in r.get_json()["script"]


def test_status_pattern():
    assert parse_status_pattern("")(200)
    assert parse_status_pattern("*")(404)
    assert parse_status_pattern("200-299")(204)
    assert not parse_status_pattern("200-299")(404)
    assert parse_status_pattern("200,204")(204)
    assert not parse_status_pattern("200,204")(201)
    assert not parse_status_pattern("200-299")(None)
    with pytest.raises(ValueError):
        parse_status_pattern("abc")
    with pytest.raises(ValueError):
        parse_status_pattern("299-200")
    with pytest.raises(ValueError):
        parse_status_pattern("99")


class _OKHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def _local_server():
    srv = HTTPServer(("127.0.0.1", 0), _OKHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_direct_test_judged_by_pattern():
    srv = _local_server()
    url = f"http://127.0.0.1:{srv.server_address[1]}/generate_204"
    try:
        assert direct_test(url, "200-299")["ok"] is True
        assert direct_test(url, "404")["ok"] is False
        assert direct_test(url, "*")["ok"] is True
        bad = direct_test(url, "bogus")
        assert bad["ok"] is True  # invalid stored pattern -> unlimited
        assert "warning" in bad
        c = _app().test_client()
        r = c.post("/api/direct-test",
                   json={"url": url, "expected": "200-299"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["status"] == 200
        assert body["via"] == "direct"
        r = c.post("/api/direct-test",
                   json={"url": url, "expected": "404"})
        assert r.get_json()["ok"] is False
        r = c.post("/api/direct-test",
                   json={"url": url, "expected": "bogus"})
        assert r.status_code == 400
    finally:
        srv.shutdown()
