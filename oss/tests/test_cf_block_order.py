"""Content-filter block rule must precede split rules (item 5).

Previously the cf block rule was emitted after the site-set loop, so a
blocked domain that also matched a proxy site set (or a front rule)
was proxied instead of blocked -- e.g. doubleclick.net via
geosite-google. The rule now sits after the infrastructure rules
(logical bypass, terminal policies, subscription/node direct) and
before every split rule (front, site sets). Firewall order: infra
first, then deny, then split.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core.models import AppConfig, SiteSet  # noqa: E402
from core.singbox import build_route_rules  # noqa: E402
from core import route_oracle as orc  # noqa: E402


def cfg(front=(), sites=(), blocked=()):
    c = AppConfig()
    c.front_rules = list(front)
    c.site_sets = list(sites)
    c.blocked_domains = list(blocked)
    return c


def site(name, **kw):
    s = SiteSet(name=name, group="所有-自动", action="proxy")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def front(rtype, domain, target):
    return {"rtype": rtype, "domain": domain, "target": target,
            "enabled": True, "note": ""}


def kinds(c):
    prov = []
    build_route_rules(c, provenance=prov)
    return [p["kind"] for p in prov]


def run(c, q, monkeypatch, **kw):
    monkeypatch.setattr(orc, "_resolve_domain", lambda *a: [])
    return orc.predict(c, q, **kw)


def test_cf_rule_before_front_and_siteset():
    c = cfg(front=[front("domain_suffix", "front.example.com", "所有-自动")],
            sites=[site("g", domain_suffix=["site.example.com"])],
            blocked=["ads.example.com"])
    ks = kinds(c)
    assert "content" in ks
    assert ks.index("content") < ks.index("front")
    assert ks.index("content") < ks.index("siteset")
    # ... and after the infrastructure bypass rule.
    assert ks.index("content") > ks.index("bypass")


def test_cf_rule_shape_unchanged():
    prov = []
    rules, _, _ = build_route_rules(
        cfg(blocked=["a.example.com", "b.example.org"]), provenance=prov)
    cf = [r for r, p in zip(rules, prov) if p["kind"] == "content"]
    assert len(cf) == 1
    assert cf[0] == {"domain_suffix": ["a.example.com", "b.example.org"],
                     "outbound": "block"}


def test_cf_beats_overlapping_siteset(monkeypatch):
    c = cfg(sites=[site("g", domain_suffix=["example.com"])],
            blocked=["example.com"])
    r = run(c, "www.example.com", monkeypatch)
    assert r["matched"]["source"] == "content"
    assert r["matched"]["target"] == "block"
    # A non-blocked domain in the same set still goes to the set.
    r = run(c, "other.example.net", monkeypatch)
    assert r["matched"]["source"] == "fallback"


def test_cf_beats_overlapping_front_rule(monkeypatch):
    c = cfg(front=[front("domain_suffix", "example.com", "所有-自动")],
            blocked=["example.com"])
    r = run(c, "www.example.com", monkeypatch)
    assert r["matched"]["source"] == "content"
    assert r["matched"]["target"] == "block"


def test_no_blocked_list_no_content_rule():
    ks = kinds(cfg(sites=[site("g", domain_suffix=["example.com"])]))
    assert "content" not in ks


def test_deploy_upstream_table_loads_blocked_domains(monkeypatch):
    """Same fidelity gap on the deploy side: _upstream_routes must number
    rules on the table deploy emits, or its ruleIndex drifts from the
    deployed file once cf sits before the split rules."""
    from core import deploy as deploy_mod
    from panel import db as dbmod

    seen = {}
    fake = _cfg_proxy()

    def fake_load(conn, with_blocked_domains=False):
        seen["with_blocked_domains"] = with_blocked_domains
        return fake

    monkeypatch.setattr(dbmod, "load_app_config", fake_load)
    calls = []

    def predict(server, port, network):
        calls.append((server, port, network))
        return {"matched": {"action": "", "owner": {"kind": "siteset",
                                                   "name": "国外"},
                            "rule_index": 41},
                "final_outbound": "node-a",
                "chain": ["flip-11", "所有-自动", "node-a"],
                "assumptions": []}

    rows = deploy_mod._upstream_routes(
        None, {"upstream_predict": predict})
    assert seen["with_blocked_domains"] is True
    assert rows[0]["ruleIndex"] == 41


def _cfg_proxy():
    from core.models import DnsConfig
    c = AppConfig()
    c.dns = DnsConfig(proxy_dns="tcp://1.1.1.1")
    return c


def test_penetration_endpoint_loads_blocked_domains(monkeypatch):
    """The penetration endpoint must build the same table deploy emits:
    with blocked domains, or blocked domains keep predicting 'proxy'."""
    from panel import app as appmod
    from panel import db as dbmod

    seen = {}
    fake = cfg(sites=[site("g", domain_suffix=["example.com"])],
               blocked=["example.com"])

    def fake_load(conn, with_blocked_domains=False):
        seen["with_blocked_domains"] = with_blocked_domains
        return fake

    monkeypatch.setattr(dbmod, "load_app_config", fake_load)
    client = appmod.create_app(":memory:").test_client()
    res = client.post("/api/openbox/penetration",
                      json={"target": "www.example.com"})
    assert res.status_code == 200
    assert seen["with_blocked_domains"] is True
    body = res.get_json()
    assert body["matched"]["source"] == "content"
    assert body["matched"]["target"] == "block"
