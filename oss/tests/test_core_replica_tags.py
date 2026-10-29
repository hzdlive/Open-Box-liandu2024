"""builtinTags: synthetic-input unit tests.

Golden equality (2 cases) is measured with harness.py against
core-golden.json, which is not a repo fixture.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "core-replica"))

import main as core_main  # noqa: E402


def _call(arg):
    r = core_main.handle(json.dumps(
        {"protocol": 1, "method": "builtinTags", "args": [arg]}))
    assert r["ok"] is True, r
    return r["value"]


def test_empty_answers_defaults():
    assert _call([]) == {"block": "拒绝", "blockEnabled": True,
                         "direct": "直连", "directEnabled": True}
    assert _call(None) == {"block": "拒绝", "blockEnabled": True,
                           "direct": "直连", "directEnabled": True}


def test_builtin_names_and_enabled_pass_through():
    v = _call([
        {"id": "builtin-direct", "name": "Direct", "enabled": False,
         "type": "selector"},
        {"id": "builtin-block", "name": "Block", "type": "selector"},
        {"id": "g1", "name": "G1", "type": "selector"},
    ])
    assert v == {"block": "Block", "blockEnabled": True,
                 "direct": "Direct", "directEnabled": False}


def test_mistyped_builtin_fields_answer_defaults():
    v = _call([
        {"id": "builtin-direct", "name": 42, "enabled": "yes",
         "type": "selector"},
    ])
    assert v["direct"] == "直连" and v["directEnabled"] is True
    assert v["block"] == "拒绝" and v["blockEnabled"] is True
