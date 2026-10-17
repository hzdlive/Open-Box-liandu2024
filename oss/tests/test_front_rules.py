"""Front-rules backend wiring: typed rules end-to-end.

Covers the zashboard management UI contract for 前置自定义分流:
bulk replace, global enable switch, validation, legacy CRUD compat,
kernel config generation for all 8 rule types, and .srs remote rule-sets.
"""

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


def test_bulk_replace_roundtrip():
    app = _app()
    c = app.test_client()
    assert c.get("/api/front-rules").get_json() == []
    rules = [
        {"type": "domain_suffix", "value": "example.com", "note": "n1",
         "target": "所有-自动"},
        {"type": "domain", "value": "a.example.com", "target": "direct"},
        {"type": "domain_keyword", "value": "ads", "target": "reject"},
        {"type": "ip_cidr", "value": "10.0.0.0/8", "target": "direct"},
        {"type": "geosite", "value": "youtube", "target": "所有-自动"},
        {"type": "geoip", "value": "cn", "target": "direct"},
        {"type": "ruleset_url", "value": "https://x.test/rules.srs",
         "target": "所有-自动"},
        {"type": "port", "value": "443", "target": "所有-自动"},
        {"type": "port", "value": "8000-9000", "target": "direct"},
    ]
    r = c.put("/api/front-rules", json={"rules": rules})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["enabled"] is True
    rows = c.get("/api/front-rules").get_json()
    assert len(rows) == 9
    assert rows[0]["rtype"] == "domain_suffix" and rows[0]["note"] == "n1"
    assert rows[4]["rtype"] == "geosite" and rows[4]["domain"] == "youtube"
    assert [r["position"] for r in rows] == list(range(9))
    # replace again -> old rows gone
    r = c.put("/api/front-rules", json={"rules": rules[:2]})
    assert r.status_code == 200
    assert len(c.get("/api/front-rules").get_json()) == 2
    # clear
    r = c.put("/api/front-rules", json={"rules": []})
    assert r.status_code == 200
    assert c.get("/api/front-rules").get_json() == []


def test_bulk_validation():
    app = _app()
    c = app.test_client()
    bad = [
        ({"type": "nope", "value": "x", "target": "direct"}, 400),
        ({"type": "ip_cidr", "value": "999.1.1.1", "target": "direct"}, 400),
        ({"type": "port", "value": "0", "target": "direct"}, 400),
        ({"type": "port", "value": "80-70", "target": "direct"}, 400),
        ({"type": "ruleset_url", "value": "ftp://x/y", "target": "direct"}, 400),
        ({"type": "domain_suffix", "value": "  ", "target": "direct"}, 400),
    ]
    for rule, code in bad:
        r = c.put("/api/front-rules", json={"rules": [rule]})
        assert r.status_code == code, (rule, r.get_json())
    # nothing persisted after failures
    assert c.get("/api/front-rules").get_json() == []
    # non-list body
    r = c.put("/api/front-rules", json={"rules": "nope"})
    assert r.status_code == 400


def test_global_enable_switch():
    app = _app()
    c = app.test_client()
    c.put("/api/front-rules", json={
        "rules": [{"type": "domain_suffix", "value": "example.com",
                   "target": "direct"}]})
    conn = _dbconn(app)
    cfg = dbmod.load_app_config(conn)
    assert len(cfg.front_rules) == 1
    # switch off via bulk endpoint
    r = c.put("/api/front-rules", json={"enabled": False})
    assert r.get_json()["enabled"] is False
    cfg = dbmod.load_app_config(_dbconn(app))
    assert cfg.front_rules == []
    # switch on via settings endpoint (frontend toggle path)
    r = c.put("/api/settings", json={"front_rules_enabled": "1"})
    assert r.get_json()["front_rules_enabled"] == "1"
    cfg = dbmod.load_app_config(_dbconn(app))
    assert len(cfg.front_rules) == 1
    # rules survive the toggle
    assert len(c.get("/api/front-rules").get_json()) == 1


def test_legacy_crud_still_works():
    app = _app()
    c = app.test_client()
    # legacy shape: {domain, target}
    r = c.post("/api/front-rules", json={"domain": "legacy.example",
                                         "target": "direct"}).get_json()
    assert r["rtype"] == "domain_suffix"
    rid = r["id"]
    r = c.put(f"/api/front-rules/{rid}", json={"enabled": False}).get_json()
    assert r["enabled"] is False
    assert c.delete(f"/api/front-rules/{rid}").get_json() == {"ok": True}
    assert c.get("/api/front-rules").get_json() == []


def test_generator_all_types():
    from core.singbox import build_route_rules
    from core.models import AppConfig

    cfg = AppConfig()
    cfg.front_rules = [
        {"rtype": "domain_suffix", "domain": ".example.com", "target": "direct"},
        {"rtype": "domain", "domain": "a.example.com", "target": "所有-自动"},
        {"rtype": "domain_keyword", "domain": "ads", "target": "reject"},
        {"rtype": "ip_cidr", "domain": "10.0.0.0/8", "target": "direct"},
        {"rtype": "geosite", "domain": "youtube", "target": "所有-自动"},
        {"rtype": "geoip", "domain": "cn", "target": "direct"},
        {"rtype": "ruleset_url", "domain": "https://x.test/rules.srs",
         "target": "所有-自动"},
        {"rtype": "ruleset_url", "domain": "https://x.test/rules.list",
         "target": "所有-自动"},  # skipped, warned
        {"rtype": "port", "domain": "443", "target": "所有-自动"},
        {"rtype": "port", "domain": "8000-9000", "target": "direct"},
    ]
    route_rules, dns_rules, _ = build_route_rules(cfg)
    by = {}
    for r in route_rules:
        key = next(k for k in ("domain_suffix", "domain", "domain_keyword",
                               "ip_cidr", "rule_set", "port", "port_range")
                   if k in r)
        by.setdefault(key, []).append(r)
    assert by["domain_suffix"][0]["domain_suffix"] == ["example.com"]
    assert by["domain_suffix"][0]["outbound"] == "direct"
    assert by["domain"][0]["outbound"] == "所有-自动"
    assert by["domain_keyword"][0]["action"] == "reject"
    assert by["ip_cidr"][0]["ip_cidr"] == ["10.0.0.0/8"]
    assert "geosite-youtube" in by["rule_set"][0]["rule_set"]
    assert "geoip-cn" in by["rule_set"][1]["rule_set"]
    # .srs url -> remote rule_set tag url-<sha1>
    url_tags = [t for rs in by["rule_set"] for t in rs["rule_set"]
                if t.startswith("url-")]
    assert len(url_tags) == 1
    # .list url rule is skipped (no route rule references it)
    assert not any("rules.list" in str(r) for r in route_rules)
    assert by["port"][0]["port"] == [443]
    assert by["port_range"][0]["port_range"] == ["8000-9000"]
    # dns companions: domain-ish + rule_set types, none for ip/port
    assert any("domain_suffix" in r for r in dns_rules)
    assert any(r.get("rule_set") == ["geosite-youtube"] for r in dns_rules)
    assert not any("ip_cidr" in r or "port" in r for r in dns_rules)
    # front rules come before site-set rules (evaluated first)
    assert route_rules[0].get("domain_suffix") == ["example.com"]

    from core.singbox import front_remote_rule_sets, front_rule_warnings
    remotes = front_remote_rule_sets(cfg)
    assert len(remotes) == 1 and remotes[0][1] == "https://x.test/rules.srs"
    warns = front_rule_warnings(cfg)
    assert len(warns) == 1 and "rules.list" in warns[0]

    from core import geodata as _gd
    names = _gd.referenced_rule_sets(cfg)
    assert "geosite-youtube" in names and "geoip-cn" in names


def test_build_config_declares_remote_rule_sets():
    from core.singbox import build_config
    from core.models import AppConfig

    cfg = AppConfig()
    cfg.front_rules = [
        {"rtype": "ruleset_url", "domain": "https://x.test/rules.srs",
         "target": "所有-自动"},
    ]
    out = build_config(cfg)
    decls = out["route"].get("rule_set", [])
    remote = [d for d in decls if d.get("type") == "remote"]
    assert len(remote) == 1
    assert remote[0]["format"] == "binary"
    assert remote[0]["url"] == "https://x.test/rules.srs"
    tag = remote[0]["tag"]
    assert any(tag in r.get("rule_set", []) for r in out["route"]["rules"])
