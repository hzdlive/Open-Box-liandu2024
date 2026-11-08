#!/usr/bin/env python3
"""Compare Go core route rules against the Python generator (slice 2).

Usage:
    python3 compare_route_rules.py [--profile fixtures/profile2.json]
                                   [--bin /tmp/oss-core]
                                   [--skip-rule-sets geosite-tiktok]

The fixture carries raw inputs; the harness derives the pre-computed
profile fields (terminal expansions, obnode domains/CIDRs) with the
same Python helpers the panel will use, patching the ARP tables and
the DNS resolver to fixed values so the comparison is deterministic.
It then runs Python build_route_rules and Go debug-route-rules and
diffs route rules, DNS rules, provenance and all four side-effect
collections (remote rulesets, obflip rulesets, obnode-direct,
front remote rulesets). A second case strips dns_filter_rulesets to
exercise the route-layer content-filter fallback.
"""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "oss"))

from core import arp as _arp  # noqa: E402
from core import singbox as _sb  # noqa: E402
from core.models import (AppConfig, Chain, DnsConfig, Group, Node,  # noqa: E402
                         SiteSet, TerminalPolicy, TerminalRule)
from core.profile import derive_precomputed  # noqa: E402
from core.singbox import build_route_rules  # noqa: E402
from compare_lib import compare  # noqa: E402

# Fixed ARP / neighbor / DNS evidence for the comparison.
ARP_TABLE = {"192.168.1.50": "aa:bb:cc:dd:ee:ff",
             "192.168.1.60": "11:22:33:44:55:66"}
V6_TABLE = {"2001:db8::50": "aa:bb:cc:dd:ee:ff",
            "2001:db8::60": "11:22:33:44:55:66"}
RESOLVED_IPS = ["198.51.100.1", "198.51.100.2"]


def _fields(cls, d):
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


def build_python_app(profile: dict) -> AppConfig:
    dns = DnsConfig(**_fields(DnsConfig, profile.get("dns", {})))
    return AppConfig(
        nodes=[Node(**_fields(Node, n)) for n in profile.get("nodes", [])],
        site_sets=[SiteSet(**_fields(SiteSet, s))
                   for s in profile.get("site_sets", [])],
        groups=[Group(**_fields(Group, g)) for g in profile.get("groups", [])],
        chains=[Chain(**_fields(Chain, c)) for c in profile.get("chains", [])],
        dns=dns,
        terminals=[TerminalPolicy(**_fields(TerminalPolicy, t))
                   for t in profile.get("terminals", [])],
        terminal_rules=[TerminalRule(**_fields(TerminalRule, t))
                        for t in profile.get("terminal_rules", [])],
        front_rules=profile.get("front_rules", []),
        subscriptions=profile.get("subscriptions", []),
        speedtest_url=profile.get("speedtest_url", ""),
        routing_fallback=profile.get("routing_fallback", "direct"),
        final_outbound=profile.get("final_outbound", "所有-自动"),
        sub_node_direct=profile.get("sub_node_direct", False),
        sub_domains=profile.get("sub_domains", []),
        blocked_domains=profile.get("blocked_domains", []),
        quic_block=profile.get("quic_block", True),
        direct_bypass_enabled=profile.get("direct_bypass_enabled", True),
    )


def derive_profile(profile: dict) -> dict:
    """Fill the pre-computed profile fields the panel will compute.

    Thin wrapper over core.profile.derive_precomputed (one
    implementation shared by the panel and the harness).
    """
    return derive_precomputed(profile)


def run_case(profile: dict, skip: set[str], bin_path: str, label: str) -> bool:
    derived = derive_profile(profile)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(derived, f, ensure_ascii=False)
        tmp = f.name
    try:
        app = build_python_app(profile)
        app._dns_filter_rulesets = profile.get("dns_filter_rulesets", [])
        prov: list = []
        dns_prov: list = []
        rr, dr, gn = build_route_rules(app, skip or None, prov, dns_prov)
        py = {
            "route_rules": rr,
            "dns_rules": dr,
            "provenance": prov,
            "dns_provenance": dns_prov,
            "group_names": sorted(gn),
            "remote_rulesets": [{"tag": t, "url": u}
                                for t, u in getattr(app, "_remote_rulesets", {}).items()],
            "obflip_rulesets": [{"tag": t, "rules": rules}
                                for t, rules in getattr(app, "_obflip_rulesets", {}).items()],
            "obnode_direct": getattr(app, "_obnode_direct", {"domains": [], "cidrs": []}),
            "front_remote_rs": [{"tag": t, "url": u}
                                for t, u in getattr(app, "_front_remote_rs", {}).items()],
        }
        cmd = [bin_path, "debug-route-rules", "--profile", tmp]
        if skip:
            cmd += ["--skip-rule-sets", ",".join(sorted(skip))]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Go core failed ({label}, exit {r.returncode}): {r.stderr.strip()}")
            return False
        go = json.loads(r.stdout)
        ok = compare(py, go, label)
        if ok:
            print(f"OK {label}: {len(rr)} route rules, {len(dr)} dns rules, "
                  f"{len(prov)} provenance records, "
                  f"{len(dns_prov)} dns owners match (semantic + key order)")
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

    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)

    ok = run_case(profile, skip, args.bin, "dns-layer")
    # Second case: no kernel rule sets -> route-layer fallback.
    fallback = copy.deepcopy(profile)
    fallback["dns_filter_rulesets"] = []
    ok = run_case(fallback, skip, args.bin, "fallback") and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
