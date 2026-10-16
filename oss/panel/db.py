"""SQLite storage for the panel backend. Standard library only.

Tables: subscriptions, nodes, site_sets, settings.
"""

from __future__ import annotations

import json
import sqlite3
import time


def _safe_json_loads(s: str) -> dict:
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _is_ip(host: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  url TEXT,
  created_at TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  auto_update_hours INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  userinfo TEXT NOT NULL DEFAULT '{}',
  urls TEXT NOT NULL DEFAULT '[]',
  rename_enabled INTEGER NOT NULL DEFAULT 0,
  rename_prefix INTEGER NOT NULL DEFAULT 1,
  rename_order TEXT NOT NULL DEFAULT '["region","feature","seq"]',
  rename_seq_digits INTEGER NOT NULL DEFAULT 2,
  rename_regions TEXT NOT NULL DEFAULT '[]',
  rename_fallback TEXT NOT NULL DEFAULT '其他',
  rename_features TEXT NOT NULL DEFAULT '',
  rename_filter TEXT NOT NULL DEFAULT '',
  dns_resolve TEXT NOT NULL DEFAULT 'auto'
);
CREATE TABLE IF NOT EXISTS nodes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  tag TEXT NOT NULL UNIQUE,
  protocol TEXT NOT NULL,
  server TEXT NOT NULL,
  port INTEGER NOT NULL,
  params TEXT NOT NULL DEFAULT '{}',
  orig_tag TEXT NOT NULL DEFAULT '',
  custom_tag TEXT NOT NULL DEFAULT '',
  disabled INTEGER NOT NULL DEFAULT 0
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
-- Front custom routing: domain patterns evaluated BEFORE all site sets.
CREATE TABLE IF NOT EXISTS front_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT 'auto',
  position INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1
);
-- Region-based routing for client apps: pick a rule group by client region.
CREATE TABLE IF NOT EXISTS region_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  region TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  rules TEXT NOT NULL DEFAULT '{}',
  position INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1
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
  position INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  interval_s INTEGER NOT NULL DEFAULT 300,
  tolerance_ms INTEGER NOT NULL DEFAULT 100,
  idle_timeout TEXT NOT NULL DEFAULT '12h',
  expected_status TEXT NOT NULL DEFAULT '',
  test_url TEXT NOT NULL DEFAULT '',
  lanes TEXT NOT NULL DEFAULT '[]'
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
  target TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1
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
  conns INTEGER NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS share_servers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL DEFAULT '',
  protocol TEXT NOT NULL DEFAULT 'shadowsocks',
  address TEXT NOT NULL DEFAULT '127.0.0.1',
  port INTEGER NOT NULL DEFAULT 8388,
  method TEXT NOT NULL DEFAULT 'aes-256-gcm',
  password TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
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
    "final_outbound": "所有-自动",
    "routing_fallback": "direct",  # 1:1 original: unmatched traffic -> direct
    "tun_stack": "mixed",
    "tun_mtu": "9000",
    "tun_address": "172.19.0.1/30",
    "quic_block": "1",              # reject UDP/443 on proxy lines (default on)
    "client_mode": "rule",
    "state_rev": "0",
    "wifi_policy": '{"enabled": false, "pause_ssids": [], "action": "pause"}',
    "dns_filter_enabled": "0",
    "dns_filter_lists": "[]",   # JSON: [{name, url, enabled}]
    "dns_filter_applied_at": "",
    "dns_filter_auto_update": "0",      # daily re-download of filter lists
    "dns_filter_update_time": "04:00",  # HH:MM local time
    "dns_filter_auto_updated_at": "",
    "dns_fakeip": "0",                # fakeip for proxied domains (198.19.0.0/16)
    "dns_split": "1",                 # split direct/proxy DNS upstreams; 0 = all via proxy
    "dns_upstream_latency": "{}",      # JSON {upstream: ms} for primary/backup ordering
    "sub_node_direct": "0",           # subscription & node server domains go direct
    "direct_bypass_kernel": "0",      # direct traffic bypasses kernel at ingress (ipset)
    "bypass_ports": "",               # e.g. "21114-21119, 2233"
    "bypass_ports_mode": "black",     # black = these ports bypass; white = only these enter
    "mss_clamp": "0",                 # TCP MSS clamp; 0 = off
    "speedtest_url": "http://www.gstatic.com/generate_204",
    "direct_speedtest_url": "http://connectivitycheck.platform.hicloud.com/generate_204",
    "router_name": "OpenBox",            # router identity shown in client apps
    "router_icon": "router",             # icon key
    "router_region": "cn",               # router region code
    "share_lan_enabled": "0",   # expose a mixed inbound on LAN for other devices
    "share_lan_port": "8088",
    "update_auto": "0",           # panel self auto-update (original: updates.openbox.auto)
    "update_hour": "4",           # hour of day to check (original: updates.openbox.hour)
    "update_channel": "auto",     # release channel (original: updates.openbox.channel)
    "update_check_channel": "mirror",  # check via mirror (original: updates.openbox.checkChannel)
    "update_days": "1",           # check interval in days (original: updates.openbox.days)
    "traffic_keep_months": "3",   # traffic history retention (original: traffic.keepMonths)
}


def _migrate_default_groups(conn: sqlite3.Connection) -> None:
    """Rename legacy default groups auto/manual to 所有-自动/所有-手动,
    updating all references (site sets, front rules, final_outbound)."""
    renames = {"auto": "所有-自动", "manual": "所有-手动"}
    for old, new in renames.items():
        row = conn.execute("SELECT id FROM groups WHERE name=?", (old,)).fetchone()
        if not row:
            continue
        exists = conn.execute("SELECT id FROM groups WHERE name=?", (new,)).fetchone()
        if exists:
            # new name already taken: drop the legacy duplicate
            conn.execute("DELETE FROM groups WHERE name=?", (old,))
        else:
            conn.execute("UPDATE groups SET name=? WHERE name=?", (new, old))
        conn.execute("UPDATE site_sets SET grp=? WHERE grp=?", (new, old))
        conn.execute("UPDATE front_rules SET target=? WHERE target=?", (new, old))
        if get_setting(conn, "final_outbound", "") == old:
            set_setting(conn, "final_outbound", new)
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # migrations for DBs created before the column/table existed
    cols = {r[1] for r in conn.execute("PRAGMA table_info(site_sets)")}
    if "flip" not in cols:
        conn.execute("ALTER TABLE site_sets ADD COLUMN flip TEXT NOT NULL DEFAULT ''")
    if "icon" not in cols:
        conn.execute("ALTER TABLE site_sets ADD COLUMN icon TEXT NOT NULL DEFAULT ''")
    rwcols = {r[1] for r in conn.execute("PRAGMA table_info(dns_rewrite)")}
    if "enabled" not in rwcols:
        conn.execute("ALTER TABLE dns_rewrite ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
    gcols = {r[1] for r in conn.execute("PRAGMA table_info(groups)")}
    if "idle_timeout" not in gcols:
        conn.execute("ALTER TABLE groups ADD COLUMN idle_timeout TEXT NOT NULL DEFAULT '12h'")
    scols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)")}
    if "url" not in scols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN url TEXT")
    for col, ddl in (("enabled", "INTEGER NOT NULL DEFAULT 1"),
                     ("auto_update_hours", "INTEGER NOT NULL DEFAULT 0"),
                     ("updated_at", "TEXT"),
                     ("userinfo", "TEXT NOT NULL DEFAULT '{}'"),
                     ("urls", "TEXT NOT NULL DEFAULT '[]'"),
                     ("rename_enabled", "INTEGER NOT NULL DEFAULT 0"),
                     ("rename_prefix", "INTEGER NOT NULL DEFAULT 1"),
                     ("rename_order", "TEXT NOT NULL DEFAULT '[\"region\",\"feature\",\"seq\"]'"),
                     ("rename_seq_digits", "INTEGER NOT NULL DEFAULT 2"),
                     ("rename_regions", "TEXT NOT NULL DEFAULT '[]'"),
                     ("rename_fallback", "TEXT NOT NULL DEFAULT '其他'"),
                     ("rename_features", "TEXT NOT NULL DEFAULT ''"),
                     ("rename_filter", "TEXT NOT NULL DEFAULT ''"),
                     ("dns_resolve", "TEXT NOT NULL DEFAULT 'auto'"),
                     ("auto_update_enabled", "INTEGER NOT NULL DEFAULT 0"),
                     ("auto_update_days", "INTEGER NOT NULL DEFAULT 1"),
                     ("auto_update_hour", "INTEGER NOT NULL DEFAULT 4")):
        if col not in scols:
            conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {col} {ddl}")
    # Migrate legacy auto_update_hours (per-N-hours) to the new
    # {enabled, days, hour} model (1:1 with the original panel).
    if "auto_update_hours" in scols and "auto_update_enabled" in {
            r[1] for r in conn.execute("PRAGMA table_info(subscriptions)")}:
        for sid, hours in conn.execute(
                "SELECT id, auto_update_hours FROM subscriptions"
                " WHERE auto_update_hours > 0 AND auto_update_enabled = 0"):
            days = max(1, round(hours / 24))
            conn.execute("UPDATE subscriptions SET auto_update_enabled=1,"
                         " auto_update_days=?, auto_update_hour=4 WHERE id=?",
                         (days, sid))
        conn.commit()
    gcols = {r[1] for r in conn.execute("PRAGMA table_info(groups)")}
    for col, ddl in (("enabled", "INTEGER NOT NULL DEFAULT 1"),
                     ("interval_s", "INTEGER NOT NULL DEFAULT 300"),
                     ("tolerance_ms", "INTEGER NOT NULL DEFAULT 100"),
                     ("expected_status", "TEXT NOT NULL DEFAULT ''"),
                     ("test_url", "TEXT NOT NULL DEFAULT ''"),
                     ("lanes", "TEXT NOT NULL DEFAULT '[]'"),
                     ("icon", "TEXT NOT NULL DEFAULT ''"),
                     ("icon_scale", "INTEGER NOT NULL DEFAULT 0")):
        if col not in gcols:
            conn.execute(f"ALTER TABLE groups ADD COLUMN {col} {ddl}")
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(traffic_daily)")}
    if "conns" not in tcols:
        conn.execute("ALTER TABLE traffic_daily ADD COLUMN conns INTEGER NOT NULL DEFAULT 0")
    ncols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)")}
    for col, ddl in (("orig_tag", "TEXT NOT NULL DEFAULT ''"),
                     ("custom_tag", "TEXT NOT NULL DEFAULT ''"),
                     ("disabled", "INTEGER NOT NULL DEFAULT 0")):
        if col not in ncols:
            conn.execute(f"ALTER TABLE nodes ADD COLUMN {col} {ddl}")
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    # default outbound groups (match original naming):
    # 所有-自动 = urltest over nodes, 所有-手动 = selector over all
    conn.execute(
        "INSERT OR IGNORE INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('所有-自动', 'urltest', '[\"*nodes*\"]', '[]', 0)")
    conn.execute(
        "INSERT OR IGNORE INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('所有-手动', 'selector', '[\"*all*\"]', '[]', 1)")
    conn.commit()
    # migrate old default names (auto/manual) to the new ones, fixing references
    _migrate_default_groups(conn)
    # default routing policies (match original 12)
    _seed_default_site_sets(conn)
    # default DNS rewrite rules (match original)
    for domain, target in (("services.googleapis.cn", "services.googleapis.com"),
                          ("developers.google.cn", "developers.google.com")):
        conn.execute(
            "INSERT OR IGNORE INTO dns_rewrite(domain, target) VALUES (?, ?)",
            (domain, target))
    conn.commit()


def _seed_default_site_sets(conn: sqlite3.Connection) -> None:
    """Seed the 12 default routing policies from the original, if none exist."""
    if conn.execute("SELECT COUNT(*) FROM site_sets").fetchone()[0] > 0:
        return
    defaults = [
        ("Speed", "proxy", {"domain": ["speed.cloudflare.com", "challenges.cloudflare.com"],
                           "domain_suffix": [
                               "yalala.com", "whois.pconline.com.cn", "ipip.net", "b0.upaiyun.com",
                               "asn247.net", "astrill.org", "ipinfo.io", "vultr.com", "test-ipv6.com",
                               "ipw.cn", "ipcheck.im", "fast.com", "speedcheck.org", "speedtest.net",
                               "speedtest.cn", "ustc.edu.cn", "dnscheck.tools", "whoer.net",
                               "browserleaks.com", "browserleaks.org", "browserleaks.net",
                               "dnsleaktest.org", "1-b.net", "workers.dev", "jsonp-ip.com",
                               "sspanel.net", "dnsleaktest.com", "browserscan.net", "surfshark.com",
                               "surfsharkdns.com", "ip-api.com", "ipleak.net", "ip-score.com",
                               "888005.xyz", "incolumitas.com", "null-addr.com", "null-addr.net",
                               "null-addr.org", "null-addr.biz", "null-addr.info", "addr.tools",
                               "ifconfig.me", "ip125.com", "skk.moe", "ip111.cn", "ping0.cc",
                               "ip.sb", "ipify.org", "whoer.com", "whatismyip.com.tw",
                               "whatismyip.com", "whoisip.me", "ipaddress.me", "ip2proxy.com",
                               "vpnapi.io", "l.google.com"],
                           "ip_cidr": ["142.251.215.0/24", "74.125.250.129/24"]},
         "misc:stopwatch"),
        ("AI", "proxy", {"rule_sets": ["geosite-category-ai-!cn"]}, "brand:openai-light"),
        ("Youtube", "proxy", {"rule_sets": ["geosite-youtube"]}, "brand:youtube"),
        ("TikTok", "proxy", {"rule_sets": ["geosite-tiktok", "geosite-tiktok@!cn"]}, "brand:tiktok"),
        ("Netflix", "proxy", {"rule_sets": ["geosite-netflix", "geoip-netflix"]}, "brand:netflix-mono"),
        ("Github", "proxy", {"rule_sets": ["geosite-github"]}, "brand:github-mono"),
        ("Google", "proxy", {"rule_sets": ["geosite-google"]}, "brand:google"),
        ("Microsoft", "proxy", {"rule_sets": ["geosite-microsoft"]}, "brand:microsoft"),
        ("Apple", "direct", {"rule_sets": ["geosite-apple"]}, "brand:apple-light"),
        ("Games", "proxy", {"rule_sets": ["geosite-steam", "geosite-sony"]}, "misc:game-soft"),
        ("国外", "proxy", {"rule_sets": ["geosite-gfw", "geoip-cloudflare", "geoip-facebook",
                          "geoip-cloudfront", "geoip-fastly", "geoip-google",
                          "geoip-netflix", "geoip-telegram", "geoip-tor",
                          "geoip-twitter"]}, "globe:earth-americas"),
        ("国内", "direct", {"rule_sets": ["geosite-cn", "geoip-cn", "geoip-private"]}, "misc:shield"),
    ]
    for pos, (name, action, rules, icon) in enumerate(defaults):
        conn.execute(
            "INSERT INTO site_sets(name, action, grp, position, rules, icon)"
            " VALUES (?, ?, '所有-自动', ?, ?, ?)",
            (name, action, pos, json.dumps(rules, ensure_ascii=False), icon))
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
            "INSERT INTO nodes(sub_id, tag, protocol, server, port, params, orig_tag)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, tag, n.protocol, n.server, n.server_port,
             json.dumps(n.params, ensure_ascii=False), n.tag),
        )
        count += 1
    conn.commit()
    bump_rev(conn)
    return sid, count


def list_subscriptions(conn: sqlite3.Connection) -> list[dict]:
    out = []
    cols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)")}
    au_cols = ""
    if "auto_update_enabled" in cols:
        au_cols = ", auto_update_enabled, auto_update_days, auto_update_hour"
    for r in conn.execute(
            "SELECT id, name, source, url, created_at, enabled, auto_update_hours,"
            " updated_at, userinfo, urls, rename_enabled, rename_prefix, rename_order,"
            " rename_seq_digits, rename_regions, rename_fallback, rename_features,"
            f" rename_filter, dns_resolve{au_cols} FROM subscriptions ORDER BY id"):
        (sid, name, source, url, created, enabled, auh, updated, userinfo,
         urls, rn_en, rn_prefix, rn_order, rn_digits, rn_regions,
         rn_fallback, rn_features, rn_filter, dns_resolve, *au_rest) = r
        if len(au_rest) == 3:
            au_en, au_days, au_hour = au_rest
        else:
            au_en, au_days, au_hour = (1 if (auh or 0) > 0 else 0,
                                      max(1, round((auh or 0) / 24)), 4)
        n = conn.execute("SELECT COUNT(*) FROM nodes WHERE sub_id=? AND disabled=0",
                         (sid,)).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM nodes WHERE sub_id=?",
                             (sid,)).fetchone()[0]
        try:
            ui = json.loads(userinfo or "{}")
        except ValueError:
            ui = {}
        try:
            url_list = json.loads(urls or "[]")
        except ValueError:
            url_list = []
        if url and url not in url_list:
            url_list.insert(0, url)
        try:
            regions = json.loads(rn_regions or "[]")
        except ValueError:
            regions = []
        try:
            order = json.loads(rn_order or "[]")
        except ValueError:
            order = ["region", "feature", "seq"]
        out.append({"id": sid, "name": name, "source": source, "url": url,
                    "urls": url_list,
                    "created_at": created, "node_count": n, "node_total": total,
                    "enabled": bool(enabled),
                    "auto_update_hours": auh or 0,
                    "auto_update": {"enabled": bool(au_en),
                                    "days": au_days or 1,
                                    "hour": au_hour if au_hour is not None else 4},
                    "updated_at": updated,
                    "userinfo": ui, "dns_resolve": dns_resolve or "auto",
                    "rename": {"enabled": bool(rn_en), "prefix": bool(rn_prefix),
                               "order": order, "seq_digits": rn_digits or 2,
                               "regions": regions, "fallback": rn_fallback or "其他",
                               "features": rn_features or "",
                               "filter": rn_filter or ""}})
    return out


def delete_subscription(conn: sqlite3.Connection, sid: int) -> bool:
    conn.execute("DELETE FROM nodes WHERE sub_id=?", (sid,))
    cur = conn.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
    conn.commit()
    bump_rev(conn)
    return cur.rowcount > 0


def add_manual_nodes(conn: sqlite3.Connection, content: str, name: str = "") -> dict:
    """Manually add node(s) from pasted share link(s). Creates a new
    subscription with the given name (or reuses '手动节点')."""
    from core.subscription import parse_subscription
    nodes = parse_subscription(content)
    if not nodes:
        raise ValueError("no nodes parsed from content")
    name = (name or "").strip() or "手动节点"
    row = conn.execute("SELECT id FROM subscriptions WHERE name=?", (name,)).fetchone()
    if row:
        sid = row[0]
    else:
        cur = conn.execute(
            "INSERT INTO subscriptions(name, source, created_at) VALUES (?, 'manual', ?)",
            (name, time.strftime("%Y-%m-%dT%H:%M:%S")))
        sid = cur.lastrowid
    existing = {r[0] for r in conn.execute("SELECT tag FROM nodes")}
    added = []
    for n in nodes:
        tag, i = n.tag, 2
        while tag in existing:
            tag = f"{n.tag} #{i}"
            i += 1
        existing.add(tag)
        conn.execute(
            "INSERT INTO nodes(sub_id, tag, protocol, server, port, params, orig_tag)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, tag, n.protocol, n.server, n.server_port,
             json.dumps(n.params, ensure_ascii=False), n.tag))
        added.append(tag)
    conn.commit()
    bump_rev(conn)
    return {"subscription_id": sid, "added": added, "node_count": len(added)}


def list_nodes(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"id": r[0], "tag": r[1], "protocol": r[2], "server": r[3],
         "port": r[4], "params": json.loads(r[5]), "sub_id": r[6],
         "orig_tag": r[7] or r[1], "custom_tag": r[8] or "",
         "disabled": bool(r[9])}
        for r in conn.execute(
            "SELECT id, tag, protocol, server, port, params, sub_id,"
            " orig_tag, custom_tag, disabled FROM nodes ORDER BY id")
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
            "flip": r[6] if len(r) > 6 else "",
            "icon": r[7] if len(r) > 7 else ""}


def list_site_sets(conn: sqlite3.Connection) -> list[dict]:
    return [_site_set_row(r) for r in conn.execute(
        "SELECT id, name, action, grp, position, rules, flip, icon FROM site_sets"
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


# -- front custom routing ----------------------------------------------
def list_front_rules(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"id": r[0], "domain": r[1], "target": r[2], "position": r[3],
         "enabled": bool(r[4])}
        for r in conn.execute(
            "SELECT id, domain, target, position, enabled FROM front_rules"
            " ORDER BY position, id")
    ]


def create_front_rule(conn: sqlite3.Connection, d: dict) -> dict:
    domain = str(d.get("domain", "")).strip()
    if not domain:
        raise ValueError("domain required")
    pos = conn.execute("SELECT COALESCE(MAX(position), -1)+1 FROM front_rules").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO front_rules(domain, target, position, enabled) VALUES (?, ?, ?, ?)",
        (domain, str(d.get("target", "auto")).strip() or "auto", pos,
         0 if d.get("enabled") is False else 1))
    conn.commit()
    bump_rev(conn)
    target = str(d.get("target", "auto")).strip() or "auto"
    return {"id": cur.lastrowid, "domain": domain, "target": target,
            "position": pos, "enabled": d.get("enabled", True) is not False}


def update_front_rule(conn: sqlite3.Connection, rid: int, d: dict) -> dict | None:
    row = conn.execute("SELECT id FROM front_rules WHERE id=?", (rid,)).fetchone()
    if not row:
        return None
    fields, vals = [], []
    for col, key in (("domain", "domain"), ("target", "target"),
                     ("position", "position"), ("enabled", "enabled")):
        if key in d:
            fields.append(f"{col}=?")
            vals.append(0 if key == "enabled" and not d[key] else d[key])
    if fields:
        vals.append(rid)
        conn.execute(f"UPDATE front_rules SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    bump_rev(conn)
    return next((r for r in list_front_rules(conn) if r["id"] == rid), None)


def delete_front_rule(conn: sqlite3.Connection, rid: int) -> bool:
    cur = conn.execute("DELETE FROM front_rules WHERE id=?", (rid,))
    conn.commit()
    bump_rev(conn)
    return cur.rowcount > 0


# -- region routing (client apps) --------------------------------------
def list_region_rules(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute(
            "SELECT id, region, name, rules, position, enabled FROM region_rules"
            " ORDER BY position, id"):
        try:
            rules = json.loads(r[3] or "{}")
        except ValueError:
            rules = {}
        out.append({"id": r[0], "region": r[1], "name": r[2], "rules": rules,
                    "position": r[4], "enabled": bool(r[5])})
    return out


def create_region_rule(conn: sqlite3.Connection, d: dict) -> dict:
    region = str(d.get("region", "")).strip()
    if not region:
        raise ValueError("region required")
    rules = d.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("rules must be an object")
    pos = conn.execute("SELECT COALESCE(MAX(position), -1)+1 FROM region_rules").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO region_rules(region, name, rules, position, enabled)"
        " VALUES (?, ?, ?, ?, ?)",
        (region, str(d.get("name", "")).strip()[:80],
         json.dumps(rules, ensure_ascii=False), pos,
         0 if d.get("enabled") is False else 1))
    conn.commit()
    bump_rev(conn)
    return {"id": cur.lastrowid, "region": region,
            "name": str(d.get("name", "")).strip()[:80], "rules": rules,
            "position": pos, "enabled": d.get("enabled", True) is not False}


def update_region_rule(conn: sqlite3.Connection, rid: int, d: dict) -> dict | None:
    row = conn.execute("SELECT id FROM region_rules WHERE id=?", (rid,)).fetchone()
    if not row:
        return None
    fields, vals = [], []
    for col, key in (("region", "region"), ("name", "name"),
                     ("position", "position"), ("enabled", "enabled")):
        if key in d:
            fields.append(f"{col}=?")
            vals.append(0 if key == "enabled" and not d[key] else d[key])
    if "rules" in d and isinstance(d["rules"], dict):
        fields.append("rules=?")
        vals.append(json.dumps(d["rules"], ensure_ascii=False))
    if fields:
        vals.append(rid)
        conn.execute(f"UPDATE region_rules SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    bump_rev(conn)
    return next((r for r in list_region_rules(conn) if r["id"] == rid), None)


def delete_region_rule(conn: sqlite3.Connection, rid: int) -> bool:
    cur = conn.execute("DELETE FROM region_rules WHERE id=?", (rid,))
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
        for r in conn.execute(
            "SELECT n.tag, n.protocol, n.server, n.port, n.params FROM nodes n"
            " JOIN subscriptions s ON s.id = n.sub_id"
            " WHERE s.enabled = 1 AND n.disabled = 0 ORDER BY n.id")
    ]
    # subscription URL hostnames (for sub_node_direct)
    sub_domains = []
    for (url,) in conn.execute(
            "SELECT url FROM subscriptions WHERE enabled=1 AND url IS NOT NULL AND url != ''"):
        try:
            from urllib.parse import urlparse as _up
            host = (_up(url).hostname or "").strip().lower()
            if host and not _is_ip(host):
                sub_domains.append(host)
        except Exception:
            pass
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
    def _mk_group(r):
        try:
            lanes = json.loads(r[11]) if len(r) > 11 and r[11] else []
        except ValueError:
            lanes = []
        return Group(name=r[0], type=r[1], members=json.loads(r[2]),
                     dynamic_keywords=json.loads(r[3]), position=r[4],
                     enabled=bool(r[5]), interval_s=r[6] or 300,
                     tolerance_ms=r[7] or 100,
                     idle_timeout=r[8] if len(r) > 8 and r[8] else "12h",
                     expected_status=r[9] if len(r) > 9 and r[9] else "",
                     test_url=r[10] if len(r) > 10 and r[10] else "",
                     lanes=lanes if isinstance(lanes, list) else [])
    groups = [
        _mk_group(r)
        for r in conn.execute(
            "SELECT name, type, members, dynamic_keywords, position, enabled,"
            " interval_s, tolerance_ms, idle_timeout, expected_status, test_url, lanes"
            " FROM groups ORDER BY position, id")
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
        enable_fakeip=get_setting(conn, "dns_fakeip", "0") == "1",
        mode=get_setting(conn, "dns_mode", "dnsmasq"),
        split=get_setting(conn, "dns_split", "1") == "1",
        region=get_setting(conn, "dns_region", "auto"),
        region_detected=get_setting(conn, "dns_region_detected", ""),
        upstream_latency=_safe_json_loads(get_setting(conn, "dns_upstream_latency", "{}")))
    # region-aware proxy DNS default (documented behavior): outside mainland
    # defaults to the upstream DNS instead of TCP 1.1.1.1, unless customized.
    eff_region = dns.region if dns.region != "auto" else (dns.region_detected or "cn")
    if (get_setting(conn, "dns_proxy", DEFAULT_SETTINGS["dns_proxy"])
            == DEFAULT_SETTINGS["dns_proxy"] and eff_region == "outside"):
        dns.proxy_dns = "8.8.8.8"
    rewrites = [
        DnsRewrite(id=r[0], domain=r[1], target=r[2])
        for r in conn.execute("SELECT id, domain, target FROM dns_rewrite WHERE enabled=1 ORDER BY domain")]
    terminals = [
        TerminalPolicy(id=r[0], ident=r[1], name=r[2], policy=r[3])
        for r in conn.execute("SELECT id, ident, name, policy FROM terminal_policies ORDER BY ident")]
    return AppConfig(
        nodes=nodes, site_sets=site_sets, groups=groups, chains=chains, dns=dns,
        dns_rewrites=rewrites, terminals=terminals,
        front_rules=[r for r in list_front_rules(conn) if r["enabled"]],
        final_outbound=get_setting(conn, "final_outbound", "所有-自动"),
        routing_fallback=get_setting(conn, "routing_fallback", "direct"),
        tun_stack=get_setting(conn, "tun_stack", "mixed"),
        tun_mtu=int(get_setting(conn, "tun_mtu", "9000") or 9000),
        tun_address=get_setting(conn, "tun_address", "172.19.0.1/30"),
        quic_block=get_setting(conn, "quic_block", "1") == "1",
        clash_api_port=int(get_setting(conn, "clash_api_port", "9090") or 9090),
        clash_api_listen=get_setting(conn, "clash_api_listen", "127.0.0.1"),
        clash_api_secret=get_setting(conn, "clash_api_secret", ""),
        share_lan_enabled=get_setting(conn, "share_lan_enabled", "0") == "1",
        share_lan_port=int(get_setting(conn, "share_lan_port", "8088") or 8088),
        share_servers=[s for s in list_share_servers(conn) if s["enabled"]],
        sub_node_direct=get_setting(conn, "sub_node_direct", "0") == "1",
        sub_domains=list(dict.fromkeys(sub_domains)),
        speedtest_url=get_setting(conn, "speedtest_url",
                                  DEFAULT_SETTINGS["speedtest_url"]) or
        DEFAULT_SETTINGS["speedtest_url"],
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
    front = d.get("front", "所有-自动")
    if isinstance(front, list):
        front = front[0] if front else "所有-自动"
    cur = conn.execute(
        "INSERT INTO chains(name, exit_protocol, server, port, params, front)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (d["name"], d.get("exit_protocol", "socks"), d.get("server", ""),
         int(d.get("port", 0)), json.dumps(d.get("params", {}), ensure_ascii=False),
         front))
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
            v = d[key]
            if key == "front" and isinstance(v, list):
                v = v[0] if v else "所有-自动"
            fields.append(f"{col}=?")
            vals.append(v)
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
    try:
        lanes = json.loads(r[12]) if len(r) > 12 and r[12] else []
    except ValueError:
        lanes = []
    return {"id": r[0], "name": r[1], "type": r[2], "members": json.loads(r[3]),
            "dynamic_keywords": json.loads(r[4]), "position": r[5],
            "enabled": bool(r[6]), "interval_s": r[7] or 300,
            "tolerance_ms": r[8] or 100,
            "idle_timeout": r[9] if len(r) > 9 and r[9] else "12h",
            "expected_status": r[10] if len(r) > 10 and r[10] else "",
            "test_url": r[11] if len(r) > 11 and r[11] else "",
            "lanes": lanes if isinstance(lanes, list) else [],
            "icon": r[13] if len(r) > 13 and r[13] else "",
            "icon_scale": r[14] if len(r) > 14 and r[14] else 0}


def list_groups(conn: sqlite3.Connection) -> list[dict]:
    from core.singbox import resolve_group_members
    from core.models import Group as _Group
    node_tags = [r[0] for r in conn.execute(
        "SELECT n.tag FROM nodes n JOIN subscriptions s ON s.id = n.sub_id"
        " WHERE s.enabled = 1 ORDER BY n.id")]
    chain_tags = [r[0] for r in conn.execute("SELECT name FROM chains ORDER BY id")]
    out = []
    for r in conn.execute(
            "SELECT id, name, type, members, dynamic_keywords, position, enabled,"
            " interval_s, tolerance_ms, idle_timeout, expected_status, test_url, lanes,"
            " icon, icon_scale"
            " FROM groups ORDER BY position, id"):
        g = _group_row(r)
        gm = _Group(name=g["name"], type=g["type"], members=g["members"],
                    dynamic_keywords=g["dynamic_keywords"])
        g["member_count"] = len(resolve_group_members(gm, node_tags, chain_tags))
        g["dynamic"] = bool(g["dynamic_keywords"]) or \
            any(m in ("*nodes*", "*all*") for m in (g["members"] or []))
        out.append(g)
    # built-in groups: 直连 first (原版默认排第一个), 拒绝 last
    # 1:1 对标原版：内置组也可拖拽排序，顺序持久化在 group_order setting
    # （0=直连, -1=拒绝, 正数=用户组 id）
    builtin_direct = {"id": 0, "name": "direct", "type": "builtin", "members": [],
                "dynamic_keywords": [], "position": -1, "enabled": True,
                "interval_s": 0, "tolerance_ms": 0, "member_count": 0,
                "dynamic": False, "builtin": True, "desc": "直连",
                "detail": "流量不经代理，直接从路由器出去。内核离不开它，停用只是站点集里选不到。"}
    builtin_block = {"id": -1, "name": "block", "type": "builtin", "members": [],
                "dynamic_keywords": [], "position": 9999, "enabled": True,
                "interval_s": 0, "tolerance_ms": 0, "member_count": 0,
                "dynamic": False, "builtin": True, "desc": "拒绝",
                "detail": "命中的流量直接丢弃。"}
    # 按 group_order setting 排序（包含内置组）
    try:
        order = json.loads(get_setting(conn, "group_order", "") or "[]")
    except ValueError:
        order = []
    if order:
        by_id = {g["id"]: g for g in out}
        by_id[0] = builtin_direct
        by_id[-1] = builtin_block
        ordered = []
        seen = set()
        for gid in order:
            if gid in by_id and gid not in seen:
                ordered.append(by_id[gid])
                seen.add(gid)
        # 新组追加到末尾（拒绝之前）
        for g in out:
            if g["id"] not in seen:
                ordered.append(g)
                seen.add(g["id"])
        if 0 not in seen:
            ordered.insert(0, builtin_direct)
        if -1 not in seen:
            ordered.append(builtin_block)
        return ordered
    out.insert(0, builtin_direct)
    out.append(builtin_block)
    return out


def _normalize_lanes(lanes) -> list[dict]:
    """Normalize failover lanes to [{name, icon, mode, members[]}].

    1:1 对标原版：每页签有独立图标、名称（可选）、模式（auto=自动优选/urltest,
    manual=手动选择/selector）。
    """
    out = []
    if not isinstance(lanes, list):
        return out
    for i, ln in enumerate(lanes):
        if not isinstance(ln, dict):
            continue
        name = str(ln.get("name") or "").strip()
        mode = ln.get("mode") or "auto"
        if mode not in ("auto", "manual"):
            mode = "auto"
        members = [str(m).strip() for m in (ln.get("members") or [])
                   if str(m).strip()]
        out.append({"name": name,
                    "icon": str(ln.get("icon") or "").strip(),
                    "mode": mode,
                    "members": members})
    return out


def _validate_failover(members, dynamic_keywords, lanes) -> None:
    # 1:1 with the original panel: failover only supports static members
    # (explicit member list, no dynamic keywords) and requires lanes
    # (primary/backup tabs).
    if dynamic_keywords:
        raise ValueError("failover 只支持静态成员，不能使用动态关键词")
    if not lanes:
        raise ValueError("failover 需要主备页签（lanes）")


def create_group(conn: sqlite3.Connection, d: dict) -> dict:
    if d.get("type", "urltest") not in ("urltest", "selector", "failover"):
        raise ValueError("type must be urltest|selector|failover")
    pos = conn.execute("SELECT COALESCE(MAX(position), -1)+1 FROM groups").fetchone()[0]
    lanes = _normalize_lanes(d.get("lanes"))
    if d.get("type") == "failover":
        _validate_failover(d.get("members", []), d.get("dynamic_keywords", []), lanes)
    cur = conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, position,"
        " enabled, interval_s, tolerance_ms, idle_timeout,"
        " expected_status, test_url, lanes, icon, icon_scale)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (d["name"], d.get("type", "urltest"),
         json.dumps(d.get("members", []), ensure_ascii=False),
         json.dumps(d.get("dynamic_keywords", []), ensure_ascii=False), pos,
         0 if d.get("enabled") is False else 1,
         int(d.get("interval_s", 300) or 300),
         int(d.get("tolerance_ms", 100) or 100),
         d.get("idle_timeout", "12h") or "12h",
         (d.get("expected_status") or "").strip(),
         (d.get("test_url") or "").strip(),
         json.dumps(lanes, ensure_ascii=False),
         (d.get("icon") or "").strip(),
         int(d.get("icon_scale", 0) or 0)))
    conn.commit()
    bump_rev(conn)
    return _group_row(conn.execute(
        "SELECT id, name, type, members, dynamic_keywords, position, enabled,"
        " interval_s, tolerance_ms, idle_timeout, expected_status, test_url, lanes,"
        " icon, icon_scale"
        " FROM groups WHERE id=?",
        (cur.lastrowid,)).fetchone())


def update_group(conn: sqlite3.Connection, gid: int, d: dict) -> dict | None:
    row = conn.execute("SELECT id FROM groups WHERE id=?", (gid,)).fetchone()
    if not row:
        return None
    fields, vals = [], []
    for col, key in (("name", "name"), ("type", "type"), ("position", "position"),
                     ("enabled", "enabled"), ("interval_s", "interval_s"),
                     ("tolerance_ms", "tolerance_ms"),
                     ("idle_timeout", "idle_timeout"),
                     ("expected_status", "expected_status"),
                     ("test_url", "test_url"),
                     ("icon", "icon"), ("icon_scale", "icon_scale")):
        if key in d:
            if key == "type" and d[key] not in ("urltest", "selector", "failover"):
                raise ValueError("type must be urltest|selector|failover")
            fields.append(f"{col}=?")
            v = d[key]
            if key == "enabled" and not v:
                v = 0
            if key in ("expected_status", "test_url") and isinstance(v, str):
                v = v.strip()
            vals.append(v)
    for key in ("members", "dynamic_keywords"):
        if key in d:
            fields.append(f"{key}=?")
            vals.append(json.dumps(d[key], ensure_ascii=False))
    if "lanes" in d:
        lanes = _normalize_lanes(d["lanes"])
        # validate against the (possibly updated) type/members
        cur_type = d.get("type")
        if cur_type is None:
            cur_type = conn.execute("SELECT type FROM groups WHERE id=?",
                                    (gid,)).fetchone()[0]
        if cur_type == "failover":
            cur_members = d.get("members")
            cur_kw = d.get("dynamic_keywords")
            if cur_members is None or cur_kw is None:
                row = conn.execute("SELECT members, dynamic_keywords FROM groups"
                                   " WHERE id=?", (gid,)).fetchone()
                if cur_members is None:
                    cur_members = json.loads(row[0])
                if cur_kw is None:
                    cur_kw = json.loads(row[1])
            _validate_failover(cur_members, cur_kw, lanes)
        fields.append("lanes=?")
        vals.append(json.dumps(lanes, ensure_ascii=False))
    if fields:
        vals.append(gid)
        conn.execute(f"UPDATE groups SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    bump_rev(conn)
    return _group_row(conn.execute(
        "SELECT id, name, type, members, dynamic_keywords, position, enabled,"
        " interval_s, tolerance_ms, idle_timeout, expected_status, test_url, lanes"
        " FROM groups WHERE id=?",
        (gid,)).fetchone())


def delete_group(conn: sqlite3.Connection, gid: int) -> bool:
    cur = conn.execute("DELETE FROM groups WHERE id=?", (gid,))
    conn.commit()
    bump_rev(conn)
    return cur.rowcount > 0


def reorder_groups(conn: sqlite3.Connection, ordered_ids: list[int]) -> None:
    """Set group positions from an ordered list of group ids.

    1:1 对标原版：ordered_ids 包含内置组（0=直连, -1=拒绝）。
    用户组按 position 排序，完整顺序（含内置组）存入 group_order setting。
    """
    # 用户组：按传入顺序更新 position
    pos = 0
    for gid in ordered_ids:
        if gid > 0:  # 只更新真实存在的用户组
            conn.execute("UPDATE groups SET position=? WHERE id=?", (pos, gid))
            pos += 1
    # 完整顺序存 setting（含内置组）
    set_setting(conn, "group_order", json.dumps(ordered_ids, ensure_ascii=False))
    conn.commit()
    bump_rev(conn)


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
    return [{"id": r[0], "domain": r[1], "target": r[2],
             "enabled": bool(r[3]) if len(r) > 3 else True}
            for r in conn.execute(
                "SELECT id, domain, target, enabled FROM dns_rewrite ORDER BY domain")]


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
    r = conn.execute("SELECT id, domain, target, enabled FROM dns_rewrite WHERE id=?",
                     (cur.lastrowid,)).fetchone()
    if not r:  # was an upsert on existing row; fetch by domain
        r = conn.execute("SELECT id, domain, target, enabled FROM dns_rewrite WHERE domain=?",
                         (domain,)).fetchone()
    return {"id": r[0], "domain": r[1], "target": r[2], "enabled": bool(r[3])}


def set_dns_rewrite_enabled(conn: sqlite3.Connection, rid: int, enabled: bool) -> bool:
    cur = conn.execute("UPDATE dns_rewrite SET enabled=? WHERE id=?",
                       (1 if enabled else 0, rid))
    conn.commit()
    if cur.rowcount:
        bump_rev(conn)
    return cur.rowcount > 0


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
def prune_old_traffic(conn: sqlite3.Connection) -> int:
    """Delete traffic_daily rows older than traffic_keep_months. Returns rows deleted."""
    try:
        months = int(get_setting(conn, "traffic_keep_months", "3"))
    except ValueError:
        months = 3
    if months <= 0:
        return 0
    import datetime
    cutoff = (datetime.date.today() - datetime.timedelta(days=months * 30)).isoformat()
    cur = conn.execute("DELETE FROM traffic_daily WHERE day < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def record_traffic(conn: sqlite3.Connection, day: str, client: str,
                   proxy: str, host: str, up: int, down: int,
                   conns: int = 0) -> None:
    conn.execute(
        "INSERT INTO traffic_daily(day, client, proxy, host, up, down, conns)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(day, client, proxy, host) DO UPDATE SET"
        " up=up+excluded.up, down=down+excluded.down, conns=conns+excluded.conns",
        (day, client or "", proxy or "", host or "", up, down, conns))
    conn.commit()


def traffic_summary(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    return [{"day": r[0], "client": r[1], "proxy": r[2], "host": r[3],
             "up": r[4], "down": r[5], "conns": r[6] or 0}
            for r in conn.execute(
                "SELECT day, client, proxy, host, SUM(up), SUM(down), SUM(conns) FROM traffic_daily"
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
        " VALUES ('所有-自动', 'urltest', '[\"*nodes*\"]', '[]', 0)")
    conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, position)"
        " VALUES ('所有-手动', 'selector', '[\"*all*\"]', '[]', 1)")
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
    """month='YYYY-MM'. Per-day rows + total + daily average.

    All days of the month are present (zero-filled), like the original panel.
    """
    import calendar as _cal
    import time as _time
    rows = {r[0]: (r[1] or 0, r[2] or 0, r[3] or 0) for r in conn.execute(
        "SELECT day, SUM(up), SUM(down), SUM(conns) FROM traffic_daily"
        " WHERE substr(day, 1, 7)=? GROUP BY day", (month,))}
    y, m = int(month[:4]), int(month[5:7])
    days = [{"day": f"{month}-{d:02d}",
             "up": rows.get(f"{month}-{d:02d}", (0, 0, 0))[0],
             "down": rows.get(f"{month}-{d:02d}", (0, 0, 0))[1],
             "conns": rows.get(f"{month}-{d:02d}", (0, 0, 0))[2]}
            for d in range(1, _cal.monthrange(y, m)[1] + 1)]
    total_up = sum(d["up"] for d in days)
    total_down = sum(d["down"] for d in days)
    total_conns = sum(d["conns"] for d in days)
    n = len(days) or 1
    return {"month": month, "today": _time.strftime("%Y-%m-%d"), "days": days,
            "total": {"up": total_up, "down": total_down, "conns": total_conns},
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


# -- share servers (1:1 original: profile.servers[]; LAN inbound proxies) ----
SS_METHODS = ("aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305",
              "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm")


def _share_row(r) -> dict:
    return {"id": r[0], "name": r[1], "protocol": r[2], "address": r[3],
            "port": r[4], "method": r[5], "password": r[6],
            "enabled": bool(r[7]), "created_at": r[8]}


def list_share_servers(conn: sqlite3.Connection) -> list[dict]:
    return [_share_row(r) for r in conn.execute(
        "SELECT id, name, protocol, address, port, method, password,"
        " enabled, created_at FROM share_servers ORDER BY id")]


def create_share_server(conn: sqlite3.Connection, d: dict) -> dict:
    import secrets as _secrets
    protocol = d.get("protocol", "shadowsocks")
    if protocol != "shadowsocks":
        raise ValueError("protocol must be shadowsocks")
    method = d.get("method", "aes-256-gcm")
    if method not in SS_METHODS:
        raise ValueError(f"method must be one of {', '.join(SS_METHODS)}")
    port = int(d.get("port", 8388))
    if not 1024 <= port <= 65535:
        raise ValueError("port must be 1024-65535")
    if conn.execute("SELECT id FROM share_servers WHERE port=?",
                    (port,)).fetchone():
        raise ValueError(f"port {port} already in use")
    password = (d.get("password") or "").strip() or _secrets.token_urlsafe(16)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    cur = conn.execute(
        "INSERT INTO share_servers(name, protocol, address, port, method,"
        " password, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(d.get("name") or "").strip(), protocol,
         str(d.get("address") or "127.0.0.1").strip(), port, method, password,
         0 if d.get("enabled") is False else 1, now))
    conn.commit()
    bump_rev(conn)
    return _share_row(conn.execute(
        "SELECT id, name, protocol, address, port, method, password,"
        " enabled, created_at FROM share_servers WHERE id=?",
        (cur.lastrowid,)).fetchone())


def update_share_server(conn: sqlite3.Connection, sid: int, d: dict) -> dict | None:
    if not conn.execute("SELECT id FROM share_servers WHERE id=?",
                        (sid,)).fetchone():
        return None
    fields, vals = [], []
    for col, key in (("name", "name"), ("protocol", "protocol"),
                     ("address", "address"), ("port", "port"),
                     ("method", "method"), ("password", "password"),
                     ("enabled", "enabled")):
        if key in d:
            v = d[key]
            if key == "protocol" and v != "shadowsocks":
                raise ValueError("protocol must be shadowsocks")
            if key == "method" and v not in SS_METHODS:
                raise ValueError(f"method must be one of {', '.join(SS_METHODS)}")
            if key == "port":
                v = int(v)
                if not 1024 <= v <= 65535:
                    raise ValueError("port must be 1024-65535")
                if conn.execute("SELECT id FROM share_servers WHERE port=? AND id!=?",
                                (v, sid)).fetchone():
                    raise ValueError(f"port {v} already in use")
            if key == "enabled":
                v = 0 if not v else 1
            if isinstance(v, str):
                v = v.strip()
            fields.append(f"{col}=?")
            vals.append(v)
    if fields:
        vals.append(sid)
        conn.execute(f"UPDATE share_servers SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    bump_rev(conn)
    return _share_row(conn.execute(
        "SELECT id, name, protocol, address, port, method, password,"
        " enabled, created_at FROM share_servers WHERE id=?",
        (sid,)).fetchone())


def delete_share_server(conn: sqlite3.Connection, sid: int) -> bool:
    cur = conn.execute("DELETE FROM share_servers WHERE id=?", (sid,))
    conn.commit()
    if cur.rowcount:
        bump_rev(conn)
    return cur.rowcount > 0


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
    try:
        from core import arp as _arp
        arp = _arp.arp_table()
    except Exception:
        arp = {}
    leases = dhcp_hostnames()
    out = [{"ip": ip, "hostname": hn, "source": "dhcp",
            "mac": arp.get(ip, "")} for ip, hn in leases.items()]
    seen = set(leases)
    try:
        for (client,) in conn.execute(
                "SELECT DISTINCT client FROM traffic_daily WHERE client != ''"):
            if client not in seen:
                out.append({"ip": client, "hostname": "",
                            "source": "traffic", "mac": arp.get(client, "")})
                seen.add(client)
    except sqlite3.Error:
        pass
    # ARP-only entries (no DHCP lease / traffic yet)
    for ip, mac in arp.items():
        if ip not in seen:
            out.append({"ip": ip, "hostname": "", "source": "arp", "mac": mac})
            seen.add(ip)
    return out


def refresh_subscription(conn: sqlite3.Connection, sid: int,
                         timeout: float = 30.0) -> dict:
    """Re-fetch subscription URL(s) and replace its nodes. Returns stats.

    Multiple URLs are merged. Rename rules (region/feature/seq, filter
    keywords) are applied on import. Per-node custom names and disabled
    flags survive refreshes (matched by original tag).
    """
    import urllib.request
    row = conn.execute(
        "SELECT name, url, urls, rename_enabled, rename_prefix, rename_order,"
        " rename_seq_digits, rename_regions, rename_fallback, rename_features,"
        " rename_filter FROM subscriptions WHERE id=?", (sid,)).fetchone()
    if not row:
        raise KeyError("not found")
    (name, url, urls_json, rn_en, rn_prefix, rn_order, rn_digits,
     rn_regions, rn_fallback, rn_features, rn_filter) = row
    try:
        urls = json.loads(urls_json or "[]")
    except ValueError:
        urls = []
    urls = [u.strip() for u in urls if u and u.strip()]
    if url and url.strip() and url.strip() not in urls:
        urls.insert(0, url.strip())
    if not urls:
        raise ValueError("subscription has no URL to refresh")
    # remember per-node customizations before wiping
    kept = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT orig_tag, custom_tag, disabled FROM nodes WHERE sub_id=?", (sid,))}
    from core.subscription import parse_subscription
    from core.clash import parse_clash_yaml, looks_like_clash
    from core import rename as _rn
    nodes = []
    userinfo: dict = {}
    for u in urls:
        req = urllib.request.Request(u, headers={"User-Agent": "openbox-oss/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read().decode("utf-8", "replace")
            if not userinfo:
                for part in r.headers.get("subscription-userinfo", "").split(";"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k in ("upload", "download", "total", "expire"):
                            try:
                                userinfo[k] = int(v)
                            except ValueError:
                                pass
        nodes.extend(parse_clash_yaml(content) if looks_like_clash(content)
                     else parse_subscription(content))
    return _replace_nodes(conn, sid, name, nodes, userinfo,
                          _rename_cfg_from_row(row))


def _rename_cfg_from_row(row) -> dict:
    """Build rename cfg from the SELECT row in refresh_subscription."""
    from core import rename as _rn
    (name, url, urls_json, rn_en, rn_prefix, rn_order, rn_digits,
     rn_regions, rn_fallback, rn_features, rn_filter) = row
    return {
        "enabled": bool(rn_en), "prefix": bool(rn_prefix), "sub_name": name,
        "order": json.loads(rn_order or "[]") or ["region", "feature", "seq"],
        "seq_digits": rn_digits or 2,
        "regions": json.loads(rn_regions or "[]") or _rn.DEFAULT_REGIONS,
        "fallback": rn_fallback or "其他",
        "features": rn_features if rn_features != "" else _rn.DEFAULT_FEATURES,
        "filter": rn_filter if rn_filter != "" else _rn.DEFAULT_FILTER,
    }


def _replace_nodes(conn: sqlite3.Connection, sid: int, name: str,
                   nodes: list, userinfo: dict | None = None,
                   rename_cfg: dict | None = None) -> dict:
    """Shared import pipeline: rename rules, filter keywords, preserve
    per-node custom names / disabled flags across replacement."""
    from core import rename as _rn
    rename_cfg = rename_cfg or {"enabled": False}
    # remember per-node customizations before wiping
    kept = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT orig_tag, custom_tag, disabled FROM nodes WHERE sub_id=?", (sid,))}
    renamed = _rn.rename_nodes([n.tag for n in nodes], rename_cfg) \
        if rename_cfg["enabled"] else \
        [{"orig": n.tag, "new": n.tag, "filtered": False} for n in nodes]
    conn.execute("DELETE FROM nodes WHERE sub_id=?", (sid,))
    existing = {r[0] for r in conn.execute("SELECT tag FROM nodes")}
    count, filtered_count = 0, 0
    for n, rn in zip(nodes, renamed):
        if rn["filtered"]:
            filtered_count += 1
            continue
        tag = rn["new"] if rename_cfg["enabled"] else n.tag
        tag, i = tag, 2
        while tag in existing:
            tag = f"{tag} #{i}"
            i += 1
        existing.add(tag)
        custom_tag, disabled = kept.get(rn["orig"], ("", 0))
        if custom_tag:
            tag = custom_tag  # user-edited name wins
            existing.add(tag)
        conn.execute(
            "INSERT INTO nodes(sub_id, tag, protocol, server, port, params,"
            " orig_tag, custom_tag, disabled)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, tag, n.protocol, n.server, n.server_port,
             json.dumps(n.params, ensure_ascii=False),
             rn["orig"], custom_tag or "", disabled or 0))
        count += 1
    conn.execute("UPDATE subscriptions SET updated_at=?, userinfo=? WHERE id=?",
                 (time.strftime("%Y-%m-%dT%H:%M:%S"),
                  json.dumps(userinfo or {}, ensure_ascii=False), sid))
    conn.commit()
    bump_rev(conn)
    return {"id": sid, "name": name, "node_count": count,
            "filtered_count": filtered_count, "userinfo": userinfo or {}}


def reimport_subscription(conn: sqlite3.Connection, sid: int, content: str,
                          format: str = "auto") -> dict:
    """Manually update a subscription's nodes from pasted content.

    Same import pipeline as refresh (rename rules, filter, preserve
    per-node custom names / disabled flags), but the source is pasted
    text instead of fetched URL(s).
    """
    import urllib.request
    row = conn.execute(
        "SELECT name, url, urls, rename_enabled, rename_prefix, rename_order,"
        " rename_seq_digits, rename_regions, rename_fallback, rename_features,"
        " rename_filter FROM subscriptions WHERE id=?", (sid,)).fetchone()
    if not row:
        raise KeyError("not found")
    name = row[0]
    from core.subscription import parse_subscription
    from core.clash import parse_clash_yaml, looks_like_clash
    nodes = (parse_clash_yaml(content) if format == "clash"
             or (format == "auto" and looks_like_clash(content))
             else parse_subscription(content))
    return _replace_nodes(conn, sid, name, nodes,
                          rename_cfg=_rename_cfg_from_row(row))
