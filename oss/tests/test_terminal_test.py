"""Tests for the terminal test orchestrator (v8 #35 对照）.

The namespace, the child and the kernel are all stubbed; nothing
here creates a netns or dials a target.
"""

import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import terminal_test as tt  # noqa: E402

LEASE = {"ip": "192.168.1.50", "hostname": "openbox-probe",
         "mac": "02:4f:42:00:00:01", "dns": ["192.168.1.1"],
         "gateway": "192.168.1.1", "override": None,
         "lanDevice": "obprobe1", "reused": False, "dhcpMs": 12}

FLOW = {"proto": "tcp", "state": "ESTABLISHED",
        "orig": {"src": "192.168.1.50", "dst": "1.2.3.4",
                 "sport": 40000, "dport": 443},
        "reply": {"src": "1.2.3.4", "dst": "192.168.1.50",
                  "sport": 443, "dport": 40000},
        "mark": None, "line": "flow-line"}

CONN = {"id": "abc", "metadata": {"sourceIP": "192.168.1.50",
                                  "sourcePort": 40000,
                                  "destinationIP": "1.2.3.4",
                                  "destinationPort": 443,
                                  "host": ""},
        "chains": ["node-a"], "rule": "final", "rulePayload": "",
        "start": "2026-10-26T13:00:00+08:00"}


class FakeChild:
    """A stub probe child: yields canned events, records close()."""

    def __init__(self, events):
        self._events = [json.dumps(e) for e in events]
        self.closed = False
        self.terminated = False

    def __call__(self, argv):
        return self

    def stdout_lines(self):
        yield from self._events

    def close(self):
        self.closed = True

    def terminate(self):
        self.terminated = True


def _fake_run(argv, timeout):
    if argv[:2] == ["ip", "-4"] or argv[:2] == ["ip", "-6"]:
        return 0, "", ""
    if argv[:3] == ["ip", "route", "get"]:
        return 0, "1.2.3.4 via 192.168.1.1 dev eth0 src 192.168.1.50\n", ""
    if argv[0] == "nft":
        return 1, "", "no set"
    return 1, "", ""


def _run_full(monkeypatch, events):
    monkeypatch.setattr(tt, "probe_capability",
                        lambda run, exists, uid: {
                            "ok": True, "missing": [],
                            "lan": {"device": "br-lan",
                                    "address": "192.168.1.1"},
                            "dhcp_client": "dhcpcd"})
    monkeypatch.setattr(tt, "ensure_probe_netns",
                        lambda run, exists, client: dict(LEASE))
    monkeypatch.setattr(tt, "read_conntrack", lambda run: [FLOW])
    child = FakeChild(events)
    report = tt.terminal_test(
        {"target": "example.com", "method": "TCP"},
        deployed={"inbounds": [{"type": "tun", "tag": "tun-in"}]},
        run=_fake_run, exists=lambda p: False,
        connections_fn=lambda: [CONN], spawn=child)
    return report, child


def test_capable_false_short_circuits(monkeypatch):
    monkeypatch.setattr(tt, "probe_capability",
                        lambda run, exists, uid: {
                            "ok": False, "missing": ["lan"],
                            "lan": None, "dhcp_client": None})

    def _boom(*a, **k):
        raise AssertionError("must not run")

    report = tt.terminal_test({"target": "example.com"},
                              run=_boom, exists=lambda p: False,
                              connections_fn=_boom, spawn=_boom)
    assert report == {"target": "example.com", "mode": "lan",
                      "capable": False, "missing": ["lan"]}


def test_setup_error(monkeypatch):
    monkeypatch.setattr(tt, "probe_capability",
                        lambda run, exists, uid: {
                            "ok": True, "missing": [],
                            "lan": {"device": "br-lan",
                                    "address": "192.168.1.1"},
                            "dhcp_client": "dhcpcd"})

    def _fail(run, exists, client):
        raise RuntimeError("no DHCP server answered")

    monkeypatch.setattr(tt, "ensure_probe_netns", _fail)
    report = tt.terminal_test({"target": "example.com"},
                              run=_fake_run, exists=lambda p: False,
                              connections_fn=lambda: [])
    assert report["setupError"] == "no DHCP server answered"
    assert report["capable"] is True


def test_full_evidence_path(monkeypatch):
    events = [
        {"event": "dns", "server": "192.168.1.1", "ok": True,
         "answers": ["1.2.3.4"], "answers6": [], "ms": 5},
        {"event": "connected", "remoteAddress": "1.2.3.4",
         "localAddress": "192.168.1.50", "localPort": 40000, "ms": 8},
        {"event": "response", "status": 200, "headers": {}, "ms": 20},
    ]
    report, child = _run_full(monkeypatch, events)
    assert report["capable"] is True
    assert report["source"]["ip"] == "192.168.1.50"
    assert report["exit"]["ok"] is True
    assert report["exit"]["status"] == 200
    assert report["exit"]["connectTo"] == "1.2.3.4"
    assert report["exit"]["localPort"] == 40000
    assert report["dns"]["answers"] == ["1.2.3.4"]
    assert report["entry"]["kind"] == "kernel"
    assert report["entry"]["via"] == "connection-table"
    assert report["kernel"]["seen"] is True
    assert report["kernel"]["chains"] == ["node-a"]
    assert report["timing"]["totalMs"] >= 0
    assert child.closed is True


def test_dns_failure_reports_not_connected(monkeypatch):
    events = [
        {"event": "dns", "server": "192.168.1.1", "ok": False,
         "answers": [], "ms": 5, "error": "timeout"},
        {"event": "error", "stage": "dns", "error": "timeout", "ms": 5},
    ]
    report, _ = _run_full(monkeypatch, events)
    assert report["exit"]["ok"] is False
    assert report["exit"]["error"] == "dns: timeout"
    assert report["entry"]["reason"] == "not-connected"


def test_serialised_releases_on_failure():
    calls = []

    def _fail():
        calls.append("fail")
        raise RuntimeError("boom")

    def _ok():
        calls.append("ok")
        return "done"

    try:
        tt.run_serialised(_fail)
    except RuntimeError:
        pass
    assert tt.run_serialised(_ok) == "done"
    assert calls == ["fail", "ok"]


def test_endpoint_gates(monkeypatch, tmp_path):
    from panel import app as appmod
    from panel import db as dbmod

    dbfile = tempfile.mktemp(suffix=".db")
    c = sqlite3.connect(dbfile)
    dbmod.init_db(c)
    c.close()
    client = appmod.create_app(dbfile).test_client()
    monkeypatch.setattr(tt, "is_container", lambda: True)
    r = client.get("/api/openbox/terminal-test/capability")
    assert r.status_code == 200
    assert r.get_json()["missing"] == [tt.CONTAINER_PROBE_REFUSAL]
    r = client.post("/api/openbox/terminal-test",
                    json={"target": "example.com"})
    assert r.status_code == 409
    monkeypatch.setattr(tt, "is_container", lambda: False)
    r = client.post("/api/openbox/terminal-test",
                    json={"target": "-oops"})
    assert r.status_code == 400
    r = client.post("/api/openbox/terminal-test",
                    json={"target": "example.com", "method": "POST"})
    assert r.status_code == 400
    monkeypatch.setattr(tt, "probe_capability",
                        lambda run, exists, uid: {
                            "ok": False, "missing": ["lan"],
                            "lan": None, "dhcp_client": None})
    monkeypatch.setenv("OPENBOX_WORKDIR", str(tmp_path))
    r = client.post("/api/openbox/terminal-test",
                    json={"target": "example.com"})
    assert r.status_code == 200
    assert r.get_json()["capable"] is False
    assert r.get_json()["missing"] == ["lan"]
