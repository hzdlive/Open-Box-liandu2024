#!/usr/bin/env python3
"""Compare Go core full config against the Python generator (slice 3).

Usage:
    python3 compare_config.py [--profile fixtures/profile2.json]
                              [--bin /tmp/oss-core]

Reuses compare_route_rules' profile derivation (terminal expansions,
obnode sets) and adds WAN DNS servers. Runs Python build_config and
Go `config` on three cases (base, WAN DNS + split off, region
outside) and diffs the whole config document.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "oss"))

from core import dnstest as _dnstest  # noqa: E402
from core import dnsfilter as _df  # noqa: E402
from core import singbox as _sb  # noqa: E402
from core.models import AppConfig  # noqa: E402
from core.singbox import build_config  # noqa: E402
from compare_lib import compare  # noqa: E402
from compare_route_rules import (ARP_TABLE, RESOLVED_IPS, V6_TABLE,  # noqa: E402
                                 build_python_app, derive_profile)
from core import arp as _arp  # noqa: E402

WAN_SERVERS = ["8.8.8.8", "1.1.1.1"]


def run_case(profile: dict, skip: set[str], bin_path: str,
             workdir: str, label: str) -> bool:
    derived = derive_profile(profile)
    derived["wan_dns_servers"] = list(WAN_SERVERS)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(derived, f, ensure_ascii=False)
        tmp = f.name
    try:
        app = build_python_app(profile)
        # Fields build_python_app does not carry (config-level).
        app.share_lan_enabled = profile.get("share_lan_enabled", False)
        app.share_lan_port = profile.get("share_lan_port", 8088)
        app.share_servers = profile.get("share_servers", [])
        app.tun_stack = profile.get("tun_stack", "mixed")
        app.tun_mtu = profile.get("tun_mtu", 9000)
        app.tun_address = profile.get("tun_address", "172.19.0.1/30")
        app.clash_api_port = profile.get("clash_api_port", 9090)
        app.clash_api_listen = profile.get("clash_api_listen", "127.0.0.1")
        app.clash_api_secret = profile.get("clash_api_secret", "")
        app.dns.split = profile.get("dns", {}).get("split", True)
        app.dns.region = profile.get("dns", {}).get("region", "auto")
        app.dns.region_detected = profile.get("dns", {}).get("region_detected", "")
        app._dns_filter_rulesets = _df.kernel_ruleset_entries(
            workdir, profile.get("blocked_domains", []))
        py = build_config(app, skip or None)
        cmd = [bin_path, "config", "--profile", tmp, "--workdir", workdir]
        if skip:
            cmd += ["--skip-rule-sets", ",".join(sorted(skip))]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Go core failed ({label}, exit {r.returncode}): {r.stderr.strip()}")
            return False
        go = json.loads(r.stdout)
        ok = compare(py, go, label)
        if ok:
            print(f"OK {label}: full config matches "
                  f"({len(py['outbounds'])} outbounds, "
                  f"{len(py['route']['rules'])} route rules, "
                  f"{len(py['dns']['rules'])} dns rules)")
        return ok
    finally:
        os.unlink(tmp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(HERE, "fixtures", "profile2.json"))
    ap.add_argument("--bin", default=os.environ.get("OSS_CORE_BIN", "/tmp/oss-core"))
    ap.add_argument("--skip-rule-sets", default="geosite-tiktok")
    args = ap.parse_args()
    skip = {s for s in args.skip_rule_sets.split(",") if s} if args.skip_rule_sets else set()

    _arp.arp_table = lambda: dict(ARP_TABLE)
    _arp.ipv6_neigh_table = lambda: dict(V6_TABLE)
    _sb.resolve_host_ips = lambda hosts, budget_s=5.0: list(RESOLVED_IPS)
    _dnstest.system_upstreams = lambda: list(WAN_SERVERS)

    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)
    # Share servers + LAN share for the config comparison.
    profile["share_lan_enabled"] = True
    profile["share_lan_port"] = 8088
    profile["share_servers"] = [
        {"enabled": 1, "id": 1, "method": "aes-256-gcm", "password": "sharepw",
         "port": 8389, "protocol": "shadowsocks"},
        {"enabled": 1, "id": 2, "password": "9d8c7b6a-5e4f-3a2b-1c0d-9e8f7a6b5c4d",
         "port": 8443, "protocol": "vless",
         "params": {"flow": "xtls-rprx-vision", "sni": "share.example.com",
                    "cert_path": "/etc/ssl/cert.pem", "key_path": "/etc/ssl/key.pem"}},
        {"enabled": 1, "id": 3, "password": "tuicshare",
         "port": 8444, "protocol": "tuic",
         "params": {"congestion_control": "bbr", "sni": ""}},
        {"enabled": 1, "id": 4, "password": "mixedpw",
         "port": 18080, "protocol": "socks5http",
         "params": {"username": "mixuser"}},
        {"enabled": 0, "id": 5, "password": "offpw",
         "port": 8390, "protocol": "shadowsocks"},
        {"enabled": 1, "id": 6, "password": "hy2share",
         "port": 8445, "protocol": "hysteria2",
         "params": {"sni": "hy.example.com", "obfs": {"password": "o", "type": "salamander"}}},
    ]

    ok = True
    with tempfile.TemporaryDirectory() as workdir:
        os.environ["OBX_GEODATA"] = os.path.join(workdir, "geodata")
        ok = run_case(profile, skip, args.bin, workdir, "base") and ok
        wan = copy.deepcopy(profile)
        wan["dns"]["direct_dns"] = "wan"
        wan["dns"]["split"] = False
        ok = run_case(wan, skip, args.bin, workdir, "wan+split-off") and ok
        outside = copy.deepcopy(profile)
        outside["dns"]["region"] = "outside"
        ok = run_case(outside, skip, args.bin, workdir, "outside") and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
