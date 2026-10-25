"""Self-test for the panel-managed dnsmasq drop-in auto-sync.

Covers: content generation from panel state (enabled rewrites only,
cname for domain targets, address for IP targets, invalid rows commented,
filter conf-file line only when enabled AND its file exists) and the
sync itself (no restart when unchanged, --test gate with restore on
failure, no restart when dnsmasq is down, systemctl with kill+start
fallback). The runner is injected so no real dnsmasq/systemctl is used.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panel import app as appmod  # noqa: E402
from panel import db as dbmod  # noqa: E402


def _db():
    c = sqlite3.connect(":memory:")
    dbmod.init_db(c)
    return c


def _seed_rewrites(c):
    dbmod.add_dns_rewrite(c, "developers.google.cn", "developers.google.com")
    dbmod.add_dns_rewrite(c, "x.example.com", "1.2.3.4")
    # Disabled row: must not appear in the file.
    r = dbmod.add_dns_rewrite(c, "off.example.com", "5.6.7.8")
    dbmod.set_dns_rewrite_enabled(c, r["id"], False)
    # Legacy invalid row (bypasses add-time validation): commented out.
    c.execute("INSERT INTO dns_rewrite(domain, target, enabled)"
              " VALUES ('bad.example.com', '!!!', 1)")
    c.commit()


class Runner:
    """Stub for subprocess calls; match by command shape, not binary path."""

    def __init__(self, test_rc=0, running=True, systemctl_rc=0):
        self.test_rc = test_rc
        self.running = running
        self.systemctl_rc = systemctl_rc
        self.cmds = []

    def __call__(self, cmd):
        self.cmds.append(list(cmd))
        if "--test" in cmd:
            return SimpleNamespace(returncode=self.test_rc)
        if cmd[0].endswith("pgrep"):
            return SimpleNamespace(returncode=0 if self.running else 1)
        if cmd[0] == "systemctl":
            return SimpleNamespace(returncode=self.systemctl_rc)
        return SimpleNamespace(returncode=0)


def test_content_rewrites_only_enabled():
    c = _db()
    _seed_rewrites(c)
    out = appmod.dnsmasq_panel_conf_content(c)
    assert "cname=developers.google.cn,developers.google.com" in out
    assert "address=/x.example.com/1.2.3.4" in out
    assert "off.example.com" not in out
    assert "skipped invalid rewrite: bad.example.com" in out
    assert "conf-file=" not in out  # filter off by default


def test_content_filter_line_only_when_file_exists(tmp_path, monkeypatch):
    import core.service as _svc
    c = _db()
    _seed_rewrites(c)
    dbmod.set_setting(c, "dns_filter_enabled", "1")
    monkeypatch.setattr(_svc, "manager_from_env",
                        lambda: SimpleNamespace(workdir=str(tmp_path)))
    # File missing -> no conf-file line (dnsmasq --test would fail on it).
    assert "conf-file=" not in appmod.dnsmasq_panel_conf_content(c)
    (tmp_path / "dnsmasq-blocklist.conf").write_text("address=/a.example/#\n")
    out = appmod.dnsmasq_panel_conf_content(c)
    assert f"conf-file={tmp_path}/dnsmasq-blocklist.conf" in out


def test_sync_unchanged_skips_restart(tmp_path):
    c = _db()
    _seed_rewrites(c)
    path = str(tmp_path / "openbox-panel.conf")
    runner = Runner()
    r1 = appmod.sync_dnsmasq_panel_conf(c, conf_path=path, run=runner, wait_ready=lambda: True)
    assert r1["changed"] is True
    ncmds = len(runner.cmds)
    r2 = appmod.sync_dnsmasq_panel_conf(c, conf_path=path, run=runner, wait_ready=lambda: True)
    assert r2 == {"changed": False, "restarted": False}
    assert len(runner.cmds) == ncmds  # no further subprocess calls


def test_sync_restarts_via_systemctl(tmp_path):
    c = _db()
    _seed_rewrites(c)
    runner = Runner()
    r = appmod.sync_dnsmasq_panel_conf(
        c, conf_path=str(tmp_path / "openbox-panel.conf"), run=runner, wait_ready=lambda: True)
    assert r["changed"] is True and r["restarted"] is True
    assert r["method"] == "systemctl"
    assert any(cmd[0] == "systemctl" for cmd in runner.cmds)


def test_sync_test_failure_restores_old(tmp_path):
    c = _db()
    _seed_rewrites(c)
    path = tmp_path / "openbox-panel.conf"
    path.write_text("OLD\n")
    runner = Runner(test_rc=1)
    r = appmod.sync_dnsmasq_panel_conf(c, conf_path=str(path), run=runner, wait_ready=lambda: True)
    assert r["changed"] is False and "error" in r
    assert path.read_text() == "OLD\n"
    assert not any(cmd[0] == "systemctl" for cmd in runner.cmds)


def test_sync_no_restart_when_dnsmasq_down(tmp_path):
    c = _db()
    _seed_rewrites(c)
    runner = Runner(running=False)
    r = appmod.sync_dnsmasq_panel_conf(
        c, conf_path=str(tmp_path / "openbox-panel.conf"), run=runner, wait_ready=lambda: True)
    assert r["changed"] is True and r["restarted"] is False
    assert not any(cmd[0] == "systemctl" for cmd in runner.cmds)


def test_sync_systemctl_failure_falls_back(tmp_path):
    c = _db()
    _seed_rewrites(c)
    runner = Runner(systemctl_rc=1)
    r = appmod.sync_dnsmasq_panel_conf(
        c, conf_path=str(tmp_path / "openbox-panel.conf"), run=runner, wait_ready=lambda: True)
    assert r["changed"] is True and r["restarted"] is True
    assert r["method"] == "kill+start"
    assert any(cmd[0] == "pkill" for cmd in runner.cmds)


def test_sync_ready_false_reported(tmp_path):
    c = _db()
    _seed_rewrites(c)
    runner = Runner()
    r = appmod.sync_dnsmasq_panel_conf(
        c, conf_path=str(tmp_path / "openbox-panel.conf"), run=runner,
        wait_ready=lambda: False)
    assert r["changed"] is True and r["restarted"] is True
    assert r["ready"] is False
