"""Self-test for bad-node location (core/badnodes.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import badnodes as bn  # noqa: E402

NODES = {
    "node-a": {"protocol": "vless", "server": "1.2.3.4", "sub_id": 5},
    "node-b": {"protocol": "trojan", "server": "5.6.7.8", "sub_id": 9},
}
SUBS = {5: "良心云", 9: "一分机场"}
GROUPS = {"JPAC直连", "BWG"}
SITES = {3: "Speed"}
CFG = {"outbounds": [
    {"type": "direct", "tag": "direct"},
    {"type": "vless", "tag": "node-a"},
    {"type": "selector", "tag": "JPAC直连", "outbounds": ["node-a", "direct"]},
    {"type": "trojan", "tag": "node-b"},
    {"type": "selector", "tag": "其他", "outbounds": ["direct"]},
    {"type": "urltest", "tag": "sub-5", "outbounds": ["node-a"]},
]}


def main() -> int:
    # index parsing (first match; ANSI stripped)
    assert bn.find_outbound_index(
        "FATAL[0000] decode: outbounds[2].server_port: boom") == 2
    assert bn.find_outbound_index(
        "\x1b[31mFATAL\x1b[0m[0000] outbounds[1]: unknown type") == 1
    assert bn.find_outbound_index("no outbound here") is None
    assert bn.find_outbound_index("route.rules[0].outbound: bad") is None

    # node location with subscription
    r = bn.locate("outbounds[1].server_port: bad", CFG, NODES, SUBS, GROUPS, SITES)
    assert r and r["kind"] == "node" and r["tag"] == "node-a", r
    assert r["subscription"] == "良心云" and r["protocol"] == "vless", r
    assert r["summary"] == "节点 node-a（订阅 良心云，vless，1.2.3.4）导致配置校验失败", r["summary"]
    assert "outbounds[1]" in r["kernel_detail"]

    # group, final, subscription group, builtin, unknown
    r = bn.locate("outbounds[2]: bad", CFG, NODES, SUBS, GROUPS, SITES)
    assert r["kind"] == "group" and r["summary"] == "分组 JPAC直连导致配置校验失败", r
    r = bn.locate("outbounds[4]: bad", CFG, NODES, SUBS, GROUPS, SITES)
    assert r["kind"] == "final", r
    r = bn.locate("outbounds[5]: bad", CFG, NODES, SUBS, GROUPS, SITES)
    assert r["kind"] == "subscription_group" and r["subscription"] == "良心云", r
    r = bn.locate("outbounds[0]: bad", CFG, NODES, SUBS, GROUPS, SITES)
    assert r["kind"] == "builtin", r
    cfg2 = {"outbounds": [{"type": "direct", "tag": "direct"},
                          {"type": "vless", "tag": "mystery"}]}
    r = bn.locate("outbounds[1]: bad", cfg2, NODES, SUBS, GROUPS, SITES)
    assert r["kind"] == "unknown" and "mystery" in r["summary"], r

    # out-of-range index / no index -> None (never crash, never guess)
    assert bn.locate("outbounds[99]: bad", CFG, NODES, SUBS, GROUPS, SITES) is None
    assert bn.locate("some other error", CFG, NODES, SUBS, GROUPS, SITES) is None
    assert bn.locate("", CFG, NODES, SUBS, GROUPS, SITES) is None

    # ValidationError carries bad
    e = bn.ValidationError("config validation failed: x", bad={"tag": "node-a"})
    assert isinstance(e, RuntimeError) and e.bad["tag"] == "node-a"
    e2 = bn.ValidationError("config validation failed: x")
    assert e2.bad is None

    print("OK: badnodes — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
