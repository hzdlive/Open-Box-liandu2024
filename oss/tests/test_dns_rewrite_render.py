"""Regression: DNS rewrites were rendered as dnsmasq `address=` lines
regardless of target type. `address=` only accepts IPs, so the two
built-in domain->domain rows (developers.google.cn ->
developers.google.com, services.googleapis.cn -> services.googleapis.com)
made dnsmasq reject the whole config (Bad address), and the generated
snippet could never be installed verbatim.

Fix: IP targets render as `address=/domain/ip`, domain targets as
`cname=domain,target` (dnsmasq's alias mechanism); invalid targets are
rejected at add/update time and commented out (never emitted) by the
snippet renderer.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import transparent as tp  # noqa: E402
from panel import db as dbmod  # noqa: E402


def test_ip_target_renders_address():
    assert tp.rewrite_dnsmasq_line("x.example.com", "1.2.3.4") == \
        "address=/x.example.com/1.2.3.4"
    assert tp.rewrite_dnsmasq_line("x.example.com", "2001:db8::1") == \
        "address=/x.example.com/2001:db8::1"


def test_domain_target_renders_cname():
    assert tp.rewrite_dnsmasq_line(
        "developers.google.cn", "developers.google.com") == \
        "cname=developers.google.cn,developers.google.com"


def test_domain_target_trailing_dot_stripped():
    assert tp.rewrite_dnsmasq_line("a.example.com", "b.example.com.") == \
        "cname=a.example.com,b.example.com"


def test_invalid_target_renders_none():
    assert tp.rewrite_dnsmasq_line("a.example.com", "") is None
    assert tp.rewrite_dnsmasq_line("a.example.com", "not a target!") is None
    assert tp.rewrite_dnsmasq_line("a.example.com", "1.2.3.999") is None
    assert tp.rewrite_dnsmasq_line("a.example.com", "singlelabel") is None


def test_snippet_mixed_rewrites():
    cfg = tp.TransparentConfig(dns_rewrites=[
        ("developers.google.cn", "developers.google.com"),
        ("x.example.com", "1.2.3.4"),
        ("bad.example.com", "!!!"),
    ])
    out = tp.dnsmasq_snippet(cfg)
    assert "cname=developers.google.cn,developers.google.com" in out
    assert "address=/x.example.com/1.2.3.4" in out
    assert "address=/developers.google.cn/developers.google.com" not in out
    assert "address=/bad.example.com" not in out
    assert "skipped invalid rewrite: bad.example.com" in out


def _db():
    c = sqlite3.connect(":memory:")
    dbmod.init_db(c)
    return c


def test_db_rejects_invalid_target():
    c = _db()
    try:
        dbmod.add_dns_rewrite(c, "new.example.com", "!!!")
    except ValueError as e:
        assert "IP address or a domain" in str(e)
    else:
        raise AssertionError("expected ValueError for garbage target")
    r = dbmod.add_dns_rewrite(c, "new.example.com", "1.2.3.4")
    assert r["target"] == "1.2.3.4"
    r2 = dbmod.add_dns_rewrite(c, "alias.example.com", "target.example.com")
    assert r2["target"] == "target.example.com"
    try:
        dbmod.update_dns_rewrite(c, r["id"], "new.example.com", "no spaces here")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on update with bad target")
