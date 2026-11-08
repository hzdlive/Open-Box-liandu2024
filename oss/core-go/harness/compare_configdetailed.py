#!/usr/bin/env python3
"""Compare Go configDetailed against the Python generator (slice 4).

Usage:
    python3 compare_configdetailed.py [--profile fixtures/profile2.json]
                                      [--bin /tmp/oss-core]

Go configDetailed = {config, directHosts, dnsRuleOwners, failover}.
The Python expected value is built from build_config (config),
the obnode sets (directHosts), a provenance-carrying
build_route_rules call (dnsRuleOwners), and the enabled failover
groups (failover).
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

from core import arp as _arp  # noqa: E402
from core import dnstest as _dnstest  # noqa: E402
from core import dnsfilter as _df  # noqa: E402
from core import singbox as _sb  # noqa: E402
from core.failover_sm import lane_display_name  # noqa: E402
from core.singbox import build_config, build_route_rules  # noqa: E402
from compare_lib import compare  # noqa: E402
from compare_route_rules import (ARP_TABLE, RESOLVED_IPS, V6_TABLE,  # noqa: E402
                                 build_python_app, derive_profile)
from compare_config import WAN_SERVERS  # noqa: E402


def python_failover(app) -> list[dict]:
    node_tags = [n.tag for n in app.nodes]
    chain_tags = [c.name for c in app.chains]
    out = []
    for g in app.groups or []:
        if g.type != "failover" or not (g.enabled if g.enabled is not None else True):
            continue
        lanes = []
        for i, ln in enumerate(g.lanes or []):
            members = [m for m in (ln.get("members") or [])
                       if m in node_tags or m in chain_tags]
            lanes.append({"name": lane_display_name(
                {"name": ln.get("name")}, i), "members": members,
                "mode": ln.get("mode") or "auto"})
        out.append({"name": g.name, "lanes": lanes})
    return out


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
    profile["share_lan_enabled"] = True
    profile["share_lan_port"] = 8088
    profile["share_servers"] = []

    ok = True
    with tempfile.TemporaryDirectory() as workdir:
        os.environ["OBX_GEODATA"] = os.path.join(workdir, "geodata")
        derived = derive_profile(profile)
        derived["wan_dns_servers"] = list(WAN_SERVERS)
        derived["dns_filter_rulesets"] = [
            {"tag": e["tag"], "path": e["path"]} for e in
            _df.kernel_ruleset_entries(workdir, profile.get("blocked_domains", []))]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(derived, f, ensure_ascii=False)
            tmp = f.name
        try:
            app = build_python_app(profile)
            app.share_lan_enabled = True
            app.share_lan_port = 8088
            app.share_servers = []
            app.dns.split = profile.get("dns", {}).get("split", True)
            app._dns_filter_rulesets = [
                {"tag": e["tag"], "path": e["path"]} for e in
                _df.kernel_ruleset_entries(workdir, profile.get("blocked_domains", []))]
            prov, dns_prov = [], []
            build_route_rules(app, skip or None, prov, dns_prov)
            py_config = build_config(app, skip or None)
            py = {
                "config": py_config,
                "directHosts": {
                    "cidrs": app._obnode_direct["cidrs"],
                    "domains": app._obnode_direct["domains"],
                },
                "dnsRuleOwners": dns_prov,
                "failover": python_failover(app),
            }
            cmd = [args.bin, "configDetailed", "--profile", tmp, "--workdir", workdir]
            if skip:
                cmd += ["--skip-rule-sets", ",".join(sorted(skip))]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"Go configDetailed failed: {r.stderr.strip()}")
                return 1
            go = json.loads(r.stdout)
            ok = compare(py, go, "configDetailed")
            if ok:
                print(f"OK configDetailed: config + directHosts "
                      f"({len(py['directHosts']['domains'])} domains, "
                      f"{len(py['directHosts']['cidrs'])} cidrs) + "
                      f"{len(dns_prov)} dns owners + "
                      f"{len(py['failover'])} failover groups match")
        finally:
            os.unlink(tmp)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
