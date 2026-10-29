"""emitGroups: synthetic-input unit tests.

Golden equality (121 cases) is measured with harness.py against
core-golden.json, which is not a repo fixture.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "core-replica"))

import main as core_main  # noqa: E402

ALL = [{"tag": "n1", "type": "vless"}, {"tag": "n2", "type": "vless"}]


def _call(groups, all_obs=ALL, opt=None):
    r = core_main.handle(json.dumps(
        {"protocol": 1, "method": "emitGroups",
         "args": [groups, all_obs, opt if opt is not None else {}]}))
    assert r["ok"] is True, r
    return r["value"]


def test_selector_resolves_and_placeholders_on_empty():
    v = _call([{"id": "g1", "name": "G1", "type": "selector",
                "members": ["n1", "nope", "n2"], "enabled": True}])
    assert v["outbounds"][1] == {"outbounds": ["n1", "n2"], "tag": "G1",
                                 "type": "selector"}
    assert v["placeholders"] == [] and v["publicTags"] == ["直连", "G1",
                                                           "拒绝"]
    v = _call([{"id": "g1", "name": "G1", "type": "selector",
                "members": ["nope"], "enabled": True}], all_obs=[])
    assert v["outbounds"][1] == {"outbounds": ["直连"], "tag": "G1",
                                 "type": "selector"}
    assert v["placeholders"] == ["G1"]


def test_disabled_group_skipped_builtins_kept_in_place():
    v = _call([{"id": "g1", "name": "G1", "type": "selector",
                "members": ["n1"], "enabled": False}])
    assert [o["tag"] for o in v["outbounds"]] == ["直连", "拒绝"]


def test_urltest_raw_interval_and_idle_max():
    v = _call([{"id": "g1", "name": "G1", "type": "urltest",
                "members": ["n1"], "enabled": True, "interval": "abc",
                "idleTimeout": "5m"}])
    ob = v["outbounds"][1]
    assert ob["interval"] == "abc" and ob["idle_timeout"] == "5m"
    v = _call([{"id": "g1", "name": "G1", "type": "urltest",
                "members": ["n1"], "enabled": True, "interval": "60s",
                "idleTimeout": "24h"}])
    assert v["outbounds"][1]["idle_timeout"] == "24h"


def test_dynamic_group_expands_to_all():
    v = _call([{"id": "all-auto", "name": "所有-自动", "type": "urltest",
                "members": [], "enabled": True, "mode": "dynamic"}])
    assert v["outbounds"][1]["outbounds"] == ["n1", "n2"]
    assert v["placeholders"] == []


def test_failover_lane_modes_and_interval_rules():
    v = _call([{"id": "g1", "name": "G1", "type": "failover",
                "enabled": True, "interval": "abc",
                "lanes": [
                    {"id": "l1", "members": ["n1", "n2"]},
                    {"id": "l2", "members": ["n1"]},
                    {"id": "l3", "members": ["nope"]},
                ]}])
    fo = v["failover"][0]
    assert fo["settings"]["interval"] == "300s"
    assert fo["settings"]["intervalMs"] == 300000
    assert [ln["mode"] for ln in fo["lanes"]] == ["urltest", "single",
                                                  "empty"]
    assert fo["lanes"][0]["ref"] == "__fo:g1:l1"
    assert fo["lanes"][1]["ref"] == "n1"
    assert v["internalTags"] == ["__fo:g1:l1"]
    grp = [o for o in v["outbounds"] if o.get("tag") == "G1"][0]
    assert grp["default"] == "__fo:g1:l1"
    assert grp["outbounds"] == ["__fo:g1:l1", "n1", "拒绝"]
    v = _call([{"id": "g1", "name": "G1", "type": "failover",
                "enabled": True, "interval": "5m3",
                "lanes": [{"id": "l1", "members": ["n1", "n2"]}]}])
    assert v["failover"][0]["settings"]["interval"] == "5m3"
    assert v["failover"][0]["settings"]["intervalMs"] == 300000
