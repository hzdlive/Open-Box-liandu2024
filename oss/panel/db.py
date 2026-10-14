"""SQLite storage for the panel backend. Standard library only.

Tables: subscriptions, nodes, site_sets, settings.
"""

from __future__ import annotations

import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  tag TEXT NOT NULL UNIQUE,
  protocol TEXT NOT NULL,
  server TEXT NOT NULL,
  port INTEGER NOT NULL,
  params TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS site_sets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL DEFAULT 'proxy',
  grp TEXT NOT NULL DEFAULT 'auto',
  position INTEGER NOT NULL DEFAULT 0,
  rules TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "dns_direct": "223.5.5.5",
    "dns_proxy": "tcp://1.1.1.1",
    "final_outbound": "auto",
    "tun_stack": "mixed",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()


def add_subscription(conn: sqlite3.Connection, name: str, content: str,
                     source: str = "manual") -> tuple[int, int]:
    from core.subscription import parse_subscription
    nodes = parse_subscription(content)
    cur = conn.execute(
        "INSERT INTO subscriptions(name, source, created_at) VALUES (?, ?, ?)",
        (name, source, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    sid = cur.lastrowid
    existing = {r[0] for r in conn.execute("SELECT tag FROM nodes")}
    count = 0
    for n in nodes:
        tag, i = n.tag, 2
        while tag in existing:
            tag = f"{n.tag} #{i}"
            i += 1
        existing.add(tag)
        conn.execute(
            "INSERT INTO nodes(sub_id, tag, protocol, server, port, params)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (sid, tag, n.protocol, n.server, n.server_port,
             json.dumps(n.params, ensure_ascii=False)),
        )
        count += 1
    conn.commit()
    return sid, count


def list_subscriptions(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for sid, name, source, created in conn.execute(
            "SELECT id, name, source, created_at FROM subscriptions ORDER BY id"):
        n = conn.execute("SELECT COUNT(*) FROM nodes WHERE sub_id=?", (sid,)).fetchone()[0]
        out.append({"id": sid, "name": name, "source": source,
                    "created_at": created, "node_count": n})
    return out


def delete_subscription(conn: sqlite3.Connection, sid: int) -> bool:
    conn.execute("DELETE FROM nodes WHERE sub_id=?", (sid,))
    cur = conn.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
    conn.commit()
    return cur.rowcount > 0


def list_nodes(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"id": r[0], "tag": r[1], "protocol": r[2], "server": r[3],
         "port": r[4], "params": json.loads(r[5])}
        for r in conn.execute(
            "SELECT id, tag, protocol, server, port, params FROM nodes ORDER BY id")
    ]


def _rules_blob(d: dict) -> str:
    rules = d.get("rules", {}) if isinstance(d.get("rules"), dict) else {}

    def pick(key: str) -> list:
        v = rules.get(key, d.get(key, []))
        return list(v) if isinstance(v, list) else []

    return json.dumps({
        "domains": pick("domains"),
        "domain_suffix": pick("domain_suffix"),
        "domain_keyword": pick("domain_keyword"),
        "ip_cidr": pick("ip_cidr"),
    }, ensure_ascii=False)


def _site_set_row(r) -> dict:
    return {"id": r[0], "name": r[1], "action": r[2], "group": r[3],
            "position": r[4], "rules": json.loads(r[5])}


def list_site_sets(conn: sqlite3.Connection) -> list[dict]:
    return [_site_set_row(r) for r in conn.execute(
        "SELECT id, name, action, grp, position, rules FROM site_sets"
        " ORDER BY position, id")]


def create_site_set(conn: sqlite3.Connection, d: dict) -> dict:
    if d.get("action", "proxy") not in ("proxy", "direct", "reject"):
        raise ValueError("action must be proxy|direct|reject")
    pos = conn.execute("SELECT COALESCE(MAX(position), -1)+1 FROM site_sets").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO site_sets(name, action, grp, position, rules) VALUES (?, ?, ?, ?, ?)",
        (d["name"], d.get("action", "proxy"), d.get("group", "auto"), pos, _rules_blob(d)),
    )
    conn.commit()
    return _site_set_row(conn.execute(
        "SELECT id, name, action, grp, position, rules FROM site_sets WHERE id=?",
        (cur.lastrowid,)).fetchone())


def update_site_set(conn: sqlite3.Connection, sid: int, d: dict) -> dict | None:
    row = conn.execute("SELECT id FROM site_sets WHERE id=?", (sid,)).fetchone()
    if not row:
        return None
    fields, vals = [], []
    for col, key in (("name", "name"), ("action", "action"), ("grp", "group"), ("position", "position")):
        if key in d:
            if key == "action" and d[key] not in ("proxy", "direct", "reject"):
                raise ValueError("action must be proxy|direct|reject")
            fields.append(f"{col}=?")
            vals.append(d[key])
    if "rules" in d:
        fields.append("rules=?")
        vals.append(_rules_blob({"rules": d["rules"]}))
    if fields:
        vals.append(sid)
        conn.execute(f"UPDATE site_sets SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    return _site_set_row(conn.execute(
        "SELECT id, name, action, grp, position, rules FROM site_sets WHERE id=?",
        (sid,)).fetchone())


def delete_site_set(conn: sqlite3.Connection, sid: int) -> bool:
    cur = conn.execute("DELETE FROM site_sets WHERE id=?", (sid,))
    conn.commit()
    return cur.rowcount > 0


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()


def load_app_config(conn: sqlite3.Connection):
    from core.models import AppConfig, DnsConfig, Node, SiteSet
    nodes = [
        Node(tag=r[0], protocol=r[1], server=r[2], server_port=r[3],
             params=json.loads(r[4]))
        for r in conn.execute("SELECT tag, protocol, server, port, params FROM nodes ORDER BY id")
    ]
    site_sets = []
    for r in conn.execute(
            "SELECT name, action, grp, rules FROM site_sets ORDER BY position, id"):
        rules = json.loads(r[3])
        site_sets.append(SiteSet(
            name=r[0], action=r[1], group=r[2],
            domains=rules.get("domains", []),
            domain_suffix=rules.get("domain_suffix", []),
            domain_keyword=rules.get("domain_keyword", []),
            ip_cidr=rules.get("ip_cidr", []),
        ))
    dns = DnsConfig(direct_dns=get_setting(conn, "dns_direct", DEFAULT_SETTINGS["dns_direct"]),
                    proxy_dns=get_setting(conn, "dns_proxy", DEFAULT_SETTINGS["dns_proxy"]))
    return AppConfig(
        nodes=nodes, site_sets=site_sets, dns=dns,
        final_outbound=get_setting(conn, "final_outbound", "auto"),
        tun_stack=get_setting(conn, "tun_stack", "mixed"),
    )
