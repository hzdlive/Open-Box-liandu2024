"""Normalize methods: synthetic-input unit tests.

Golden equality (8+9+2+2 cases) is measured with
oss/core-replica/harness.py against core-golden.json, which is not a
repo fixture (35 MB, live-install snapshot). These tests pin the
rules on synthetic inputs so regressions surface without the corpus.
Rules marked INFERRED in methods/normalize.py are tested here as
our current reading, not as measured facts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "core-replica"))

import main as core_main  # noqa: E402


def _call(method, arg):
    r = core_main.handle(__import__("json").dumps(
        {"protocol": 1, "method": method, "args": [arg]}))
    assert r["ok"] is True, r
    return r["value"]


def test_routing_empty_defaults():
    v = _call("normalizeRouting", {})
    assert v["policies"] == [] and v["activePolicies"] == []
    assert v["custom"] == {"enabled": True, "icon": "misc:pin",
                           "iconScale": 0, "name": "前置自定义分流",
                           "rules": []}
    assert v["fallback"] == {"default": "",
                             "icon": "globe:earth-meridians",
                             "name": "其他"}


def test_routing_drops_ruleless_policy_keeps_rest():
    v = _call("normalizeRouting", {
        "policies": [
            {"name": "P1", "outbound": "direct"},
            {"id": "p2", "name": "P2", "domain": ["a.com"]},
            {"id": "p3", "name": "P3", "domain": ["b.com"],
             "enabled": False},
        ]})
    assert [p["id"] for p in v["policies"]] == ["p2", "p3"]
    assert v["policies"][0]["enabled"] is True
    # INFERRED: activePolicies are the enabled policies only.
    assert [p["id"] for p in v["activePolicies"]] == ["p2"]
    # Unknown policy fields do not survive.
    assert "outbound" not in v["policies"][0]


def test_policy_standalone_defaults_are_positional_zero():
    v = _call("normalizePolicy", {})
    assert v["id"] == "policy-0" and v["name"] == "策略-1"
    assert v["enabled"] is True and v["notes"] == {}
    assert v["domain"] == [] and v["rulesets"] == []


def test_custom_rule_needs_outbound():
    v = _call("normalizeCustom", {
        "name": "X",
        "rules": [
            {"type": "domain", "value": "a.com", "outbound": "direct"},
            {"type": "domain", "value": "b.com", "action": "direct"},
            {"type": "domain", "value": "c.com"},
        ]})
    assert v["name"] == "X"
    assert v["rules"] == [{"outbound": "direct", "type": "domain",
                           "value": "a.com"}]


def test_groups_builtin_ensure_and_place():
    v = _call("normalizeGroups", [
        {"id": "g1", "name": "G1", "type": "selector", "members": []}])
    assert [g["id"] for g in v] == ["builtin-direct", "g1",
                                   "builtin-block"]
    assert v[0]["name"] == "直连" and v[-1]["name"] == "拒绝"
    # An input builtin stays in place; no extra direct is prepended.
    v = _call("normalizeGroups", [
        {"id": "builtin-direct", "name": "直连", "type": "selector",
         "kind": "direct", "members": []}])
    assert [g["id"] for g in v] == ["builtin-direct", "builtin-block"]


def test_groups_failover_recovery_null_rules():
    base = {"id": "g1", "name": "G1", "type": "failover", "members": [],
            "lanes": []}
    v = _call("normalizeGroups", [{**base}])
    fo = [g for g in v if g["id"] == "g1"][0]
    assert fo["failover"] == {"failureThreshold": 2,
                              "recoveryHoldMs": 60000,
                              "restorePrimary": True, "timeoutMs": 5000}
    assert fo["interval"] == "300s" and fo["tolerance"] == 100
    v = _call("normalizeGroups",
              [{**base, "failover": {"recoveryHoldMs": None}}])
    fo = [g for g in v if g["id"] == "g1"][0]
    assert fo["failover"]["recoveryHoldMs"] == 0
    v = _call("normalizeGroups",
              [{**base, "failover": {"recoveryHoldMs": "x"}}])
    fo = [g for g in v if g["id"] == "g1"][0]
    assert fo["failover"]["recoveryHoldMs"] == 60000


def test_groups_unknown_type_becomes_selector():
    v = _call("normalizeGroups", [
        {"id": "y", "name": "Y", "type": "nope", "members": []}])
    g = [x for x in v if x["id"] == "y"][0]
    assert g["type"] == "selector"
