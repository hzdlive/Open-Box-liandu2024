"""v0.1.357: pinned-UA refresh, Xboard/V2Board login, fetch_ua edit.

- Refresh tries the stored fetch_ua first so a refresh does not
  silently switch to a different provider node list; a rejected pin
  falls back to the ladder and the UA that actually succeeded is
  recorded back. 429 still stops everything immediately.
- Login (Xboard/V2Board standard endpoints) imports nodes and
  traffic/plan info; the password is used for one POST only and must
  never appear in any stored subscription or node field.
- fetch_ua is editable via PATCH (ladder UA / "curl" / empty clears).
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
    def __init__(self, body=b"", headers=None):
        self._body = body
        self.headers = headers or {}

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


def test_pinned_ua_tried_first():
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        return FakeResp(b"ss://x")

    with mock.patch("urllib.request.urlopen", side_effect=fake):
        text, _info, ua = subfetch.fetch_subscription_text(
            "http://x/sub", pinned_ua="mihomo")
    assert text == "ss://x"
    assert ua == "mihomo"
    assert _uas(calls) == ["mihomo"]


def test_pinned_failure_falls_back_and_reports_new_ua():
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            raise _http_error(req.full_url, 403)
        return FakeResp(b"ss://x")

    with mock.patch("urllib.request.urlopen", side_effect=fake):
        _text, _info, ua = subfetch.fetch_subscription_text(
            "http://x/sub", pinned_ua="clash-verge")
    assert _uas(calls) == ["clash-verge", "ClashMetaForAndroid"]
    assert ua == "ClashMetaForAndroid"


def test_pinned_429_stops_immediately():
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        raise _http_error(req.full_url, 429)

    with mock.patch("urllib.request.urlopen", side_effect=fake), \
            mock.patch.object(subfetch.subprocess, "run") as run:
        try:
            subfetch.fetch_subscription_text("http://x/sub",
                                             pinned_ua="mihomo")
            raise AssertionError("expected FetchError")
        except subfetch.FetchError as e:
            assert "429" in str(e)
    assert len(calls) == 1
    run.assert_not_called()


def test_pinned_curl_tried_first():
    headers = b"HTTP/1.1 200 OK\r\n\r\n"
    body = b"ss://x"
    curl_out = headers + body + f"\n200 {len(headers)}".encode()
    proc = mock.Mock(returncode=0, stdout=curl_out, stderr=b"")
    with mock.patch("urllib.request.urlopen") as urlopen, \
            mock.patch.object(subfetch.subprocess, "run",
                              return_value=proc) as run:
        text, _info, ua = subfetch.fetch_subscription_text(
            "http://x/sub", pinned_ua="curl")
    assert text == "ss://x"
    assert ua == "curl"
    urlopen.assert_not_called()
    run.assert_called_once()


def _seed_app():
    app = create_app(":memory:")
    conn = sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])
    return app, conn


def test_refresh_persists_and_reuses_pin():
    app, conn = _seed_app()
    sample = (ROOT / "sample-sub.txt").read_text()
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=",
                                    url="http://x/sub")
    with mock.patch("core.subfetch.fetch_subscription_text",
                    return_value=(sample, {"total": 999},
                                  "ClashMetaForAndroid")):
        stats = dbmod.refresh_subscription(conn, sid)
    assert stats["fetch_ua"] == "ClashMetaForAndroid"
    row = conn.execute("SELECT fetch_ua FROM subscriptions WHERE id=?",
                       (sid,)).fetchone()
    assert row[0] == "ClashMetaForAndroid"
    listed = [s for s in dbmod.list_subscriptions(conn) if s["id"] == sid]
    assert listed and listed[0]["fetch_ua"] == "ClashMetaForAndroid"
    # Second refresh with the real fetcher: the pinned UA goes first.
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        return FakeResp(sample.encode())

    with mock.patch("urllib.request.urlopen", side_effect=fake):
        dbmod.refresh_subscription(conn, sid)
    assert _uas(calls)[0] == "ClashMetaForAndroid"
    conn.close()


def _login_router(sample, login_status=200):
    """Route mocked urlopen calls by panel endpoint."""
    def fake(req, timeout=None):
        url = req.full_url
        if "/passport/auth/login" in url:
            if login_status != 200:
                raise _http_error(url, login_status)
            return FakeResp(json.dumps(
                {"data": {"token": "tok123"}}).encode())
        if "/client/subscribe" in url:
            return FakeResp(sample.encode(), {
                "subscription-userinfo":
                    "upload=1; download=2; total=100"})
        if "/user/info" in url:
            return FakeResp(json.dumps(
                {"data": {"plan": {"name": "Pro"},
                          "transfer_enable": 100}}).encode())
        raise _http_error(url, 404)
    return fake


def test_login_creates_subscription_without_password():
    app, _conn = _seed_app()
    client = app.test_client()
    sample = (ROOT / "sample-sub.txt").read_text()
    password = "s3cret-pw-357"
    with mock.patch("urllib.request.urlopen",
                    side_effect=_login_router(sample)):
        r = client.post("/api/openbox/subscriptions/login", json={
            "site": "https://panel.example", "email": "u@example.com",
            "password": password, "name": "mypanel"})
    assert r.status_code == 201, r.get_json()
    data = r.get_json()
    assert data["node_count"] > 0
    assert data["plan"] and data["plan"].get("name") == "Pro"
    assert data["fetch_ua"] == "clash-verge"
    subs = client.get("/api/subscriptions").get_json()
    assert len(subs) == 1
    assert subs[0]["source"] == "login"
    assert any("token=tok123" in u for u in subs[0]["urls"])
    # The password must not appear in any stored field the API exposes.
    assert password not in json.dumps(subs, ensure_ascii=False)
    nodes = client.get(f"/api/subscriptions/{data['id']}/nodes").get_json()
    assert password not in json.dumps(nodes, ensure_ascii=False)


def test_login_bad_credentials_creates_nothing():
    app, _conn = _seed_app()
    client = app.test_client()
    sample = (ROOT / "sample-sub.txt").read_text()
    with mock.patch("urllib.request.urlopen",
                    side_effect=_login_router(sample, login_status=401)):
        r = client.post("/api/openbox/subscriptions/login", json={
            "site": "https://panel.example", "email": "u@example.com",
            "password": "wrong"})
    assert r.status_code == 400
    assert client.get("/api/subscriptions").get_json() == []


def test_patch_fetch_ua():
    app, conn = _seed_app()
    client = app.test_client()
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=",
                                    url="http://x/sub")
    r = client.patch(f"/api/openbox/subscriptions/{sid}",
                     json={"fetch_ua": "sing-box"})
    assert r.status_code == 200, r.get_json()
    assert "fetch_ua" in r.get_json()["changed"]
    listed = [s for s in dbmod.list_subscriptions(conn) if s["id"] == sid]
    assert listed[0]["fetch_ua"] == "sing-box"
    r = client.patch(f"/api/openbox/subscriptions/{sid}",
                     json={"fetch_ua": "bogus"})
    assert r.status_code == 400
    r = client.patch(f"/api/openbox/subscriptions/{sid}",
                     json={"fetch_ua": ""})
    assert r.status_code == 200
    listed = [s for s in dbmod.list_subscriptions(conn) if s["id"] == sid]
    assert listed[0]["fetch_ua"] is None
    conn.close()
