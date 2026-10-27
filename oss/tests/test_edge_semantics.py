"""Edge semantics bundle (third-party report §7-§9, implemented subset).

- Share tokens: 24 random bytes -> 48 hex; a user-supplied token is
  used only when 40-64 hex and unoccupied, else silently replaced.
- Subscription delete is idempotent (unknown id -> 200); share delete
  still 404s on unknown id.
- node-info serves enabled nodes; disabled nodes answer "not found"
  (manual nodes live inside subscriptions in our model, so the
  enabled check is the operative part of the original's scope).
- Outbound generation failure answers 400 with the original's prefix.
"""

import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402

HEX48 = re.compile(r"^[0-9a-f]{48}$")


def _app():
    return create_app(":memory:")


def _dbconn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


def test_share_token_format_and_user_token():
    app = _app()
    c = app.test_client()
    s = c.post("/api/subscription-shares",
               json={"name": "a"}).get_json()
    assert HEX48.match(s["token"]), s["token"]

    good = "ab" * 20  # 40 hex
    s2 = c.post("/api/subscription-shares",
                json={"name": "b", "token": good}).get_json()
    assert s2["token"] == good

    # Occupied token is silently replaced.
    s3 = c.post("/api/subscription-shares",
                json={"name": "c", "token": good}).get_json()
    assert s3["token"] != good and HEX48.match(s3["token"])

    # Too short / non-hex tokens are silently replaced.
    for bad in ("ab" * 19, "zz" * 20, "ab" * 33):
        s4 = c.post("/api/subscription-shares",
                    json={"name": "d", "token": bad}).get_json()
        assert s4["token"] != bad and HEX48.match(s4["token"])

    # Regenerate: new 48-hex token, old one dead.
    r = c.post(f"/api/subscription-shares/{s['id']}/regenerate").get_json()
    assert r["token"] != s["token"] and HEX48.match(r["token"])
    assert c.get(f"/sub/{s['token']}").status_code == 404


def test_subscription_delete_is_idempotent():
    app = _app()
    c = app.test_client()
    assert c.delete("/api/subscriptions/999").status_code == 200
    assert c.delete("/api/subscriptions/999").get_json() == {"ok": True}
    # Share delete keeps its 404.
    assert c.delete("/api/subscription-shares/999").status_code == 404


def _seed_nodes(app):
    conn = _dbconn(app)
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=")
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params, disabled)"
        " VALUES (?, 'off1', 'vmess', 'example.com', 443, '{}', 1)",
        (sid,))
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
        " VALUES (?, 'on1', 'vmess', 'example.com', 443, '{}')",
        (sid,))
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
        " VALUES (?, 'wg1', 'wireguard', 'example.com', 51820, '{}')",
        (sid,))
    conn.commit()
    conn.close()


def test_node_info_scope():
    # Enabled nodes are served; disabled ones answer "not found".
    # (Manual nodes live inside subscriptions in our model -- source
    # defaults to 'manual' even for URL subscriptions -- so no source
    # filter can separate them; the enabled check is the operative
    # part of the original's subscription-node scope here.)
    app = _app()
    _seed_nodes(app)
    c = app.test_client()
    assert c.get("/api/node-info/off1").get_json() == {"error": "not found"}
    d = c.get("/api/node-info/on1").get_json()
    assert d["ok"] is False and "暂无缓存" in d["message"]


def test_node_info_outbound_failure_is_400():
    app = _app()
    _seed_nodes(app)
    c = app.test_client()
    mgr = SimpleNamespace(bin_path="/bin/true")
    with mock.patch("core.service.manager_from_env", return_value=mgr):
        r = c.post("/api/node-info/wg1/exit")
    assert r.status_code == 400, r.get_json()
    assert r.get_json()["error"].startswith("生成不出这个节点的出站:")
