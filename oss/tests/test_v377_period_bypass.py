"""v0.1.377:
- #694: nft prerouting chain admits established LAN flows before any
  bypass reclassification, so a bypass-set update cannot reroute a
  live connection mid-flight.
- #715: failover next round is anchored to the round's start, not
  its end, so probe time no longer stacks onto the period.
"""
import sys
import time
from unittest import mock

sys.path.insert(0, "oss")

from core import failover_sm as fsm
from core.transparent import TransparentConfig, nft_script


def test_nft_established_rule_first():
    s = nft_script(TransparentConfig(lan_iface="br-lan"))
    chain = s.split("chain prerouting")[1]
    est = chain.index("ct state established,related accept")
    bypass = chain.index("ip daddr @bypass4 accept")
    tproxy = chain.index("tproxy to 127.0.0.1")
    assert est < bypass < tproxy
    assert 'iifname "br-lan" ct state established,related accept' in chain


def _state():
    st = fsm.failover_init("g", [
        {"name": "", "members": ["m1"]},
        {"name": "", "members": ["m2"]},
    ], {"probe_interval_s": 300})
    return st


def test_finish_anchors_to_round_start():
    st = _state()
    # Simulate a round that started 120s ago and finishes now.
    start = time.time() - 120
    fsm.failover_finish(st, {"target": _lane_id(st, 0),
                             "switchTo": "m1",
                             "reason": fsm.REASON_HEALTHY,
                             "reorderMove": None},
                        round_started=start)
    nxt = time.mktime(time.strptime(st.next_round_at, "%Y-%m-%dT%H:%M:%S"))
    # Start-anchored: ~start+300 (180s from now), not now+300.
    assert abs(nxt - (start + 300)) < 5


def _lane_id(st, idx):
    return st.lanes[idx]["id"]


def test_run_round_period_does_not_stack_probe_time():
    st = _state()
    clock = {"now": 1_000_000.0}

    def fake_time():
        return clock["now"]

    def fake_probe(*a, **k):
        clock["now"] += 120  # probes take 120s
        return {"ok": True, "infra": False, "latency_ms": 50,
                "reason": "ok"}

    with mock.patch.object(fsm.time, "time", side_effect=fake_time), \
            mock.patch.object(fsm, "probe_lane", side_effect=fake_probe):
        fsm.run_round(st, "http://127.0.0.1:9090", "")
    nxt = time.mktime(time.strptime(st.next_round_at, "%Y-%m-%dT%H:%M:%S"))
    # Start 1_000_000 + 300, not finish 1_000_120 + 300.
    assert abs(nxt - 1_000_300) < 5
