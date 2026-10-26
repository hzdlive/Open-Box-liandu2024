"""Wire the entry bypass set (was Phase C TODO).

The nft generator's blacklist branch (obx_entry4) and the entry-plan
endpoint both consumed entry_cidrs, but nothing ever assigned them:
the generator never emitted the entry set and the plan always reported
need_cidrs=[]. These tests cover the shared collection (site sets +
front rules, both action sides), the generator end of the wire, and
both endpoints with a stubbed app config.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.models import AppConfig, SiteSet  # noqa: E402
from core.transparent import (  # noqa: E402
    TransparentConfig, entry_cidr_sets, nft_script)
from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _fake_geoip(name):
    return {"geoip-cn": ["203.0.113.0/24"],
            "geoip-us": ["198.51.100.0/24"]}.get(name, [])


def _site(name, action, ip_cidr=(), rule_sets=()):
    return SiteSet(name=name, action=action, ip_cidr=list(ip_cidr),
                   rule_sets=list(rule_sets))


def test_helper_splits_both_sides():
    sets = entry_cidr_sets(
        [_site("d", "direct", ["10.0.0.0/8"], ["geoip-cn"]),
         _site("p", "proxy", ["9.0.0.0/8"]),
         _site("r", "reject", ["8.0.0.0/8"], ["geoip-us"]),
         _site("?", "other", ["7.0.0.0/8"])],
        [{"rtype": "ip_cidr", "target": "direct", "domain": "6.0.0.0/8"},
         {"rtype": "ip_cidr", "target": "所有-自动", "domain": "5.0.0.0/8"},
         {"rtype": "ip_cidr", "target": "block", "domain": "4.0.0.0/8"},
         {"rtype": "geoip", "target": "direct", "domain": "cn"},
         {"rtype": "geoip", "target": "所有-手动", "domain": "us"},
         {"rtype": "ip_cidr", "target": "", "domain": "3.0.0.0/8"},
         {"rtype": "domain", "target": "direct", "domain": "example.com"},
         "not-a-dict"],
        _fake_geoip)
    assert sets["direct"] == ["10.0.0.0/8", "203.0.113.0/24", "6.0.0.0/8"]
    assert sets["proxy"] == ["198.51.100.0/24", "4.0.0.0/8", "5.0.0.0/8",
                             "8.0.0.0/8", "9.0.0.0/8"]


def test_helper_dedup_and_sort():
    sets = entry_cidr_sets(
        [_site("d", "direct", ["10.0.0.0/8", "10.0.0.0/8"])],
        [{"rtype": "ip_cidr", "target": "direct", "domain": "10.0.0.0/8"},
         {"rtype": "ip_cidr", "target": "direct", "domain": "9.0.0.0/8"}],
        _fake_geoip)
    assert sets["direct"] == ["10.0.0.0/8", "9.0.0.0/8"]
    assert sets["proxy"] == []


def test_generator_emits_wired_entry_set():
    sets = entry_cidr_sets(
        [_site("p", "proxy", ["9.9.9.9/32"])], [], _fake_geoip)
    cfg = TransparentConfig(entry_mode="blacklist",
                            entry_cidrs=sets["proxy"],
                            bypass_v4=[], enable_ipv6=False)
    s = nft_script(cfg)
    assert "set obx_entry4" in s
    assert "9.9.9.9/32" in s.split("set obx_entry4")[1].split("}")[0]
    assert "ip daddr != @obx_entry4 accept" in s


def _client(monkeypatch, cfg, overrides):
    """Test client with a stubbed app config and settings overrides."""
    monkeypatch.setattr(dbmod, "load_app_config", lambda c: cfg)
    orig = dbmod.get_setting

    def _fake_get(c, key, default=""):
        return overrides.get(key, orig(c, key, default))

    monkeypatch.setattr(dbmod, "get_setting", _fake_get)
    return create_app(":memory:").test_client()


def _cfg():
    c = AppConfig()
    c.site_sets = [_site("p", "proxy", ["9.9.9.9/32"]),
                   _site("d", "direct", ["8.8.8.8/32"])]
    c.front_rules = [
        {"rtype": "ip_cidr", "target": "所有-自动", "domain": "7.0.0.0/8"},
        {"rtype": "ip_cidr", "target": "direct", "domain": "6.0.0.0/8"},
    ]
    return c


def test_endpoint_blacklist_reports_proxy_cidrs(monkeypatch):
    c = _client(monkeypatch, _cfg(), {
        "direct_bypass_kernel": "1", "dns_fakeip": "1",
        "final_outbound": "direct"})
    body = c.get("/api/openbox/entry-plan").get_json()
    assert body["mode"] == "blacklist"
    assert body["need_cidrs"] == ["7.0.0.0/8", "9.9.9.9/32"]


def test_endpoint_whitelist_reports_direct_cidrs(monkeypatch):
    c = _client(monkeypatch, _cfg(), {
        "direct_bypass_kernel": "1", "dns_fakeip": "0",
        "final_outbound": "所有-自动"})
    body = c.get("/api/openbox/entry-plan").get_json()
    assert body["mode"] == "whitelist"
    assert body["need_cidrs"] == ["6.0.0.0/8", "8.8.8.8/32"]


def test_endpoint_disabled_reports_none(monkeypatch):
    c = _client(monkeypatch, _cfg(), {
        "direct_bypass_kernel": "0", "dns_fakeip": "1",
        "final_outbound": "direct"})
    body = c.get("/api/openbox/entry-plan").get_json()
    assert body["enabled"] is False
    assert body["need_cidrs"] == []


def test_nft_endpoint_contains_wired_entry_set(monkeypatch):
    c = _client(monkeypatch, _cfg(), {
        "direct_bypass_kernel": "1", "dns_fakeip": "1",
        "final_outbound": "direct"})
    script = c.get("/api/transparent/nft").get_json()["script"]
    assert "set obx_entry4" in script
    block = script.split("set obx_entry4")[1].split("}")[0]
    assert "9.9.9.9/32" in block
    assert "7.0.0.0/8" in block
    assert "ip daddr != @obx_entry4 accept" in script
