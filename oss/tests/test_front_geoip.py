"""front geoip->direct expansion tests."""
import sys

sys.path.insert(0, "oss")

from core.transparent import front_geoip_direct_cidrs

FAKE = {"geoip-google": ["8.8.8.0/24", "8.8.4.0/24"],
         "geoip-cn": ["1.0.1.0/24"]}


def _expand(name):
    return list(FAKE.get(name, []))


def test_front_geoip_direct():
    rules = [
        {"rtype": "geoip", "domain": "google", "target": "direct"},
        {"rtype": "geoip", "domain": "cn", "target": "直连"},
        {"rtype": "geoip", "domain": "facebook", "target": "故障转移测试"},
        {"rtype": "geosite", "domain": "x", "target": "direct"},
        {"rtype": "ip_cidr", "domain": "1.2.3.0/24", "target": "direct"},
        {"rtype": "geoip", "domain": "", "target": "direct"},
        {"rtype": "geoip", "domain": "missing", "target": "direct"},
        "not-a-dict",
        {"rtype": "geoip", "domain": "google", "target": "Direct"},
    ]
    got = front_geoip_direct_cidrs(rules, _expand)
    # google twice (direct + Direct) + cn once; group/geosite/ip_cidr/
    # empty/missing/non-dict all skipped.
    assert got == ["8.8.8.0/24", "8.8.4.0/24", "1.0.1.0/24",
                   "8.8.8.0/24", "8.8.4.0/24"], got
    assert front_geoip_direct_cidrs([], _expand) == []
    assert front_geoip_direct_cidrs(None, _expand) == []


if __name__ == "__main__":
    test_front_geoip_direct()
    print("OK: front geoip->direct — all cases pass")
