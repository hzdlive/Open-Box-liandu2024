"""migrateStoredRouting: synthetic tests.

Golden equality (3 cases) is measured with harness.py against
core-golden.json, which is not a repo fixture. All three golden
cases return their input unchanged with changed=false, so these
tests pin the identity behavior (including preservation of
legacy top-level keys) rather than any transformation.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "core-replica"))

import main as core_main  # noqa: E402


def _call(routing):
    r = core_main.handle(json.dumps(
        {"protocol": 1, "method": "migrateStoredRouting",
         "args": [routing]}))
    assert r["ok"] is True, r
    return r["value"]


def test_empty_and_legacy_pass_through():
    assert _call({}) == {"changed": False, "routing": {}}
    legacy = {"rules": [], "final": "direct", "groups": [],
              "policies": []}
    assert _call(legacy) == {"changed": False, "routing": legacy}


def test_modern_routing_unchanged_and_input_not_mutated():
    routing = {"policies": [{"name": "P1", "default": "G1",
                             "rulesets": ["geosite-x"]}],
               "fallbackName": "其他", "fallbackDefault": "direct",
               "custom": {"enabled": True, "rules": []},
               "unknownKey": {"kept": True}}
    out = _call(routing)
    assert out == {"changed": False, "routing": routing}
    assert routing["unknownKey"] == {"kept": True}
