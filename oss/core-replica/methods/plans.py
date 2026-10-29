"""classes / entryPlan / bypassPlan / forwardPlan.

Derived from core-golden.json (2 + 3 + 3 + 3 cases). These four
share one model: policies resolve to a class (proxy/direct/block)
through the live selections, and the three plans branch on the
entry conditions (the "直连不进内核" setting, FakeIP, fallback class).

classes(routing, members, builtin, selections) -> {name: class}:
- One entry per policy plus one for the fallback (keyed by its
  name, default 其他). Resolution: selections[name] if present and
  non-empty, else the policy default (fallbackDefault for the
  fallback); "direct" or the direct builtin tag -> "direct",
  "block" or the block builtin tag -> "block", anything else ->
  "proxy". Selections-first is INFERRED (the corpus never separates
  selections from defaults, but the signature passes selections and
  the live selection is what the kernel actually uses). Policies
  are included as given (no enabled filter, no no-rule drop —
  INFERRED; no case separates these).

entryPlan(routing, ctx) / bypassPlan(routing, ctx):
- ctx = {members, builtin, selections, clientRoutes, fakeIp,
  dnsMode, enabled}; clientRoutes/dnsMode have no measured effect
  and are ignored. Absent ctx.enabled passes the enabled check
  (only an explicit false triggers the disabled branch); absent
  ctx.fakeIp counts as off.
- entryPlan branches: enabled false -> "关掉了「直连不进内核」"
  (blacklist); fakeIp off -> "没开 FakeIP" (blacklist); fallback
  not direct -> "兜底走代理" (blacklist; INFERRED, reuses the
  bypassPlan string); else whitelist with needSets/needCidrs from
  proxy/block policies (custom first, then policies in order,
  deduped in first-appearance order).
- bypassPlan branches: enabled false -> "关掉了" (enabled false);
  fallback not direct -> "兜底走代理" (enabled false); fakeIp off
  -> "没开 FakeIP" (enabled false; INFERRED, reuses the entryPlan
  string); else the pending computation (enabled = no pending
  policies; sets always [] — the core never approves sets itself,
  INFERRED).
- needSets = geoip-* rulesets of proxy/block policies (+ custom
  geoip rules first); needCidrs = ipCidr of proxy/block policies
  (+ custom ipCidr rules first). Direct policies never contribute.
  Disabled policies are skipped (INFERRED).
- bypass pending = direct-class policies with non-empty geoip
  sets, each with "against" = earlier proxy/block policies with IP
  conditions (custom first). The reason is templated: the FakeIP
  base plus one "站点集「P」的集合要先和前面带 IP 条件的「…」
  核对重叠,部署时决定" clause per pending policy (multiple
  pending policies join clauses with ";", INFERRED — only one
  pending policy is measured).

forwardPlan(routing, members, builtin, selections, {rewriteDomains}):
- domains = custom domain/domainSuffix rules with proxy outbounds
  (in rule order) + proxy-class policies' domain then domainSuffix
  (per policy, in policy order) + rewriteDomains, deduped in
  first-appearance order (dedup is INFERRED; no duplicate domain
  is measured). domainKeyword is excluded (a keyword is not a
  forwardable domain — INFERRED).
- expand = custom geosite rules with proxy outbounds
  ({owner: 前置自定义分流「value」, tag: geosite-value}, in rule
  order) + proxy-class policies' geosite-* rulesets
  ({owner: 站点集「policy」, tag: ruleset verbatim}, in policy
  then ruleset order). No dedup (geosite-youtube appears twice in
  the real case: once custom, once policy).
- mode: fallback proxy -> "all" (reason is the SHORT form
  "兜底「{fallback}」走代理", templated with the fallback name —
  INFERRED); otherwise "domains" with an empty reason. Custom
  outbound class: direct
  builtin / "direct" -> direct, block builtin / "block" -> block,
  anything else -> proxy.
"""

from .normalize import normalize_custom_value

DEFAULT_TEST_URL = "http://www.gstatic.com/generate_204"

_REASON_DISABLED = ("后端设置里关掉了「直连不进内核」:"
                    "所有流量都进内核,入口不放行")
_REASON_NO_FAKEIP = ("没开 FakeIP:走代理的域名解析出来是真实 IP,"
                     "入口分不出它和直连目标,不能默认放行")
_REASON_FALLBACK_PROXY = ("兜底「{name}」走代理:没命中域名规则的域名都走兜底,"
                          "它们解析出来的真实地址在入口分不出来,"
                          "按 IP 放走会放错（开 FakeIP 后它们拿的是占位地址,"
                          "就不挡了）")
_REASON_ENTRY_OK = ("FakeIP 开着、兜底直连:入口默认放行,"
                    "只有 FakeIP 占位池和走代理 / 拒绝的 IP 集合进内核")
_REASON_BYPASS_BASE = ("FakeIP 试验开着:走代理的域名规则按占位地址计,"
                       "不挡直连集合（终端自带加密 DNS / 开启前已缓存的"
                       "真实地址 / 转发漏匹配不在此保证内）")


def _dict(v):
    return v if isinstance(v, dict) else {}


def _str(v, default=""):
    return v if isinstance(v, str) else default


def _policies(routing):
    r = _dict(routing)
    ps = r.get("policies")
    return ps if isinstance(ps, list) else []


def _fallback(routing):
    r = _dict(routing)
    return {
        "name": _str(r.get("fallbackName"), "其他") or "其他",
        "default": _str(r.get("fallbackDefault"), ""),
    }


def _resolve_class(value, builtin):
    if value == "direct" or value == builtin.get("direct"):
        return "direct"
    if value == "block" or value == builtin.get("block"):
        return "block"
    return "proxy"


def _policy_class(policy, selections, builtin):
    name = policy.get("name") if isinstance(policy, dict) else None
    sel = selections.get(name) if isinstance(name, str) else None
    if not isinstance(sel, str) or not sel:
        sel = _str(policy.get("default"), "") if isinstance(policy,
                                                           dict) else ""
    return _resolve_class(sel, builtin)


def _classes_value(routing, builtin, selections):
    selections = _dict(selections)
    builtin = _dict(builtin)
    out = {}
    for p in _policies(routing):
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not isinstance(name, str) or not name:
            continue
        out[name] = _policy_class(p, selections, builtin)
    fb = _fallback(routing)
    sel = selections.get(fb["name"])
    if not isinstance(sel, str) or not sel:
        sel = fb["default"]
    out[fb["name"]] = _resolve_class(sel, builtin)
    return out


def _custom(routing):
    return normalize_custom_value(_dict(routing).get("custom"))


def _geoip_of_rulesets(rulesets):
    out = []
    for rs in rulesets:
        if isinstance(rs, str) and rs.startswith("geoip-"):
            out.append(rs)
    return out


def _policy_ip(policy):
    if not isinstance(policy, dict):
        return [], []
    cidrs = [c for c in policy.get("ipCidr", [])
             if isinstance(c, str)] if isinstance(
                 policy.get("ipCidr"), list) else []
    geoip = _geoip_of_rulesets(policy.get("rulesets")
                               if isinstance(policy.get("rulesets"),
                                            list) else [])
    return cidrs, geoip


def _custom_ip(custom, builtin):
    cidrs, geoip = [], []
    if not custom.get("enabled"):
        return cidrs, geoip
    for rule in custom.get("rules", []):
        cls = _resolve_class(rule.get("outbound"), builtin)
        if cls not in ("proxy", "block"):
            continue
        if rule.get("type") == "geoip":
            geoip.append("geoip-" + rule["value"])
        elif rule.get("type") == "ipCidr":
            cidrs.append(rule["value"])
    return cidrs, geoip


def _dedup(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _collect_ip(routing, builtin, selections, want_classes=("proxy",
                                                            "block")):
    """(needCidrs, needSets) in first-appearance order, custom first."""
    custom = _custom(routing)
    cc, cg = _custom_ip(custom, builtin)
    cidrs = list(cc)
    geoip = list(cg)
    for p in _policies(routing):
        if not isinstance(p, dict):
            continue
        if p.get("enabled") is False:
            continue
        if _policy_class(p, selections, builtin) not in want_classes:
            continue
        c, g = _policy_ip(p)
        cidrs.extend(c)
        geoip.extend(g)
    return _dedup(cidrs), _dedup(geoip)


def _ctx(args, index):
    ctx = args[index] if len(args) > index else None
    return _dict(ctx)


def _entry_conditions(routing, ctx):
    builtin = ctx.get("builtin")
    selections = ctx.get("selections")
    classes = _classes_value(routing, builtin, selections)
    fb = _fallback(routing)
    return classes.get(fb["name"], "proxy")


def entry_plan(args):
    routing = args[0] if args else None
    ctx = _ctx(args, 1)
    fake_ip = ctx.get("fakeIp") is True
    if ctx.get("enabled") is False:
        return {"directAnswer": False, "fakeIp": fake_ip,
                "mode": "blacklist", "needCidrs": [], "needSets": [],
                "reason": _REASON_DISABLED}
    if not fake_ip:
        return {"directAnswer": False, "fakeIp": False,
                "mode": "blacklist", "needCidrs": [], "needSets": [],
                "reason": _REASON_NO_FAKEIP}
    if _entry_conditions(routing, ctx) != "direct":
        fb = _fallback(routing)
        return {"directAnswer": False, "fakeIp": True,
                "mode": "blacklist", "needCidrs": [], "needSets": [],
                "reason": _REASON_FALLBACK_PROXY.format(name=fb["name"])}
    cidrs, geoip = _collect_ip(routing, ctx.get("builtin"),
                               ctx.get("selections"))
    return {"directAnswer": True, "fakeIp": True, "mode": "whitelist",
            "needCidrs": cidrs, "needSets": geoip,
            "reason": _REASON_ENTRY_OK}


def bypass_plan(args):
    routing = args[0] if args else None
    ctx = _ctx(args, 1)
    fake_ip = ctx.get("fakeIp") is True
    if ctx.get("enabled") is False:
        return {"enabled": False, "fakeIp": fake_ip, "pending": [],
                "reason": _REASON_DISABLED, "sets": []}
    fb = _fallback(routing)
    if _entry_conditions(routing, ctx) != "direct":
        return {"enabled": False, "fakeIp": fake_ip, "pending": [],
                "reason": _REASON_FALLBACK_PROXY.format(name=fb["name"]),
                "sets": []}
    if not fake_ip:
        return {"enabled": False, "fakeIp": False, "pending": [],
                "reason": _REASON_NO_FAKEIP, "sets": []}
    builtin = _dict(ctx.get("builtin"))
    selections = _dict(ctx.get("selections"))
    custom = _custom(routing)
    cc, cg = _custom_ip(custom, builtin)
    # against-so-far starts with custom (the front rules), then each
    # earlier proxy/block policy with IP conditions, in order.
    against = []
    if cc or cg:
        against.append({"cidrs": cc, "geoip": cg,
                        "name": custom.get("name") or "前置自定义分流"})
    pending = []
    for p in _policies(routing):
        if not isinstance(p, dict):
            continue
        cls = _policy_class(p, selections, builtin)
        c, g = _policy_ip(p)
        if cls in ("proxy", "block"):
            if p.get("enabled") is False:
                continue
            if c or g:
                against.append({"cidrs": c, "geoip": g,
                                "name": p.get("name")})
        elif cls == "direct":
            if p.get("enabled") is False:
                continue
            if g:
                pending.append({
                    "against": [dict(a) for a in against],
                    "policy": p.get("name"),
                    "sets": list(g),
                })
    if pending:
        clauses = []
        for entry in pending:
            names = "".join("「%s」" % a["name"]
                            for a in entry["against"])
            clauses.append("站点集「%s」的集合要先和前面带 IP 条件的%s"
                           "核对重叠,部署时决定"
                           % (entry["policy"], names))
        reason = _REASON_BYPASS_BASE + ";" + ";".join(clauses)
        return {"enabled": False, "fakeIp": True, "pending": pending,
                "reason": reason, "sets": []}
    return {"enabled": True, "fakeIp": True, "pending": [],
            "reason": _REASON_BYPASS_BASE, "sets": []}


def classes_fn(args):
    routing = args[0] if args else None
    builtin = args[2] if len(args) > 2 else {}
    selections = args[3] if len(args) > 3 else {}
    return _classes_value(routing, builtin, selections)


def forward_plan(args):
    routing = args[0] if args else None
    builtin = _dict(args[2] if len(args) > 2 else {})
    selections = _dict(args[3] if len(args) > 3 else {})
    opts = _dict(args[4] if len(args) > 4 else {})
    rewrite = opts.get("rewriteDomains")
    rewrite = rewrite if isinstance(rewrite, list) else []
    custom = _custom(routing)
    domains = []
    expand = []
    if custom.get("enabled"):
        for rule in custom.get("rules", []):
            cls = _resolve_class(rule.get("outbound"), builtin)
            if rule.get("type") in ("domain", "domainSuffix"):
                if cls == "proxy":
                    domains.append(rule["value"])
            elif rule.get("type") == "geosite":
                if cls == "proxy":
                    expand.append({
                        "owner": "前置自定义分流「%s」" % rule["value"],
                        "tag": "geosite-" + rule["value"],
                    })
    for p in _policies(routing):
        if not isinstance(p, dict):
            continue
        if p.get("enabled") is False:
            continue
        if _policy_class(p, selections, builtin) != "proxy":
            continue
        for field in ("domain", "domainSuffix"):
            vals = p.get(field)
            if isinstance(vals, list):
                domains.extend(v for v in vals if isinstance(v, str))
        rulesets = p.get("rulesets")
        if isinstance(rulesets, list):
            for rs in rulesets:
                if isinstance(rs, str) and rs.startswith("geosite-"):
                    expand.append({"owner": "站点集「%s」" % p.get("name"),
                                   "tag": rs})
    domains.extend(v for v in rewrite if isinstance(v, str))
    domains = _dedup(domains)
    fb = _fallback(routing)
    fb_class = _classes_value(routing, builtin, selections).get(
        fb["name"], "proxy")
    if fb_class == "proxy":
        # NOTE: forwardPlan's mode-all reason is the SHORT form
        # ("兜底「其他」走代理"), not the long entry/bypass sentence.
        mode, reason = "all", "兜底「%s」走代理" % fb["name"]
    else:
        mode, reason = "domains", ""
    return {"domains": domains, "expand": expand, "mode": mode,
            "reason": reason}
