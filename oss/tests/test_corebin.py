"""Core binary client (oss/core/corebin.py) + profile serialization.

A fake core binary (a small script) pins the client logic: handshake
validation, loud failures (no silent fallback), and the profile
document passed to the binary. A real-binary test runs only when a
binary is available (OBX_CORE_BIN or oss-core on PATH) and compares
the core output with the in-process Python generator.
"""

import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import corebin  # noqa: E402
from core.models import AppConfig, DnsConfig, Group, Node  # noqa: E402
from core.profile import app_config_to_profile  # noqa: E402
from core.singbox import build_config  # noqa: E402

FAKE_SCRIPT = '''#!/usr/bin/env python3
import json, os, sys
mode = os.environ.get("FAKE_CORE_MODE", "ok")
cmd = sys.argv[1]
if cmd == "version":
    if mode == "bad-json":
        print("not json")
        sys.exit(0)
    hs = {"name": "oss-core", "version": "0.1.0", "singbox": "1.14.1",
          "methods": ["emitGroups", "configDetailed", "config"]}
    if mode == "wrong-singbox":
        hs["singbox"] = "1.13.0"
    if mode == "missing-methods":
        hs["methods"] = ["config"]
    if mode == "wrong-name":
        hs["name"] = "other-core"
    print(json.dumps(hs))
    sys.exit(0)
if mode == "fail-config" and cmd in ("config", "configDetailed"):
    print("boom", file=sys.stderr)
    sys.exit(3)
profile = {}
workdir = ""
for i, a in enumerate(sys.argv):
    if a == "--profile":
        profile = json.load(open(sys.argv[i + 1]))
    if a == "--workdir":
        workdir = sys.argv[i + 1]
if cmd == "config":
    print(json.dumps({"outbounds": [{"tag": n["tag"]} for n in profile.get("nodes", [])],
                      "workdir": workdir,
                      "blocked": len(profile.get("blocked_domains") or [])}))
elif cmd == "configDetailed":
    print(json.dumps({"config": {"outbounds": []},
                      "directHosts": {"cidrs": [], "domains": []},
                      "dnsRuleOwners": [], "failover": []}))
elif cmd == "emitGroups":
    print(json.dumps({"builtin": {"direct": "直连"}, "groups": []}))
else:
    print("unknown", file=sys.stderr)
    sys.exit(2)
'''


def _fake_bin(tmp_path, mode="ok"):
    p = tmp_path / "oss-core"
    p.write_text(FAKE_SCRIPT, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


def _cfg():
    return AppConfig(
        nodes=[Node(tag="n1", protocol="vless", server="example.com",
                    server_port=443, params={})],
        groups=[Group(name="g1", type="selector", members=["n1"])],
        dns=DnsConfig(),
    )


def test_handshake_ok(tmp_path):
    hs = corebin.handshake(_fake_bin(tmp_path))
    assert hs["name"] == "oss-core" and hs["singbox"] == "1.14.1"
    assert "config" in hs["methods"]


def test_handshake_rejects_mismatch(tmp_path, monkeypatch):
    for mode in ("wrong-singbox", "missing-methods", "wrong-name", "bad-json"):
        monkeypatch.setenv("FAKE_CORE_MODE", mode)
        with pytest.raises(corebin.CoreError):
            corebin.handshake(_fake_bin(tmp_path))
    monkeypatch.delenv("FAKE_CORE_MODE", raising=False)


def test_handshake_missing_binary(tmp_path):
    with pytest.raises(corebin.CoreError):
        corebin.handshake(str(tmp_path / "no-such-binary"))


def test_build_config_via_core_passes_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CORE_MODE", "ok")
    cfg = _cfg()
    cfg.blocked_domains = ["a.example.com", "b.example.com"]
    out = corebin.build_config_via_core(cfg, "/tmp/wd", set(),
                                        _fake_bin(tmp_path))
    assert [o["tag"] for o in out["outbounds"]] == ["n1"]
    assert out["workdir"] == "/tmp/wd"
    assert out["blocked"] == 2


def test_build_config_via_core_failure_is_loud(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CORE_MODE", "fail-config")
    with pytest.raises(corebin.CoreError, match="exit 3"):
        corebin.build_config_via_core(_cfg(), "/tmp/wd", set(),
                                      _fake_bin(tmp_path))


def test_find_core_bin_prefers_env(tmp_path, monkeypatch):
    fake = _fake_bin(tmp_path)
    monkeypatch.setenv("OBX_CORE_BIN", fake)
    assert corebin.find_core_bin() == fake
    monkeypatch.delenv("OBX_CORE_BIN")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert corebin.find_core_bin() == fake


def test_build_config_auto_falls_back_without_binary(monkeypatch):
    # No binary configured anywhere: the Python generator is used.
    monkeypatch.delenv("OBX_CORE_BIN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert corebin.find_core_bin() is None
    cfg = _cfg()
    assert corebin.build_config_auto(cfg, "/tmp/wd", set()) == \
        build_config(cfg, set())


def test_build_config_auto_uses_core_when_configured(tmp_path, monkeypatch):
    fake = _fake_bin(tmp_path)
    monkeypatch.setenv("OBX_CORE_BIN", fake)
    monkeypatch.setenv("FAKE_CORE_MODE", "ok")
    out = corebin.build_config_auto(_cfg(), "/tmp/wd", set())
    # The fake core's shape, not the Python generator's.
    assert out == {"outbounds": [{"tag": "n1"}], "workdir": "/tmp/wd",
                   "blocked": 0}


def test_preview_config_auto_uses_detailed(tmp_path, monkeypatch):
    fake = _fake_bin(tmp_path)
    monkeypatch.setenv("OBX_CORE_BIN", fake)
    monkeypatch.setenv("FAKE_CORE_MODE", "ok")
    out = corebin.preview_config_auto(_cfg(), "/tmp/wd", set())
    assert out == {"outbounds": []}


def test_app_config_to_profile(tmp_path, monkeypatch):
    # WAN DNS + terminal/obnode derivation land in the profile.
    monkeypatch.setattr("core.profile._dnstest.system_upstreams",
                        lambda: ["8.8.8.8"])
    monkeypatch.setattr("core.profile._arp.expand_terminal_idents",
                        lambda idents: [f"{i}/32" for i in idents])
    monkeypatch.setattr("core.profile._arp.expand_terminal_supplement_v6",
                        lambda idents: [])
    monkeypatch.setattr("core.profile._sb.resolve_host_ips",
                        lambda hosts, budget_s=5.0: ["93.184.216.34"])
    cfg = _cfg()
    cfg.sub_node_direct = True
    cfg.sub_domains = ["sub.example.com"]
    cfg.terminals = [type("T", (), {"ident": "192.168.1.50",
                                    "policy": "direct"})()]
    # TerminalPolicy is a dataclass; build it properly.
    from core.models import TerminalPolicy
    cfg.terminals = [TerminalPolicy(ident="192.168.1.50", policy="direct")]
    prof = app_config_to_profile(cfg, "/tmp/wd")
    assert prof["wan_dns_servers"] == ["8.8.8.8"]
    assert prof["terminal_direct_cidrs"] == ["192.168.1.50/32"]
    assert prof["terminal_direct_v6"] == []
    assert prof["obnode_domains"] == ["example.com", "sub.example.com"]
    assert prof["obnode_cidrs"] == ["93.184.216.34/32"]
    assert prof["dns_filter_rulesets"] == []
    assert prof["nodes"][0]["tag"] == "n1"
    assert prof["dns"]["direct_dns"] == "223.5.5.5"


def test_real_binary_matches_python():
    """End-to-end: the real core binary vs the Python generator.

    Skipped when no binary is available (OBX_CORE_BIN or oss-core on
    PATH). Run with OBX_CORE_BIN=/tmp/oss-core to exercise it.
    """
    bin_path = os.environ.get("OBX_CORE_BIN") or shutil.which("oss-core")
    if not bin_path:
        pytest.skip("no oss-core binary available")
    cfg = _cfg()
    cfg.sub_node_direct = True
    cfg.sub_domains = ["sub.example.com"]
    go = corebin.build_config_via_core(cfg, "/tmp/wd", set(), bin_path)
    py = build_config(cfg, set())
    assert go == py
