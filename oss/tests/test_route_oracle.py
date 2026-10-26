"""Tests for the routing oracle (core/route_oracle.py, v8 #33).

The oracle evaluates the rules build_route_rules actually emits, so
these tests build a real AppConfig and stub only the outside world:
rule-set expansion, DNS resolution and the Clash proxy table.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core import route_oracle as orc  # noqa: E402
from core.models import AppConfig, DnsRewrite, SiteSet  # noqa: E402
from core.singbox import flip_tag  # noqa: E402
from panel.app import create_app  # noqa: E402


def fake_geosite(name):
    data = {
        "geosite-youtube": ([], ["youtube.com", "ytimg.com"]),
        "geosite-demo": (["exact.example.com"], ["suffix.example.com"]),
    }
    return data.get(name, ([], []))


def fake_geoip(name):
    return {"geoip-google": ["8.8.8.0/24", "8.8.4.0/24"]}.get(name, [])


def cfg(front=(), sites=(), **kw):
    c = AppConfig()
    c.front_rules = list(front)
    c.site_sets = list(sites)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def front(rtype, domain, target, note=""):
    return {"rtype": rtype, "domain": domain, "target": target,
            "enabled": True, "note": note}


def site(name, group="所有-自动", action="proxy", **kw):
    s = SiteSet(name=name, group=group, action=action)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def run(c, q, monkeypatch, resolved=None, proxies=None, **kw):
    monkeypatch.setattr(orc, "_resolve_domain",
                        lambda *a: list(resolved or []))
    # The stubbed sets count as present, so the builder does not drop
    # their references the way it drops genuinely missing .srs files.
    from core import geodata as gdmod
    orig_avail = gdmod.is_available
    monkeypatch.setattr(
        gdmod, "is_available",
        lambda n, db_path=None: n in ("geosite-youtube", "geosite-demo",
                                      "geoip-google")
        or orig_avail(n, db_path))
    return orc.predict(c, q, proxies=proxies,
                       geosite_split=fake_geosite, geoip_expand=fake_geoip,
                       **kw)


# ---------------------------------------------------------------- parsing

def test_parse_target_shapes():
    t = orc.parse_target("google.com")
    assert (t.kind, t.value, t.port) == ("domain", "google.com", None)
    t = orc.parse_target("example.com.")
    assert t.value == "example.com"
    t = orc.parse_target("1.2.3.4")
    assert (t.kind, t.version) == ("ip", 4)
    t = orc.parse_target("[2001:db8::1]:443")
    assert (t.kind, t.value, t.port, t.version) == (
        "ip", "2001:db8::1", 443, 6)
    t = orc.parse_target("example.com:8443")
    assert (t.kind, t.port) == ("domain", 8443)


def test_parse_target_invalid():
    for bad in ("", "  ", "http://example.com", "exa mple.com",
                "example.com:0", "example.com:99999", "example.com:abc",
                "[::1", "[::1]:0", "a" * 64 + ".com"):
        with pytest.raises(orc.TargetError):
            orc.parse_target(bad)


def test_classify():
    assert orc.parse_target("198.19.1.5").classify()["is_fakeip"] is True
    assert orc.parse_target("192.168.1.1").classify()["is_private"] is True
    assert orc.parse_target("::1").classify()["is_loopback"] is True
    assert orc.parse_target("8.8.8.8").classify()["is_fakeip"] is False


# ---------------------------------------------------------------- ordering

def test_front_beats_siteset(monkeypatch):
    c = cfg(front=[front("domain_suffix", "google.com", "direct")],
            sites=[site("g", domain_suffix=["google.com"])])
    r = run(c, "www.google.com", monkeypatch)
    assert r["matched"]["source"] == "front"
    assert r["matched"]["target"] == "direct"
    assert r["matched"]["rule_index"] == 1  # 0 is the logical bypass rule
    assert r["verdict"] == "hit"


def test_siteset_geosite_expanded(monkeypatch):
    s = site("yt", rule_sets=["geosite-youtube"])
    c = cfg(sites=[s])
    r = run(c, "www.youtube.com", monkeypatch)
    assert r["matched"]["source"] == "siteset"
    assert "geosite-youtube" in r["matched"]["rule_value"]
    assert r["matched"]["target"] == flip_tag(s)
    assert r["chain"] == [flip_tag(s), "所有-自动"]
    assert r["final_outbound"] == "所有-自动"


def test_obnode_direct_beats_siteset(monkeypatch):
    c = cfg(sites=[site("g", domain_suffix=["example.com"])],
            sub_node_direct=True, sub_domains=["sub.example.com"])
    r = run(c, "sub.example.com", monkeypatch)
    assert r["matched"]["source"] == "obnode"
    assert r["matched"]["target"] == "direct"


def test_quic_block_udp_443(monkeypatch):
    s = site("g", domain_suffix=["example.com"])
    c = cfg(sites=[s])
    r = run(c, "www.example.com", monkeypatch, network="udp", port=443)
    assert r["matched"]["source"] == "quic"
    assert r["matched"]["target"] == "block"
    r = run(c, "www.example.com", monkeypatch)
    assert r["matched"]["source"] == "siteset"


def test_content_block_after_siteset(monkeypatch):
    c = cfg(sites=[site("g", domain_suffix=["example.com"])],
            blocked_domains=["ads.example.com", "blocked2.example.org"])
    r = run(c, "www.example.com", monkeypatch)
    assert r["matched"]["source"] == "siteset"
    r = run(c, "blocked2.example.org", monkeypatch)
    assert r["matched"]["source"] == "content"
    assert r["matched"]["target"] == "block"


def test_fallback_is_other(monkeypatch):
    c = cfg()
    r = run(c, "nomatch.example.com", monkeypatch)
    assert r["matched"]["source"] == "fallback"
    assert r["matched"]["target"] == "其他"
    assert r["verdict"] == "miss"


def test_port_rule_needs_port(monkeypatch):
    c = cfg(front=[front("port", "443", "direct")])
    r = run(c, "example.com", monkeypatch, port=443)
    assert r["matched"]["source"] == "front"
    r = run(c, "example.com", monkeypatch)
    assert r["matched"]["source"] == "fallback"
    assert r["skipped_port_rules"]


# ---------------------------------------------------------------- chains

def test_chain_walk_live():
    proxies = {
        "所有-自动": {"type": "urltest", "now": "node-a"},
        "node-a": {"type": "ss"},
        "flip-x": {"type": "selector", "now": "所有-自动"},
    }
    ch = orc.walk_chain("flip-x", proxies, AppConfig())
    assert ch["chain"] == ["flip-x", "所有-自动", "node-a"]
    assert ch["final"] == "node-a"
    assert ch["chain"] == orc.walk_chain("flip-x", proxies,
                                         AppConfig())["chain"]


def test_chain_walk_db_fallback_flip(monkeypatch):
    s = site("g", group="所有-手动", action="proxy")
    c = cfg(sites=[s])
    r = run(c, "nomatch.example.com", monkeypatch)
    # fallback chain is not this site; check the flip default directly
    ch = orc.walk_chain(flip_tag(s), None, c)
    assert ch["chain"] == [flip_tag(s), "所有-手动"]


# ---------------------------------------------------------------- unknowns

def test_remote_set_is_assumption_not_block(monkeypatch):
    s1 = site("remote", ruleset_urls=["https://example.com/x.srs"])
    s2 = site("g", domain_suffix=["example.com"])
    c = cfg(sites=[s1, s2])
    r = run(c, "www.example.com", monkeypatch)
    assert r["matched"]["source"] == "siteset"
    assert r["matched"]["source_name"] == "站点集：g"
    assert any("url-0" in a["reason"] for a in r["assumptions"])


def test_unresolved_domain_assumption(monkeypatch):
    c = cfg(sites=[site("g", domain_suffix=["example.com"])])
    r = run(c, "www.example.com", monkeypatch, resolved=[])
    assert r["matched"]["source"] == "siteset"
    assert any("未解析" in a["reason"] for a in r["assumptions"])


def test_resolved_ip_matches_geoip(monkeypatch):
    c = cfg(sites=[site("g", rule_sets=["geoip-google"])])
    r = run(c, "dns.example.com", monkeypatch, resolved=["8.8.8.8"])
    assert r["matched"]["source"] == "siteset"
    assert "8.8.8.0/24" in r["matched"]["rule_value"]


# ---------------------------------------------------------------- DNS walk

def test_dns_walk_and_rewrite(monkeypatch):
    c = cfg(front=[front("geosite", "youtube", "所有-自动")],
            dns_rewrites=[DnsRewrite(domain="example.com",
                                     target="1.2.3.4")])
    r = run(c, "www.youtube.com", monkeypatch)
    assert r["dns"]["server"] == "dns-proxy"
    r = run(c, "example.com", monkeypatch)
    assert r["dns"]["rewrite"] == {"domain": "example.com",
                                   "target": "1.2.3.4", "kind": "address"}


# ---------------------------------------------------------------- endpoint

def test_endpoint_validation_and_shape(monkeypatch):
    monkeypatch.setattr(orc, "_resolve_domain", lambda *a: [])
    app = create_app(":memory:")
    c = app.test_client()
    r = c.post("/api/openbox/penetration", json={"target": "a b"})
    assert r.status_code == 400
    r = c.post("/api/openbox/penetration",
               json={"target": "nomatch.example.com"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["verdict"] == "miss"
    assert body["matched"]["target"] == "其他"
    r = c.post("/api/openbox/penetration", json={})
    assert r.status_code == 400
