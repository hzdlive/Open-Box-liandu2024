"""CIDR deduction for nft entry-bypass sets (v6 #15 native-bypass 对照).

v6 的 native-bypass 给每个旁路集合算三个扣减，按顺序：
地址空间末尾一位（255.255.255.255 / ffff:…:ffff，某些内核上放进集合
会让整段命中）→ FakeIP 池（入口放行它等于真实目标永远不被解析）
→ 前面集合已覆盖的部分；扣完不剩是回落不是空集合。

本模块是该语义在我们 nft 脚本生成上的实现：

- 扣减 1（末尾地址）：把 255.255.255.255/32 与 ffff:…:ffff/128 从
  同族网络里减掉。含末尾地址的大网段用 address_exclude 切开
  （如 0.0.0.0/0 切后不再含 .255），而不是整段丢弃。
- 扣减 2（FakeIP 池）：198.19.0.0/16 与 fc00::/18。这两个值必须与
  singbox.py 里 dns-fakeip 的 inet4_range / inet6_range 保持一致
  （那边定义池子，这边排除池子；改一边必须改另一边）。
- 扣减 3（前面集合）：减掉在同一条链里排在前面的静态集合
  （bypass4/bypass6、私网终端放行集，以及 entry 集前面的
  direct_ip 结果）。动态集（dnsmasq 填充的 direct4、direct-answer）
  生成时内容未知，无法静态扣减，不在此列。
- 扣完：collapse 合并相邻网段、排序、去重。扣完不剩时调用方
  不生成该集合（流量进内核，即安全回落），并以 notes 说明。

v6 侧注意：v4 与 v6 分开扣减、分开返回。脚本目前没有 v6
prerouting 链（v6 只有 bypass6 定义、无引用规则），所以 v6 结果
只报告、不写进任何 ipv4_addr 集合——以前 v6 CIDR 会直接混进
ipv4_addr 集导致整条脚本加载失败，这是本项顺带堵住的潜伏 bug。

CIDR 减法利用前缀块的性质：任意两个前缀块要么不交、要么一个
包含另一个，所以减法只有三种情况（被含则整段丢、含对方则
address_exclude 切开、不交则保留），无需通用区间运算。
"""

from __future__ import annotations

import ipaddress

LAST_V4 = ipaddress.ip_network("255.255.255.255/32")
LAST_V6 = ipaddress.ip_network("ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff/128")
# Must match singbox.py dns-fakeip inet4_range / inet6_range.
FAKEIP_V4 = ipaddress.ip_network("198.19.0.0/16")
FAKEIP_V6 = ipaddress.ip_network("fc00::/18")


def parse(cidrs) -> tuple[list, list, int]:
    """Split raw strings into (v4 nets, v6 nets, invalid count)."""
    v4, v6, invalid = [], [], 0
    for s in cidrs or []:
        try:
            n = ipaddress.ip_network(str(s).strip(), strict=False)
        except ValueError:
            invalid += 1
            continue
        (v4 if n.version == 4 else v6).append(n)
    return v4, v6, invalid


def _stage(nets: list, subs: list) -> tuple[list, int]:
    """Subtract subs from nets; return (remaining, affected net count)."""
    affected = 0
    for sub in subs:
        step = []
        for n in nets:
            if n.version == sub.version and (
                    sub.subnet_of(n) or n.subnet_of(sub)):
                affected += 1
                if sub.subnet_of(n):
                    step.extend(n.address_exclude(sub))
                # else n is fully inside sub -> dropped
            else:
                step.append(n)
        nets = step
    return nets, affected


def deduct(cidrs, *, fakeip: bool = True, earlier=()) -> dict:
    """Apply the three deductions in v6 order.

    Returns {"v4": [str], "v6": [str], "removed": {...}, "empty": bool}.
    "removed" counts networks affected per stage (a split network counts
    once, even though it yields several pieces).
    """
    v4, v6, invalid = parse(cidrs)
    ev4, ev6, _ = parse(earlier)
    removed = {"invalid": invalid, "last_address": 0, "fakeip": 0, "earlier": 0}
    v4, n = _stage(v4, [LAST_V4])
    v6, m = _stage(v6, [LAST_V6])
    removed["last_address"] = n + m
    if fakeip:
        v4, n = _stage(v4, [FAKEIP_V4])
        v6, m = _stage(v6, [FAKEIP_V6])
        removed["fakeip"] = n + m
    v4, n = _stage(v4, ev4)
    v6, m = _stage(v6, ev6)
    removed["earlier"] = n + m
    v4 = sorted(ipaddress.collapse_addresses(v4))
    v6 = sorted(ipaddress.collapse_addresses(v6))
    return {"v4": [str(n) for n in v4], "v6": [str(n) for n in v6],
            "removed": removed, "empty": not v4 and not v6}


def note_line(name: str, total_in: int, result: dict) -> str:
    """One-line ';' style note for a deducted set (v6 reason 用 ';' 拼)."""
    r = result["removed"]
    parts = [f"输入 {total_in} 条"]
    if r["invalid"]:
        parts.append(f"非法 {r['invalid']} 条")
    if r["last_address"]:
        parts.append(f"末尾地址扣减 {r['last_address']} 条")
    if r["fakeip"]:
        parts.append(f"FakeIP 池扣减 {r['fakeip']} 条")
    if r["earlier"]:
        parts.append(f"已被前面集合覆盖 {r['earlier']} 条")
    parts.append(f"剩余 v4 {len(result['v4'])} 条")
    if result["v6"]:
        parts.append(f"v6 {len(result['v6'])} 条未生成规则")
    if result["empty"] and total_in:
        parts.append("扣减后无剩余，相关流量进内核（回落）")
    return f"{name}：" + ";".join(parts)
