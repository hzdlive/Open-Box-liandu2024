"""Failover state-machine hardening (third-party report §5 candidates).

- apply_switch verifies the switch by reading back the selector's
  actual choice ("切换失败:切到 B 后读回的是 A").
- A round whose probes never reach the kernel (Clash API down for
  every lane) switches nothing.
- A urltest lane with no kernel selection yet is "unconfirmed", not
  failed; only after UNCONFIRMED_MAX_ROUNDS does it count as failed.
- Stale rounds (roundId mismatch) never update state.
- A failed kernel switch reverts the panel state to the snapshot.
"""

import json
import sys
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import failover_sm as fsm  # noqa: E402

API = "http://127.0.0.1:9090"


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _state():
    return fsm.failover_init("g", [
        {"name": "主用", "members": ["m1"]},
        {"name": "备用", "members": ["m2"]},
    ])


def _lane(st, i):
    return st.lanes[i]


# ---- apply_switch read-back ----

def _urlopen_for(put_status, get_now):
    def fake(req, timeout=None):
        if req.get_method() == "PUT":
            return FakeResp({}, status=put_status)
        return FakeResp({"now": get_now})
    return fake


def test_apply_switch_readback_ok():
    with mock.patch.object(fsm.urllib.request, "urlopen",
                           side_effect=_urlopen_for(200, "m2")):
        ok, msg = fsm.apply_switch(API, "", "g", "m2")
    assert ok and "m2" in msg


def test_apply_switch_readback_mismatch():
    with mock.patch.object(fsm.urllib.request, "urlopen",
                           side_effect=_urlopen_for(200, "m1")):
        ok, msg = fsm.apply_switch(API, "", "g", "m2")
    assert not ok
    assert msg == "切换失败:切到 m2 后读回的是 m1"


def test_apply_switch_put_error():
    def fake(req, timeout=None):
        raise urllib.error.URLError("refused")
    with mock.patch.object(fsm.urllib.request, "urlopen", side_effect=fake):
        ok, msg = fsm.apply_switch(API, "", "g", "m2")
    assert not ok and msg.startswith("switch failed:")


# ---- probe_lane: unconfirmed + infra ----

def test_probe_urltest_unconfirmed_no_delay_test():
    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        return FakeResp({"type": "URLTest", "now": None})

    with mock.patch.object(fsm.urllib.request, "urlopen", side_effect=fake):
        r = fsm.probe_lane(API, "", {"tag": "g#备用"})
    assert r.get("unconfirmed") is True
    assert len(calls) == 1  # no delay test for an unconverged urltest


def test_probe_urltest_with_selection_delay_tests():
    def fake(req, timeout=None):
        if "/delay" in req.full_url:
            return FakeResp({"delay": 123})
        return FakeResp({"type": "URLTest", "now": "m2"})

    with mock.patch.object(fsm.urllib.request, "urlopen", side_effect=fake):
        r = fsm.probe_lane(API, "", {"tag": "g#备用"})
    assert r["ok"] is True and r["latency_ms"] == 123


def test_probe_api_down_is_infra_not_lane_failure():
    def fake(req, timeout=None):
        raise urllib.error.URLError("refused")

    with mock.patch.object(fsm.urllib.request, "urlopen", side_effect=fake):
        r = fsm.probe_lane(API, "", {"tag": "m1"})
    assert r.get("infra") is True
    assert r["reason"] == fsm.FAIL_REFUSED


# ---- observe: staleness, infra skip, unconfirmed streak ----

def test_observe_ignores_stale_round():
    st = _state()
    st.last_round_id = "r2"
    fsm.failover_observe(st, [{"laneId": _lane(st, 0)["id"], "ok": False,
                               "latency_ms": None, "reason": "x"}],
                         round_id="r1")
    assert _lane(st, 0)["fail_streak"] == 0


def test_observe_infra_leaves_lane_untouched():
    st = _state()
    lane = _lane(st, 0)
    lane["fail_streak"] = 1
    lane["ok"] = True
    fsm.failover_observe(st, [{"laneId": lane["id"], "ok": False,
                               "infra": True, "latency_ms": None,
                               "reason": "refused"}])
    assert lane["fail_streak"] == 1 and lane["ok"] is True


def test_unconfirmed_bound_marks_lane_failed():
    st = _state()
    lane = _lane(st, 1)
    for _ in range(fsm.UNCONFIRMED_MAX_ROUNDS):
        fsm.failover_observe(st, [{"laneId": lane["id"], "ok": False,
                                   "unconfirmed": True, "latency_ms": None,
                                   "reason": "unconfirmed"}])
        fsm.assess_lane(st)
    assert lane["health"] == "failed" and lane["ok"] is False
    # ...but before the bound it keeps its previous health.
    st2 = _state()
    lane2 = _lane(st2, 1)
    fsm.failover_observe(st2, [{"laneId": lane2["id"], "ok": False,
                                "unconfirmed": True, "latency_ms": None,
                                "reason": "unconfirmed"}])
    fsm.assess_lane(st2)
    assert lane2["health"] == "unknown"  # never evaluated, not failed


# ---- run_round: all-infra round switches nothing ----

def test_all_infra_round_switches_nothing():
    st = _state()
    with mock.patch.object(fsm, "probe_lane",
                           return_value={"ok": False, "infra": True,
                                         "latency_ms": None,
                                         "reason": "refused"}):
        result = fsm.run_round(st, API, "")
    assert result["switched"] is False
    assert result["roundFailed"] is True
    assert result["reason"] == fsm.ROUND_FAILED_INFRA
    assert _lane(st, 0)["fail_streak"] == 0
    assert _lane(st, 0)["health"] == "unknown"
    assert st.next_round_at is None  # stays due: retry next tick


# ---- decided switch: apply failure reverts state ----

def test_failed_apply_reverts_state():
    st = _state()
    snap = fsm.snapshot_switch(st)
    lane0, lane1 = _lane(st, 0), _lane(st, 1)
    result = fsm.failover_finish(st, {"target": lane1["id"],
                                      "switchTo": lane1["tag"],
                                      "reason": fsm.REASON_LANE_FAILED,
                                      "reorderMove": None})
    assert result["switched"] is True
    assert st.current_lane_id == lane1["id"]
    with mock.patch.object(fsm, "apply_switch",
                           return_value=(False, "切换失败:切到 m2 后读回的是 m1")):
        ok, msg = fsm.apply_decided_switch(st, snap, "g", API, "")
    assert not ok
    assert st.current_lane_id == lane0["id"]
    assert st.current_id == lane0["tag"]
    assert st.logs == []
    assert st.last_switch_error == "切换失败:切到 m2 后读回的是 m1"


def test_successful_apply_clears_error():
    st = _state()
    st.last_switch_error = "old failure"
    snap = fsm.snapshot_switch(st)
    with mock.patch.object(fsm, "apply_switch",
                           return_value=(True, "switched g -> m2")):
        ok, _ = fsm.apply_decided_switch(st, snap, "g", API, "")
    assert ok and st.last_switch_error == ""
