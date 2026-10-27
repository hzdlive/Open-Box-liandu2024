"""Tests for the one-click diagnostics support bundle
(GET /api/openbox/diagnostics, original-panel shape).

Shape keys come from the third-party contract's live-captured response
shapes; desensitization order (secrets before hosts) is the contract's
stated rule.
"""

import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import support_bundle as sb
from panel import db as dbmod


class FakeManager:
    def __init__(self, workdir):
        self.workdir = workdir
        self.log_path = os.path.join(workdir, "sing-box.log")

    def to_dict(self):
        return {"running": True, "installed": True, "version": "1.14.1-test",
                "uptime_s": 60, "bin_path": "/usr/local/bin/sing-box",
                "autostart": False}


class RaisingManager(FakeManager):
    def to_dict(self):
        raise RuntimeError("manager exploded")


def _fresh_db():
    path = tempfile.mktemp(suffix=".db")
    c = sqlite3.connect(path)
    dbmod.init_db(c)
    c.close()
    return path


def _setup(tmp):
    """DB + workdir with a config containing a secret-bearing outbound."""
    dbfile = _fresh_db()
    conn = sqlite3.connect(dbfile)
    conn.execute(
        "INSERT INTO subscriptions (name, url, created_at) VALUES (?, ?, ?)",
        ("sub", "https://sub.example.com/link?token=tok-123456",
         "2026-10-27 00:00:00"))
    conn.execute(
        "INSERT INTO nodes (sub_id, tag, protocol, server, port, params) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        ("node1", "shadowsocks", "node.example.com", 8388,
         json.dumps({"password": "pw-example.com-9", "method": "aes-256-gcm"})))
    conn.execute(
        "INSERT INTO site_sets (name, action, flip) VALUES (?, ?, ?)",
        ("yt", "proxy", "direct"))
    conn.execute(
        "INSERT INTO front_rules (domain, rtype, target) VALUES (?, ?, ?)",
        ("example.org", "domain_suffix", "proxy"))
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("openbox_deploy_state", json.dumps({
            "ok": True, "stage": "ok", "at": "2026-10-27 12:00:00",
            "dns_upstream_routes": ["route-a"]})))
    conn.commit()
    workdir = tempfile.mkdtemp(dir=tmp)
    cfg = {
        "log": {"level": "info"},
        "inbounds": [{"type": "tun", "tag": "tun-in", "auto_redirect": True},
                     {"type": "mixed", "tag": "mixed-in"}],
        "outbounds": [
            {"type": "shadowsocks", "tag": "node1",
             "server": "node.example.com", "server_port": 8388,
             "password": "pw-example.com-9", "method": "aes-256-gcm"},
            {"type": "direct", "tag": "direct"}],
        "route": {"rules": []},
    }
    with open(os.path.join(workdir, "config.json"), "w") as f:
        json.dump(cfg, f)
    with open(os.path.join(workdir, "sing-box.log"), "w") as f:
        f.write("kernel started\n")
    return conn, workdir


def test_shape_keys(tmp_path):
    conn, workdir = _setup(str(tmp_path))
    b = sb.collect(conn, FakeManager(workdir), workdir)
    assert set(b.keys()) == {"format", "generatedAt", "dnsPort53", "kernel",
                             "lastDeploy", "logs", "settings", "system",
                             "versions"}
    assert set(b["kernel"].keys()) == {"config", "configMeta", "flip",
                                       "nftTables", "processes", "status"}
    assert set(b["settings"].keys()) == {
        "bypassPorts", "bypassPortsMode", "bypassPortsWhitelist",
        "clientRoutes", "directBypass", "directForNodes", "dns", "ipv6",
        "rejectQuic", "routing", "tun"}
    assert set(b["lastDeploy"].keys()) == {"at", "badTags", "message", "stage"}
    assert set(b["logs"].keys()) == {"kernel", "panel"}
    assert set(b["system"].keys()) == {"arch", "board", "conflictingPlugins",
                                       "disk", "memAvailable", "memTotal",
                                       "nodePreload", "tunDevice",
                                       "uptimeSeconds"}
    assert set(b["versions"].keys()) == {"builtAt", "node", "openBox",
                                         "singBox"}
    assert b["lastDeploy"]["stage"] == "ok"
    assert b["lastDeploy"]["at"] > 0
    assert b["kernel"]["configMeta"]["dnsUpstreamRoutes"] == ["route-a"]
    assert b["kernel"]["configMeta"]["autoRedirect"] is True
    assert "yt" in b["kernel"]["flip"]["bypass"]
    assert any(p["domain"] == "example.org"
               for p in b["settings"]["routing"]["policies"])


def test_desensitization_secrets_before_hosts(tmp_path):
    conn, workdir = _setup(str(tmp_path))
    b = sb.collect(conn, FakeManager(workdir), workdir)
    text = json.dumps(b["kernel"]["config"], ensure_ascii=False)
    # The password itself is gone, including its hostname-looking part:
    # secrets-first means no "pw-" fragment survives host scrubbing.
    assert "pw-example.com-9" not in text
    assert "pw-" not in text
    # Node server hostname and subscription token host are scrubbed.
    assert "node.example.com" not in text
    assert "sub.example.com" not in text
    assert "tok-123456" not in text
    # Tags (non-secret identifiers) survive.
    assert "node1" in text
    assert b["kernel"]["config"]["outbounds"][0]["server"] == "[host]"


def test_probe_failure_is_text_not_500(tmp_path, monkeypatch):
    import subprocess
    conn, workdir = _setup(str(tmp_path))

    def boom(*a, **k):
        raise OSError("no such tool")
    monkeypatch.setattr(subprocess, "run", boom)
    b = sb.collect(conn, FakeManager(workdir), workdir)
    assert isinstance(b["kernel"]["nftTables"], str)
    assert b["kernel"]["nftTables"].startswith("command failed")
    assert b["dnsPort53"] == []


def test_assembly_failure_raises(tmp_path):
    conn, workdir = _setup(str(tmp_path))
    try:
        sb.collect(conn, RaisingManager(workdir), workdir)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected collect to raise on manager failure")


def test_ss_listen_parses_local_not_peer():
    sample = (
        "State  Recv-Q Send-Q  Local Address:Port  Peer Address:Port\n"
        "LISTEN 0      32      0.0.0.0:53         0.0.0.0:*   \n"
        "LISTEN 0      32      [::]:53            [::]:*   \n"
        "LISTEN 0      4096    127.0.0.1:2080      0.0.0.0:*   \n"
        "LISTEN 0      4096    [fd7a:115c:a1e0::1]%tailscale0:35480  [::]:*   \n"
    )
    assert sb._parse_ss_listen(sample) == ["0.0.0.0:53", "[::]:53"]


def test_missing_config_still_collects(tmp_path):
    conn, workdir = _setup(str(tmp_path))
    os.remove(os.path.join(workdir, "config.json"))
    b = sb.collect(conn, FakeManager(workdir), workdir)
    assert b["kernel"]["config"] == {}
    assert b["kernel"]["configMeta"]["routingHash"] == ""
