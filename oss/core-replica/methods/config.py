"""configDetailed: build the sing-box config the panel deploys.

Input is one state dict (see the method docstring in __init__ for the
field list). Output is {config, directHosts, dnsRuleOwners, failover}.

The derivation is documented inline per section. Two deliberate gaps
are carried openly, not papered over:

- obflip-<hash> rule-set tags: a deterministic 12-hex digest per
  policy, not present in state and not matched by ~70 candidate
  constructions (md5/sha1/sha256/blake2b6/fnv1a/fnv1/xxh64/xxh3_64/
  xxh128/HMAC(filterExpectedKey) over policy JSON variants). The
  placeholder below is md5(policy-normalized-json)[:12]; the harness
  blind comparator normalizes obflip-[0-9a-f]{12} before diffing so
  every other byte is verified exactly.
- directHosts: the clean rule (all node servers, deduped in node
  order, + subscription URL hosts) matches real except for 50 IP
  servers of one subscription that the golden excludes for no reason
  visible in state (see _direct_hosts). The clean rule is implemented
  and the deviation is reported, not fitted.

Unprobed corners (no golden variation) are marked INFERRED and use
the conservative reading: policy/custom enabled defaults true;
disabled policies are skipped like disabled groups; localSubnets are
appended to tun route_exclude_address; directHostCidrs are appended
to directHosts.cidrs; ipv6-open dns strategy is "prefer_ipv4".
"""

import hashlib
import ipaddress
from urllib.parse import urlparse

from .emit import emit_groups_value
from .plans import (_custom, _dedup, _fallback, _policies,
                    _resolve_class)

DIRECT_FALLBACK = "其他"
ROUTE_EXCLUDE_ADDRESS = [
    "10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16", "172.16.0.0/15",
    "172.18.0.0/16", "172.19.0.4/30", "172.19.0.8/29", "172.19.0.16/28",
    "172.19.0.32/27", "172.19.0.64/26", "172.19.0.128/25",
    "172.19.1.0/24", "172.19.2.0/23", "172.19.4.0/22", "172.19.8.0/21",
    "172.19.16.0/20", "172.19.32.0/19", "172.19.64.0/18",
    "172.19.128.0/17", "172.20.0.0/14", "172.24.0.0/13",
    "192.168.0.0/16", "224.0.0.0/4",
]
DOMAIN_REGEX = "^[^:]*[a-z][^:]*$"


def _dict(v):
    return v if isinstance(v, dict) else {}


def _str(v, default=""):
    return v if isinstance(v, str) else default


def _str_list(v):
    return [x for x in v if isinstance(x, str)] if isinstance(v,
                                                             list) else []


def _bool(v, default):
    return v if isinstance(v, bool) else default


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v,
                                                               bool) else None


# ------------------------------------------------------------------ state

class _State:
    """Parsed view of the configDetailed input state."""

    def __init__(self, state):
        s = _dict(state)
        self.profile = _dict(s.get("profile"))
        self.routing = _dict(self.profile.get("routing"))
        self.dns = _dict(self.profile.get("dns"))
        self.tun = _dict(self.profile.get("tun"))
        self.selections = _dict(s.get("selections"))
        self.nodes = s.get("nodes") if isinstance(s.get("nodes"),
                                                  list) else []
        self.user_groups = s.get("userGroups") if isinstance(
            s.get("userGroups"), list) else []
        self.subscriptions = s.get("subscriptions") if isinstance(
            s.get("subscriptions"), list) else []
        self.chain_nodes = s.get("chainNodes") if isinstance(
            s.get("chainNodes"), list) else []
        self.ruleset_dir = _str(s.get("rulesetDir"), "")
        self.cache_path = _str(s.get("cacheFilePath"),
                               "/opt/open-box/data/cache.db")
        self.dns_filter = _dict(s.get("dnsFilter"))
        self.rule_lists = _dict(s.get("ruleLists"))
        nb = s.get("nativeBypass")
        self.native_bypass = nb if isinstance(nb, dict) else None
        self.local_subnets = _str_list(s.get("localSubnets"))
        self.direct_host_cidrs = _str_list(s.get("directHostCidrs"))
        self.policies = [p for p in _policies(self.routing)
                         if isinstance(p, dict) and p.get("name")
                         and _bool(p.get("enabled"), True)]
        self.custom = _custom(self.routing)
        # A disabled custom section contributes no rules anywhere.
        self.custom_rules = self.custom.get("rules", []) \
            if self.custom.get("enabled") else []
        fb = _fallback(self.routing)
        self.fallback_name = fb["name"]
        self.fallback_default = fb["default"]
        self.reject_quic = _bool(self.profile.get("rejectQuic"), True)
        self.auto_redirect = _bool(self.tun.get("autoRedirect"), False)


def _default_tag(value, builtin):
    """Policy/fallback default value -> outbound tag."""
    cls = _resolve_class(value, builtin)
    if cls == "direct":
        return builtin.get("direct", "直连")
    if cls == "block":
        return builtin.get("block", "拒绝")
    return value


def _flip_tag(policy_name, policy):
    """PLACEHOLDER for the unbroken obflip hash (see module docstring).

    Deterministic per policy so the shape is right; the harness
    comparator normalizes these tags before diffing.
    """
    import json
    payload = json.dumps(
        {"name": policy_name,
         "domain": sorted(_str_list(policy.get("domain"))),
         "domainSuffix": sorted(_str_list(policy.get("domainSuffix"))),
         "domainKeyword": sorted(_str_list(policy.get("domainKeyword"))),
         "rulesets": sorted(_str_list(policy.get("rulesets"))),
         "ipCidr": sorted(_str_list(policy.get("ipCidr")))},
        ensure_ascii=False, sort_keys=True)
    return "obflip-" + hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


def _policy_rulesets(policy):
    """(geosite sets, geoip sets) of one policy, in policy order."""
    geosite, geoip = [], []
    for rs in _str_list(policy.get("rulesets")):
        if rs.startswith("geoip-"):
            geoip.append(rs)
        else:
            geosite.append(rs)
    return geosite, geoip


def _policy_domain_match(policy):
    """Domain-class match object for one policy, or None."""
    m = {}
    for key, out_key in (("domain", "domain"),
                         ("domainSuffix", "domain_suffix"),
                         ("domainKeyword", "domain_keyword")):
        vals = _str_list(policy.get(key))
        if vals:
            m[out_key] = vals
    return m or None


def _fnv1a32(text):
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return "%08x" % h


def _policy_list_tags(policy, rule_lists):
    """Downloaded-pending rule-URL tags for one policy.

    Each non-blank ruleUrl becomes list-<fnv1a32(url)> UNLESS
    ruleLists already holds that exact key (the download is
    recorded: downloaded lists contribute nothing to the config).
    A mismatched key ("weird") or a missing key does not suppress
    the tag; a key with no url field still suppresses it (key
    presence is the test). Deduped, ruleUrls order.
    """
    out = []
    for url in _str_list(policy.get("ruleUrls")):
        if not url.strip():
            continue
        tag = "list-" + _fnv1a32(url)
        if tag in rule_lists:
            continue
        if tag not in out:
            out.append(tag)
    return out


def _policy_dns_match(policy, rule_lists=None):
    """DNS match for one policy: domain-class + geosite sets merged.

    The rule_set part is geosite sets + pending list tags (geoip
    sets never enter DNS).
    """
    m = _policy_domain_match(policy) or {}
    geosite, _ = _policy_rulesets(policy)
    rule_sets = list(geosite)
    if rule_lists is not None:
        rule_sets.extend(_policy_list_tags(policy, rule_lists))
    if rule_sets:
        m = dict(m)
        m["rule_set"] = rule_sets
    return m or None


def _need_sets(st, builtin):
    """(geoip_union, bypass_geoip) for the autoRedirect rule sets.

    Golden order (real) is policy order first: Netflix's netflix,
    then 国外's cloudflare..twitter, then direct 国内's cn/private.
    Custom geoip rules (real's google/facebook/twitter) are all
    duplicates of policy sets, so custom-after-policies and
    custom-excluded are indistinguishable on golden; custom sets are
    appended after policies (deduped). Class is selection-aware
    (like classes); all golden selections agree with defaults on
    class, so that choice is unprobed either way.
    geoip_union = need_geoip + bypass_geoip (deduped): it feeds
    BOTH obflip-need-* (after the three fixed entries) and
    obflip-byp-* (the whole list).
    """
    need, bypass, custom_geo = [], [], []
    for p in st.policies:
        _, geoip = _policy_rulesets(p)
        sel = st.selections.get(p["name"])
        cls = _resolve_class(sel if isinstance(sel, str) and sel
                             else _str(p.get("default"), ""), builtin)
        if cls in ("proxy", "block"):
            need.extend(geoip)
        elif cls == "direct":
            bypass.extend(geoip)
    for r in st.custom_rules:
        if r.get("type") == "geoip" and _resolve_class(
                r.get("outbound"), builtin) in ("proxy", "block"):
            custom_geo.append("geoip-" + r["value"])
    need = _dedup(need)
    bypass = _dedup(bypass)
    union = _dedup(need + bypass + custom_geo)
    return union, bypass


def _resolvable_custom(st, public_tags, node_tags, chain_tags, builtin):
    """Custom rules whose outbound resolves, in custom order.

    Resolvable = emit publicTags + policy names + fallback name +
    node tags + kept chain tags + literal direct/block (mapped to
    the builtin tags). Returns list of (rule, resolved_tag).
    """
    policy_names = {p["name"] for p in st.policies}
    ok = set(public_tags) | policy_names | {st.fallback_name}
    ok |= set(node_tags) | set(chain_tags)
    out = []
    for r in st.custom_rules:
        ob = r.get("outbound")
        if ob == "direct":
            out.append((r, builtin.get("direct", "直连")))
        elif ob == "block":
            out.append((r, builtin.get("block", "拒绝")))
        elif ob in ok:
            out.append((r, ob))
    return out


# ------------------------------------------------------------ outbounds

def _convert_node(node):
    """Node/chain entry -> sing-box outbound dict.

    {tag, type, server, server_port} + fields flattened; empty-dict
    field values are dropped; hysteria2 drops down_mbps/up_mbps;
    server_ports is kept. tls: reality-valid (dict, enabled not
    false) -> insecure deleted; tls without reality -> insecure =
    input value, default True; no tls -> no insecure key.
    ws transport: a path containing ?ed=N loses the query string
    and gains early_data_header_name "Sec-WebSocket-Protocol" and
    max_early_data N (int) -- INFERRED as the general ws mechanism
    (371 vless nodes fit it).
    """
    out = {}
    for key in ("tag", "type", "server", "server_port"):
        if node.get(key) is not None:
            out[key] = node[key]
    fields = _dict(node.get("fields"))
    for key, value in fields.items():
        if isinstance(value, dict) and not value:
            continue
        if node.get("type") == "hysteria2" and key in ("down_mbps",
                                                       "up_mbps"):
            continue
        out[key] = value
    # tls.insecure (inside tls, never top-level): reality valid
    # (dict, enabled not false) -> insecure deleted; tls without
    # valid reality -> insecure = input value, default True.
    tls = fields.get("tls")
    if isinstance(tls, dict) and tls:
        t = dict(tls)
        reality = t.get("reality")
        if isinstance(reality, dict) and reality.get("enabled") is not False:
            t.pop("insecure", None)
        elif not isinstance(t.get("insecure"), bool):
            t["insecure"] = True
        out["tls"] = t
    transport = fields.get("transport")
    if isinstance(transport, dict) and transport.get("type") == "ws":
        path = transport.get("path")
        if isinstance(path, str) and "?ed=" in path:
            base, _, query = path.partition("?ed=")
            num = query.split("&")[0].split("#")[0]
            try:
                early = int(num)
            except ValueError:
                early = None
            if early is not None:
                tr = dict(transport)
                tr["path"] = base
                tr["early_data_header_name"] = "Sec-WebSocket-Protocol"
                tr["max_early_data"] = early
                out["transport"] = tr
    return out


def _kept_chains(st, builtin):
    """Chain entries whose detour is not a builtin tag.

    A chain outbound is kept iff detour is not direct/block
    (literal or the builtin tag names). Kept chains keep the detour
    key on top of the node conversion.
    """
    direct = builtin.get("direct", "直连")
    block = builtin.get("block", "拒绝")
    kept = []
    for cn in st.chain_nodes:
        detour = cn.get("detour")
        if detour in ("direct", "block", direct, block):
            continue
        ob = _convert_node(cn)
        ob["detour"] = detour
        kept.append(ob)
    return kept


def _build_outbounds(st, builtin):
    """(outbounds, public_tags, failover, chain_tags, node_tags)."""
    node_obs = [_convert_node(n) for n in st.nodes]
    node_tags = [o["tag"] for o in node_obs if o.get("tag")]
    chain_obs = _kept_chains(st, builtin)
    chain_tags = [o["tag"] for o in chain_obs if o.get("tag")]
    all_in = [{"tag": t} for t in node_tags + chain_tags]
    emit = emit_groups_value(st.user_groups, all_in)
    emit_obs = emit["outbounds"]
    # Dynamic groups expand to all_in, but chain tags are NOT part
    # of a dynamic group's expansion (chain case: 所有-手动/所有-自动
    # stay 588 nodes). Post-filter dynamic groups to node tags.
    from .emit import _normalize_emit_group
    dynamic_tags = set()
    for g in st.user_groups:
        if not isinstance(g, dict):
            continue
        ng = _normalize_emit_group(g, 0)
        if ng["enabled"] and ng["type"] in ("selector", "urltest") \
                and ng["mode"] == "dynamic":
            dynamic_tags.add(ng["name"])
    for ob in emit_obs:
        if ob.get("tag") in dynamic_tags and isinstance(
                ob.get("outbounds"), list):
            filtered = [t for t in ob["outbounds"] if t not in chain_tags]
            ob["outbounds"] = filtered or [builtin.get("direct", "直连")]
    # Group selector default post-processing: a plain selector
    # group's outbound gains default=selections[name] iff the
    # selection is one of its outbounds -- but ONLY when the
    # fakeip DNS server is present (split and fakeIpForProxy).
    # dns-fakeip-off and dns-autoRedirect-off-split-off both drop
    # the defaults (dynamic and static alike); real and
    # dns-static-pick keep them. Failover/urltest/builtin
    # selectors are untouched.
    _split, fakeip_on, _proxy, _local, _rw = _dns_presence(st)
    group_names = {}
    for g in st.user_groups:
        if isinstance(g, dict) and g.get("name"):
            group_names[g["name"]] = g
    for ob in emit_obs:
        if ob.get("type") != "selector" or not fakeip_on:
            continue
        tag = ob.get("tag")
        g = group_names.get(tag)
        if not isinstance(g, dict):
            continue
        if g.get("type") != "selector":
            continue
        sel = st.selections.get(tag)
        if isinstance(sel, str) and sel and sel in (ob.get("outbounds")
                                                    or []):
            ob["default"] = sel
    public_tags = emit["publicTags"]
    outbounds = list(emit_obs)
    for p in st.policies:
        default = _default_tag(_str(p.get("default"), ""), builtin)
        ob = {"outbounds": list(public_tags), "tag": p["name"],
              "type": "selector"}
        if default:
            ob["default"] = default
        outbounds.append(ob)
    fb_default = _default_tag(st.fallback_default, builtin)
    fb_ob = {"outbounds": list(public_tags), "tag": st.fallback_name,
             "type": "selector"}
    # An empty fallback default resolves to direct (minimal proves
    # it); policy selectors with an empty default omit the key
    # (unprobed: every golden policy has a default).
    fb_ob["default"] = fb_default or builtin.get("direct", "直连")
    outbounds.append(fb_ob)
    # Order: emit + policy selectors + nodes + chains LAST (chain
    # case proves it: outbounds[25] is the first node, the kept
    # chain is the final entry).
    outbounds.extend(node_obs)
    outbounds.extend(chain_obs)
    return outbounds, public_tags, emit["failover"], chain_tags, node_tags


# ----------------------------------------------------------- directHosts

def _direct_hosts(st):
    """{domains, cidrs} from node servers + subscription URL hosts.

    Node servers, deduped in node order: hostnames -> domains,
    IPv4 -> cidrs as /32, IPv6 -> cidrs as /128 (INFERRED: no
    golden IPv6 server is ever included, so the /128 suffix is a
    guess). Subscription URL hosts not already present are appended
    in subscription order (hostnames -> domains, IPs -> cidrs).
    directHostCidrs (empty in all golden cases) are appended to
    cidrs, deduped. KNOWN DEVIATION on real: 50 IP servers of one
    subscription are excluded by the golden for no reason visible
    in state; the clean rule includes them.
    """
    domains, cidrs = [], []
    seen_d, seen_c = set(), set()

    def add_host(host):
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is None:
            if host not in seen_d:
                seen_d.add(host)
                domains.append(host)
        elif ip.version == 4:
            cidr = host + "/32"
            if cidr not in seen_c:
                seen_c.add(cidr)
                cidrs.append(cidr)
        else:
            cidr = host + "/128"
            if cidr not in seen_c:
                seen_c.add(cidr)
                cidrs.append(cidr)

    for n in st.nodes:
        server = n.get("server")
        if isinstance(server, str) and server:
            add_host(server)
    for sub in st.subscriptions:
        urls = []
        if isinstance(sub.get("urls"), list):
            urls.extend(sub["urls"])
        if isinstance(sub.get("url"), str):
            urls.append(sub["url"])
        for u in urls:
            try:
                host = urlparse(u).hostname
            except Exception:
                host = None
            if host:
                add_host(host)
    for cidr in st.direct_host_cidrs:
        if cidr not in seen_c:
            seen_c.add(cidr)
            cidrs.append(cidr)
    return {"cidrs": cidrs, "domains": domains}


# ---------------------------------------------------------------- route

def _flip_dir(ruleset_dir):
    if "/" in ruleset_dir:
        return ruleset_dir.rsplit("/", 1)[0] + "/flip"
    return "flip"


def _rule_set_entry(fmt, path, tag):
    return {"format": fmt, "path": path, "tag": tag, "type": "local"}


def _custom_set_tag(rule):
    # Custom rule values are bare ("youtube", "google"); the
    # rule-set tag prefixes them (policies already carry full tags).
    if rule.get("type") == "geosite":
        v = rule["value"]
        return v if v.startswith("geosite-") else "geosite-" + v
    if rule.get("type") == "geoip":
        v = rule["value"]
        return v if v.startswith("geoip-") else "geoip-" + v
    return None


def _quic_reject(match):
    # QUIC reject ports are scalar 443 (unlike the [123]/[53] lists
    # elsewhere); golden proves it for custom and policy rules alike.
    return {"action": "reject", "network": "udp", "port": 443, **match}


def _logical(rules, action=None, outbound=None):
    ob = {"mode": "and", "rules": rules, "type": "logical"}
    if action is not None:
        ob["action"] = action
    if outbound is not None:
        ob["outbound"] = outbound
    return ob


def _build_route(st, builtin, public_tags, node_tags, chain_tags,
                 geoip_union, bypass_geoip):
    direct = builtin.get("direct", "直连")
    resolvable = _resolvable_custom(st, public_tags, node_tags,
                                     chain_tags, builtin)
    # --- rule_set
    rule_set = []
    seen_rs = set()

    def add_rs(entry):
        if entry["tag"] not in seen_rs:
            seen_rs.add(entry["tag"])
            rule_set.append(entry)

    for rule, _tag in resolvable:
        tag = _custom_set_tag(rule)
        if tag:
            add_rs(_rule_set_entry("binary",
                                   st.ruleset_dir + "/" + tag + ".srs",
                                   tag))
    for p in st.policies:
        for rs in _str_list(p.get("rulesets")):
            add_rs(_rule_set_entry("binary",
                                   st.ruleset_dir + "/" + rs + ".srs",
                                   rs))
        for tag in _policy_list_tags(p, st.rule_lists):
            add_rs(_rule_set_entry("binary",
                                   st.ruleset_dir + "/" + tag + ".srs",
                                   tag))
    dns_filter_on = bool(st.dns_filter) and _bool(
        _dict(st.dns.get("filter")).get("enabled"), True)
    if dns_filter_on:
        for s in st.dns_filter.get("sets", []):
            if isinstance(s, dict):
                rule_set.append(dict(s))
    add_rs(_rule_set_entry("source",
                           st.ruleset_dir + "/obnode-direct.json",
                           "obnode-direct"))
    add_rs(_rule_set_entry("source",
                           st.ruleset_dir + "/obnode-direct-ip.json",
                           "obnode-direct-ip"))
    flip_tags = {}
    for p in st.policies:
        tag = _flip_tag(p["name"], p)
        flip_tags[p["name"]] = tag
        add_rs(_rule_set_entry("source",
                               _flip_dir(st.ruleset_dir) + "/" + tag
                               + ".json", tag))
    add_rs(_rule_set_entry("source",
                           _flip_dir(st.ruleset_dir)
                           + "/obflip-fallback.json", "obflip-fallback"))
    need_tags, byp_tags = [], []
    if st.auto_redirect:
        need_tags = ["obflip-need-all", "obflip-need-fakeip",
                     "obflip-need-cidr"] + ["obflip-need-" + s
                                            for s in geoip_union]
        byp_tags = ["obflip-byp-" + s for s in geoip_union]
        for tag in byp_tags:
            add_rs(_rule_set_entry("binary",
                                   _flip_dir(st.ruleset_dir) + "/" + tag
                                   + ".srs", tag))
        for tag in need_tags:
            add_rs(_rule_set_entry("binary",
                                   _flip_dir(st.ruleset_dir) + "/" + tag
                                   + ".srs", tag))
    # --- rules
    rules = []
    custom_sets = _dedup([_custom_set_tag(r) for r, _ in resolvable
                          if _custom_set_tag(r)])
    # The bypass logical exists only with autoRedirect (tun
    # interception on); autoRedirect-off cases start at sniff.
    if custom_sets and st.auto_redirect:
        rules.append(_logical([
            {"rule_set": ["obnode-direct-ip"]},
            {"invert": True, "ip_cidr": ["172.19.0.0/30"]},
            {"invert": True, "rule_set": custom_sets},
            {"invert": True, "port": [53]},
        ], action="bypass"))
    rules.append({"action": "sniff"})
    # Both hijack-dns rules vanish when dns.mode is "disabled".
    if _str(st.dns.get("mode"), "") != "disabled":
        rules.append({"action": "hijack-dns", "protocol": "dns"})
        rules.append({"action": "hijack-dns", "inbound": ["dns-in"]})
    rules.append({"action": "reject", "ip_cidr": ["172.19.0.0/30"]})
    for rule, out_tag in resolvable:
        t, v = rule.get("type"), rule.get("value")
        if t == "geosite":
            tag = _custom_set_tag(rule)
            if st.reject_quic:
                rules.append(_quic_reject({"rule_set": [tag]}))
            rules.append({"outbound": out_tag, "rule_set": [tag]})
        elif t == "geoip":
            tag = "geoip-" + v
            regex = {"domain_regex": [DOMAIN_REGEX], "invert": True}
            if st.reject_quic:
                rules.append(_logical([{"rule_set": [tag]}, regex,
                                       {"network": "udp", "port": 443}],
                                      action="reject"))
            rules.append(_logical([{"rule_set": [tag]}, regex],
                                  outbound=out_tag))
        elif t in ("domain", "domainSuffix", "domainKeyword"):
            key = {"domain": "domain", "domainSuffix": "domain_suffix",
                   "domainKeyword": "domain_keyword"}[t]
            match = {key: [v]}
            if st.reject_quic:
                rules.append(_quic_reject(match))
            rules.append({**match, "outbound": out_tag})
        elif t == "ipCidr":
            # INFERRED: ipCidr customs pair like geoip customs.
            regex = {"domain_regex": [DOMAIN_REGEX], "invert": True}
            if st.reject_quic:
                rules.append(_logical([{"ip_cidr": [v]}, regex,
                                       {"network": "udp", "port": 443}],
                                      action="reject"))
            rules.append(_logical([{"ip_cidr": [v]}, regex],
                                  outbound=out_tag))
    rules.append({"ip_is_private": True, "outbound": direct})
    rules.append({"network": "udp", "outbound": direct, "port": [123]})
    rules.append({"outbound": direct,
                  "rule_set": ["obnode-direct", "obnode-direct-ip"]})
    for p in st.policies:
        name = p["name"]
        flip = flip_tags[name]
        domain_match = _policy_domain_match(p)
        geosite, geoip = _policy_rulesets(p)
        geosite = geosite + _policy_list_tags(p, st.rule_lists)
        cidrs = _str_list(p.get("ipCidr"))
        if domain_match:
            if st.reject_quic:
                rules.append(_logical([domain_match,
                                       {"rule_set": [flip]},
                                       {"network": "udp", "port": 443}],
                                      action="reject"))
            rules.append({**domain_match, "outbound": name})
        if geosite:
            if st.reject_quic:
                rules.append(_logical([{"rule_set": geosite},
                                       {"rule_set": [flip]},
                                       {"network": "udp", "port": 443}],
                                      action="reject"))
            rules.append({"outbound": name, "rule_set": geosite})
        if geoip:
            regex = {"domain_regex": [DOMAIN_REGEX], "invert": True}
            if st.reject_quic:
                rules.append(_logical([{"rule_set": geoip}, regex,
                                       {"rule_set": [flip]},
                                       {"network": "udp", "port": 443}],
                                      action="reject"))
            rules.append(_logical([{"rule_set": geoip}, regex],
                                  outbound=name))
        if cidrs:
            regex = {"domain_regex": [DOMAIN_REGEX], "invert": True}
            if st.reject_quic:
                rules.append(_logical([{"ip_cidr": cidrs}, regex,
                                       {"rule_set": [flip]},
                                       {"network": "udp", "port": 443}],
                                      action="reject"))
            rules.append(_logical([{"ip_cidr": cidrs}, regex],
                                  outbound=name))
    # Catch-all QUIC reject for the fallback flip set, last rule.
    # Minimal (no policies) has none, so it is conditioned on
    # policies being non-empty (and on rejectQuic like all QUIC
    # rejects); no golden case varies rejectQuic.
    if st.policies and st.reject_quic:
        rules.append(_logical([{"rule_set": ["obflip-fallback"]},
                               {"network": "udp", "port": 443}],
                              action="reject"))
    return {
        "auto_detect_interface": True,
        "default_domain_resolver": "dns-direct",
        "final": st.fallback_name,
        "rule_set": rule_set,
        "rules": rules,
    }, need_tags, byp_tags


# ------------------------------------------------ inbounds / misc sections

def _build_inbounds(st, need_tags, byp_tags):
    tun = {"address": ["172.19.0.1/30"], "auto_route": True,
           "interface_name": "openbox-tun",
           "route_exclude_address": list(ROUTE_EXCLUDE_ADDRESS)
           + list(st.local_subnets),
           "stack": _str(st.tun.get("stack"), "") or "mixed",
           "strict_route": True, "tag": "tun-in", "type": "tun",
           "udp_timeout": "60s"}
    mtu = _num(st.tun.get("mtu"))
    if mtu is not None and mtu > 0:
        tun["mtu"] = mtu
    mss = _num(st.tun.get("tcpMss"))
    if mss is not None and mss > 0:
        tun["tcp_mss"] = mss
    if st.auto_redirect:
        tun["auto_redirect"] = True
        tun["dns_address"] = ["172.19.0.2"]
        tun["dns_mode"] = "hijack"
        tun["route_address_set"] = list(need_tags)
        if byp_tags:
            tun["route_exclude_address_set"] = list(byp_tags)
    else:
        tun["dns_mode"] = "disabled"
        # With autoRedirect off, a native bypass (enabled, non-empty
        # sets) still lands as route_exclude_address_set with the
        # RAW set names (not obflip-byp tags). With autoRedirect on,
        # nativeBypass is ignored (flip sets take over).
        nb = st.native_bypass
        if nb and nb.get("enabled"):
            sets = _str_list(nb.get("sets"))
            if sets:
                tun["route_exclude_address_set"] = sets
    inbounds = [tun,
                {"listen": "127.0.0.1", "listen_port": 7891,
                 "tag": "panel-in", "type": "mixed"},
                {"listen": "0.0.0.0", "listen_port": 7853,
                 "tag": "dns-in", "type": "direct"}]
    for srv in st.profile.get("servers", []) \
            if isinstance(st.profile.get("servers"), list) else []:
        if not isinstance(srv, dict):
            continue
        if not _bool(srv.get("enabled"), True):
            continue
        inbounds.append({"listen": "::",
                         "listen_port": srv.get("port"),
                         "tag": "share-" + _str(srv.get("id"), ""),
                         "type": _str(srv.get("protocol"), "")})
    return inbounds


def _dns_presence(st):
    """(split, fakeip, proxy, local, rewrite) server presence."""
    dns = st.dns
    split = _bool(dns.get("split"), False)
    fakeip = split and _bool(dns.get("fakeIpForProxy"), False)
    proxy = split
    local = _str(dns.get("mode"), "") != "disabled"
    # The rewrite server exists only when the rewrite section itself
    # is present (minimal has no rewrite key at all -> no server)
    # and enabled is not false (real has no enabled key -> present).
    rw = dns.get("rewrite")
    rewrite = isinstance(rw, dict) and _bool(rw.get("enabled"), True)
    return split, fakeip, proxy, local, rewrite


def _build_experimental(st, fakeip):
    path = st.cache_path
    if fakeip:
        path += ".fakeip-198_19_0_0_16_fc00___18"
    return {
        "cache_file": {"enabled": True, "path": path,
                       "store_fakeip": fakeip},
        "clash_api": {
            "external_controller": "127.0.0.1:9095",
            "secret": _str(st.profile.get("clashApiSecret"), ""),
        },
    }


# -------------------------------------------------------------------- dns

def _custom_dns_match(rule):
    t, v = rule.get("type"), rule.get("value")
    if t == "geosite":
        return {"rule_set": [_custom_set_tag(rule)]}
    if t == "domain":
        return {"domain": [v]}
    if t == "domainSuffix":
        return {"domain_suffix": [v]}
    if t == "domainKeyword":
        return {"domain_keyword": [v]}
    return None


def _build_dns(st, flip_tags, direct_hosts):
    dns = st.dns
    split, fakeip, proxy, local, rewrite_on = _dns_presence(st)
    servers = []
    direct_val = _str(dns.get("direct"), "")
    try:
        ipaddress.ip_address(direct_val)
        direct_server = direct_val
    except ValueError:
        direct_server = "223.5.5.5" if direct_val in ("", "wan") \
            else direct_val
    direct_ob = {"server": direct_server, "tag": "dns-direct",
                 "type": _str(dns.get("directProtocol"), "") or "udp"}
    port = _num(dns.get("directPort"))
    if port is not None and port != 53:
        direct_ob["server_port"] = port
    servers.append(direct_ob)
    if rewrite_on:
        servers.append({"server": "127.0.0.1", "server_port": 7854,
                        "tag": "dns-rewrite", "type": "udp"})
    if proxy:
        proxy_ob = {"detour": st.fallback_name,
                    "server": _str(dns.get("proxy"), ""),
                    "tag": "dns-proxy",
                    "type": _str(dns.get("proxyProtocol"), "") or "udp"}
        pport = _num(dns.get("proxyPort"))
        if pport is not None and pport != 53:
            proxy_ob["server_port"] = pport
        servers.append(proxy_ob)
    if fakeip:
        fakeip_ob = {"inet4_range": "198.19.0.0/16",
                     "tag": "dns-fakeip", "type": "fakeip"}
        if _bool(st.profile.get("ipv6"), False):
            fakeip_ob["inet6_range"] = "fc00::/18"
        servers.append(fakeip_ob)
    if local:
        servers.append({"tag": "dns-local", "type": "local"})
    rules = []
    owners = []

    def emit_owner(index, name, start, kind):
        if len(rules) > start:
            owners.append({"from": start, "index": index, "kind": kind,
                           "name": name, "to": len(rules)})

    if rewrite_on:
        sources = []
        for r in _dict(dns.get("rewrite")).get("rules", []) \
                if isinstance(_dict(dns.get("rewrite")).get("rules"),
                              list) else []:
            if isinstance(r, dict) and _bool(r.get("enabled"), True) \
                    and isinstance(r.get("source"), str) and r["source"]:
                if r["source"] not in sources:
                    sources.append(r["source"])
        if sources:
            rules.append({"domain": sources, "server": "dns-rewrite"})
    if local:
        rules.append({"domain_suffix": [".lan", ".local", ".home",
                                        ".internal", ".home.arpa"],
                      "server": "dns-local"})
        rules.append({"domain_regex": ["^[^.]+$"], "server": "dns-local"})
    if split:
        rules.append({"action": "predefined",
                      "query_type": ["HTTPS", "SVCB"], "rcode": "NOERROR"})
    dns_filter_on = bool(st.dns_filter) and _bool(
        _dict(dns.get("filter")).get("enabled"), True)
    if dns_filter_on:
        allow = _str_list(st.dns_filter.get("allow"))
        for block in st.dns_filter.get("blocks", []) \
                if isinstance(st.dns_filter.get("blocks"), list) else []:
            if not isinstance(block, dict):
                continue
            inner = [{"rule_set": [block.get("tag")]}]
            if allow:
                inner.append({"invert": True, "rule_set": allow})
            rules.append({"action": "predefined", "mode": "and",
                          "rcode": "NXDOMAIN", "rules": inner,
                          "type": "logical"})
    for i, rule in enumerate(st.custom_rules):
        match = _custom_dns_match(rule)
        if match is None:
            continue
        start = len(rules)
        if fakeip:
            rules.append({**match, "query_type": ["A"],
                          "server": "dns-fakeip"})
        if proxy:
            rules.append({**match, "server": "dns-proxy"})
        emit_owner(i, "", start, "custom")
    # The obnode DNS rule needs a split DNS to be useful: with
    # split off (no proxy/fakeip server) it is omitted even when
    # directHosts is non-empty (split-off proves it).
    if (direct_hosts["domains"] or direct_hosts["cidrs"]) \
            and (proxy or fakeip):
        start = len(rules)
        rules.append({"rule_set": ["obnode-direct"],
                      "server": "dns-direct"})
        emit_owner(0, "", start, "directHosts")
    for pi, p in enumerate(st.policies):
        match = _policy_dns_match(p, st.rule_lists)
        if match is None:
            continue
        start = len(rules)
        flip = flip_tags[p["name"]]
        if fakeip:
            rules.append({"mode": "and",
                          "rules": [match, {"rule_set": [flip]},
                                    {"query_type": ["A"]}],
                          "server": "dns-fakeip", "type": "logical"})
        if proxy:
            rules.append({"mode": "and",
                          "rules": [match, {"rule_set": [flip]}],
                          "server": "dns-proxy", "type": "logical"})
        if proxy or fakeip:
            rules.append({**match, "server": "dns-direct"})
        emit_owner(pi, p["name"], start, "policy")
    if proxy or fakeip:
        start = len(rules)
        if fakeip:
            rules.append({"mode": "and",
                          "rules": [{"rule_set": ["obflip-fallback"]},
                                    {"query_type": ["A"]}],
                          "server": "dns-fakeip", "type": "logical"})
        if proxy:
            rules.append({"rule_set": ["obflip-fallback"],
                          "server": "dns-proxy"})
        emit_owner(0, st.fallback_name, start, "fallback")
    strategy = "ipv4_only"
    if _bool(st.profile.get("ipv6"), False):
        strategy = "prefer_ipv4"  # INFERRED: no ipv6-open golden case.
    return {
        "final": "dns-direct",
        "reverse_mapping": True,
        "rules": rules,
        "servers": servers,
        "strategy": strategy,
    }, owners


# -------------------------------------------------------------------- main

def config_detailed(args):
    st = _State(args[0] if args else None)
    # Builtin tags come from emit (userGroups may rename them).
    probe = emit_groups_value(st.user_groups, [])
    builtin = probe["builtin"]
    node_tags = [n["tag"] for n in st.nodes
                 if isinstance(n.get("tag"), str)]
    chain_obs = _kept_chains(st, builtin)
    chain_tags = [o["tag"] for o in chain_obs if o.get("tag")]
    outbounds, public_tags, failover, _ct, _nt = _build_outbounds(
        st, builtin)
    geoip_union, _bypass = _need_sets(st, builtin)
    route, need_tags, byp_tags = _build_route(
        st, builtin, public_tags, node_tags, chain_tags, geoip_union,
        _bypass)
    inbounds = _build_inbounds(st, need_tags, byp_tags)
    direct_hosts = _direct_hosts(st)
    flip_tags = {p["name"]: _flip_tag(p["name"], p)
                 for p in st.policies}
    _split, fakeip, _proxy, _local, _rw = _dns_presence(st)
    dns, owners = _build_dns(st, flip_tags, direct_hosts)
    experimental = _build_experimental(st, fakeip)
    config = {
        "dns": dns,
        "experimental": experimental,
        "inbounds": inbounds,
        "log": {"level": "warn"},
        "outbounds": outbounds,
        "route": route,
    }
    return {
        "config": config,
        "directHosts": direct_hosts,
        "dnsRuleOwners": owners,
        "failover": failover,
    }
