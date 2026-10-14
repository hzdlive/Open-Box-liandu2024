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
CREATE TABLE IF NOT EXISTS rule_sets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL DEFAULT '',
  format TEXT NOT NULL DEFAULT 'auto',
  content TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chains(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  exit_protocol TEXT NOT NULL DEFAULT 'socks',
  server TEXT NOT NULL DEFAULT '',
  port INTEGER NOT NULL DEFAULT 0,
  params TEXT NOT NULL DEFAULT '{}',
  front TEXT NOT NULL DEFAULT 'auto'
);
CREATE TABLE IF NOT EXISTS groups(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL DEFAULT 'urltest',
  members TEXT NOT NULL DEFAULT '[]',
  dynamic_keywords TEXT NOT NULL DEFAULT '[]',
  position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS node_health(
  tag TEXT PRIMARY KEY,
  ok INTEGER,
  latency_ms REAL,
  error TEXT NOT NULL DEFAULT '',
  checked_at TEXT NOT NULL DEFAULT ''
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
    # default outbound groups: auto = urltest over nodes, manual = selector over all
    conn.execute(
        "INSERT OR IGNORE INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('auto', 'urltest', '[\"*nodes*\"]', '[]', 0)")
    conn.execute(
        "INSERT OR IGNORE INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('manual', 'selector', '[\"*all*\"]', '[]', 1)")
    conn.commit()


def add_subscription(conn: sqlite3.Connection, name: str, content: str,
                     source: str = "manual", format: str = "auto") -> tuple[int, int]:
    from core.subscription import parse_subscription
    from core.clash import parse_clash_yaml, looks_like_clash
    if format == "clash" or (format == "auto" and looks_like_clash(content)):
        nodes = parse_clash_yaml(content)
    else:
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
        "rule_sets": list(rules.get("rule_sets", d.get("rule_sets", []))),
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
    from core.models import AppConfig, Chain, DnsConfig, Group, Node, SiteSet
    from core.ruleset import parse_ruleset_text
    nodes = [
        Node(tag=r[0], protocol=r[1], server=r[2], server_port=r[3],
             params=json.loads(r[4]))
        for r in conn.execute("SELECT tag, protocol, server, port, params FROM nodes ORDER BY id")
    ]
    # rule set contents, parsed once
    rs_parsed = {}
    for name, fmt, content in conn.execute("SELECT name, format, content FROM rule_sets"):
        if content:
            try:
                rs_parsed[name] = parse_ruleset_text(content, fmt)
            except Exception:
                pass
    site_sets = []
    for r in conn.execute(
            "SELECT name, action, grp, rules FROM site_sets ORDER BY position, id"):
        rules = json.loads(r[3])
        domains = list(rules.get("domains", []))
        suffix = list(rules.get("domain_suffix", []))
        keyword = list(rules.get("domain_keyword", []))
        cidrs = list(rules.get("ip_cidr", []))
        rs_names = list(rules.get("rule_sets", []))
        for rs_name in rs_names:
            parsed = rs_parsed.get(rs_name)
            if parsed:
                domains += parsed["domains"]
                suffix += parsed["domain_suffix"]
                keyword += parsed["domain_keyword"]
                cidrs += parsed["ip_cidr"]
        site_sets.append(SiteSet(
            name=r[0], action=r[1], group=r[2],
            domains=list(dict.fromkeys(domains)),
            domain_suffix=list(dict.fromkeys(suffix)),
            domain_keyword=list(dict.fromkeys(keyword)),
            ip_cidr=list(dict.fromkeys(cidrs)),
            rule_sets=rs_names,
        ))
    groups = [
        Group(name=r[0], type=r[1], members=json.loads(r[2]),
              dynamic_keywords=json.loads(r[3]), position=r[4])
        for r in conn.execute(
            "SELECT name, type, members, dynamic_keywords, position FROM groups"
            " ORDER BY position, id")
    ]
    chains = [
        Chain(name=r[0], exit_protocol=r[1], server=r[2], server_port=r[3],
              params=json.loads(r[4]), front=r[5])
        for r in conn.execute(
            "SELECT name, exit_protocol, server, port, params, front FROM chains ORDER BY id")
    ]
    dns = DnsConfig(direct_dns=get_setting(conn, "dns_direct", DEFAULT_SETTINGS["dns_direct"]),
                    proxy_dns=get_setting(conn, "dns_proxy", DEFAULT_SETTINGS["dns_proxy"]))
    return AppConfig(
        nodes=nodes, site_sets=site_sets, groups=groups, chains=chains, dns=dns,
        final_outbound=get_setting(conn, "final_outbound", "auto"),
        tun_stack=get_setting(conn, "tun_stack", "mixed"),
    )


# ---- rule sets ----
def list_rule_sets(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r[0], "name": r[1], "url": r[2], "format": r[3],
             "updated_at": r[4], "size": len(r[5] or "")}
            for r in conn.execute(
                "SELECT id, name, url, format, updated_at, content FROM rule_sets ORDER BY id")]


def create_rule_set(conn: sqlite3.Connection, d: dict) -> dict:
    cur = conn.execute(
        "INSERT INTO rule_sets(name, url, format) VALUES (?, ?, ?)",
        (d["name"], d.get("url", ""), d.get("format", "auto")))
    conn.commit()
    return get_rule_set(conn, cur.lastrowid)


def get_rule_set(conn: sqlite3.Connection, rid: int) -> dict | None:
    r = conn.execute(
        "SELECT id, name, url, format, updated_at, content FROM rule_sets WHERE id=?",
        (rid,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "name": r[1], "url": r[2], "format": r[3],
            "updated_at": r[4], "content": r[5]}


def update_rule_set(conn: sqlite3.Connection, rid: int, d: dict) -> dict | None:
    if not get_rule_set(conn, rid):
        return None
    fields, vals = [], []
    for col, key in (("name", "name"), ("url", "url"), ("format", "format")):
        if key in d:
            fields.append(f"{col}=?")
            vals.append(d[key])
    if fields:
        vals.append(rid)
        conn.execute(f"UPDATE rule_sets SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    return get_rule_set(conn, rid)


def delete_rule_set(conn: sqlite3.Connection, rid: int) -> bool:
    cur = conn.execute("DELETE FROM rule_sets WHERE id=?", (rid,))
    conn.commit()
    return cur.rowcount > 0


def refresh_rule_set(conn: sqlite3.Connection, rid: int, timeout: int = 15) -> dict:
    from core.ruleset import fetch_ruleset
    rs = get_rule_set(conn, rid)
    if not rs:
        raise KeyError("not found")
    if not rs["url"]:
        raise ValueError("rule set has no url")
    content = fetch_ruleset(rs["url"], timeout=timeout)
    conn.execute("UPDATE rule_sets SET content=?, updated_at=? WHERE id=?",
                 (content, time.strftime("%Y-%m-%dT%H:%M:%S"), rid))
    conn.commit()
    return get_rule_set(conn, rid)


# ---- chains ----
def _chain_row(r) -> dict:
    return {"id": r[0], "name": r[1], "exit_protocol": r[2], "server": r[3],
            "port": r[4], "params": json.loads(r[5]), "front": r[6]}


def list_chains(conn: sqlite3.Connection) -> list[dict]:
    return [_chain_row(r) for r in conn.execute(
        "SELECT id, name, exit_protocol, server, port, params, front FROM chains ORDER BY id")]


def create_chain(conn: sqlite3.Connection, d: dict) -> dict:
    if d.get("exit_protocol", "socks") not in ("socks", "http"):
        raise ValueError("exit_protocol must be socks|http")
    cur = conn.execute(
        "INSERT INTO chains(name, exit_protocol, server, port, params, front)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (d["name"], d.get("exit_protocol", "socks"), d.get("server", ""),
         int(d.get("port", 0)), json.dumps(d.get("params", {}), ensure_ascii=False),
         d.get("front", "auto")))
    conn.commit()
    return _chain_row(conn.execute(
        "SELECT id, name, exit_protocol, server, port, params, front FROM chains WHERE id=?",
        (cur.lastrowid,)).fetchone())


def update_chain(conn: sqlite3.Connection, cid: int, d: dict) -> dict | None:
    row = conn.execute("SELECT id FROM chains WHERE id=?", (cid,)).fetchone()
    if not row:
        return None
    fields, vals = [], []
    for col, key in (("name", "name"), ("exit_protocol", "exit_protocol"),
                     ("server", "server"), ("port", "port"), ("front", "front")):
        if key in d:
            if key == "exit_protocol" and d[key] not in ("socks", "http"):
                raise ValueError("exit_protocol must be socks|http")
            fields.append(f"{col}=?")
            vals.append(d[key])
    if "params" in d:
        fields.append("params=?")
        vals.append(json.dumps(d["params"], ensure_ascii=False))
    if fields:
        vals.append(cid)
        conn.execute(f"UPDATE chains SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    return _chain_row(conn.execute(
        "SELECT id, name, exit_protocol, server, port, params, front FROM chains WHERE id=?",
        (cid,)).fetchone())


def delete_chain(conn: sqlite3.Connection, cid: int) -> bool:
    cur = conn.execute("DELETE FROM chains WHERE id=?", (cid,))
    conn.commit()
    return cur.rowcount > 0


# ---- groups ----
def _group_row(r) -> dict:
    return {"id": r[0], "name": r[1], "type": r[2], "members": json.loads(r[3]),
            "dynamic_keywords": json.loads(r[4]), "position": r[5]}


def list_groups(conn: sqlite3.Connection) -> list[dict]:
    return [_group_row(r) for r in conn.execute(
        "SELECT id, name, type, members, dynamic_keywords, position FROM groups"
        " ORDER BY position, id")]


def create_group(conn: sqlite3.Connection, d: dict) -> dict:
    if d.get("type", "urltest") not in ("urltest", "selector"):
        raise ValueError("type must be urltest|selector")
    pos = conn.execute("SELECT COALESCE(MAX(position), -1)+1 FROM groups").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES (?, ?, ?, ?, ?)",
        (d["name"], d.get("type", "urltest"),
         json.dumps(d.get("members", []), ensure_ascii=False),
         json.dumps(d.get("dynamic_keywords", []), ensure_ascii=False), pos))
    conn.commit()
    return _group_row(conn.execute(
        "SELECT id, name, type, members, dynamic_keywords, position FROM groups WHERE id=?",
        (cur.lastrowid,)).fetchone())


def update_group(conn: sqlite3.Connection, gid: int, d: dict) -> dict | None:
    row = conn.execute("SELECT id FROM groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return None
    fields, vals = [], []
    for col, key in (("name", "name"), ("type", "type"), ("position", "position")):
        if key in d:
            if key == "type" and d[key] not in ("urltest", "selector"):
                raise ValueError("type must be urltest|selector")
            fields.append(f"{col}=?")
            vals.append(d[key])
    for key in ("members", "dynamic_keywords"):
        if key in d:
            fields.append(f"{key}=?")
            vals.append(json.dumps(d[key], ensure_ascii=False))
    if fields:
        vals.append(gid)
        conn.execute(f"UPDATE groups SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    return _group_row(conn.execute(
        "SELECT id, name, type, members, dynamic_keywords, position FROM groups WHERE id=?",
        (gid,)).fetchone())


def delete_group(conn: sqlite3.Connection, gid: int) -> bool:
    cur = conn.execute("DELETE FROM groups WHERE id=?", (gid,))
    conn.commit()
    return cur.rowcount > 0


# ---- node health ----
def save_health(conn: sqlite3.Connection, results: list) -> None:
    for r in results:
        conn.execute(
            "INSERT INTO node_health(tag, ok, latency_ms, error, checked_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(tag) DO UPDATE SET ok=excluded.ok, latency_ms=excluded.latency_ms,"
            " error=excluded.error, checked_at=excluded.checked_at",
            (r.tag, None if r.ok is None else int(r.ok), r.latency_ms, r.error, r.checked_at))
    conn.commit()


def list_health(conn: sqlite3.Connection) -> list[dict]:
    return [{"tag": r[0], "ok": (None if r[1] is None else bool(r[1])),
             "latency_ms": r[2], "error": r[3], "checked_at": r[4]}
            for r in conn.execute(
                "SELECT tag, ok, latency_ms, error, checked_at FROM node_health ORDER BY tag")]
