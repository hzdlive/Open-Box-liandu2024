#!/usr/bin/env python3
"""Compare Go core outbounds against the Python generator (slice 1).

Usage:
    python3 compare_outbounds.py [--profile fixtures/profile1.json]
                                 [--bin /tmp/oss-core]

Builds the Python AppConfig from the same profile JSON the Go core
reads, runs Python build_outbounds/build_endpoints and Go
debug-outbounds, and diffs them twice: once canonically (sorted keys,
numbers as float) for semantic equality, and once by key order
(Python dict insertion order vs Go emission order) for byte
equivalence. Exit 0 when both match, 1 otherwise, printing the
first difference with its path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "oss"))

from core.models import AppConfig, Chain, DnsConfig, Group, Node, SiteSet  # noqa: E402
from core.singbox import build_endpoints, build_outbounds  # noqa: E402
from compare_lib import canon, compare, key_order  # noqa: E402


def build_python_app(profile: dict) -> AppConfig:
    dns = DnsConfig(**{k: v for k, v in profile.get("dns", {}).items()
                       if k in DnsConfig.__dataclass_fields__})
    return AppConfig(
        nodes=[Node(**{k: v for k, v in n.items()
                       if k in Node.__dataclass_fields__})
               for n in profile.get("nodes", [])],
        site_sets=[SiteSet(**{k: v for k, v in s.items()
                              if k in SiteSet.__dataclass_fields__})
                   for s in profile.get("site_sets", [])],
        groups=[Group(**{k: v for k, v in g.items()
                         if k in Group.__dataclass_fields__})
                for g in profile.get("groups", [])],
        chains=[Chain(**{k: v for k, v in c.items()
                         if k in Chain.__dataclass_fields__})
                for c in profile.get("chains", [])],
        dns=dns,
        subscriptions=profile.get("subscriptions", []),
        speedtest_url=profile.get("speedtest_url", ""),
        routing_fallback=profile.get("routing_fallback", "direct"),
        final_outbound=profile.get("final_outbound", "所有-自动"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(HERE, "fixtures", "profile1.json"))
    ap.add_argument("--bin", default=os.environ.get("OSS_CORE_BIN", "/tmp/oss-core"))
    args = ap.parse_args()

    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)

    app = build_python_app(profile)
    py = {"outbounds": build_outbounds(app), "endpoints": build_endpoints(app)}

    r = subprocess.run([args.bin, "debug-outbounds", "--profile", args.profile],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Go core failed (exit {r.returncode}): {r.stderr.strip()}")
        return 1
    go = json.loads(r.stdout)

    ok = compare(py, go)
    if ok:
        print(f"OK: {len(py['outbounds'])} outbounds, "
              f"{len(py['endpoints'])} endpoints match "
              f"(semantic + key order)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
