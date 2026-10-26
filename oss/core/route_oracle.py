"""路由预言机：预测一次流量会命中哪条内置规则、走哪条出口链、DNS 走哪台服务器。

对标原版 POST /api/openbox/penetration 的公开行为（第三方报告 v8 #33），
但规则表不手写：直接取 ``core.singbox.build_route_rules`` 的输出——
预言机评估的是 build_config 将要生成的规则，顺序与内核一致
（逻辑旁路 → 终端 → 前置 → 订阅节点直连 → QUIC 拦截 → 站点集 →
内容过滤 → 兜底），命中规则用 provenance 映射回前置/站点集/内置项。

与旧版 ``core.penetration.penetrate``（前置→站点集→兜底三段字面匹配）
相比，预言机补齐的维度：
- 目标解析与校验（域名/IP/[IPv6]/可选端口；非法目标 400）；
- 内置规则全量（旁路、终端、订阅直连、QUIC、内容过滤），兜底按内核
  的 ``route.final = 其他`` 而非面板的 final_outbound；
- 规则集引用展开（geosite exact/suffix 分开、geoip CIDR、obnode、
  obflip 内联、任意本地 .srs 经 decompile；远程 url-* 无法本地展开
  时记为假设而非静默不命中）；
- 域名查询的解析 IP 也参与 IP 类规则匹配（fakeip 域名除外：内核对
  fakeip 流量按域名路由，IP 条件不参与）；
- 端口/网络条件（默认 TCP；无端口输入时端口规则记入 skipped 而非
  假装不命中）；
- Clash 链路展开（实时选择优先，Clash 不可达时回落 DB：flip 默认值、
  selector 默认出站；urltest 类无 DB 选择时如实记为未决）；
- DNS  walk（内置 dns 规则表 + 分离 final + 域名重写提示）。

诚实边界（v1 不做）：
- 无源信息：终端 source 规则、nft 入口旁路无法评估，记入
  skipped_source_rules，不冒充命中；
- DNS 重写只提示不改写匹配（重写后的域名是否参与路由，取决于
  dnsmasq 与内核的交互，现有证据不足以断言）；
- 共享守卫 inbound 在我们生成的规则里不存在；若将来出现，
  share-* 守卫按原版 ni 语义剥离，其余 inbound 记入 skipped。
"""

import ipaddress
import re
import socket

from core import geodata as _gd
from core.penetration import _match_domain, _match_ip

FAKEIP_V4 = ipaddress.ip_network("198.19.0.0/16")
FAKEIP_V6 = ipaddress.ip_network("fc00::/18")

# 逻辑旁路规则的 IP 集恒为 sentinel（_obnode_direct["cidrs"] 从未被
# 填充）：只有 192.0.2.255 能命中它，实际流量永不触发该旁路。
# 预言机按此实际行为建模，不替用户补齐该集（补齐会改变现网路由）。
OBNODE_IP_SENTINEL = ["192.0.2.255/32"]
OBNODE_DOMAIN_SENTINEL = ["obnode-direct.invalid"]

_MAX_CHAIN_HOPS = 16
_MAX_RESOLVED = 5


class TargetError(ValueError):
    """Bad penetration input: the endpoint maps this to 400."""


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def _port_match(entry, port: int) -> bool:
    if isinstance(entry, int):
        return entry == port
    s = str(entry).strip()
    if "-" in s:
        try:
            lo, hi = s.split("-", 1)
            return int(lo) <= port <= int(hi)
        except ValueError:
            return False
    try:
        return int(s) == port
    except ValueError:
        return False


class Target:
    def __init__(self, kind, value, port=None, version=None):
        self.kind = kind  # "domain" | "ip"
        self.value = value  # domain str (case kept) or ip str
        self.port = port
        self.version = version  # 4 | 6 for ip; None for domain
        self.ip = None
        if kind == "ip":
            self.ip = ipaddress.ip_address(value)

    def classify(self) -> dict:
        if self.kind != "ip":
            return {}
        ip = self.ip
        return {
            "is_fakeip": ip in FAKEIP_V4 if ip.version == 4 else ip in FAKEIP_V6,
            "is_private": ip.is_private,
            "is_loopback": ip.is_loopback,
            "is_link_local": ip.is_link_local,
        }


def parse_target(raw, ip_version=None) -> Target:
    """Parse and validate a penetration target.

    Accepts a bare domain, a bare IPv4/IPv6 address, [IPv6], and an
    optional :port suffix on the non-bracketed forms. ip_version only
    constrains domain queries (a literal's version comes from the
    address itself, mirroring the reference oracle).
    """
    if ip_version is not None and ip_version not in (4, 6):
        raise TargetError("ip_version 只能是 4 或 6")
    s = (raw or "").strip()
    if not s:
        raise TargetError("target 不能为空")
    if len(s) > 253:
        raise TargetError("target 过长")
    if any(c.isspace() for c in s) or "://" in s or "/" in s \
            or "?" in s or "#" in s or "@" in s:
        raise TargetError("target 格式不正确")
    port = None
    if s.startswith("["):
        # [IPv6] or [IPv6]:port
        m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", s)
        if not m:
            raise TargetError("target 格式不正确")
        addr, port_s = m.group(1), m.group(2)
        if port_s is not None:
            port = _checked_port(port_s)
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise TargetError("target 格式不正确")
        return Target("ip", str(ip), port=port, version=ip.version)
    if ":" in s:
        # Bare IPv6 (no port allowed un-bracketed) or host:port.
        try:
            ip = ipaddress.ip_address(s)
            return Target("ip", str(ip), version=ip.version)
        except ValueError:
            pass
        if s.count(":") == 1:
            host, port_s = s.rsplit(":", 1)
            if port_s.isdigit():
                port = _checked_port(port_s)
                s = host
            else:
                raise TargetError("target 格式不正确")
        else:
            raise TargetError("target 格式不正确")
    try:
        ip = ipaddress.ip_address(s)
        return Target("ip", str(ip), port=port, version=ip.version)
    except ValueError:
        pass
    domain = s.rstrip(".")
    labels = domain.split(".")
    if not labels or any(not lab or len(lab) > 63 for lab in labels):
        raise TargetError("target 格式不正确")
    if any(not re.match(r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?$",
                        lab) for lab in labels):
        raise TargetError("target 格式不正确")
    return Target("domain", domain, port=port)


def _checked_port(port_s: str) -> int:
    try:
        port = int(port_s)
    except ValueError:
        raise TargetError("端口格式不正确")
    if not 1 <= port <= 65535:
        raise TargetError("端口超出范围 1-65535")
    return port


class Ctx:
    """Everything a rule evaluation may need."""

    def __init__(self, target: Target, network: str, ip_version,
                 resolved_ips, fakeip_dns, cfg,
                 geosite_split=None, geoip_expand=None):
        self.target = target
        self.network = network
        self.ip_version = ip_version
        self.resolved_ips = resolved_ips  # list[str], possibly []
        self.fakeip_dns = fakeip_dns
        self.cfg = cfg
        self.geosite_split = geosite_split or _gd.expand_geosite_split
        self.geoip_expand = geoip_expand or _gd.expand_geoip
        obd = getattr(cfg, "_obnode_direct", None) or {}
        self.obnode_domains = obd.get("domains") or OBNODE_DOMAIN_SENTINEL
        self.obnode_cidrs = obd.get("cidrs") or OBNODE_IP_SENTINEL
        self.obflip = getattr(cfg, "_obflip_rulesets", None) or {}


# ---------------------------------------------------------------- matching

def _match_domain_field(values, domain: str):
    """OR over a domain list (exact). Returns (hit, detail)."""
    for v in values:
        if _match_domain("domain", str(v), domain):
            return True, f"domain: {v}"
    return False, ""


def _match_suffix_field(values, domain: str):
    for v in values:
        if _match_domain("domain_suffix", str(v), domain):
            return True, f"domain_suffix: {v}"
    return False, ""


def _match_keyword_field(values, domain: str):
    for v in values:
        if _match_domain("domain_keyword", str(v), domain):
            return True, f"domain_keyword: {v}"
    return False, ""


def _match_ip_field(values, ips: list[str]):
    """OR over CIDRs x candidate IPs. Returns (hit, detail)."""
    for cidr in values:
        for ip in ips:
            if _match_ip(str(cidr), ip):
                return True, f"ip_cidr: {cidr}"
    return False, ""


def _ip_candidates(ctx: Ctx):
    """IPs an ip_cidr/ip_version condition may match against.

    Returns (ips, unknown_reason): unknown when a domain query has no
    usable IPs (unresolved, or fakeip where IP conditions do not apply
    at all — the latter is a decided miss, flagged separately).
    """
    t = ctx.target
    if t.kind == "ip":
        return [t.value], ""
    if ctx.fakeip_dns:
        return [], "fakeip"
    ips = list(ctx.resolved_ips)
    if ctx.ip_version is not None:
        ips = [ip for ip in ips
               if ipaddress.ip_address(ip).version == ctx.ip_version]
    if not ips:
        return [], "unresolved"
    return ips, ""


def _match_rule_set(tag: str, ctx: Ctx, depth=0, seen=None,
                    dns_mode=False):
    """Match one rule-set reference.

    Returns (status, detail): status hit/miss/unknown. Unknown means
    the set cannot be expanded locally (remote url-* sets, decompile
    failure) — the caller records it as an assumption, it never
    silently counts as a miss. In dns_mode a DNS query has no IP, so
    IP-only sets are a decided miss rather than unknown.
    """
    t = ctx.target
    seen = seen or set()
    if tag in _gd.INLINE_RULE_SETS:
        if dns_mode:
            return "miss", ""
        ips, unk = _ip_candidates(ctx)
        if unk == "fakeip":
            return "miss", ""
        if unk:
            return "unknown", f"规则集 {tag} 需目的 IP，域名未解析"
        hit, detail = _match_ip_field(_gd.INLINE_RULE_SETS[tag], ips)
        return ("hit", f"rule_set {tag}: {detail}") if hit else ("miss", "")
    if tag.startswith("geosite-"):
        if t.kind != "domain":
            return "miss", ""
        domains, suffixes = ctx.geosite_split(tag)
        hit, detail = _match_domain_field(domains, t.value)
        if hit:
            return "hit", f"rule_set {tag}: {detail}"
        hit, detail = _match_suffix_field(suffixes, t.value)
        if hit:
            return "hit", f"rule_set {tag}: {detail}"
        return "miss", ""
    if tag.startswith("geoip-"):
        if dns_mode:
            return "miss", ""
        ips, unk = _ip_candidates(ctx)
        if unk == "fakeip":
            return "miss", ""
        if unk:
            return "unknown", f"规则集 {tag} 需目的 IP，域名未解析"
        hit, detail = _match_ip_field(ctx.geoip_expand(tag), ips)
        return ("hit", f"rule_set {tag}: {detail}") if hit else ("miss", "")
    if tag == "obnode-direct":
        if t.kind != "domain":
            return "miss", ""
        for d in ctx.obnode_domains:
            if t.value == d:
                return "hit", f"rule_set {tag}: domain: {d}"
        return "miss", ""
    if tag == "obnode-direct-ip":
        if dns_mode:
            return "miss", ""
        ips, unk = _ip_candidates(ctx)
        if unk == "fakeip":
            return "miss", ""
        if unk:
            return "unknown", f"规则集 {tag} 需目的 IP，域名未解析"
        hit, detail = _match_ip_field(ctx.obnode_cidrs, ips)
        return ("hit", f"rule_set {tag}: {detail}") if hit else ("miss", "")
    if tag.startswith("obflip-"):
        rules = ctx.obflip.get(tag)
        if rules is None:
            return "unknown", f"内联规则集 {tag} 未生成"
        first_other = None
        for r in rules:
            st, detail = _eval_rule(r, ctx, depth=depth + 1,
                                    dns_mode=dns_mode)
            if st == "hit":
                return "hit", f"rule_set {tag}: {detail}"
            if st in ("unknown", "skip-source", "skip-port") \
                    and first_other is None:
                first_other = (st, detail)
        if first_other is not None:
            return first_other
        return "miss", ""
    if tag.startswith("url-"):
        return "unknown", f"远程规则集 {tag} 无法本地展开"
    # Any other local .srs: decode with the same authoritative decoder
    # the public expanders use; a missing file was already dropped by
    # the builder (skip_rule_sets), so reaching here with no file means
    # the reference is dangling.
    if not _gd.is_available(tag):
        return "unknown", f"规则集 {tag} 本地文件缺失"
    if depth >= 3 or tag in seen:
        return "unknown", f"规则集 {tag} 嵌套过深或成环"
    rules = _gd._decompile(_gd.local_path(tag), None)
    if rules is None:
        return "unknown", f"规则集 {tag} 解码失败"
    first_other = None
    for r in rules:
        st, detail = _eval_rule(r, ctx, depth=depth + 1,
                                seen=seen | {tag}, dns_mode=dns_mode)
        if st == "hit":
            return "hit", f"rule_set {tag}: {detail}"
        if st in ("unknown", "skip-source", "skip-port") \
                and first_other is None:
            first_other = (st, detail)
    if first_other is not None:
        return first_other
    return "miss", ""


def _eval_rule(rule: dict, ctx: Ctx, depth=0, seen=None, dns_mode=False):
    """Evaluate one built rule dict.

    Returns (status, detail) with status in hit/miss/unknown/
    skip-source/skip-port. Across fields AND, within a field OR; a
    definite miss dominates unknown/skip (Kleene logic), so an
    unevaluable field only matters when every other field hits.
    In dns_mode a DNS query is matched on domain dimensions only:
    IP/port/network/protocol/source fields are ignored, and a rule
    with no domain dimension at all is a miss.
    """
    if not isinstance(rule, dict):
        return "miss", ""
    if rule.get("type") == "logical":
        mode = (rule.get("mode") or "and").lower()
        subs = [_eval_rule(r, ctx, depth=depth + 1, seen=seen,
                           dns_mode=dns_mode)
                for r in rule.get("rules", [])]
        details = [d for s, d in subs if s == "hit" and d]
        if mode == "or":
            if any(s == "hit" for s, _ in subs):
                st = "hit"
            elif any(s in ("unknown", "skip-source", "skip-port")
                     for s, _ in subs):
                st = next(s for s, _ in subs
                          if s in ("unknown", "skip-source", "skip-port"))
            else:
                st = "miss"
        else:
            if any(s == "miss" for s, _ in subs):
                st = "miss"
            elif any(s in ("unknown", "skip-source", "skip-port")
                     for s, _ in subs):
                st = next(s for s, _ in subs
                          if s in ("unknown", "skip-source", "skip-port"))
            else:
                st = "hit"
        if rule.get("invert"):
            st = {"hit": "miss", "miss": "hit"}.get(st, st)
        return st, ("逻辑规则：" + "；".join(details)) if st == "hit" else ""
    # Share-guard stripping (ni): a bare {invert, inbound: share-*}
    # guard is not a routing condition for non-share inbounds.
    r = rule
    if "inbound" in rule:
        inb = _as_list(rule.get("inbound"))
        if rule.get("invert") is True and inb and all(
                str(x).startswith("share-") for x in inb):
            r = {k: v for k, v in rule.items() if k != "inbound"}
        elif dns_mode:
            r = {k: v for k, v in rule.items() if k != "inbound"}
        else:
            return "skip-source", "规则含入站条件，需源信息"
    if "source_ip_cidr" in r and not dns_mode:
        return "skip-source", "规则含源 IP 条件，需源信息"
    t = ctx.target
    fields = []  # (status, detail) per present field
    if "domain" in r:
        if t.kind != "domain":
            fields.append(("miss", ""))
        else:
            hit, detail = _match_domain_field(_as_list(r["domain"]), t.value)
            fields.append(("hit", detail) if hit else ("miss", ""))
    if "domain_suffix" in r:
        if t.kind != "domain":
            fields.append(("miss", ""))
        else:
            hit, detail = _match_suffix_field(_as_list(r["domain_suffix"]),
                                              t.value)
            fields.append(("hit", detail) if hit else ("miss", ""))
    if "domain_keyword" in r:
        if t.kind != "domain":
            fields.append(("miss", ""))
        else:
            hit, detail = _match_keyword_field(_as_list(r["domain_keyword"]),
                                               t.value)
            fields.append(("hit", detail) if hit else ("miss", ""))
    if "domain_regex" in r:
        if t.kind != "domain":
            fields.append(("miss", ""))
        else:
            try:
                hit = any(re.search(str(p), t.value)
                          for p in _as_list(r["domain_regex"]))
                fields.append(("hit", f"domain_regex: {r['domain_regex']}")
                              if hit else ("miss", ""))
            except re.error as e:
                fields.append(("unknown", f"正则无效：{e}"))
    if "ip_cidr" in r and not dns_mode:
        ips, unk = _ip_candidates(ctx)
        if unk == "fakeip":
            fields.append(("miss", ""))
        elif unk:
            fields.append(("unknown", "IP 条件需目的 IP，域名未解析"))
        else:
            hit, detail = _match_ip_field(_as_list(r["ip_cidr"]), ips)
            fields.append(("hit", detail) if hit else ("miss", ""))
    if "ip_version" in r and not dns_mode:
        if t.kind == "ip":
            fields.append(("hit", f"ip_version: {t.version}")
                          if int(r["ip_version"]) == t.version
                          else ("miss", ""))
        else:
            ips, unk = _ip_candidates(ctx)
            if unk == "fakeip":
                fields.append(("miss", ""))
            elif unk:
                fields.append(("unknown", "IP 条件需目的 IP，域名未解析"))
            else:
                fields.append(("hit", f"ip_version: {r['ip_version']}")
                              if ips else ("miss", ""))
    if ("port" in r or "port_range" in r) and not dns_mode:
        if t.port is None:
            return "skip-port", "规则含端口条件，未给端口"
        ports = _as_list(r.get("port")) + _as_list(r.get("port_range"))
        fields.append(("hit", f"port: {t.port}")
                      if any(_port_match(p, t.port) for p in ports)
                      else ("miss", ""))
    if "network" in r and not dns_mode:
        fields.append(("hit", f"network: {ctx.network}")
                      if str(r["network"]).lower() == ctx.network
                      else ("miss", ""))
    if "protocol" in r and not dns_mode:
        fields.append(("unknown", "规则含协议条件，无法评估"))
    if "rule_set" in r:
        rs_status, rs_detail = "miss", ""
        for tag in _as_list(r["rule_set"]):
            st, detail = _match_rule_set(str(tag), ctx, depth=depth,
                                         seen=seen, dns_mode=dns_mode)
            if st == "hit":
                rs_status, rs_detail = "hit", detail
                break
            if st in ("unknown", "skip-source", "skip-port") \
                    and rs_status == "miss":
                rs_status, rs_detail = st, detail
        fields.append((rs_status, rs_detail))
    if not fields:
        # A rule with no evaluable condition (e.g. only a stripped
        # share guard): it matches everything it was attached to.
        # In dns_mode a rule with no domain dimension cannot match
        # a DNS query.
        st = "miss" if dns_mode else "hit"
        detail = ""
    elif any(s == "miss" for s, _ in fields):
        st, detail = "miss", ""
    elif any(s in ("unknown", "skip-source", "skip-port")
             for s, _ in fields):
        st, detail = next((s, d) for s, d in fields
                          if s in ("unknown", "skip-source", "skip-port"))
    else:
        st = "hit"
        detail = "; ".join(d for _, d in fields if d)
    if r.get("invert") and r.get("type") != "logical":
        st = {"hit": "miss", "miss": "hit"}.get(st, st)
    return st, detail


# ---------------------------------------------------------------- DNS walk

def _rewrite_of(cfg, domain: str):
    for r in getattr(cfg, "dns_rewrites", None) or []:
        if isinstance(r, dict):
            d, tgt, en = r.get("domain"), r.get("target"), r.get("enabled", True)
        else:
            d, tgt, en = getattr(r, "domain", None), getattr(r, "target", None), \
                getattr(r, "enabled", True)
        if en and d and d.strip().rstrip(".") == domain:
            try:
                ipaddress.ip_address((tgt or "").strip())
                kind = "address"
            except ValueError:
                kind = "cname"
            return {"domain": d, "target": tgt, "kind": kind}
    return None


def _dns_walk(cfg, dns_rules, ctx: Ctx):
    """Which DNS server answers this domain, per the built dns rules.

    DNS rules are evaluated on domain dimensions only (a DNS query has
    no destination IP, port or network yet); rules that cannot be
    decided are recorded as assumptions, not silently skipped.
    """
    if ctx.target.kind != "domain":
        return {"server": None, "rule_index": None, "detail": "",
                "rewrite": None, "assumptions": [], "note": "IP 目标无需 DNS"}
    assumptions = []
    for idx, rule in enumerate(dns_rules):
        st, detail = _eval_rule(rule, ctx, dns_mode=True)
        if st == "hit":
            return {"server": rule.get("server"), "rule_index": idx,
                    "detail": detail,
                    "rewrite": _rewrite_of(cfg, ctx.target.value),
                    "assumptions": assumptions, "note": ""}
        if st in ("unknown", "skip-source", "skip-port"):
            assumptions.append({"rule_index": idx, "reason": detail})
    split = getattr(getattr(cfg, "dns", None), "split", True)
    return {"server": "dns-direct" if split else "dns-proxy",
            "rule_index": None, "detail": "未命中 DNS 规则，走 final",
            "rewrite": _rewrite_of(cfg, ctx.target.value),
            "assumptions": assumptions, "note": ""}


# ---------------------------------------------------------------- chain walk

def _flip_default(site_set, cfg) -> str:
    """The flip selector's default choice, mirroring flip_outbound."""
    grp = site_set.group if getattr(site_set, "group", "") else "所有-自动"
    action = getattr(site_set, "action", "proxy")
    flip = getattr(site_set, "flip", "") or ""
    if action == "reject":
        return "block"
    if flip == "direct" or action == "direct":
        return "direct"
    return grp


def walk_chain(tag, proxies, cfg, _depth=0):
    """Resolve an outbound tag to its leaf through live Clash selections.

    proxies: Clash /proxies entries dict, or None for DB fallback.
    Returns {chain, final, unresolved, note}.
    """
    if tag in ("direct", "block", "reject"):
        return {"chain": [tag], "final": tag, "unresolved": False, "note": ""}
    if _depth > _MAX_CHAIN_HOPS:
        return {"chain": [tag], "final": tag, "unresolved": True,
                "note": "链路过深，停止展开"}
    if proxies and tag in proxies:
        chain = [tag]
        cur = tag
        visited = {tag}
        while len(chain) <= _MAX_CHAIN_HOPS:
            entry = proxies.get(cur)
            now = entry.get("now") if isinstance(entry, dict) else None
            if not now or not isinstance(now, str) or now == cur \
                    or now in visited:
                break
            chain.append(now)
            visited.add(now)
            if now not in proxies:
                break
            cur = now
        return {"chain": chain, "final": chain[-1], "unresolved": False,
                "note": ""}
    # DB fallback: live selection unavailable.
    from core.singbox import flip_tag
    for s in getattr(cfg, "site_sets", None) or []:
        if flip_tag(s) == tag:
            nxt = _flip_default(s, cfg)
            if nxt in ("direct", "block"):
                return {"chain": [tag, nxt], "final": nxt,
                        "unresolved": False, "note": "DB 回落：flip 默认值"}
            sub = walk_chain(nxt, None, cfg, _depth + 1)
            return {"chain": [tag] + sub["chain"], "final": sub["final"],
                    "unresolved": sub["unresolved"],
                    "note": "DB 回落：flip 默认值"}
    node_tags = [n.tag for n in getattr(cfg, "nodes", None) or []]
    chain_tags = [c.name for c in getattr(cfg, "chains", None) or []]
    if tag in node_tags:
        return {"chain": [tag], "final": tag, "unresolved": False, "note": ""}
    if tag in chain_tags:
        return {"chain": [tag], "final": tag, "unresolved": False,
                "note": "链式代理内部不再展开"}
    for g in getattr(cfg, "groups", None) or []:
        if g.name != tag:
            continue
        if g.type != "selector":
            return {"chain": [tag], "final": tag, "unresolved": True,
                    "note": f"{g.type} 组需实时内核选择"}
        try:
            from core.singbox import resolve_group_members
            members = resolve_group_members(g, node_tags, chain_tags)
        except Exception:
            members = list(getattr(g, "members", None) or [])
        nxt = None
        if getattr(g, "default_outbound", "") in members:
            nxt = g.default_outbound
        elif members:
            nxt = members[0]
        if not nxt:
            return {"chain": [tag], "final": tag, "unresolved": True,
                    "note": "组无可选成员"}
        sub = walk_chain(nxt, None, cfg, _depth + 1)
        return {"chain": [tag] + sub["chain"], "final": sub["final"],
                "unresolved": sub["unresolved"],
                "note": "DB 回落：组默认出站"}
    return {"chain": [tag], "final": tag, "unresolved": True,
            "note": "未知出站标签"}


# ---------------------------------------------------------------- predict

def _resolve_domain(domain: str, ip_version) -> list[str]:
    try:
        infos = socket.getaddrinfo(domain, None)
    except Exception:
        return []
    ips = []
    for info in infos:
        fam, _, _, _, sockaddr = info
        ip = sockaddr[0]
        if ip_version is not None and \
                ipaddress.ip_address(ip).version != ip_version:
            continue
        if ip not in ips:
            ips.append(ip)
    return ips[:_MAX_RESOLVED]


def predict(cfg, target_raw, port=None, network="tcp", ip_version=None,
            proxies=None, geosite_split=None, geoip_expand=None) -> dict:
    """Predict the route for one flow. Raises TargetError on bad input;
    a build failure propagates (the endpoint maps it to 500)."""
    target = parse_target(target_raw)
    if port is not None:
        target.port = _checked_port(str(port))
    network = (network or "tcp").lower()
    if network not in ("tcp", "udp"):
        raise TargetError("network 只能是 tcp 或 udp")
    if ip_version is not None and ip_version not in (4, 6):
        raise TargetError("ip_version 只能是 4 或 6")

    from core import geodata as _gd2
    from core.singbox import build_route_rules
    skip = {n for n in _gd2.referenced_rule_sets(cfg)
            if not _gd2.is_available(n)}
    prov = []
    route_rules, dns_rules, _groups = build_route_rules(cfg, skip, prov)
    assert len(prov) == len(route_rules), "provenance 与规则表失配"

    # DNS walk first: a fakeip answer changes how IP rules are treated.
    dns_ctx = Ctx(target, network, ip_version, [], False, cfg,
                  geosite_split, geoip_expand)
    dns = _dns_walk(cfg, dns_rules, dns_ctx)
    fakeip_dns = dns.get("server") == "dns-fakeip"

    resolved = []
    if target.kind == "domain" and not fakeip_dns:
        resolved = _resolve_domain(target.value, ip_version)
    ctx = Ctx(target, network, ip_version, resolved, fakeip_dns, cfg,
              geosite_split, geoip_expand)

    assumptions = []
    skipped_source = []
    skipped_port = []
    matched = None
    for idx, rule in enumerate(route_rules):
        st, detail = _eval_rule(rule, ctx)
        owner = prov[idx]
        if st == "hit":
            action = rule.get("action")
            outbound = rule.get("outbound")
            target_field = "reject" if action == "reject" else outbound
            matched = {
                "source": owner["kind"],
                "source_name": _source_name(owner),
                "rule_type": _rule_type(rule, owner),
                "rule_value": detail,
                "rule_note": owner.get("note", ""),
                "target": target_field,
                "rule_index": idx,
                "owner": {"kind": owner["kind"], "name": owner["name"]},
                "action": action or "",
                "outbound": outbound or "",
            }
            chain = ({"chain": ["reject"], "final": "reject",
                      "unresolved": False, "note": ""}
                     if action == "reject"
                     else walk_chain(outbound, proxies, cfg))
            matched["chain"] = chain["chain"]
            matched["final_outbound"] = chain["final"]
            matched["chain_unresolved"] = chain["unresolved"]
            matched["chain_note"] = chain["note"]
            break
        if st == "unknown":
            assumptions.append({"rule_index": idx, "owner": owner,
                                "reason": detail})
        elif st == "skip-source":
            skipped_source.append({"rule_index": idx, "owner": owner,
                                   "reason": detail})
        elif st == "skip-port":
            skipped_port.append({"rule_index": idx, "owner": owner,
                                 "reason": detail})
    if matched is None:
        chain = walk_chain("其他", proxies, cfg)
        matched = {
            "source": "fallback",
            "source_name": "兜底",
            "rule_type": "fallback",
            "rule_value": "",
            "rule_note": "",
            "target": "其他",
            "rule_index": None,
            "owner": {"kind": "final", "name": "兜底"},
            "action": "",
            "outbound": "其他",
            "chain": chain["chain"],
            "final_outbound": chain["final"],
            "chain_unresolved": chain["unresolved"],
            "chain_note": chain["note"],
        }
    if target.kind == "domain" and not resolved and not fakeip_dns:
        assumptions.append({"rule_index": None, "owner": None,
                            "reason": "域名未解析出 IP，IP 类规则未评估；"
                            "若解析后落入某 IP 段，更靠前的 IP 规则可能优先"})
    verdict = "hit" if matched["source"] != "fallback" else "miss"
    return {
        "query": target.value,
        "is_ip": target.kind == "ip",
        "port": target.port,
        "network": network,
        "ip_version": target.version if target.kind == "ip" else ip_version,
        "classification": target.classify() or None,
        "resolved_ips": resolved,
        "matched": matched,
        "verdict": verdict,
        "rule_index": matched["rule_index"],
        "owner": matched["owner"],
        "chain": matched["chain"],
        "final_outbound": matched["final_outbound"],
        "dns": dns,
        "dns_server": dns["server"] or "dns-direct",
        "assumptions": assumptions,
        "skipped_source_rules": skipped_source,
        "skipped_port_rules": skipped_port,
    }


def _source_name(owner: dict) -> str:
    kind = owner["kind"]
    if kind == "front":
        return "前置自定义分流"
    if kind == "siteset":
        return f"站点集：{owner['name']}"
    if kind == "fallback":
        return "兜底"
    return owner["name"]


def _rule_type(rule: dict, owner: dict) -> str:
    if owner["kind"] == "siteset":
        return "siteset"
    if rule.get("type") == "logical":
        return "logical"
    for key in ("domain", "domain_suffix", "domain_keyword", "domain_regex",
                "ip_cidr", "ip_version", "port", "port_range", "network",
                "rule_set"):
        if key in rule:
            return key
    return owner["kind"]
