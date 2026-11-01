"""v0.1.359: DNS wildcard rewrite keeps the subdomain prefix.

- "*.googleapis.cn -> *.googleapis.com" rewrites "maps.googleapis.cn"
  to "maps.googleapis.com" (prefix preserved, any depth).
- A non-wildcard target is used literally (prefix dropped).
- The wildcard pattern never matches the bare suffix itself, and
  disabled rules are skipped; first matching rule in stored order
  wins. The oracle result carries "rewritten" for the UI's
  "original -> rewritten" access-target display.
- dnsmasq cannot enforce wildcard rewrites: verified against
  dnsmasq 2.91 that "cname=*.example.cn,*.example.com" is syntax-OK
  but never expands, so the snippet renderer comments wildcard rows
  out (with the reason) instead of emitting a dead line. Wildcard
  targets are now accepted at add/update time (previously rejected
  by target validation, so such a rule could not even be saved).
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import transparent as tp  # noqa: E402
from core import route_oracle as orc  # noqa: E402


def test_wildcard_target_validation():
    assert tp.is_rewrite_target_valid("*.googleapis.com")
    assert tp.is_rewrite_target_valid("*.googleapis.com.")
    assert not tp.is_rewrite_target_valid("*")
    assert not tp.is_rewrite_target_valid("*.")
    assert not tp.is_rewrite_target_valid("*.com")
    assert not tp.is_rewrite_target_valid("*.*.com")
    # Exact/IP behaviour unchanged.
    assert tp.is_rewrite_target_valid("googleapis.com")
    assert tp.is_rewrite_target_valid("1.2.3.4")
    assert not tp.is_rewrite_target_valid("1.2.3.999")


def test_wildcard_renders_none_but_snippet_comments_reason():
    assert tp.rewrite_dnsmasq_line(
        "*.googleapis.cn", "*.googleapis.com") is None
    assert tp.rewrite_dnsmasq_line(
        "*.googleapis.cn", "googleapis.com") is None
    assert tp.rewrite_dnsmasq_line(
        "maps.googleapis.cn", "*.googleapis.com") is None
    cfg = tp.TransparentConfig(dns_rewrites=[
        ("*.googleapis.cn", "*.googleapis.com"),
        ("services.googleapis.cn", "services.googleapis.com"),
    ])
    out = tp.dnsmasq_snippet(cfg)
    assert "cname=*.googleapis.cn" not in out
    assert "skipped wildcard rewrite" in out
    assert "cname=services.googleapis.cn,services.googleapis.com" in out


def _cfg(rules):
    return types.SimpleNamespace(dns_rewrites=[
        {"domain": d, "target": t, "enabled": en}
        for d, t, en in rules])


def test_oracle_exact_unchanged():
    r = orc._rewrite_of(_cfg([
        ("services.googleapis.cn", "services.googleapis.com", True)]),
        "services.googleapis.cn")
    assert r == {"domain": "services.googleapis.cn",
                 "target": "services.googleapis.com",
                 "rewritten": "services.googleapis.com", "kind": "cname"}


def test_oracle_wildcard_prefix_preserved():
    cfg = _cfg([("*.googleapis.cn", "*.googleapis.com", True)])
    assert orc._rewrite_of(cfg, "maps.googleapis.cn")["rewritten"] == \
        "maps.googleapis.com"
    assert orc._rewrite_of(cfg, "a.b.googleapis.cn")["rewritten"] == \
        "a.b.googleapis.com"
    # Bare suffix itself is not matched by the wildcard.
    assert orc._rewrite_of(cfg, "googleapis.cn") is None
    # Case-insensitive, trailing dot tolerated.
    assert orc._rewrite_of(cfg, "Maps.Googleapis.CN.")["rewritten"] == \
        "maps.googleapis.com"


def test_oracle_wildcard_literal_target_drops_prefix():
    cfg = _cfg([("*.googleapis.cn", "googleapis.com", True)])
    assert orc._rewrite_of(cfg, "maps.googleapis.cn")["rewritten"] == \
        "googleapis.com"


def test_oracle_disabled_and_order():
    cfg = _cfg([
        ("*.googleapis.cn", "*.googleapis.com", False),
        ("maps.googleapis.cn", "maps.example.com", True),
    ])
    assert orc._rewrite_of(cfg, "maps.googleapis.cn")["rewritten"] == \
        "maps.example.com"
    # First matching rule in stored order wins.
    cfg = _cfg([
        ("*.googleapis.cn", "*.googleapis.com", True),
        ("maps.googleapis.cn", "maps.example.com", True),
    ])
    assert orc._rewrite_of(cfg, "maps.googleapis.cn")["rewritten"] == \
        "maps.googleapis.com"
