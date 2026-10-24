"""front domain/geosite->direct DNS bypass tests."""
import json
import os
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, "oss")

from core import geodata  # noqa: E402
from core.transparent import front_dns_direct_domains  # noqa: E402

FAKE = {"geosite-x": ["twitter.com", "x.com"],
        "geosite-apple": ["apple.com"]}


def _expand(name):
    return list(FAKE.get(name, []))


def test_front_dns_direct_domains():
    rules = [
        {"rtype": "domain", "domain": "flow.google.com", "target": "direct"},
        {"rtype": "domain_suffix", "domain": "example.com", "target": "直连"},
        {"rtype": "geosite", "domain": "x", "target": "direct"},
        # skipped: group target, keyword (not expressible as an ipset
        # line), geoip/ip_cidr/port (other bypasses), empty, missing
        # file, non-dict, case-insensitive target still counts.
        {"rtype": "domain", "domain": "aistudio.google.com",
         "target": "故障转移测试"},
        {"rtype": "domain_keyword", "domain": "google", "target": "direct"},
        {"rtype": "geoip", "domain": "google", "target": "direct"},
        {"rtype": "ip_cidr", "domain": "1.2.3.0/24", "target": "direct"},
        {"rtype": "port", "domain": "443", "target": "direct"},
        {"rtype": "domain", "domain": "", "target": "direct"},
        {"rtype": "geosite", "domain": "missing", "target": "direct"},
        {"rtype": "geosite", "domain": "apple", "target": "Direct"},
        "not-a-dict",
    ]
    got = front_dns_direct_domains(rules, _expand)
    assert got == ["flow.google.com", "example.com",
                   "twitter.com", "x.com", "apple.com"], got
    assert front_dns_direct_domains([], _expand) == []
    assert front_dns_direct_domains(None, _expand) == []


def _fake_binary(doc, fail=False):
    """A stand-in sing-box that writes `doc` as decompile output."""
    d = tempfile.mkdtemp()
    script = os.path.join(d, "sing-box")
    with open(script, "w") as f:
        f.write("#!/usr/bin/env python3\nimport json, sys\n")
        if fail:
            f.write("sys.exit(3)\n")
        else:
            f.write("doc = " + repr(doc) + "\n")
            f.write("out = sys.argv[sys.argv.index('-o') + 1]\n")
            f.write("json.dump(doc, open(out, 'w'))\n")
    os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
    return script


def test_expand_geosite_with_fake_binary():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "geodata"), exist_ok=True)
    path = os.path.join(d, "geodata", "geosite-x.srs")
    with open(path, "wb") as f:
        f.write(b"x")  # content irrelevant: the fake binary ignores it
    doc = {"rules": [
        {"domain": ["exact.example", "dup.example"],
         "domain_suffix": ["dup.example", "suf.example"],
         "domain_keyword": ["key"], "domain_regex": ["^re.*"],
         "ip_cidr": ["1.2.3.0/24"]},
        {"domain_suffix": ["second.example"]},
        "not-a-rule",
    ]}
    geodata._expand_cache.clear()
    got = geodata.expand_geosite(
        "geosite-x", db_path=os.path.join(d, "panel.db"),
        binary=_fake_binary(doc))
    # domain + suffix only, deduped, order-preserving; keyword/regex/
    # ip_cidr never leak into a DNS bypass list.
    assert got == ["exact.example", "dup.example", "suf.example",
                   "second.example"], got
    # cache hit: same result even if the binary now fails.
    got2 = geodata.expand_geosite(
        "geosite-x", db_path=os.path.join(d, "panel.db"),
        binary=_fake_binary(doc, fail=True))
    assert got2 == got, got2


def test_expand_geosite_fail_closed():
    geodata._expand_cache.clear()
    assert geodata.expand_geosite("geosite-x") == []  # no such file here
    assert geodata.expand_geosite("geoip-cn") == []  # wrong family
    assert geodata.expand_geosite("../evil") == []  # traversal guard
    assert geodata.expand_geosite("") == []


if __name__ == "__main__":
    test_front_dns_direct_domains()
    test_expand_geosite_with_fake_binary()
    test_expand_geosite_fail_closed()
    print("OK: front dns direct domains — all cases pass")
