"""geoip rule-set expansion tests.

expand_geoip decodes via `sing-box rule-set decompile` (authoritative),
never by reimplementing the .srs binary format. A fake binary script
stands in for sing-box here; the live binary is verified on the VPS.
"""
import json
import os
import stat
import sys
import tempfile

sys.path.insert(0, "oss")

from core import geodata
from core.models import SiteSet
from core.transparent import classify_direct_ip_gaps

FAKE_JSON = {"version": 1, "rules": [{"ip_cidr": [
    "1.0.1.0/24", "1.0.2.0/23", "1.0.1.0/24",  # dup collapses
    "not-a-cidr",  # dropped
    "2001:db8::/32",
]}]}


def _setup_fake_binary():
    td = tempfile.mkdtemp()
    gd = os.path.join(td, "geodata")
    os.makedirs(gd)
    open(os.path.join(gd, "geoip-cn.srs"), "wb").write(b"SRS\x01fake")
    count = os.path.join(td, "calls.txt")
    script = os.path.join(td, "fake-sing-box")
    with open(script, "w") as f:
        f.write("#!/usr/bin/env python3\n"
                "import json, sys\n"
                f"open({count!r}, 'a').write('x')\n"
                "out = sys.argv[sys.argv.index('-o') + 1]\n"
                f"json.dump({FAKE_JSON!r}, open(out, 'w'))\n")
    os.chmod(script, stat.S_IRWXU)
    os.environ["OBX_GEODATA"] = gd
    return td, script, count


def test_expand_geoip():
    td, script, count = _setup_fake_binary()
    try:
        got = geodata.expand_geoip("geoip-cn", binary=script)
        assert got == ["1.0.1.0/24", "1.0.2.0/23", "2001:db8::/32"], got
        # Cached: second call must not re-invoke the binary.
        assert geodata.expand_geoip("geoip-cn", binary=script) == got
        assert open(count).read() == "x"
        # geosite holds domains, never CIDRs; bad names rejected outright.
        assert geodata.expand_geoip("geosite-apple", binary=script) == []
        assert geodata.expand_geoip("../geoip-cn", binary=script) == []
        assert geodata.expand_geoip("geoip-missing", binary=script) == []
    finally:
        del os.environ["OBX_GEODATA"]
        geodata._expand_cache.clear()


def test_expand_failure_closed():
    td, script, count = _setup_fake_binary()
    try:
        open(os.path.join(os.environ["OBX_GEODATA"], "geoip-xx.srs"), "wb").write(b"x")
        assert geodata.expand_geoip("geoip-xx", binary="/bin/false") == []
    finally:
        del os.environ["OBX_GEODATA"]
        geodata._expand_cache.clear()


def test_classify_gaps():
    apple = SiteSet(name="Apple", action="direct", rule_sets=["geosite-apple"])
    china = SiteSet(name="国内", action="direct",
                    rule_sets=["geosite-cn", "geoip-cn", "geoip-private"])
    dom = SiteSet(name="D", action="direct", domains=["example.com"])
    lit = SiteSet(name="L", action="direct", ip_cidr=["1.2.3.0/24"])
    proxy = SiteSet(name="P", action="proxy", rule_sets=["geoip-cn"])
    causes = classify_direct_ip_gaps([apple, china, dom, lit, proxy],
                                     expanded_names={"国内"})
    assert causes == {"域名条件": 1, "port 等非 IP 条件": 0,
                      "规则集未展开": 1, "没有 ip_cidr": 0}, causes
    # Without expansion, 国内 would count as unexpanded too.
    causes2 = classify_direct_ip_gaps([apple, china])
    assert causes2["规则集未展开"] == 2, causes2


if __name__ == "__main__":
    test_expand_geoip()
    test_expand_failure_closed()
    test_classify_gaps()
    print("OK: geoip expansion — all cases pass")
