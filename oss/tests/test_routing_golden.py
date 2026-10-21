"""路由金标准抽查：用第三方报告 v3 的 81 个 sing-box 路由测例
（panel-contract/routing-golden.json，生成于 1.14.1-openbox-tcp24）
验证 oss/core/penetration.py 的匹配语义。

测例输入是原始 sing-box route rules；本脚本将其转译为穿透模型
（前置规则列表）后调用 penetrate()，比对期望出口。

转译规则：
- 仅 domain / domain_suffix / domain_keyword / ip_cidr 可转译；
- domain_regex、ip_is_private、ip_version、port、port_range、rule_set、
  invert、多条件 AND、显式 and/or 逻辑 → SKIP（穿透模型不支持）；
- 期望命中下标之前的规则若含不支持字段，整例 SKIP（无法证明其不命中）；
  期望命中下标之后的规则不影响首胜结果，可忽略；
- action=reject 的规则转译为 target=reject；
- final 缺失的测例 SKIP（面板恒有兜底出口，不适用）。

用法：python3 oss/tests/test_routing_golden.py
"""
import json
import os
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# 穿透只关心匹配，不做真实 DNS 解析（example.com 等测例域名无需解析）
socket.gethostbyname_ex = lambda host: (host, [], [])  # type: ignore

from core.penetration import penetrate  # noqa: E402

SUPPORTED = {"domain", "domain_suffix", "domain_keyword", "ip_cidr"}


class FakeCfg:
    def __init__(self, front_rules, final):
        self.front_rules = front_rules
        self.site_sets = []
        self.final_outbound = final


def translate(case):
    """返回 (front_rules, skip_reason)。"""
    route = case["input"]["config"].get("route") or {}
    rules = route.get("rules") or []
    expected = case["expected"]
    exp_idx = expected.get("index", 0)
    final = route.get("final")
    if exp_idx == 0 and not final:
        return None, "no final defined (panel always has fallback)"
    front = []
    for i, r in enumerate(rules):
        if exp_idx and i + 1 > exp_idx:
            break  # 首胜之后的规则不影响结果
        if r.get("invert"):
            return None, "invert"
        conds = {k: v for k, v in r.items() if k not in ("outbound", "action", "invert")}
        if not conds:
            return None, "unconditional rule"
        if len(conds) > 1:
            return None, "multi-condition AND " + "+".join(sorted(conds))
        k, vals = next(iter(conds.items()))
        if k not in SUPPORTED:
            return None, "unsupported " + k
        target = "reject" if r.get("action") == "reject" else r.get("outbound", "")
        for v in vals:
            front.append({"rtype": k, "domain": v, "target": target,
                          "note": "", "enabled": True})
    return front, None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    golden = json.load(open(os.path.join(here, "routing-golden.json")))
    cases = golden["cases"]
    n_pass = n_fail = n_skip = 0
    failures = []
    skips = {}
    for case in cases:
        front, reason = translate(case)
        if front is None:
            n_skip += 1
            skips.setdefault(reason, []).append(case["id"])
            continue
        route = case["input"]["config"].get("route") or {}
        final = route.get("final") or "DIRECT"
        res = penetrate(FakeCfg(front, final), case["input"]["target"])
        m = res["matched"]
        exp = case["expected"]
        if exp["action"] == "reject":
            ok = m is not None and m["target"] == "reject"
            got = m["target"] if m else None
        elif exp.get("index", 0) == 0:
            ok = m is not None and m["source"] == "fallback" and m["target"] == exp["outbound"]
            got = f"{m['source']}:{m['target']}" if m else None
        else:
            ok = m is not None and m["source"] == "front" and m["target"] == exp["outbound"]
            got = f"{m['source']}:{m['target']}" if m else None
        if ok:
            n_pass += 1
        else:
            n_fail += 1
            failures.append((case["id"], case["group"], exp["outbound"], got))
    print(f"total={len(cases)} pass={n_pass} fail={n_fail} skip={n_skip}")
    print("--- failures ---")
    for fid, grp, exp, got in failures:
        print(f"  FAIL {fid} [{grp}] expected={exp} got={got}")
    print("--- skips by reason ---")
    for reason, ids in sorted(skips.items(), key=lambda kv: -len(kv[1])):
        print(f"  {reason}: {len(ids)} 例 ({', '.join(ids[:5])}{'...' if len(ids) > 5 else ''})")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
