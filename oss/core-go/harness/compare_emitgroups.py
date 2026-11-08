#!/usr/bin/env python3
"""Compare Go emitGroups against the Python generator (slice 4).

Usage:
    python3 compare_emitgroups.py [--profile fixtures/profile2.json]
                                  [--bin /tmp/oss-core]

Go emitGroups = {builtin labels, groups: the group-derived outbounds}.
The Python expected value is the same slice of build_outbounds output
(nodes + chains first, then the group part).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "oss"))

from core.singbox import build_outbounds  # noqa: E402
from compare_lib import compare  # noqa: E402
from compare_route_rules import build_python_app, derive_profile  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(HERE, "fixtures", "profile2.json"))
    ap.add_argument("--bin", default=os.environ.get("OSS_CORE_BIN", "/tmp/oss-core"))
    args = ap.parse_args()

    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)
    derived = derive_profile(profile)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(derived, f, ensure_ascii=False)
        tmp = f.name
    try:
        app = build_python_app(profile)
        py_out = build_outbounds(app)
        prefix = sum(1 for n in app.nodes if n.protocol != "wireguard") + len(app.chains)
        py_groups = py_out[prefix:]
        py = {
            "builtin": {
                "direct": "直连", "directEnabled": True,
                "block": "拒绝", "blockEnabled": True,
            },
            "groups": py_groups,
        }
        r = subprocess.run([args.bin, "emitGroups", "--profile", tmp],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Go emitGroups failed: {r.stderr.strip()}")
            return 1
        go = json.loads(r.stdout)
        ok = compare(py, go, "emitGroups")
        if ok:
            print(f"OK emitGroups: {len(py_groups)} group outbounds match")
        return 0 if ok else 1
    finally:
        os.unlink(tmp)


if __name__ == "__main__":
    sys.exit(main())
