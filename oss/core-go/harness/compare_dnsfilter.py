#!/usr/bin/env python3
"""Compare Go dnsfilter rule-set writing against Python (slice 4).

Usage:
    python3 compare_dnsfilter.py [--bin /tmp/oss-core]

Builds a 60,001-domain blocklist (3 shards of 25,000) plus an allow
list, runs Python write_kernel_rulesets and Go `debug-dnsfilter` in
two workdirs, and compares the entries (tags + relative paths) and
every file's bytes. Also checks the empty-blocklist case (allow
sentinel only) and idempotency (a second run rewrites nothing).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "oss"))

from core import dnsfilter as _df  # noqa: E402


def domains(n: int) -> list[str]:
    out = [f"domain{i:05d}.example.com" for i in range(n)]
    # Normalization edge cases: dupes, case, leading/trailing dots.
    out += ["DOMAIN00000.EXAMPLE.COM", ".domain00001.example.com.",
            "domain00002.example.com", "ads.tracker.net"]
    return out


def snapshot(workdir: str) -> dict[str, bytes]:
    base = os.path.join(workdir, "dns-filter")
    if not os.path.isdir(base):
        return {}
    return {f: open(os.path.join(base, f), "rb").read()
            for f in sorted(os.listdir(base))}


def mtimes(workdir: str) -> dict[str, float]:
    base = os.path.join(workdir, "dns-filter")
    if not os.path.isdir(base):
        return {}
    return {f: os.path.getmtime(os.path.join(base, f))
            for f in sorted(os.listdir(base))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=os.environ.get("OSS_CORE_BIN", "/tmp/oss-core"))
    args = ap.parse_args()

    ok = True
    for label, blocked, allow in (
        ("3-shards", domains(60001), ["safe.example.org", "cdn.example.net", "ok.example.com"]),
        ("empty-block", [], []),
        ("one-shard-no-allow", domains(12), []),
    ):
        with tempfile.TemporaryDirectory() as wa, tempfile.TemporaryDirectory() as wb:
            py_entries = _df.write_kernel_rulesets(wa, blocked, allow or None)
            py_files = snapshot(wa)
            py_mt = mtimes(wa)
            time.sleep(0.01)
            _df.write_kernel_rulesets(wa, blocked, allow or None)
            if mtimes(wa) != py_mt:
                print(f"FAIL {label}: Python second run rewrote files")
                ok = False

            profile = {"blocked_domains": blocked, "allow_domains": allow}
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(profile, f)
                tmp = f.name
            try:
                r = subprocess.run([args.bin, "debug-dnsfilter",
                                    "--profile", tmp, "--workdir", wb],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    print(f"FAIL {label}: Go failed: {r.stderr.strip()}")
                    ok = False
                    continue
                go_entries = json.loads(r.stdout)["entries"]
            finally:
                os.unlink(tmp)
            go_files = snapshot(wb)
            go_mt = mtimes(wb)
            time.sleep(0.01)
            # Second Go run: reuse the same profile via a fresh temp file.
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(profile, f)
                tmp2 = f.name
            r = subprocess.run([args.bin, "debug-dnsfilter",
                                "--profile", tmp2, "--workdir", wb],
                               capture_output=True, text=True)
            os.unlink(tmp2)
            if mtimes(wb) != go_mt:
                print(f"FAIL {label}: Go second run rewrote files")
                ok = False

            py_rel = [(e["tag"], os.path.relpath(e["path"], wa)) for e in py_entries]
            go_rel = [(e["tag"], os.path.relpath(e["path"], wb)) for e in go_entries]
            if py_rel != go_rel:
                print(f"FAIL {label}: entries differ\n  py: {py_rel}\n  go: {go_rel}")
                ok = False
            elif py_files != go_files:
                diff = [k for k in py_files if py_files.get(k) != go_files.get(k)]
                print(f"FAIL {label}: file bytes differ: {diff}")
                ok = False
            else:
                total = sum(len(v) for v in py_files.values())
                print(f"OK {label}: {len(py_files)} files, {total} bytes, "
                      f"entries match, idempotent")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
