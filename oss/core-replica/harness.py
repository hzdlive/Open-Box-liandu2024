"""Golden-diff harness for the core replica.

Usage:
    python3 oss/core-replica/harness.py --golden <core-golden.json>
        [--method NAME] [--only-id ID]

Feeds each case's args through main.handle and diffs (ok, value/error)
against the case's expected answer. The golden corpus is NOT in the
repo (35 MB, snapshot of a live install): pass its path explicitly.

Diff reporting masks credential-like keys: for those keys only the
path is reported, never the value. For other keys the first differing
path is reported with short previews.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main as core_main  # noqa: E402

SENSITIVE_KEYS = {
    "password", "passwd", "token", "secret", "uuid", "cert", "tlsCert",
    "privateKey", "private_key", "apiKey", "api_key", "auth", "license",
    "licence", "code", "credential",
}


def _mask(path):
    return any(part in SENSITIVE_KEYS for part in path.split("."))


def _first_diff(a, b, path=""):
    if type(a) is not type(b):
        return path, a, b
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else str(k)
            if k not in a or k not in b:
                return p, a.get(k, "<missing>"), b.get(k, "<missing>")
            d = _first_diff(a[k], b[k], p)
            if d is not None:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return path + ".<len>", len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_diff(x, y, f"{path}[{i}]")
            if d is not None:
                return d
        return None
    if a != b:
        return path, a, b
    return None


def _preview(v):
    if isinstance(v, (dict, list)):
        return f"<{type(v).__name__} len={len(v)}>"
    s = str(v)
    return s if len(s) <= 120 else s[:117] + "..."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", required=True)
    ap.add_argument("--method")
    ap.add_argument("--only-id")
    args = ap.parse_args()
    golden = json.loads(Path(args.golden).read_text())
    cases = golden["cases"]
    if args.method:
        cases = [c for c in cases if c["method"] == args.method]
    if args.only_id:
        cases = [c for c in cases if c["id"] == args.only_id]
    passed = failed = errored = 0
    for case in cases:
        req = {"protocol": 1, "method": case["method"],
               "args": case["args"]}
        got = core_main.handle(json.dumps(req, ensure_ascii=False))
        want_ok = bool(case.get("ok"))
        if got.get("ok") != want_ok:
            errored += 1
            print(f'FAIL {case["id"]} {case["method"]}: ok '
                  f'{got.get("ok")} != {want_ok} '
                  f'(error={got.get("error")!r})')
            continue
        want = case.get("value") if want_ok else case.get("error")
        got_v = got.get("value") if want_ok else got.get("error")
        d = _first_diff(got_v, want)
        if d is None:
            passed += 1
        else:
            failed += 1
            path, gv, wv = d
            if _mask(path):
                print(f'FAIL {case["id"]} {case["method"]}: '
                      f'diff at <masked path>')
            else:
                print(f'FAIL {case["id"]} {case["method"]}: '
                      f'diff at {path}: got {_preview(gv)} '
                      f'want {_preview(wv)}')
    print(f'{passed} passed, {failed} failed, {errored} ok-mismatch, '
          f'{len(cases)} total')
    return 0 if (failed == 0 and errored == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
