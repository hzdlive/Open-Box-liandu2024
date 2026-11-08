#!/usr/bin/env python3
"""Live-DB comparison for the Go core (runs ON the target machine).

Dumps the live panel.db AppConfig to a profile, runs Python
build_config and Go `config`, compares them, compares the
dns-filter files, and runs `sing-box check` on the Go output.
The profile holds node credentials and never leaves the machine;
only the comparison summary is printed.

Usage on the VPS (repo venv):
  PYTHONPATH=/root/openbox-zashboard/oss OBX_DB=<datadir>/panel.db \
    /root/.venv-openbox/bin/python /tmp/live_compare.py \
    --bin /tmp/oss-core --workdir <datadir>
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

# compare_lib + compare_route_rules live next to this script (/tmp).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import dnstest as _dnstest  # noqa: E402
from core import dnsfilter as _df  # noqa: E402
from core import geodata as _gd  # noqa: E402
from core.singbox import build_config  # noqa: E402
from panel import db as dbmod  # noqa: E402
from compare_lib import compare  # noqa: E402
from compare_route_rules import derive_profile  # noqa: E402


def read_files(workdir: str) -> dict[str, bytes]:
    base = os.path.join(workdir, "dns-filter")
    if not os.path.isdir(base):
        return {}
    return {f: open(os.path.join(base, f), "rb").read()
            for f in sorted(os.listdir(base))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--skip-rule-sets", default="")
    args = ap.parse_args()
    workdir = args.workdir
    db_path = os.path.join(workdir, "panel.db")

    conn = sqlite3.connect(db_path)
    try:
        app = dbmod.load_app_config(conn, with_blocked_domains=True)
    finally:
        conn.close()
    blocked = list(app.blocked_domains or [])
    print(f"live: {len(app.nodes)} nodes, {len(app.chains)} chains, "
          f"{len(app.groups)} groups, {len(app.site_sets)} site sets, "
          f"{len(app.front_rules)} front rules, {len(blocked)} blocked domains")

    profile = dataclasses.asdict(app)
    profile["wan_dns_servers"] = list(_dnstest.system_upstreams())
    profile["dns_filter_rulesets"] = [
        {"tag": e["tag"], "path": e["path"]} for e in
        _df.kernel_ruleset_entries(workdir, blocked)]
    profile = derive_profile(profile)

    if args.skip_rule_sets:
        skip = {s for s in args.skip_rule_sets.split(",") if s}
    else:
        names = _gd.referenced_rule_sets(app)
        skip = {n for n in names if not _gd.is_available(n, db_path)}
    print(f"live: skip rule sets: {sorted(skip) or 'none'}")

    app._dns_filter_rulesets = _df.kernel_ruleset_entries(workdir, blocked)
    py = build_config(app, skip or None)

    prof_path = "/tmp/live-profile.json"
    with open(prof_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False,
                  default=lambda v: sorted(v) if isinstance(v, set) else str(v))
    cmd = [args.bin, "config", "--profile", prof_path, "--workdir", workdir]
    if skip:
        cmd += ["--skip-rule-sets", ",".join(sorted(skip))]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL: Go config failed (exit {r.returncode}): {r.stderr.strip()}")
        return 1
    go = json.loads(r.stdout)
    ok = compare(py, go, "live")
    if ok:
        print(f"OK live: full config matches ({len(py['outbounds'])} outbounds, "
              f"{len(py['route']['rules'])} route rules, "
              f"{len(py['dns']['rules'])} dns rules)")

    # dns-filter files: Go wrote them to the live dir; Python writes
    # the same content to a temp dir for a byte comparison.
    with tempfile.TemporaryDirectory() as td:
        _df.write_kernel_rulesets(td, blocked, None)
        py_files = read_files(td)
    go_files = read_files(workdir)
    if py_files != go_files:
        diff = [k for k in set(py_files) | set(go_files)
                if py_files.get(k) != go_files.get(k)]
        print(f"FAIL live: dns-filter files differ: {diff}")
        ok = False
    else:
        print(f"OK live: {len(go_files)} dns-filter files byte-identical")

    # sing-box check on the Go output (the real kernel binary).
    go_cfg_path = "/tmp/live-config-go.json"
    with open(go_cfg_path, "w", encoding="utf-8") as f:
        json.dump(go, f, ensure_ascii=False)
    chk = subprocess.run(["/usr/local/bin/sing-box", "check", "-c", go_cfg_path],
                         capture_output=True, text=True)
    if chk.returncode != 0:
        print(f"FAIL live: sing-box check on Go config: "
              f"{(chk.stderr or chk.stdout).strip()[:500]}")
        ok = False
    else:
        print("OK live: sing-box check passed on the Go config")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
