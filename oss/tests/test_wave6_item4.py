"""Wave6 item 4 (2026-11-01): profile GET/PUT, latency queue,
policies/entries.

Profile shape comes from the original's UI-consumed fields (bundle
behavior comparison): testUrl/testExpectedStatus/directTestUrl,
routing.policies/fallback*/displayOrder/custom. PUT deep-merges and
returns {applied, profile, renamed}; renamed is always [] because a
name-keyed PUT cannot express a rename. Queue returns
{busy, running, waiting}; waiting is always 0 (synchronous model).
policies/entries returns a flat per-policy list (contract keys
empty); ?policy=/?name= unknown -> 400 (contract's 400 status).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import app as appmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _client():
    return create_app(":memory:").test_client()


def test_profile_get_defaults():
    c = _client()
    r = c.get("/api/openbox/profile")
    assert r.status_code == 200
    p = r.get_json()["profile"]
    assert p["testUrl"] == "http://www.gstatic.com/generate_204"
    assert p["testExpectedStatus"] == "*"
    assert p["directTestUrl"] == ("http://connectivitycheck.platform."
                                  "hicloud.com/generate_204")
    # list_groups synthesizes the direct/block built-ins around the
    # stored groups (same as the original's policy list).
    assert [x["name"] for x in p["routing"]["policies"]] == [
        "direct", "所有-自动", "所有-手动", "block"]
    assert p["routing"]["fallbackName"] == "其他"
    assert p["routing"]["fallbackIcon"] == "globe:earth-meridians"
    assert p["routing"]["fallbackIconScale"] == 0
    assert p["routing"]["displayOrder"] == [
        "direct", "所有-自动", "所有-手动", "block"]
    assert p["routing"]["custom"] == {
        "name": "前置自定义分流", "icon": "misc:pin", "iconScale": 0,
        "enabled": True, "rules": []}
    # Trailing slash serves the same document (contract path profile/).
    r = c.get("/api/openbox/profile/")
    assert r.status_code == 200
    assert r.get_json()["profile"] == p


def test_profile_put_merges_and_returns_full_profile():
    c = _client()
    r = c.put("/api/openbox/profile", json={
        "routing": {"displayOrder": ["所有-手动", "所有-自动"]}})
    assert r.status_code == 200
    body = r.get_json()
    assert body["applied"] == 1
    assert body["renamed"] == []
    # Stored positions flipped (所有-手动 0, 所有-自动 1); the
    # assembled order still brackets them with the direct/block
    # built-ins (list_groups synthesizes those first/last).
    assert body["profile"]["routing"]["displayOrder"] == [
        "direct", "所有-手动", "所有-自动", "block"]
    r = c.put("/api/openbox/profile", json={
        "testExpectedStatus": "200-299",
        "routing": {"fallbackName": "FB",
                    "policies": [{"name": "所有-自动", "enabled": False,
                                  "icon": "globe:asia"}]}})
    assert r.status_code == 200
    body = r.get_json()
    # testExpectedStatus + fallbackName + enabled + icon = 4 leaves.
    assert body["applied"] == 4
    p = body["profile"]
    assert p["testExpectedStatus"] == "200-299"
    assert p["routing"]["fallbackName"] == "FB"
    pol = [x for x in p["routing"]["policies"]
           if x["name"] == "所有-自动"][0]
    assert pol["enabled"] is False
    assert pol["icon"] == "globe:asia"
    # No-op PUT applies nothing.
    r = c.put("/api/openbox/profile", json={
        "testExpectedStatus": "200-299"})
    assert r.get_json()["applied"] == 0


def test_profile_put_validation():
    c = _client()
    assert c.put("/api/openbox/profile",
                 json={"routing": "x"}).status_code == 400
    assert c.put("/api/openbox/profile", json={
        "routing": {"displayOrder": "x"}}).status_code == 400
    assert c.put("/api/openbox/profile",
                 json={"routing": {"policies": [{"icon": "x"}]}}).status_code == 400
    assert c.put("/api/openbox/profile",
                 json=[1, 2]).status_code == 400


def test_latency_queue_idle_and_driven():
    c = _client()
    body = c.get("/api/openbox/nodes/latency/queue").get_json()
    assert body == {"busy": False, "running": 0, "waiting": 0}
    appmod._latency_begin()
    try:
        body = c.get("/api/openbox/nodes/latency/queue").get_json()
        assert body == {"busy": True, "running": 1, "waiting": 0}
    finally:
        appmod._latency_end()
    assert c.get("/api/openbox/nodes/latency/queue").get_json() == {
        "busy": False, "running": 0, "waiting": 0}


def test_policies_entries():
    c = _client()
    r = c.get("/api/openbox/policies/entries")
    assert r.status_code == 200
    entries = r.get_json()
    assert isinstance(entries, list)
    assert [e["name"] for e in entries] == ["所有-自动", "所有-手动"]
    assert entries[0]["members"] == ["*nodes*"]
    r = c.get("/api/openbox/policies/entries",
              query_string={"policy": "所有-自动"})
    assert len(r.get_json()) == 1
    r = c.get("/api/openbox/policies/entries",
              query_string={"policy": "nope"})
    assert r.status_code == 400
    r = c.get("/api/openbox/policies/entries",
              query_string={"q": "手动"})
    assert [e["name"] for e in r.get_json()] == ["所有-手动"]
