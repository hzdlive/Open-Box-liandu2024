"""Phase 4a tests: panel auth, pairing flow, client API.

Covers the stack-agnostic backend from docs/client-api.md.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent


def seed(conn):
    dbmod.add_subscription(conn, "t", (ROOT / "sample-sub.txt").read_text())


def test_auth_flow():
    app = create_app(":memory:")
    c = app.test_client()
    # no password -> dev mode open
    assert c.get("/api/auth/status").get_json() == {
        "has_password": False, "logged_in": False}
    assert c.get("/api/nodes").status_code == 200

    # set password (first time, no old needed)
    assert c.post("/api/auth/password", json={"new": "s3cret"}).status_code == 200
    st = c.get("/api/auth/status").get_json()
    assert st["has_password"] and not st["logged_in"]

    # now the gate is active
    assert c.get("/api/nodes").status_code == 401
    assert c.get("/").status_code == 200  # frontend static stays public
    assert c.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"password": "s3cret"}).status_code == 200
    assert c.get("/api/nodes").status_code == 200
    # too-short password rejected (when logged in)
    assert c.post("/api/auth/password", json={"new": "ab"}).status_code == 400
    # change password needs old
    assert c.post("/api/auth/password", json={"new": "newpw"}).status_code == 401
    assert c.post("/api/auth/password",
                  json={"old": "s3cret", "new": "newpw"}).status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/nodes").status_code == 401
    assert c.post("/api/auth/login", json={"password": "newpw"}).status_code == 200
    print("OK: auth login/logout/password + gate")


def test_pairing():
    app = create_app(":memory:")
    c = app.test_client()
    code = c.post("/api/pair/code").get_json()
    assert code["token"] and code["expires_in"] == 600

    r = c.post("/api/pair/confirm", json={"token": code["token"], "device": "Pixel"})
    assert r.status_code == 200, r.get_data(as_text=True)
    client_token = r.get_json()["client_token"]
    # one-time: reuse fails
    assert c.post("/api/pair/confirm",
                  json={"token": code["token"]}).status_code == 401
    # bad token fails
    assert c.post("/api/pair/confirm", json={"token": "nope"}).status_code == 401

    devs = c.get("/api/pair/devices").get_json()
    assert len(devs) == 1 and devs[0]["name"] == "Pixel"
    did = devs[0]["id"]
    assert c.delete(f"/api/pair/devices/{did}").status_code == 200
    assert c.get("/api/pair/devices").get_json() == []

    # expired code
    code2 = c.post("/api/pair/code").get_json()["token"]
    conn = app.config["DB"]
    conn.execute("UPDATE pair_codes SET expires_at=? WHERE token=?",
                 (time.time() - 1, code2))
    conn.commit()
    assert c.post("/api/pair/confirm", json={"token": code2}).status_code == 401
    print("OK: pairing one-time code + device management")


def _paired_client():
    app = create_app(":memory:")
    seed(app.config["DB"])
    c = app.test_client()
    tok = c.post("/api/pair/confirm", json={
        "token": c.post("/api/pair/code").get_json()["token"],
        "device": "test"}).get_json()["client_token"]
    return app, c, {"Authorization": f"Bearer {tok}"}


def test_client_api():
    app, c, hdr = _paired_client()

    r = c.get("/api/client/status", headers=hdr)
    assert r.status_code == 200
    st = r.get_json()
    assert st["mode"] == "rule" and st["rev"] >= 1 and "running" in st

    nodes = c.get("/api/client/nodes", headers=hdr).get_json()
    assert len(nodes) == 5 and "latency_ms" in nodes[0]

    groups = c.get("/api/client/groups", headers=hdr).get_json()
    assert any(g["name"] == "auto" for g in groups)

    # group select with no kernel -> 502, but validates input first
    r = c.post("/api/client/groups/auto/select", headers=hdr, json={})
    assert r.status_code == 400
    r = c.post("/api/client/groups/auto/select", headers=hdr,
               json={"tag": nodes[0]["tag"]})
    assert r.status_code == 502  # clash API not running here

    for mode, final in (("global", "auto"), ("rule", "auto"), ("direct", "direct")):
        conf = c.get(f"/api/client/config?mode={mode}", headers=hdr).get_json()
        assert conf["route"]["final"] == final, (mode, conf["route"]["final"])
        assert conf["inbounds"][0]["type"] == "tun"
        assert conf["inbounds"][0]["auto_route"] is False
    assert c.get("/api/client/config?mode=bogus", headers=hdr).status_code == 400
    conf = c.get("/api/client/config?ruleset=local", headers=hdr).get_json()
    assert conf["route"]["rules"] == [{"protocol": "dns", "outbound": "dns-out"}]

    assert c.get("/api/client/mode", headers=hdr).get_json() == {"mode": "rule"}
    assert c.post("/api/client/mode", headers=hdr,
                  json={"mode": "bogus"}).status_code == 400
    assert c.post("/api/client/mode", headers=hdr,
                  json={"mode": "global"}).get_json() == {"mode": "global"}

    # sync pull
    rev0 = c.get("/api/client/status", headers=hdr).get_json()["rev"]
    r = c.post("/api/client/subscriptions/sync", headers=hdr,
               json={"direction": "pull", "client_rev": rev0}).get_json()
    assert r["nodes"] == [] and r["rev"] == rev0
    r = c.post("/api/client/subscriptions/sync", headers=hdr,
               json={"direction": "pull", "client_rev": 0}).get_json()
    assert len(r["nodes"]) == 5
    # sync push
    r = c.post("/api/client/subscriptions/sync", headers=hdr, json={
        "direction": "push", "name": "from-phone",
        "content": "trojan://pw@1.1.1.1:443#push-node", "format": "auto"}).get_json()
    assert r["added"] == 1 and r["rev"] > rev0

    # wifi policy
    p = c.get("/api/client/wifi-policy", headers=hdr).get_json()
    assert p["enabled"] is False
    p2 = c.put("/api/client/wifi-policy", headers=hdr, json={
        "enabled": True, "pause_ssids": ["Home"], "action": "direct"}).get_json()
    assert p2["pause_ssids"] == ["Home"] and p2["action"] == "direct"
    assert c.put("/api/client/wifi-policy", headers=hdr,
                 json={"action": "bogus"}).status_code == 400
    print("OK: client API (status/nodes/groups/config/mode/sync/wifi)")


def test_client_api_needs_token_when_locked():
    app = create_app(":memory:")
    seed(app.config["DB"])
    c = app.test_client()
    c.post("/api/auth/password", json={"new": "pw1234"})
    # no bearer, no session -> 401 on client API
    assert c.get("/api/client/status").status_code == 401
    # pair confirm stays open (one-time code is the credential)
    code = c.post("/api/pair/code")  # needs login now
    assert code.status_code == 401
    c.post("/api/auth/login", json={"password": "pw1234"})
    code = c.post("/api/pair/code").get_json()["token"]
    c.post("/api/auth/logout")
    tok = c.post("/api/pair/confirm",
                 json={"token": code, "device": "d"}).get_json()["client_token"]
    r = c.get("/api/client/status",
              headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    # revoked device -> token dead
    assert c.get("/api/pair/devices").status_code == 401  # needs login
    c.post("/api/auth/login", json={"password": "pw1234"})
    did = c.get("/api/pair/devices").get_json()[0]["id"]
    c.delete(f"/api/pair/devices/{did}")
    # fresh client (no session cookie): revoked token must be dead
    c2 = app.test_client()
    assert c2.get("/api/client/status",
                  headers={"Authorization": f"Bearer {tok}"}).status_code == 401
    print("OK: client API auth (bearer, revocation, locked-down pairing)")


if __name__ == "__main__":
    test_auth_flow()
    test_pairing()
    test_client_api()
    test_client_api_needs_token_when_locked()
    print("ALL PHASE4A TESTS PASSED")
