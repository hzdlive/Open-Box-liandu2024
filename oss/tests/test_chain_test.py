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


def _run_probe(monkeypatch, curl_script, proc_poll=None):
    """Run test_chain with stubbed Popen/run/port-wait.

    curl_script: list of _Result, one per curl call in order (extra
    calls reuse the last entry). Returns (result, curl_argvs).
    """
    curl_argvs = []
    script = {"i": 0}
    monkeypatch.setattr(ct, "_wait_for_port", lambda port: True)
    monkeypatch.setattr(ct.subprocess, "Popen",
                        lambda *a, **k: _Proc(proc_poll))

    def fake_run(argv, **kwargs):
        if argv and argv[0].endswith("sing-box"):
            return _Result(0)
        curl_argvs.append(list(argv))
        idx = min(script["i"], len(curl_script) - 1)
        script["i"] += 1
        return curl_script[idx]

    monkeypatch.setattr(ct.subprocess, "run", fake_run)
    result = ct.test_chain(dict(CHAIN), timeout=15)
    return result, curl_argvs


def test_retry_after_cold_start_failure(monkeypatch):
    # First attempt hits a dead urltest member (the cold-start
    # false negative); the second attempt, after the urltest round
    # settles, succeeds. The chain must be reported up.
    script = [
        _Result(97, stderr=b"curl: (97) cannot complete SOCKS5 connection"),
        _Result(0, stdout=b'{"status":"success","country":"Singapore",'
                           b'"query":"1.2.3.4"}'),
    ]
    result, argvs = _run_probe(monkeypatch, script)
    assert result["ok"] is True
    assert result["exit_ip"] == "1.2.3.4"
    assert result["country"] == "Singapore"
    assert result["latency_ms"] is not None
    assert result["error"] is None
    assert len(argvs) == 2


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


def test_singbox_start_failure(monkeypatch):
    script = [_Result(0, stdout=b'{"status":"success"}')]
    result, _ = _run_probe(monkeypatch, script, proc_poll=0)
    assert result["ok"] is False
    assert result["error"] == "sing-box failed to start"
