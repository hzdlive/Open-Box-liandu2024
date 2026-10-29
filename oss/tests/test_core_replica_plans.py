"""classes / entryPlan / bypassPlan / forwardPlan: synthetic tests.

Golden equality (11 cases) is measured with harness.py against
core-golden.json, which is not a repo fixture.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "core-replica"))

import main as core_main  # noqa: E402

BUILTIN = {"block": "拒绝", "blockEnabled": True,
           "direct": "直连", "directEnabled": True}

ROUTING = {
    "policies": [
        {"name": "P1", "default": "G1", "rulesets": ["geosite-x",
                                                    "geoip-aa"],
         "domain": ["a.com"], "domainSuffix": ["b.com"],
         "ipCidr": ["10.0.0.0/24"]},
        {"name": "D1", "default": "direct",
         "rulesets": ["geoip-cn"]},
    ],
    "fallbackName": "其他",
    "fallbackDefault": "direct",
    "custom": {"enabled": True, "rules": [
        {"type": "geoip", "value": "gg", "outbound": "G1"},
        {"type": "domain", "value": "c.com", "outbound": "G1"},
        {"type": "geosite", "value": "yt", "outbound": "G1"},
    ]},
}
SELECTIONS = {"P1": "G1", "D1": "直连", "其他": "直连"}
MEMBERS = ["直连", "G1", "拒绝"]


def _call(method, args):
    r = core_main.handle(json.dumps(
        {"protocol": 1, "method": method, "args": args}))
    assert r["ok"] is True, r
    return r["value"]


def test_classes_resolution():
    v = _call("classes", [ROUTING, MEMBERS, BUILTIN, SELECTIONS])
    assert v == {"P1": "proxy", "D1": "direct", "其他": "direct"}
    v = _call("classes", [{}, [], BUILTIN, {}])
    assert v == {"其他": "proxy"}


def test_entry_plan_branches():
    ctx = {"members": MEMBERS, "builtin": BUILTIN,
           "selections": SELECTIONS, "clientRoutes": [],
           "fakeIp": True, "dnsMode": "hijack", "enabled": True}
    v = _call("entryPlan", [ROUTING, ctx])
    assert v["mode"] == "whitelist" and v["directAnswer"] is True
    assert v["needSets"] == ["geoip-gg", "geoip-aa"]
    assert v["needCidrs"] == ["10.0.0.0/24"]
    ctx2 = dict(ctx, enabled=False)
    v = _call("entryPlan", [ROUTING, ctx2])
    assert v["mode"] == "blacklist" and "直连不进内核" in v["reason"]
    ctx3 = dict(ctx, fakeIp=False)
    v = _call("entryPlan", [ROUTING, ctx3])
    assert v["mode"] == "blacklist" and v["reason"].startswith("没开 FakeIP")


def test_bypass_plan_pending():
    ctx = {"members": MEMBERS, "builtin": BUILTIN,
           "selections": SELECTIONS, "clientRoutes": [],
           "fakeIp": True, "dnsMode": "hijack", "enabled": True}
    v = _call("bypassPlan", [ROUTING, ctx])
    assert v["enabled"] is False and len(v["pending"]) == 1
    entry = v["pending"][0]
    assert entry["policy"] == "D1" and entry["sets"] == ["geoip-cn"]
    assert [a["name"] for a in entry["against"]] == ["前置自定义分流",
                                                     "P1"]
    assert "D1" in v["reason"] and "P1" in v["reason"]


def test_forward_plan_modes_and_rewrite():
    v = _call("forwardPlan", [ROUTING, MEMBERS, BUILTIN, SELECTIONS,
                              {"rewriteDomains": ["r.example"]}])
    assert v["mode"] == "domains" and v["reason"] == ""
    assert v["domains"] == ["c.com", "a.com", "b.com", "r.example"]
    assert v["expand"] == [
        {"owner": "前置自定义分流「yt」", "tag": "geosite-yt"},
        {"owner": "站点集「P1」", "tag": "geosite-x"},
    ]
    v = _call("forwardPlan", [{}, [], BUILTIN, {}, {}])
    assert v["mode"] == "all" and v["domains"] == []
    assert v["reason"] == "兜底「其他」走代理"
