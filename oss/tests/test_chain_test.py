"""Tests for the chain speedtest probe (core/chain_test.py).

All subprocess interaction is stubbed: the temp sing-box binary is
never started and no socket is opened. What is verified is the probe
logic itself: retry after a cold-start failure, preserved curl error
text, and the -sS flag.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import chain_test as ct  # noqa: E402


CHAIN = {"name": "t", "exit_protocol": "socks", "server": "127.0.0.1",
         "server_port": 1080, "params": {}, "front": "direct"}


class _Proc:
    def __init__(self, poll_result=None):
        self._poll = poll_result

    def poll(self):
        return self._poll

    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass

    def kill(self):
        pass


class _Result:
    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_probe(monkeypatch, curl_script, proc_poll=None, front_ob=None,
               gate=None, chain=None, gate_members="unset"):
    """Run test_chain with stubbed Popen/run/port-wait (and, for a
    urltest front, a stubbed readiness gate).

    curl_script: list of _Result, one per curl call in order (extra
    calls reuse the last entry). Returns (result, curl_argvs).
    """
    curl_argvs = []
    script = {"i": 0}
    monkeypatch.setattr(ct, "_wait_for_port", lambda port: True)
    monkeypatch.setattr(ct.subprocess, "Popen",
                        lambda *a, **k: _Proc(proc_poll))
    if gate is not None:
        monkeypatch.setattr(ct, "_wait_for_front_ready",
                            lambda *a, **k: gate)

    def fake_run(argv, **kwargs):
        if argv and argv[0].endswith("sing-box"):
            return _Result(0)
        curl_argvs.append(list(argv))
        idx = min(script["i"], len(curl_script) - 1)
        script["i"] += 1
        return curl_script[idx]

    monkeypatch.setattr(ct.subprocess, "run", fake_run)
    kwargs = {} if gate_members == "unset" else {"gate_members": gate_members}
    result = ct.test_chain(dict(chain or CHAIN), front_ob, None,
                           timeout=15, **kwargs)
    return result, curl_argvs


def test_gate_waits_for_live_member():
    # No delay at first, then one member measures: the gate must
    # report ready (it does not require every member to be alive).
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] < 3:
            return {"m1": {"history": []}, "m2": {"history": []}}
        return {"m1": {"history": []},
                "m2": {"history": [{"delay": 90, "time": "t"}]}}

    assert ct._wait_for_front_ready(0, ["m1", "m2"], budget_s=5,
                                    fetch=fetch,
                                    sleep=lambda s: None) == "ready"
    assert calls["n"] == 3


def test_gate_no_live_member_vs_api_down():
    # API answers but nobody ever measures -> no-live-member;
    # API never answers -> api-unavailable (gate inconclusive).
    assert ct._wait_for_front_ready(
        0, ["m1"], budget_s=0.5,
        fetch=lambda: {"m1": {"history": []}},
        sleep=lambda s: None) == "no-live-member"

    def boom():
        raise ConnectionError("refused")

    assert ct._wait_for_front_ready(0, ["m1"], budget_s=0.5, fetch=boom,
                                    sleep=lambda s: None) == "api-unavailable"


def test_gate_waits_for_group_selection_not_first_member():
    # Regression: a 53-member sub group measured its first live member
    # at ~1s but its urltest round only produced a selection at ~115s.
    # The gate must wait for the group's "now" selection, not for any
    # member delay — members alive from the start must NOT make it
    # return ready while the selection is still empty.
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        now = "m2" if calls["n"] >= 3 else ""
        return {"g": {"now": now, "history": []},
                "m1": {"history": [{"delay": 50, "time": "t"}]},
                "m2": {"history": [{"delay": 90, "time": "t"}]}}

    assert ct._wait_for_front_ready(0, ["m1", "m2"], group_tag="g",
                                    budget_s=5, fetch=fetch,
                                    sleep=lambda s: None) == "ready"
    assert calls["n"] == 3


def test_gate_group_never_selects_reports_not_converged():
    # Members alive but the group never selects within budget: the
    # gate must say so explicitly instead of letting the probe run
    # through a selection-less group (curl 97/52/28 artifacts).
    assert ct._wait_for_front_ready(
        0, ["m1"], group_tag="g", budget_s=0.5,
        fetch=lambda: {"g": {"now": "", "history": []},
                       "m1": {"history": [{"delay": 50, "time": "t"}]}},
        sleep=lambda s: None) == "not-converged"
    # No live member at all in group mode stays no-live-member.
    assert ct._wait_for_front_ready(
        0, ["m1"], group_tag="g", budget_s=0.5,
        fetch=lambda: {"g": {"now": "", "history": []},
                       "m1": {"history": []}},
        sleep=lambda s: None) == "no-live-member"


def test_not_converged_front_fails_fast(monkeypatch):
    front = {"type": "urltest", "tag": "g", "outbounds": ["m1", "m2"]}
    result, argvs = _run_probe(
        monkeypatch,
        [_Result(0, stdout=b'{"status":"success"}')],
        front_ob=front, gate="not-converged",
        chain=dict(CHAIN, front="g"))
    assert result["ok"] is False
    assert "did not converge" in result["error"]
    assert argvs == []


def test_urltest_front_without_live_member_skips_probe(monkeypatch):
    # Gate says no live member: the chain is reported down with the
    # front diagnosis, and no probe is attempted at all.
    front = {"type": "urltest", "tag": "g", "outbounds": ["m1", "m2"]}
    result, argvs = _run_probe(
        monkeypatch,
        [_Result(0, stdout=b'{"status":"success"}')],
        front_ob=front, gate="no-live-member")
    assert result["ok"] is False
    assert result["error"] == "front urltest has no live member"
    assert argvs == []


def test_urltest_front_ready_probes_once(monkeypatch):
    # Gate says ready: exactly one probe runs and its result stands.
    front = {"type": "urltest", "tag": "g", "outbounds": ["m1", "m2"]}
    script = [_Result(0, stdout=b'{"status":"success","country":"SG",'
                                 b'"query":"1.2.3.4"}')]
    result, argvs = _run_probe(monkeypatch, script, front_ob=front,
                               gate="ready")
    assert result["ok"] is True
    assert result["exit_ip"] == "1.2.3.4"
    assert len(argvs) == 1


def test_error_keeps_curl_stderr(monkeypatch):
    # A genuinely dead chain: every attempt fails, and the reported
    # error must carry curl's own text, not a bare "proxy request
    # failed:" with nothing after the colon.
    script = [_Result(28, stderr=b"curl: (28) Operation timed out")]
    result, _ = _run_probe(monkeypatch, script)
    assert result["ok"] is False
    assert "Operation timed out" in result["error"]
    assert result["error"].startswith("proxy request failed: curl:")


def test_curl_uses_sS_flag(monkeypatch):
    script = [_Result(0, stdout=b'{"status":"success","country":"JP",'
                                  b'"query":"5.6.7.8"}')]
    _, argvs = _run_probe(monkeypatch, script)
    assert argvs and "-sS" in argvs[0]
    assert "-s" not in argvs[0]


def test_saved_chain_port_key_is_honored(monkeypatch):
    # Regression: db.list_chains returns "port", not "server_port".
    # Reading only "server_port" built the probe with port 0, so
    # every saved-chain speedtest failed with "proxy request
    # failed:" while the modal (unsaved) form worked.
    from core import singbox as sbmod
    seen = {}

    def fake_chain_to_outbound(ch):
        seen["server_port"] = ch.server_port
        return {"type": "direct", "tag": "chain-test"}

    monkeypatch.setattr(sbmod, "chain_to_outbound",
                        fake_chain_to_outbound)
    db_row = {"name": "t", "exit_protocol": "shadowsocks",
              "server": "singapore.extls.pp.ua", "port": 22101,
              "params": {}, "front": "direct"}
    monkeypatch.setattr(ct, "_wait_for_port", lambda port: True)
    monkeypatch.setattr(ct.subprocess, "Popen",
                        lambda *a, **k: _Proc(None))
    monkeypatch.setattr(ct.subprocess, "run",
                        lambda argv, **kw: _Result(
                            0) if argv[0].endswith("sing-box")
                        else _Result(0, stdout=b'{"status":"success",'
                                                b'"country":"SG",'
                                                b'"query":"1.2.3.4"}'))
    result = ct.test_chain(db_row, None, None, timeout=15)
    assert seen["server_port"] == 22101
    assert result["ok"] is True


def test_unresolvable_front_fails_fast(monkeypatch):
    # A front that cannot be resolved must not probe through a
    # dangling detour (sing-box check passes those, rc=0); the error
    # must name the front. Block cannot be probed at all.
    ok_script = [_Result(0, stdout=b'{"status":"success"}')]
    chain = dict(CHAIN, front="deleted-group")
    result, argvs = _run_probe(monkeypatch, ok_script, chain=chain)
    assert result["ok"] is False
    assert result["error"] == "front not found: deleted-group"
    assert argvs == []
    chain = dict(CHAIN, front="block")
    result, _ = _run_probe(monkeypatch, ok_script, chain=chain)
    assert result["error"] == "front is block"


def test_direct_only_group_skips_gate(monkeypatch):
    # A front that resolved to nothing but "direct" (empty group)
    # routes direct: the gate must not run (it would report
    # no-live-member for a working direct path).
    front = {"type": "urltest", "tag": "g", "outbounds": ["direct"]}
    script = [_Result(0, stdout=b'{"status":"success","country":"SG",'
                                 b'"query":"1.2.3.4"}')]
    result, argvs = _run_probe(monkeypatch, script, front_ob=front,
                               gate="no-live-member",
                               gate_members=["direct"])
    assert result["ok"] is True
    assert len(argvs) == 1


def test_singbox_start_failure(monkeypatch):
    script = [_Result(0, stdout=b'{"status":"success"}')]
    result, _ = _run_probe(monkeypatch, script, proc_poll=0)
    assert result["ok"] is False
    assert result["error"] == "sing-box failed to start"
