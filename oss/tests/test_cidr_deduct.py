"""Self-test for CIDR deduction (core/cidr_deduct.py + nft_script wiring)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import cidr_deduct as cd  # noqa: E402
from core.transparent import TransparentConfig, nft_script  # noqa: E402


def main() -> int:
    # 1. last-address deduction: 0.0.0.0/0 loses .255 (split, never
    # contains it afterwards); collapse may absorb smaller nets into the
    # remainder, so assert address-set semantics, not literal membership.
    import ipaddress as _ip
    r = cd.deduct(["192.168.1.0/24", "0.0.0.0/0"])
    nets = [_ip.ip_network(x) for x in r["v4"]]
    covered = lambda a: any(_ip.ip_address(a) in n for n in nets)
    assert covered("192.168.1.5") and not covered("255.255.255.255"), r
    assert not covered("198.19.1.1"), r  # FakeIP pool deducted too
    assert r["removed"]["last_address"] == 1, r

    # 2. FakeIP pool: 198.19.0.0/15 minus 198.19.0.0/16 -> 198.18.0.0/16.
    r = cd.deduct(["198.19.0.0/15"])
    assert r["v4"] == ["198.18.0.0/16"], r
    assert r["removed"]["fakeip"] == 1, r

    # 3. earlier sets: fully covered -> dropped; partial overlap -> split.
    r = cd.deduct(["10.0.0.0/8", "172.16.0.0/12", "8.8.8.8/32"],
                  earlier=["10.0.0.0/8"])
    assert r["v4"] == ["8.8.8.8/32", "172.16.0.0/12"], r
    assert r["removed"]["earlier"] == 1, r

    # 4. collapse + sort + invalid counting.
    r = cd.deduct(["10.0.0.128/25", "10.0.0.0/25", "bogus", "10.0.0.0/24"])
    assert r["v4"] == ["10.0.0.0/24"], r
    assert r["removed"]["invalid"] == 1, r

    # 5. v6 split: v6 never lands in the v4 list; last v6 address deducted.
    r = cd.deduct(["2001:db8::/32", "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff/128"])
    assert r["v4"] == [] and r["v6"] == ["2001:db8::/32"], r
    assert r["removed"]["last_address"] == 1, r

    # 6. empty after deductions -> empty flag (fallback, not an empty set).
    r = cd.deduct(["198.19.0.0/16"])
    assert r["empty"] and r["v4"] == [], r

    # 7. nft_script wiring: deductions apply, v6 never enters the v4 set,
    # notes appear in the script header.
    cfg = TransparentConfig(
        entry_mode="whitelist",
        direct_ip_cidrs=["10.0.0.0/8", "198.19.1.0/24", "2001:db8::/32",
                         "8.8.8.8/32"],
        bypass_v4=["10.0.0.0/8", "127.0.0.0/8"],
        bypass_v6=["::1/128"],
        enable_ipv6=True)
    s = nft_script(cfg)
    assert "10.0.0.0/8" not in s.split("set obx_direct_ip4")[1].split("}")[0], s
    assert "198.19.1.0/24" not in s, s  # FakeIP pool deducted
    assert "8.8.8.8/32" in s, s
    assert "2001:db8::" not in s.split("set obx_direct_ip4")[1].split("}")[0], s
    assert "# direct_ip4：" in s, s

    # 8. entry set uses the same deduction, with direct_ip as earlier.
    cfg = TransparentConfig(
        entry_mode="blacklist",
        entry_cidrs=["10.0.0.0/8", "9.9.9.9/32"],
        direct_ip_cidrs=["8.8.8.8/32"],
        bypass_v4=["10.0.0.0/8"],
        enable_ipv6=False)
    s = nft_script(cfg)
    entry_block = s.split("set obx_entry4")[1].split("}")[0]
    assert "9.9.9.9/32" in entry_block, s
    assert "10.0.0.0/8" not in entry_block, s
    assert "# entry4：" in s, s

    # 9. entry fully deducted -> no set (fallback), note says so.
    cfg = TransparentConfig(
        entry_mode="blacklist",
        entry_cidrs=["10.0.0.0/8"],
        bypass_v4=["10.0.0.0/8"],
        enable_ipv6=False)
    s = nft_script(cfg)
    assert "obx_entry4" not in s, s
    assert "回落" in s, s

    print("OK: cidr_deduct — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
