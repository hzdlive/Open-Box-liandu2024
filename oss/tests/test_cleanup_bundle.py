"""Cleanup bundle (item 2): config preview cf caliber, failover
member_count, direct-bypass wiring. (The rule-0 comment alignment is
comment-only; test_core already pins bypass as route rule #0.)"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def _dbconn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


def _bypass_rules(conf):
    out = []
    for r in conf["route"]["rules"]:
        if r.get("type") != "logical":
            continue
        subs = r.get("rules") or []
        if any(s.get("rule_set") == "obnode-direct-ip" for s in subs
               if isinstance(s, dict)):
            out.append(r)
    return out


def test_config_preview_includes_blocked_domains():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    conn.execute(
        "INSERT INTO cf_rulesets(id, name, rules, enabled, updated_at)"
        " VALUES ('testcleanup01', 't', ?, 1, '2099-01-01T00:00:00')",
        (json.dumps([{"action": "reject", "pattern": "blocked.example.com",
                      "type": "domain_suffix"}]),))
    conn.commit()
    conn.close()
    conf = c.get("/api/config").get_json()
    blocks = [r for r in conf["route"]["rules"]
              if r.get("outbound") == "block"
              and "blocked.example.com" in (r.get("domain_suffix") or [])]
    assert blocks, "preview must carry the content-filter block rule"


def test_failover_member_count():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    sid, _ = dbmod.add_subscription(conn, "s", "vmess://e30=")
    for tag in ("n1", "n2"):
        conn.execute(
            "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
            " VALUES (?, ?, 'vmess', 'example.com', 443, '{}')",
            (sid, tag))
    conn.execute(
        "INSERT INTO groups(name, type, members, lanes)"
        " VALUES ('fo', 'failover', '[]', ?)",
        (json.dumps([{"name": "主用", "members": ["n1", "n2"], "mode": "auto"},
                     {"name": "备用", "members": ["n2"], "mode": "auto"}]),))
    conn.execute(
        "INSERT INTO groups(name, type, members) VALUES ('u', 'urltest', ?)",
        (json.dumps(["n1"]),))
    conn.commit()
    conn.close()
    groups = {g["name"]: g for g in c.get("/api/groups").get_json()}
    assert groups["fo"]["member_count"] == 2  # unique lane members
    assert groups["u"]["member_count"] == 1


def test_direct_bypass_wiring():
    from core.models import AppConfig
    from core.singbox import build_config

    # Setting off -> no logical bypass rule; on (default) -> present.
    assert not _bypass_rules(build_config(
        AppConfig(direct_bypass_enabled=False)))
    assert _bypass_rules(build_config(AppConfig()))  # default on

    # load_app_config wires the setting into the config object.
    app = _app()
    conn = _dbconn(app)
    dbmod.set_setting(conn, "direct_bypass_kernel", "0")
    assert dbmod.load_app_config(conn).direct_bypass_enabled is False
    dbmod.set_setting(conn, "direct_bypass_kernel", "1")
    assert dbmod.load_app_config(conn).direct_bypass_enabled is True
    conn.close()
