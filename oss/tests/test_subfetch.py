"""Subscription UA ladder (third-party report §6).

- Six UAs in order; any non-429 failure tries the next UA.
- 429 stops the ladder immediately (no further UAs, no curl).
- Only after all UAs are rejected does the system curl fallback run.
- A successful fetch that parses to zero nodes is "订阅是空的"
  and must never wipe existing nodes on refresh.
"""

import json
import sqlite3
import sys
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import subfetch  # noqa: E402
from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent


class FakeResp:
    def __init__(self, body=b"", headers=None, status=200):
        self._body = body
        self.headers = headers or {}
        self.status = status

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(url, code):
    return urllib.error.HTTPError(url, code, "err", {}, None)


def _uas(calls):
    return [req.get_header("User-agent") for req in calls]


def test_ladder_order_and_second_ua_success():
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            raise _http_error(req.full_url, 403)
        return FakeResp(b"ss://x", {"subscription-userinfo": "upload=1; download=2"})

    with mock.patch("urllib.request.urlopen", side_effect=fake):
        text, info = subfetch.fetch_subscription_text("http://x/sub")
    assert text == "ss://x"
    assert info == {"upload": 1, "download": 2}
    assert _uas(calls) == subfetch.UA_LADDER[:2]


def test_429_stops_ladder_immediately():
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        raise _http_error(req.full_url, 429)

    with mock.patch("urllib.request.urlopen", side_effect=fake), \
            mock.patch.object(subfetch.subprocess, "run") as run:
        try:
            subfetch.fetch_subscription_text("http://x/sub")
            raise AssertionError("expected FetchError")
        except subfetch.FetchError as e:
            assert "429" in str(e)
    assert len(calls) == 1
    run.assert_not_called()


def test_all_rejected_falls_back_to_curl():
    body = b"line1\n\nline3"
    headers = (b"HTTP/1.1 200 OK\r\n"
               b"subscription-userinfo: upload=10; total=20\r\n\r\n")
    trailer = f"\n200 {len(headers)}".encode()
    curl_out = headers + body + trailer
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        raise _http_error(req.full_url, 403)

    proc = mock.Mock(returncode=0, stdout=curl_out, stderr=b"")
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
            mock.patch.object(subfetch.subprocess, "run",
                              return_value=proc) as run:
        text, info = subfetch.fetch_subscription_text("http://x/sub")
    assert text == "line1\n\nline3"
    assert info == {"upload": 10, "total": 20}
    assert len(calls) == len(subfetch.UA_LADDER)
    run.assert_called_once()
    assert run.call_args[0][0][0] == "curl"


def test_curl_failure_reports_ladder_exhausted():
    def fake(req, timeout=None):
        raise _http_error(req.full_url, 403)

    proc = mock.Mock(returncode=22, stdout=b"", stderr=b"404")
    with mock.patch("urllib.request.urlopen", side_effect=fake), \
            mock.patch.object(subfetch.subprocess, "run", return_value=proc):
        try:
            subfetch.fetch_subscription_text("http://x/sub")
            raise AssertionError("expected FetchError")
        except subfetch.FetchError as e:
            assert "curl" in str(e)


def test_over_cap_fails_that_attempt_only():
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            return FakeResp(b"x" * 11)
        return FakeResp(b"ok")

    with mock.patch("urllib.request.urlopen", side_effect=fake), \
            mock.patch.object(subfetch, "MAX_DOWNLOAD_BYTES", 10):
        text, _ = subfetch.fetch_subscription_text("http://x/sub")
    assert text == "ok"
    assert len(calls) == 2


def test_parse_userinfo():
    assert subfetch.parse_userinfo(
        "upload=123; download=456; total=789; expire=1700000000; junk") == {
        "upload": 123, "download": 456, "total": 789, "expire": 1700000000}
    assert subfetch.parse_userinfo("upload=abc") == {}


def test_curl_output_429_and_bad_status():
    try:
        subfetch._parse_curl_output(b"HTTP/1.1 429 X\r\n\r\n\n429 18")
        raise AssertionError("expected _RateLimited")
    except subfetch._RateLimited:
        pass
    try:
        subfetch._parse_curl_output(b"HTTP/1.1 500 X\r\n\r\n\n500 18")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "500" in str(e)


def _seed_app():
    app = create_app(":memory:")
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    return app, conn


def test_refresh_empty_result_keeps_nodes():
    app, conn = _seed_app()
    sid, _ = dbmod.add_subscription(
        conn, "s", (ROOT / "sample-sub.txt").read_text(),
        url="http://x/sub")
    before = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE sub_id=?", (sid,)).fetchone()[0]
    assert before > 0
    # db.py imports fetch_subscription_text at call time, so patching
    # the module attribute is what the refresh path resolves.
    import panel.db as dbmod2
    with mock.patch("core.subfetch.fetch_subscription_text",
                    return_value=("", {})):
        try:
            dbmod2.refresh_subscription(conn, sid)
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert str(e) == "订阅是空的"
    after = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE sub_id=?", (sid,)).fetchone()[0]
    assert after == before
    conn.close()


def test_refresh_success_replaces_nodes():
    app, conn = _seed_app()
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=",
                                    url="http://x/sub")
    sample = (ROOT / "sample-sub.txt").read_text()
    with mock.patch("core.subfetch.fetch_subscription_text",
                    return_value=(sample, {"total": 999})):
        import panel.db as dbmod2
        stats = dbmod2.refresh_subscription(conn, sid)
    assert stats["node_count"] > 0
    conn.close()


def test_preview_empty_result_reports_empty():
    app = create_app(":memory:")
    c = app.test_client()
    with mock.patch("core.subfetch.fetch_subscription_text",
                    return_value=("", {})):
        r = c.post("/api/openbox/subscriptions/preview",
                   json={"urls": ["http://x/sub"]})
    data = r.get_json()
    assert data["nodes"] == []
    assert any(e.get("error") == "订阅是空的" for e in data["errors"])
