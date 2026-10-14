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
  url TEXT,
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
CREATE TABLE IF NOT EXISTS pair_codes(
  token TEXT PRIMARY KEY,
  expires_at REAL NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS devices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL DEFAULT '',
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dns_rewrite(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL UNIQUE,
  target TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS terminal_policies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ident TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  policy TEXT NOT NULL DEFAULT 'proxy'
);
CREATE TABLE IF NOT EXISTS traffic_daily(
  day TEXT NOT NULL,
  client TEXT NOT NULL DEFAULT '',
  proxy TEXT NOT NULL DEFAULT '',
  host TEXT NOT NULL DEFAULT '',
  up BIGINT NOT NULL DEFAULT 0,
  down BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY (day, client, proxy, host)
);
CREATE TABLE IF NOT EXISTS failover_state(
  group_name TEXT PRIMARY KEY,
  current_tag TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  last_switch_at TEXT
);
CREATE TABLE IF NOT EXISTS latency_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag TEXT NOT NULL,
  ok INTEGER NOT NULL DEFAULT 1,
  latency_ms REAL,
  checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_latency_history_tag ON latency_history(tag, id);
CREATE TABLE IF NOT EXISTS site_latency_sites(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS site_latency_checks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id INTEGER NOT NULL REFERENCES site_latency_sites(id) ON DELETE CASCADE,
  ok INTEGER NOT NULL DEFAULT 1,
  latency_ms REAL,
  checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscription_shares(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  node_filter TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_info_cache(
  tag TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "dns_direct": "223.5.5.5",
    "dns_proxy": "tcp://1.1.1.1",
    "dns_mode": "dnsmasq",          # dnsmasq | firewall | off
    "dns_region": "auto",           # auto | cn | outside
    "dns_region_detected": "",
    "final_outbound": "auto",
    "tun_stack": "mixed",
    "tun_mtu": "9000",
    "quic_block": "1",              # reject UDP/443 on proxy lines (default on)
    "client_mode": "rule",
    "state_rev": "0",
    "wifi_policy": '{"enabled": false, "pause_ssids": [], "action": "pause"}',
    "dns_filter_enabled": "0",
    "dns_filter_lists": "[]",   # JSON: [{name, url, enabled}]
    "dns_filter_applied_at": "",
    "share_lan_enabled": "0",   # expose a mixed inbound on LAN for other devices
    "share_lan_port": "8088",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # migrations for DBs created before the column/table existed
    cols = {r[1] for r in conn.execute("PRAGMA table_info(site_sets)")}
    if "flip" not in cols:
        conn.execute("ALTER TABLE site_sets ADD COLUMN flip TEXT NOT NULL DEFAULT ''")
    scols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)")}
    if "url" not in scols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN url TEXT")
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
                     source: str = "manual", format: str = "auto",
                     url: str | None = None) -> tuple[int, int]:
    from core.subscription import parse_subscription
    from core.clash import parse_clash_yaml, looks_like_clash
    if format == "clash" or (format == "auto" and looks_like_clash(content)):
        nodes = parse_clash_yaml(content)
    else:
        nodes = parse_subscription(content)
    cur = conn.execute(
        "INSERT INTO subscriptions(name, source, url, created_at) VALUES (?, ?, ?, ?)",
        (name, source, url, time.strftime("%Y-%m-%dT%H:%M:%S")),
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
    bump_rev(conn)
    return sid, count


def list_subscriptions(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for sid, name, source, url, created in conn.execute(
            "SELECT id, name, source, url, created_at FROM subscriptions ORDER BY id"):
        n = conn.execute("SELECT COUNT(*) FROM nodes WHERE sub_id=?", (sid,)).fetchone()[0]
        out.append({"id": sid, "name": name, "source": source, "url": url,
                    "created_at": created, "node_count": n})
    return out


def delete_subscription(conn: sqlite3.Connection, sid: int) -> bool:
    conn.execute("DELETE FROM nodes WHERE sub_id=?", (sid,))
    cur = conn.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
    conn.commit()
    bump_rev(conn)
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
            "position": r[4], "rules": json.loads(r[5]),
            "flip": r[6] if len(r) > 6 else ""}


def list_site_sets(conn: sqlite3.Connection) -> list[dict]:
    return [_site_set_row(r) for r in conn.execute(
        "SELECT id, name, action, grp, position, rules, flip FROM site_sets"
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
    bump_rev(conn)
    return _site_set_row(conn.execute(
        "SELECT id, name, action, grp, position, rules, flip FROM site_sets WHERE id=?",
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
    bump_rev(conn)
    return _site_set_row(conn.execute(
        "SELECT id, name, action, grp, position, rules, flip FROM site_sets WHERE id=?",
        (sid,)).fetchone())


def delete_site_set(conn: sqlite3.Connection, sid: int) -> bool:
    cur = conn.execute("DELETE FROM site_sets WHERE id=?", (sid,))
    conn.commit()
    bump_rev(conn)
    return cur.rowcount > 0


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()


def bump_rev(conn: sqlite3.Connection) -> int:
    """Bump the state revision counter (client sync). Returns the new rev."""
    rev = int(get_setting(conn, "state_rev", "0")) + 1
    set_setting(conn, "state_rev", str(rev))
    return rev


def get_rev(conn: sqlite3.Connection) -> int:
    return int(get_setting(conn, "state_rev", "0"))


# ---- pairing & devices ----
def create_pair_code(conn: sqlite3.Connection, token: str, ttl_s: float = 600) -> None:
    now = time.time()
    conn.execute("INSERT INTO pair_codes(token, expires_at, used, created_at)"
                 " VALUES (?, ?, 0, ?)", (token, now + ttl_s, now))
    conn.commit()


def consume_pair_code(conn: sqlite3.Connection, token: str) -> bool:
    """Mark a pair code used if valid. Returns True on success."""
    r = conn.execute("SELECT expires_at, used FROM pair_codes WHERE token=?",
                     (token,)).fetchone()
    if not r or r[1] or r[0] < time.time():
        return False
    conn.execute("UPDATE pair_codes SET used=1 WHERE token=?", (token,))
    conn.commit()
    return True


def register_device(conn: sqlite3.Connection, name: str, token_hash: str) -> int:
    cur = conn.execute("INSERT INTO devices(name, token_hash, created_at)"
                       " VALUES (?, ?, ?)",
                       (name, token_hash, time.strftime("%Y-%m-%dT%H:%M:%S")))
    conn.commit()
    return cur.lastrowid


def find_device_by_token_hash(conn: sqlite3.Connection, token_hash: str):
    return conn.execute("SELECT id, name, created_at FROM devices WHERE token_hash=?",
                        (token_hash,)).fetchone()


def list_devices(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r[0], "name": r[1], "created_at": r[2]}
            for r in conn.execute("SELECT id, name, created_at FROM devices ORDER BY id")]


def delete_device(conn: sqlite3.Connection, did: int) -> bool:
    cur = conn.execute("DELETE FROM devices WHERE id=?", (did,))
    conn.commit()
    return cur.rowcount > 0


def load_app_config(conn: sqlite3.Connection):
    from core.models import (AppConfig, Chain, DnsConfig, DnsRewrite, Group, Node,
                             SiteSet, TerminalPolicy)
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
            "SELECT id, name, action, grp, rules, flip FROM site_sets ORDER BY position, id"):
        rules = json.loads(r[4])
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
            sid=r[0], name=r[1], action=r[2], group=r[3], flip=r[5] or "",
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
    dns = DnsConfig(
        direct_dns=get_setting(conn, "dns_direct", DEFAULT_SETTINGS["dns_direct"]),
        proxy_dns=get_setting(conn, "dns_proxy", DEFAULT_SETTINGS["dns_proxy"]),
        mode=get_setting(conn, "dns_mode", "dnsmasq"),
        region=get_setting(conn, "dns_region", "auto"),
        region_detected=get_setting(conn, "dns_region_detected", ""))
    # region-aware proxy DNS default (documented behavior): outside mainland
    # defaults to the upstream DNS instead of TCP 1.1.1.1, unless customized.
    eff_region = dns.region if dns.region != "auto" else (dns.region_detected or "cn")
    if (get_setting(conn, "dns_proxy", DEFAULT_SETTINGS["dns_proxy"])
            == DEFAULT_SETTINGS["dns_proxy"] and eff_region == "outside"):
        dns.proxy_dns = "8.8.8.8"
    rewrites = [
        DnsRewrite(id=r[0], domain=r[1], target=r[2])
        for r in conn.execute("SELECT id, domain, target FROM dns_rewrite ORDER BY domain")]
    terminals = [
        TerminalPolicy(id=r[0], ident=r[1], name=r[2], policy=r[3])
        for r in conn.execute("SELECT id, ident, name, policy FROM terminal_policies ORDER BY ident")]
    return AppConfig(
        nodes=nodes, site_sets=site_sets, groups=groups, chains=chains, dns=dns,
        dns_rewrites=rewrites, terminals=terminals,
        final_outbound=get_setting(conn, "final_outbound", "auto"),
        tun_stack=get_setting(conn, "tun_stack", "mixed"),
        tun_mtu=int(get_setting(conn, "tun_mtu", "9000") or 9000),
        quic_block=get_setting(conn, "quic_block", "1") == "1",
        share_lan_enabled=get_setting(conn, "share_lan_enabled", "0") == "1",
        share_lan_port=int(get_setting(conn, "share_lan_port", "8088") or 8088),
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
    bump_rev(conn)
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
    bump_rev(conn)
    return get_rule_set(conn, rid)


def delete_rule_set(conn: sqlite3.Connection, rid: int) -> bool:
    cur = conn.execute("DELETE FROM rule_sets WHERE id=?", (rid,))
    conn.commit()
    bump_rev(conn)
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
    bump_rev(conn)
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
    bump_rev(conn)
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
    bump_rev(conn)
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
    if d.get("type", "urltest") not in ("urltest", "selector", "failover"):
        raise ValueError("type must be urltest|selector|failover")
    pos = conn.execute("SELECT COALESCE(MAX(position), -1)+1 FROM groups").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES (?, ?, ?, ?, ?)",
        (d["name"], d.get("type", "urltest"),
         json.dumps(d.get("members", []), ensure_ascii=False),
         json.dumps(d.get("dynamic_keywords", []), ensure_ascii=False), pos))
    conn.commit()
    bump_rev(conn)
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
                raise ValueError("type must be urltest|selector|failover")
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
    bump_rev(conn)
    return _group_row(conn.execute(
        "SELECT id, name, type, members, dynamic_keywords, position FROM groups WHERE id=?",
        (gid,)).fetchone())


def delete_group(conn: sqlite3.Connection, gid: int) -> bool:
    cur = conn.execute("DELETE FROM groups WHERE id=?", (gid,))
    conn.commit()
    bump_rev(conn)
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


def set_site_set_flip(conn: sqlite3.Connection, sid: int, flip: str) -> bool:
    """Set the hot-switch state of a site set ('' | 'direct' | 'proxy')."""
    if flip not in ("", "direct", "proxy"):
        raise ValueError("flip must be ''|direct|proxy")
    cur = conn.execute("UPDATE site_sets SET flip=? WHERE id=?", (flip, sid))
    conn.commit()
    if cur.rowcount:
        bump_rev(conn)
    return cur.rowcount > 0


# ---- DNS rewrites ----
def list_dns_rewrites(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r[0], "domain": r[1], "target": r[2]}
            for r in conn.execute("SELECT id, domain, target FROM dns_rewrite ORDER BY domain")]


def add_dns_rewrite(conn: sqlite3.Connection, domain: str, target: str) -> dict:
    domain = domain.strip().lower()
    if not domain or not target.strip():
        raise ValueError("domain and target are required")
    cur = conn.execute(
        "INSERT INTO dns_rewrite(domain, target) VALUES (?, ?)"
        " ON CONFLICT(domain) DO UPDATE SET target=excluded.target",
        (domain, target.strip()))
    conn.commit()
    bump_rev(conn)
    r = conn.execute("SELECT id, domain, target FROM dns_rewrite WHERE id=?",
                     (cur.lastrowid,)).fetchone()
    if not r:  # was an upsert on existing row; fetch by domain
        r = conn.execute("SELECT id, domain, target FROM dns_rewrite WHERE domain=?",
                         (domain,)).fetchone()
    return {"id": r[0], "domain": r[1], "target": r[2]}


def delete_dns_rewrite(conn: sqlite3.Connection, rid: int) -> bool:
    cur = conn.execute("DELETE FROM dns_rewrite WHERE id=?", (rid,))
    conn.commit()
    if cur.rowcount:
        bump_rev(conn)
    return cur.rowcount > 0


# ---- terminal policies ----
def list_terminals(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r[0], "ident": r[1], "name": r[2], "policy": r[3]}
            for r in conn.execute(
                "SELECT id, ident, name, policy FROM terminal_policies ORDER BY ident")]


def upsert_terminal(conn: sqlite3.Connection, ident: str, name: str,
                    policy: str) -> dict:
    ident = ident.strip()
    if not ident:
        raise ValueError("ident is required")
    if policy not in ("direct", "proxy", "bypass"):
        raise ValueError("policy must be direct|proxy|bypass")
    conn.execute(
        "INSERT INTO terminal_policies(ident, name, policy) VALUES (?, ?, ?)"
        " ON CONFLICT(ident) DO UPDATE SET name=excluded.name, policy=excluded.policy",
        (ident, name.strip(), policy))
    conn.commit()
    bump_rev(conn)
    r = conn.execute("SELECT id, ident, name, policy FROM terminal_policies WHERE ident=?",
                     (ident,)).fetchone()
    return {"id": r[0], "ident": r[1], "name": r[2], "policy": r[3]}


def delete_terminal(conn: sqlite3.Connection, tid: int) -> bool:
    cur = conn.execute("DELETE FROM terminal_policies WHERE id=?", (tid,))
    conn.commit()
    if cur.rowcount:
        bump_rev(conn)
    return cur.rowcount > 0


# ---- traffic accounting ----
def record_traffic(conn: sqlite3.Connection, day: str, client: str,
                   proxy: str, host: str, up: int, down: int) -> None:
    conn.execute(
        "INSERT INTO traffic_daily(day, client, proxy, host, up, down)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(day, client, proxy, host) DO UPDATE SET"
        " up=up+excluded.up, down=down+excluded.down",
        (day, client or "", proxy or "", host or "", up, down))
    conn.commit()


def traffic_summary(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    return [{"day": r[0], "client": r[1], "proxy": r[2], "host": r[3],
             "up": r[4], "down": r[5]}
            for r in conn.execute(
                "SELECT day, client, proxy, host, SUM(up), SUM(down) FROM traffic_daily"
                " WHERE day >= date('now', ? || ' days') GROUP BY day, client, proxy, host"
                " ORDER BY day DESC, down DESC LIMIT 500", (-days,))]


# ---- failover runtime state ----
def get_failover_state(conn: sqlite3.Connection, group_name: str) -> dict | None:
    r = conn.execute(
        "SELECT group_name, current_tag, updated_at, last_switch_at"
        " FROM failover_state WHERE group_name=?", (group_name,)).fetchone()
    return ({"group_name": r[0], "current_tag": r[1], "updated_at": r[2],
             "last_switch_at": r[3]} if r else None)


def set_failover_state(conn: sqlite3.Connection, group_name: str,
                       current_tag: str, switched: bool) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    prev = get_failover_state(conn, group_name)
    last_switch = now if switched else (prev["last_switch_at"] if prev else None)
    conn.execute(
        "INSERT INTO failover_state(group_name, current_tag, updated_at, last_switch_at)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT(group_name) DO UPDATE SET current_tag=excluded.current_tag,"
        " updated_at=excluded.updated_at, last_switch_at=excluded.last_switch_at",
        (group_name, current_tag, now, last_switch))
    conn.commit()


# ---- factory reset ----
_DATA_TABLES = ("subscriptions", "nodes", "site_sets", "rule_sets", "chains",
                "groups", "node_health", "pair_codes", "devices", "dns_rewrite",
                "terminal_policies", "traffic_daily", "failover_state",
                "latency_history", "site_latency_sites", "site_latency_checks",
                "subscription_shares", "node_info_cache")


def factory_reset(conn: sqlite3.Connection) -> None:
    """Clear all user data and re-seed defaults. Auth-adjacent tables
    (pair_codes, devices) are cleared too; the panel password is kept so the
    operator is not locked out of the box (change it afterwards)."""
    for t in _DATA_TABLES:
        try:
            conn.execute(f"DELETE FROM {t}")
        except sqlite3.Error:
            pass
    conn.execute("DELETE FROM settings")
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('auto', 'urltest', '[\"*nodes*\"]', '[]', 0)")
    conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('manual', 'selector', '[\"*all*\"]', '[]', 1)")
    conn.execute("INSERT OR REPLACE INTO settings(key, value)"
                 " VALUES ('applied_rev', '')")
    conn.commit()


# ---- latency history (shared across browsers) ----
def record_latency(conn: sqlite3.Connection, tag: str, ok: bool,
                   latency_ms: float | None) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO latency_history(tag, ok, latency_ms, checked_at)"
        " VALUES (?, ?, ?, ?)", (tag, 1 if ok else 0, latency_ms, now))
    conn.execute(
        "DELETE FROM latency_history WHERE tag=? AND id NOT IN"
        " (SELECT id FROM latency_history WHERE tag=? ORDER BY id DESC LIMIT 50)",
        (tag, tag))
    conn.commit()


def get_latency_history(conn: sqlite3.Connection) -> dict:
    out: dict = {}
    for tag, ok, ms, at in conn.execute(
            "SELECT tag, ok, latency_ms, checked_at FROM latency_history"
            " ORDER BY id DESC LIMIT 2000"):
        out.setdefault(tag, []).append(
            {"ok": bool(ok), "latency_ms": ms, "checked_at": at})
    for v in out.values():
        v.reverse()
    return out


# ---- site latency ----
def set_site_latency_sites(conn: sqlite3.Connection, sites: list[dict]) -> list[dict]:
    conn.execute("DELETE FROM site_latency_sites")
    for s in sites:
        if not s.get("url"):
            continue
        conn.execute("INSERT INTO site_latency_sites(name, url) VALUES (?, ?)",
                     (s.get("name") or s["url"], s["url"]))
    conn.commit()
    return list_site_latency_sites(conn)


def list_site_latency_sites(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r[0], "name": r[1], "url": r[2]}
            for r in conn.execute(
                "SELECT id, name, url FROM site_latency_sites ORDER BY id")]


def record_site_check(conn: sqlite3.Connection, site_id: int, ok: bool,
                      latency_ms: float | None) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO site_latency_checks(site_id, ok, latency_ms, checked_at)"
        " VALUES (?, ?, ?, ?)", (site_id, 1 if ok else 0, latency_ms, now))
    conn.execute(
        "DELETE FROM site_latency_checks WHERE site_id=? AND id NOT IN"
        " (SELECT id FROM site_latency_checks WHERE site_id=?"
        "  ORDER BY id DESC LIMIT 100)", (site_id, site_id))
    conn.commit()


def site_latency_history(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    return [{"site_id": r[0], "ok": bool(r[1]), "latency_ms": r[2],
             "checked_at": r[3]}
            for r in conn.execute(
                "SELECT site_id, ok, latency_ms, checked_at FROM site_latency_checks"
                " WHERE checked_at >= datetime('now', ? || ' days')"
                " ORDER BY checked_at", (-days,))]


# ---- traffic aggregation ----
def traffic_month(conn: sqlite3.Connection, month: str) -> dict:
    """month='YYYY-MM'. Per-day rows + total + daily average."""
    rows = conn.execute(
        "SELECT day, SUM(up), SUM(down) FROM traffic_daily"
        " WHERE substr(day, 1, 7)=? GROUP BY day ORDER BY day", (month,)).fetchall()
    days = [{"day": r[0], "up": r[1] or 0, "down": r[2] or 0} for r in rows]
    total_up = sum(d["up"] for d in days)
    total_down = sum(d["down"] for d in days)
    n = len(days) or 1
    return {"month": month, "days": days,
            "total": {"up": total_up, "down": total_down},
            "daily_avg": {"up": total_up // n, "down": total_down // n}}


def traffic_day(conn: sqlite3.Connection, day: str, limit: int = 50) -> dict:
    by_proxy = [{"proxy": r[0], "up": r[1] or 0, "down": r[2] or 0}
                for r in conn.execute(
                    "SELECT proxy, SUM(up), SUM(down) FROM traffic_daily"
                    " WHERE day=? GROUP BY proxy ORDER BY SUM(up)+SUM(down) DESC"
                    " LIMIT ?", (day, limit))]
    by_host = [{"host": r[0], "up": r[1] or 0, "down": r[2] or 0}
               for r in conn.execute(
                   "SELECT host, SUM(up), SUM(down) FROM traffic_daily"
                   " WHERE day=? GROUP BY host ORDER BY SUM(up)+SUM(down) DESC"
                   " LIMIT ?", (day, limit))]
    by_client = [{"client": r[0], "up": r[1] or 0, "down": r[2] or 0}
                 for r in conn.execute(
                     "SELECT client, SUM(up), SUM(down) FROM traffic_daily"
                     " WHERE day=? GROUP BY client ORDER BY SUM(up)+SUM(down) DESC"
                     " LIMIT ?", (day, limit))]
    return {"day": day, "by_proxy": by_proxy, "by_host": by_host,
            "by_client": by_client}


def traffic_drill(conn: sqlite3.Connection, month: str, dim: str) -> list[dict]:
    """Aggregate one month by dimension: proxy | host | client."""
    col = {"proxy": "proxy", "host": "host", "client": "client"}.get(dim, "proxy")
    return [{dim: r[0], "up": r[1] or 0, "down": r[2] or 0}
            for r in conn.execute(
                f"SELECT {col}, SUM(up), SUM(down) FROM traffic_daily"
                " WHERE substr(day, 1, 7)=? GROUP BY 1"
                " ORDER BY SUM(up)+SUM(down) DESC LIMIT 100", (month,))]


def traffic_usage(conn: sqlite3.Connection) -> dict:
    days = conn.execute(
        "SELECT COUNT(DISTINCT day) FROM traffic_daily").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM traffic_daily").fetchone()[0]
    total = conn.execute(
        "SELECT COALESCE(SUM(up),0), COALESCE(SUM(down),0)"
        " FROM traffic_daily").fetchone()
    oldest = conn.execute(
        "SELECT MIN(day) FROM traffic_daily").fetchone()[0]
    return {"days": days, "rows": rows, "up": total[0], "down": total[1],
            "oldest_day": oldest}


# ---- subscription shares (public capability links) ----
def list_sub_shares(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r[0], "name": r[1], "token": r[2], "node_filter": r[3],
             "created_at": r[4]}
            for r in conn.execute(
                "SELECT id, name, token, node_filter, created_at"
                " FROM subscription_shares ORDER BY id")]


def create_sub_share(conn: sqlite3.Connection, name: str,
                     node_filter: str = "") -> dict:
    import secrets as _secrets
    token = _secrets.token_urlsafe(24)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    cur = conn.execute(
        "INSERT INTO subscription_shares(name, token, node_filter, created_at)"
        " VALUES (?, ?, ?, ?)", (name, token, node_filter or "", now))
    conn.commit()
    return {"id": cur.lastrowid, "name": name, "token": token,
            "node_filter": node_filter or "", "created_at": now}


def update_sub_share(conn: sqlite3.Connection, sid: int, name: str | None,
                     node_filter: str | None) -> dict | None:
    row = conn.execute("SELECT id FROM subscription_shares WHERE id=?",
                       (sid,)).fetchone()
    if not row:
        return None
    if name is not None:
        conn.execute("UPDATE subscription_shares SET name=? WHERE id=?",
                     (name, sid))
    if node_filter is not None:
        conn.execute("UPDATE subscription_shares SET node_filter=? WHERE id=?",
                     (node_filter, sid))
    conn.commit()
    return [s for s in list_sub_shares(conn) if s["id"] == sid][0]


def regenerate_sub_share(conn: sqlite3.Connection, sid: int) -> dict | None:
    import secrets as _secrets
    if not conn.execute("SELECT id FROM subscription_shares WHERE id=?",
                        (sid,)).fetchone():
        return None
    token = _secrets.token_urlsafe(24)
    conn.execute("UPDATE subscription_shares SET token=? WHERE id=?",
                 (token, sid))
    conn.commit()
    return [s for s in list_sub_shares(conn) if s["id"] == sid][0]


def delete_sub_share(conn: sqlite3.Connection, sid: int) -> bool:
    cur = conn.execute("DELETE FROM subscription_shares WHERE id=?", (sid,))
    conn.commit()
    return cur.rowcount > 0


def find_sub_share(conn: sqlite3.Connection, token: str) -> dict | None:
    r = conn.execute(
        "SELECT id, name, token, node_filter, created_at"
        " FROM subscription_shares WHERE token=?", (token,)).fetchone()
    return ({"id": r[0], "name": r[1], "token": r[2], "node_filter": r[3],
             "created_at": r[4]} if r else None)


# ---- node exit-info cache ----
def get_node_info_cache(conn: sqlite3.Connection, tag: str,
                        max_age_s: int = 21600) -> dict | None:
    import json as _json
    r = conn.execute("SELECT data, updated_at FROM node_info_cache WHERE tag=?",
                     (tag,)).fetchone()
    if not r:
        return None
    try:
        data = _json.loads(r[0])
    except ValueError:
        return None
    try:
        age = time.time() - time.mktime(time.strptime(r[1], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        age = max_age_s + 1
    data["_age_s"] = age
    return data if age <= max_age_s else None


def set_node_info_cache(conn: sqlite3.Connection, tag: str, data: dict) -> None:
    import json as _json
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO node_info_cache(tag, data, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(tag) DO UPDATE SET data=excluded.data,"
        " updated_at=excluded.updated_at",
        (tag, _json.dumps(data, ensure_ascii=False), now))
    conn.commit()


# ---- terminal candidates (DHCP leases + traffic clients) ----
def terminal_candidates(conn: sqlite3.Connection) -> list[dict]:
    from core.dnslog import dhcp_hostnames
    leases = dhcp_hostnames()
    out = [{"ip": ip, "hostname": hn, "source": "dhcp"} for ip, hn in leases.items()]
    seen = set(leases)
    try:
        for (client,) in conn.execute(
                "SELECT DISTINCT client FROM traffic_daily WHERE client != ''"):
            if client not in seen:
                out.append({"ip": client, "hostname": "", "source": "traffic"})
                seen.add(client)
    except sqlite3.Error:
        pass
    return out


def refresh_subscription(conn: sqlite3.Connection, sid: int,
                         timeout: float = 30.0) -> dict:
    """Re-fetch a subscription URL and replace its nodes. Returns stats."""
    import urllib.request
    row = conn.execute("SELECT name, url FROM subscriptions WHERE id=?",
                       (sid,)).fetchone()
    if not row:
        raise KeyError("not found")
    name, url = row
    if not url:
        raise ValueError("subscription has no URL to refresh")
    req = urllib.request.Request(url, headers={"User-Agent": "openbox-oss/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        content = r.read().decode("utf-8", "replace")
    from core.subscription import parse_subscription
    from core.clash import parse_clash_yaml, looks_like_clash
    nodes = (parse_clash_yaml(content) if looks_like_clash(content)
             else parse_subscription(content))
    conn.execute("DELETE FROM nodes WHERE sub_id=?", (sid,))
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
             json.dumps(n.params, ensure_ascii=False)))
        count += 1
    conn.commit()
    bump_rev(conn)
    return {"id": sid, "name": name, "node_count": count}
