"""configDetailed: synthetic-input unit tests for the derived rules.

No golden corpus here (it is a live snapshot and stays out of the
repo). These tests pin the rules derived from the 38 golden cases:
skeleton defaults, node conversion, chain filtering/order, policy
selectors, DNS server presence, group-default gating, list tags,
and the native-bypass tun rule.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "core-replica"))

from methods.config import config_detailed  # noqa: E402


def _vless(tag, server="example.com", **fields):
    node = {"tag": tag, "type": "vless", "server": server,
            "server_port": 443, "fields": fields}
    return node


def test_minimal_skeleton():
    out = config_detailed([{"profile": {"clashApiSecret": "s"}}])
    cfg = out["config"]
    assert [o["tag"] for o in cfg["outbounds"]] == ["直连", "拒绝", "其他"]
    assert cfg["outbounds"][2]["default"] == "直连"
    assert cfg["log"] == {"level": "warn"}
    tun = cfg["inbounds"][0]
    assert tun["tag"] == "tun-in" and tun["dns_mode"] == "disabled"
    assert tun["stack"] == "mixed"
    assert [i["tag"] for i in cfg["inbounds"]] == ["tun-in", "panel-in",
                                                   "dns-in"]
    assert cfg["experimental"]["cache_file"]["path"] == \
        "/opt/open-box/data/cache.db"
    assert cfg["experimental"]["cache_file"]["store_fakeip"] is False
    assert cfg["experimental"]["clash_api"]["secret"] == "s"
    assert [e["tag"] for e in cfg["route"]["rule_set"]] == \
        ["obnode-direct", "obnode-direct-ip", "obflip-fallback"]
    # No policies -> no catch-all QUIC rule.
    assert not any(r.get("action") == "reject" and r.get("mode") == "and"
                   for r in cfg["route"]["rules"]
                   if {"rule_set": ["obflip-fallback"]} in r.get("rules", []))
    assert [s["tag"] for s in cfg["dns"]["servers"]] == ["dns-direct",
                                                         "dns-local"]
    assert len(cfg["dns"]["rules"]) == 2
    assert out["directHosts"] == {"cidrs": [], "domains": []}
    assert out["dnsRuleOwners"] == [] and out["failover"] == []


def test_node_conversion_tls_reality_and_fallback():
    with_reality = _vless(
        "a", tls={"enabled": True, "insecure": True,
                  "reality": {"enabled": True}, "server_name": "x"})
    without = _vless("b", tls={"enabled": True, "server_name": "y"})
    state = {"profile": {"routing": {"policies": []}}, "nodes": [
        with_reality, without]}
    obs = config_detailed([state])["config"]["outbounds"]
    by_tag = {o["tag"]: o for o in obs}
    assert "insecure" not in by_tag["a"]["tls"]
    assert by_tag["b"]["tls"]["insecure"] is True


def test_node_conversion_ws_early_data_and_drops():
    node = _vless("w", transport={"type": "ws", "path": "/p?ed=7"},
                  empty={}, uuid="u1", server_ports=[1, 2])
    hy = {"tag": "h", "type": "hysteria2", "server": "h.example",
          "server_port": 443,
          "fields": {"password": "p", "down_mbps": 10, "up_mbps": 5}}
    obs = config_detailed([{"profile": {}, "nodes": [node, hy]}])["config"]["outbounds"]
    by_tag = {o["tag"]: o for o in obs}
    tr = by_tag["w"]["transport"]
    assert tr["path"] == "/p"
    assert tr["early_data_header_name"] == "Sec-WebSocket-Protocol"
    assert tr["max_early_data"] == 7
    assert "empty" not in by_tag["w"]
    assert by_tag["w"]["server_ports"] == [1, 2]
    assert "down_mbps" not in by_tag["h"]
    assert "up_mbps" not in by_tag["h"]
    assert by_tag["h"]["password"] == "p"


def test_chain_filtering_and_order():
    node = _vless("n1")
    dropped = dict(_vless("c1"), chain=True, chainId="x", detour="直连")
    kept = dict(_vless("c2"), chain=True, chainId="y",
                detour="n1")
    state = {"profile": {}, "nodes": [node], "chainNodes": [dropped, kept]}
    obs = config_detailed([state])["config"]["outbounds"]
    tags = [o["tag"] for o in obs]
    assert "c1" not in tags
    assert tags[-1] == "c2"  # chains last, after nodes
    assert tags.index("n1") < tags.index("c2")
    assert [o for o in obs if o["tag"] == "c2"][0]["detour"] == "n1"


def test_policy_selector_and_fallback_quic():
    policy = {"name": "P", "default": "直连",
              "rulesets": ["geosite-example"], "domain": [],
              "domainSuffix": [], "domainKeyword": [], "ipCidr": []}
    state = {"profile": {"routing": {"policies": [policy],
                                     "fallbackName": "其他"}},
             "rulesetDir": "/opt/open-box/data/rulesets"}
    cfg = config_detailed([state])["config"]
    sel = [o for o in cfg["outbounds"] if o["tag"] == "P"][0]
    assert sel["default"] == "直连"
    assert sel["outbounds"] == ["直连", "拒绝"]
    flip = [e for e in cfg["route"]["rule_set"]
            if e["tag"].startswith("obflip-")
            and e["tag"] != "obflip-fallback"][0]
    assert len(flip["tag"]) == len("obflip-") + 12
    # Flip dir is the sibling of the rulesets dir, not a child.
    assert flip["path"] == "/opt/open-box/data/flip/" + flip["tag"] \
        + ".json"
    assert cfg["route"]["rules"][-1] == {
        "action": "reject", "mode": "and",
        "rules": [{"rule_set": ["obflip-fallback"]},
                  {"network": "udp", "port": 443}], "type": "logical"}


def test_group_default_gated_on_fakeip():
    group = {"name": "dyn", "type": "selector", "mode": "dynamic",
             "enabled": True}
    node = _vless("n1")
    base = {"userGroups": [group], "nodes": [node],
            "selections": {"dyn": "n1"}}
    dns_on = {"split": True, "fakeIpForProxy": True}
    dns_off = {"split": True, "fakeIpForProxy": False}
    for dns, want in ((dns_on, "n1"), (dns_off, None)):
        state = dict(base)
        state["profile"] = {"dns": dns}
        obs = config_detailed([state])["config"]["outbounds"]
        dyn = [o for o in obs if o["tag"] == "dyn"][0]
        assert dyn.get("default") == want


def test_list_tags_fnv_and_suppression():
    policy = {"name": "P", "default": "直连", "rulesets": ["geosite-x"],
              "domain": [], "domainSuffix": [], "domainKeyword": [],
              "ipCidr": [],
              "ruleUrls": ["", "  ", "https://example.invalid/a.txt",
                           "https://example.invalid/a.txt"]}
    # fnv1a32 of the URL, computed by the implementation itself.
    from methods.config import _fnv1a32
    tag = "list-" + _fnv1a32("https://example.invalid/a.txt")
    state = {"profile": {"routing": {"policies": [policy]}},
             "rulesetDir": "/rs", "ruleLists": {}}
    cfg = config_detailed([state])["config"]
    assert any(e["tag"] == tag for e in cfg["route"]["rule_set"])
    pair = [r for r in cfg["route"]["rules"]
            if r.get("outbound") == "P"
            and "rule_set" in r][0]
    assert pair["rule_set"] == ["geosite-x", tag]
    # Downloaded (key present) -> no tag anywhere.
    state["ruleLists"] = {tag: {"url": "https://example.invalid/a.txt"}}
    cfg2 = config_detailed([state])["config"]
    assert not any(e["tag"] == tag for e in cfg2["route"]["rule_set"])


def test_native_bypass_tun_rule():
    tun_base = {"autoRedirect": False, "stack": "mixed"}
    state = {"profile": {"tun": tun_base},
             "nativeBypass": {"enabled": True,
                              "sets": ["geoip-cn", "geoip-netflix"]}}
    tun = config_detailed([state])["config"]["inbounds"][0]
    assert tun["dns_mode"] == "disabled"
    assert tun["route_exclude_address_set"] == ["geoip-cn",
                                                "geoip-netflix"]
    assert "route_address_set" not in tun
    state["nativeBypass"] = {"enabled": False,
                             "sets": ["geoip-cn"]}
    tun2 = config_detailed([state])["config"]["inbounds"][0]
    assert "route_exclude_address_set" not in tun2
