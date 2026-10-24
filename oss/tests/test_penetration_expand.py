"""Regression: penetration skipped every rule-set reference, so domains
covered only by geosite/geoip answered fallback while the kernel routed
them elsewhere (2026-10-24: youtube.com answered fallback/direct, the
kernel routes geosite-youtube -> JPAC转甲骨文新加坡).

Fix: front geosite/geoip and site-set rule_sets are expanded via
sing-box rule-set decompile (geodata helpers) before matching. Exact
and suffix entries stay apart: an exact entry must not match subdomains.
Expanders are injectable so these tests need no binary or .srs files.
"""
import sys
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core import penetration as pen  # noqa: E402


def fake_geosite(name):
    data = {
        "geosite-youtube": ([], ["youtube.com", "ytimg.com"]),
        "geosite-demo": (["exact.example.com"], ["suffix.example.com"]),
    }
    return data.get(name, ([], []))


def fake_geoip(name):
    data = {
        "geoip-google": ["8.8.8.0/24", "8.8.4.0/24"],
    }
    return data.get(name, [])


def cfg(front=(), sites=(), final="direct"):
    return SimpleNamespace(front_rules=list(front), site_sets=list(sites),
                          final_outbound=final)


def front(rtype, domain, target, enabled=True):
    return {"rtype": rtype, "domain": domain, "target": target,
            "enabled": enabled, "note": ""}


def site(name, group, domains=(), suffix=(), keyword=(), cidrs=(),
         rule_sets=(), action="proxy"):
    return SimpleNamespace(enabled=True, action=action, name=name,
                          group=group, domains=list(domains),
                          domain_suffix=list(suffix),
                          domain_keyword=list(keyword),
                          ip_cidr=list(cidrs), rule_sets=list(rule_sets))


def run(c, q):
    return pen.penetrate(c, q, geosite_split=fake_geosite,
                         geoip_expand=fake_geoip)


def test_front_geosite_suffix_match():
    c = cfg(front=[front("geosite", "youtube", "JPAC")])
    r = run(c, "www.youtube.com")
    assert r["matched"]["source"] == "front"
    assert r["matched"]["target"] == "JPAC"
    assert r["matched"]["rule_type"] == "geosite"


def test_front_geosite_exact_match():
    c = cfg(front=[front("geosite", "demo", "G")])
    r = run(c, "exact.example.com")
    assert r["matched"]["source"] == "front"


def test_front_geosite_exact_does_not_match_subdomain():
    # Exact entries must not behave as suffixes.
    c = cfg(front=[front("geosite", "demo", "G")])
    r = run(c, "sub.exact.example.com")
    assert r["matched"]["source"] == "fallback"


def test_front_geosite_suffix_matches_bare_and_sub():
    c = cfg(front=[front("geosite", "demo", "G")])
    assert run(c, "suffix.example.com")["matched"]["source"] == "front"
    assert run(c, "deep.suffix.example.com")["matched"]["source"] == "front"


def test_front_geoip_match_for_ip():
    c = cfg(front=[front("geoip", "google", "G")])
    r = run(c, "8.8.8.8")
    assert r["matched"]["source"] == "front"
    assert r["matched"]["target"] == "G"


def test_geosite_never_matches_ip():
    c = cfg(front=[front("geosite", "youtube", "JPAC")])
    r = run(c, "1.2.3.4")
    assert r["matched"]["source"] == "fallback"


def test_siteset_ruleset_match():
    c = cfg(sites=[site("Youtube", "ALL", rule_sets=["geosite-youtube"])])
    r = run(c, "i.ytimg.com")
    assert r["matched"]["source"] == "siteset"
    assert "Youtube" in r["matched"]["source_name"]
    assert r["matched"]["target"] == "ALL"
    assert "geosite-youtube" in r["matched"]["rule_value"]


def test_siteset_geoip_ruleset_match_for_ip():
    c = cfg(sites=[site("G", "ALL", rule_sets=["geoip-google"])])
    r = run(c, "8.8.4.4")
    assert r["matched"]["source"] == "siteset"


def test_unexpandable_set_falls_through():
    c = cfg(front=[front("geosite", "missing", "JPAC")],
            sites=[site("S", "ALL", suffix=["example.com"])])
    r = run(c, "www.example.com")
    assert r["matched"]["source"] == "siteset"


def test_literal_rules_still_work_without_expansion():
    c = cfg(front=[front("domain", "muse.ai", "F")],
            sites=[site("Speed", "ALL", suffix=["yalala.com"])])
    assert run(c, "muse.ai")["matched"]["source"] == "front"
    assert run(c, "yalala.com")["matched"]["source"] == "siteset"
    assert run(c, "example.com")["matched"]["source"] == "fallback"


def test_front_order_preserved_with_expansion():
    # An earlier front rule wins even when a later one would also match.
    c = cfg(front=[front("geosite", "youtube", "FIRST"),
                   front("domain", "www.youtube.com", "SECOND")])
    r = run(c, "www.youtube.com")
    assert r["matched"]["target"] == "FIRST"
