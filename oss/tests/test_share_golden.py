"""Conformance: share-link parsing against the 43-case golden answers.

Source: third-party report v3's panel-contract/sharelink-golden.json
(vendored here as test data -- behavior-contract answers, not code).
The oracle is the DESKTOP client's Go parser, which supports only
vless, shadowsocks, hysteria2, tuic and socks5; cases it rejects carry
a panel `expect` (accept/reject) transcribed from the panel source.

Comparison:
- oracle emitted, no expect: the generated sing-box outbound
  (node_to_outbound) must contain every oracle.outbound field (subset
  match, recursive for dicts) after removing the case's `ignore` paths.
  Extra fields on our side (defaults like transport tcp, alter_id 0)
  do not fail the case.
- expect == "accept": the link must parse to a node.
- expect == "reject": the link must not parse (covers the
  emitted-but-panel-rejects case invalid-reality-no-pbk too).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.subscription import parse_subscription  # noqa: E402
from core.singbox import node_to_outbound  # noqa: E402


def _strip_ignores(obj, ignore):
    """Remove dotted ignore paths from a nested dict (copy)."""
    import copy
    obj = copy.deepcopy(obj)
    for path in ignore or []:
        parts = path.split(".")
        cur = obj
        for p in parts[:-1]:
            if not isinstance(cur, dict) or p not in cur:
                cur = None
                break
            cur = cur[p]
        if isinstance(cur, dict):
            cur.pop(parts[-1], None)
    return obj


def _subset(expected, actual, trail=""):
    """Recursive subset match: every expected key/value must be in actual."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f"{trail or '<root>'}: expected dict, got {actual!r}"
        for k, v in expected.items():
            if k not in actual:
                return f"{trail}.{k}: missing (expected {v!r})"
            err = _subset(v, actual[k], f"{trail}.{k}")
            if err:
                return err
        return None
    if isinstance(expected, list):
        if actual != expected:
            return f"{trail}: expected {expected!r}, got {actual!r}"
        return None
    if expected != actual:
        return f"{trail}: expected {expected!r}, got {actual!r}"
    return None


def main() -> int:
    golden = json.loads(
        (Path(__file__).resolve().parent / "sharelink-golden.json")
        .read_text(encoding="utf-8"))
    failures = []
    for case in golden["cases"]:
        cid = case["id"]
        nodes = parse_subscription(case["link"])
        node = nodes[0] if nodes else None
        if "expect" in case:
            if case["expect"] == "accept" and node is None:
                failures.append((cid, "expected accept, got reject"))
            elif case["expect"] == "reject" and node is not None:
                failures.append((cid, "expected reject, got node "
                                 f"{node.protocol} {node.server}:{node.server_port}"))
            continue
        # emitted, no expect: outbound subset match
        if node is None:
            failures.append((cid, "expected outbound, got reject"))
            continue
        got = node_to_outbound(node)
        want = _strip_ignores(case["oracle"]["outbound"], case.get("ignore"))
        err = _subset(want, got)
        if err:
            failures.append((cid, err))
    for cid, why in failures:
        print(f"FAIL {cid}: {why}")
    print(f"{len(golden['cases']) - len(failures)}/{len(golden['cases'])} pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
