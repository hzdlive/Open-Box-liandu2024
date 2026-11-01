"""v0.1.344 upgrade preparation and restore.

Preparation before the first network request: suspend a running kernel,
wait for real exit, clean the local DNS cache; restore rules shared by
success, failure, and cancel paths; a previously stopped kernel stays
stopped.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core import selfupdate as su  # noqa: E402
from core import upgradeprep as up  # noqa: E402


class FakeClient:
    """Panel service API double. stop/start flip running immediately
    unless told otherwise."""

    def __init__(self, running=True, stop_works=True, start_works=True,
                 dead_rounds=0):
        self._running = running
        self._stop_works = stop_works
        self._start_works = start_works
        self._dead_rounds = dead_rounds
        self.stops = 0
        self.starts = 0

    def get_service(self):
        if self._dead_rounds > 0:
            self._dead_rounds -= 1
            return False, "connection refused"
        return True, {"running": self._running}

    def stop_service(self):
        self.stops += 1
        if self._stop_works:
            self._running = False
        return True, {}

    def start_service(self):
        self.starts += 1
        if self._start_works:
            self._running = True
        return True, {}


def _clean_ok():
    return True, "test-clean"


def test_prepare_running_kernel_stops_and_cleans():
    c = FakeClient(running=True)
    res = up.prepare(c, dns_cleaner=_clean_ok, poll=0.01)
    assert res == {"ok": True, "was_running": True, "error": "",
                   "detail": "test-clean"}
    assert c.stops == 1


def test_prepare_stopped_kernel_skips_stop_but_cleans():
    c = FakeClient(running=False)
    res = up.prepare(c, dns_cleaner=_clean_ok, poll=0.01)
    assert res["ok"] is True and res["was_running"] is False
    assert c.stops == 0


def test_prepare_unreachable_service_fails_before_anything():
    c = FakeClient(running=True, dead_rounds=99)
    res = up.prepare(c, dns_cleaner=_clean_ok, poll=0.01)
    assert res["ok"] is False and c.stops == 0


def test_prepare_stop_failure_skips_clean():
    c = FakeClient(running=True, stop_works=False)
    called = []
    res = up.prepare(c, dns_cleaner=lambda: called.append(1) or (True, "x"),
                     stop_timeout=0.05, poll=0.01)
    assert res["ok"] is False and res["error"] == "kernel did not stop"
    assert called == []


def test_prepare_clean_failure_restores_kernel():
    c = FakeClient(running=True)
    res = up.prepare(c, dns_cleaner=lambda: (False, "flush boom"),
                     poll=0.01)
    assert res["ok"] is False and res["error"] == "DNS cache clean failed"
    assert c.starts == 1 and c._running is True


def test_restore_running_kernel_starts():
    c = FakeClient(running=False)
    res = up.restore(c, True, poll=0.01)
    assert res["restored"] is True and c.starts == 1


def test_restore_stopped_kernel_left_stopped():
    c = FakeClient(running=False)
    res = up.restore(c, False, poll=0.01)
    assert res["restored"] is False and c.starts == 0


def test_restore_waits_for_panel_then_starts():
    c = FakeClient(running=False, dead_rounds=3)
    res = up.restore(c, True, wait_panel=True, panel_timeout=5, poll=0.01)
    assert res["restored"] is True and c.starts == 1


def test_restore_start_failure_reported():
    c = FakeClient(running=False, start_works=False)
    res = up.restore(c, True, start_timeout=0.05, poll=0.01)
    assert res["restored"] is False


def _run(stdout="", stderr="", returncode=0):
    return mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)


def test_clean_resolvectl_ok():
    ok, detail = up.clean_dns_cache(
        run=lambda *a, **k: _run(),
        which=lambda name: "/usr/bin/resolvectl" if name == "resolvectl" else None)
    assert ok is True and "resolvectl" in detail


def test_clean_resolvectl_hard_failure_fails():
    ok, _ = up.clean_dns_cache(
        run=lambda *a, **k: _run(stderr="permission denied", returncode=1),
        which=lambda name: "/usr/bin/resolvectl" if name == "resolvectl" else None)
    assert ok is False


def test_clean_resolvectl_no_daemon_falls_through_to_dnsmasq():
    calls = []

    def run(args, **k):
        calls.append(args[0])
        if args[0] == "resolvectl":
            return _run(stderr="System has not been booted with systemd",
                        returncode=1)
        return _run(stdout="1234\n")

    ok, detail = up.clean_dns_cache(
        run=run,
        which=lambda name: "/usr/bin/" + name,
        kill=lambda pid, sig: calls.append(("kill", pid, sig)))
    assert ok is True and "dnsmasq" in detail


def test_clean_no_tooling_is_noop_ok():
    ok, detail = up.clean_dns_cache(
        run=lambda *a, **k: _run(),
        which=lambda name: None)
    assert ok is True and "nothing to clean" in detail


def test_clean_dnsmasq_hup_failure_fails():
    def run(args, **k):
        if args[0] == "resolvectl":
            return _run(stderr="System has not been booted with systemd",
                        returncode=1)
        return _run(stdout="1234\n")

    ok, _ = up.clean_dns_cache(
        run=run,
        which=lambda name: "/usr/bin/" + name,
        kill=lambda pid, sig: (_ for _ in ()).throw(OSError("no perm")))
    assert ok is False


class FakeManager:
    def __init__(self, running):
        self._running = running
        self.starts = 0

    def status(self):
        return SimpleNamespace(running=self._running)

    def start(self):
        self.starts += 1
        self._running = True


def _setup_status_and_prep(monkeypatch, tmp_path, stage, pid, at_ms, was):
    monkeypatch.setattr(su, "STATUS_FILE", str(tmp_path / "update.status"))
    monkeypatch.setattr(up, "DEFAULT_STATE_FILE",
                        str(tmp_path / "prep.json"))
    if pid is not None:
        su.write_status(stage, pid=pid, ref="refs/heads/x")
    else:
        (tmp_path / "update.status").write_text(
            f"stage={stage}\nat={at_ms}\n")
    up.write_prep_state(str(tmp_path / "prep.json"), was)


def test_cancel_kills_applier_and_restores_kernel(monkeypatch, tmp_path):
    proc = subprocess.Popen(["sleep", "60"])
    try:
        _setup_status_and_prep(monkeypatch, tmp_path, "running", proc.pid,
                               0, True)
        mgr = FakeManager(running=False)
        res = su.cancel_update(mgr)
        assert res["cancelled"] is True
        assert res["kernel_restored"] is True and mgr.starts == 1
    finally:
        proc.wait(timeout=10)


def test_cancel_does_not_start_when_prep_never_suspended(monkeypatch,
                                                         tmp_path):
    proc = subprocess.Popen(["sleep", "60"])
    try:
        _setup_status_and_prep(monkeypatch, tmp_path, "running", proc.pid,
                               0, False)
        mgr = FakeManager(running=False)
        res = su.cancel_update(mgr)
        assert res["cancelled"] is True
        assert res["kernel_restored"] is False and mgr.starts == 0
    finally:
        proc.wait(timeout=10)


def test_cancel_no_running_update_stale_stage_does_not_start(monkeypatch,
                                                             tmp_path):
    old_ms = int((time.time() - 7200) * 1000)
    _setup_status_and_prep(monkeypatch, tmp_path, "done", None, old_ms,
                           True)
    mgr = FakeManager(running=False)
    res = su.cancel_update(mgr)
    assert res["cancelled"] is False
    assert res["kernel_restored"] is False and mgr.starts == 0


def test_cancel_safety_net_restores_killed_applier_kernel(monkeypatch,
                                                          tmp_path):
    now_ms = int(time.time() * 1000)
    _setup_status_and_prep(monkeypatch, tmp_path, "running", None, now_ms,
                           True)
    mgr = FakeManager(running=False)
    res = su.cancel_update(mgr)
    assert res["cancelled"] is False  # nothing was running to cancel
    assert res["kernel_restored"] is True and mgr.starts == 1


def test_cancel_without_manager_reports_none(monkeypatch, tmp_path):
    proc = subprocess.Popen(["sleep", "60"])
    try:
        _setup_status_and_prep(monkeypatch, tmp_path, "running", proc.pid,
                               0, True)
        res = su.cancel_update()
        assert res["cancelled"] is True and res["kernel_restored"] is None
    finally:
        proc.wait(timeout=10)


def test_cli_prepare_writes_state(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "clean_dns_cache", lambda *a, **k: (True, "t"))

    class FakePanel(FakeClient):
        def __init__(self, port):
            super().__init__(running=True)

    monkeypatch.setattr(up, "PanelClient", FakePanel)
    state = str(tmp_path / "prep.json")
    rc = up.main(["prepare", "--port", "8080", "--state-file", state])
    assert rc == 0
    assert up.read_prep_state(state) is True
