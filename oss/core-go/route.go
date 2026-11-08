// Route-rule generation: a Go port of oss/core/singbox.py's
// build_route_rules (plus _front_url_tag / front_remote_rule_sets).
//
// The Python function mutates the AppConfig with side-effect
// attributes (_remote_rulesets, _obflip_rulesets, _obnode_direct,
// _front_remote_rs) that build_config later reads for rule-set
// declarations. Here those become fields of RouteResult instead:
// the core is a pure function, so nothing is smuggled through
// mutable state.
package main

import (
	"crypto/sha1"
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// Content-filter kernel rule-set tags (oss/core/dnsfilter.py).
const (
	kernelBlockTag = "dns-filter-anti-ad-block"
	kernelAllowTag = "dns-filter-anti-ad-allow"
)

// inlineRuleSets are rule sets expanded inline instead of downloaded
// (fixed, well-known ranges; oss/core/geodata.py INLINE_RULE_SETS).
var inlineRuleSets = map[string][]string{
	"geoip-private": {
		"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
		"127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
		"::1/128", "fc00::/7", "fe80::/10",
	},
}

// TagURL is one (tag, url) pair, in insertion order.
type TagURL struct {
	Tag string
	URL string
}

// TagRules is one (tag, rules) pair, in insertion order.
type TagRules struct {
	Tag   string
	Rules []*Obj
}

// ObnodeDirect is the direct-host domain/CIDR set (1:1 with the
// original's obnode-direct / obnode-direct-ip rule sets).
type ObnodeDirect struct {
	Domains []string
	Cidrs   []string
}

// RouteResult is everything buildRouteRules produces: the two rule
// lists plus the side-effect collections build_config needs for
// rule-set declarations.
type RouteResult struct {
	RouteRules     []*Obj
	DNSRules       []*Obj
	GroupNames     map[string]bool
	RemoteRulesets []TagURL   // site-set ruleset_urls, insertion order
	ObflipRulesets []TagRules // per-site-set QUIC inline sets
	ObnodeDirect   ObnodeDirect
	FrontRemoteRS  []TagURL // front ruleset_url (.srs), insertion order
}

// frontURLTag returns the stable rule-set tag for a front ruleset_url.
func frontURLTag(url string) string {
	sum := sha1.Sum([]byte(url))
	return "url-" + fmt.Sprintf("%x", sum)[:12]
}

// frontRemoteRuleSets returns (tag, url) pairs for front ruleset_url
// rules pointing at .srs files, in front-rule order, deduplicated by
// tag. (Recomputed, no enabled check — used by build_config for
// declarations.)
func frontRemoteRuleSets(p Profile) []TagURL {
	var out []TagURL
	seen := map[string]bool{}
	for _, fr := range p.FrontRules {
		if fr == nil {
			continue
		}
		if Str(fr.Get("rtype")) != "ruleset_url" {
			continue
		}
		url := strings.TrimSpace(Str(fr.Get("domain")))
		if !strings.HasSuffix(strings.ToLower(url), ".srs") {
			continue
		}
		tag := frontURLTag(url)
		if !seen[tag] {
			seen[tag] = true
			out = append(out, TagURL{Tag: tag, URL: url})
		}
	}
	return out
}

// buildRouteRules builds (route_rules, dns_rules, group_names) from
// site sets, front rules, terminals and the content filter. provenance,
// when non-nil, receives one owner record per route rule, in the same
// order (the route oracle maps a matched rule back to its producer).
// dnsProvenance is the same, one owner record per DNS rule, in the
// same order as DNSRules.
func buildRouteRules(p Profile, skipRuleSets map[string]bool, provenance, dnsProvenance *[]*Obj) RouteResult {
	groups := p.Groups
	if len(groups) == 0 {
		groups = defaultGroups()
	}
	groupNames := map[string]bool{}
	for _, g := range groups {
		groupNames[g.Name] = true
	}
	res := RouteResult{GroupNames: groupNames}
	prov := func(rec *Obj) {
		if provenance != nil {
			*provenance = append(*provenance, rec)
		}
	}
	dnsProv := func(rec *Obj) {
		if dnsProvenance != nil {
			*dnsProvenance = append(*dnsProvenance, rec)
		}
	}
	jstrs := func(ss []string) []JVal {
		a := make([]JVal, 0, len(ss))
		for _, s := range ss {
			a = append(a, s)
		}
		return a
	}

	// Rule 0: logical ingress bypass (1:1 with the original).
	if p.DirectBypassEnabledOr() {
		var proxyGeosites []string
		for _, s := range p.SiteSets {
			if s.Action != "proxy" {
				continue
			}
			for _, gs := range s.Geosite {
				tag := "geosite-" + gs
				if !containsStr(proxyGeosites, tag) {
					proxyGeosites = append(proxyGeosites, tag)
				}
			}
		}
		logical := []*Obj{
			O("rule_set", "obnode-direct-ip"),
			O("invert", true, "ip_cidr", "172.19.0.0/30"),
		}
		if len(proxyGeosites) > 0 {
			logical = append(logical, O("invert", true, "rule_set", jstrs(proxyGeosites)))
		}
		logical = append(logical, O("invert", true, "port", float64(53)))
		logicalRules := make([]JVal, 0, len(logical))
		for _, r := range logical {
			logicalRules = append(logicalRules, r)
		}
		res.RouteRules = append(res.RouteRules, O(
			"type", "logical", "mode", "and",
			"rules", logicalRules, "outbound", "direct",
		))
		prov(O("kind", "bypass", "name", "入口直连旁路"))
	}

	// Terminal policies: direct terminals bypass at the route level.
	if len(p.TerminalDirectCidrs) > 0 {
		res.RouteRules = append(res.RouteRules, O(
			"source_ip_cidr", jstrs(p.TerminalDirectCidrs), "outbound", "direct",
		))
		prov(O("kind", "terminal", "name", "终端直连策略"))
	}
	// IPv6 supplement for MAC terminals (v0.1.343), minus addresses
	// the main rule already covers.
	var directV6 []string
	for _, ip := range p.TerminalDirectV6 {
		if !containsStr(p.TerminalDirectCidrs, ip) {
			directV6 = append(directV6, ip)
		}
	}
	if len(directV6) > 0 {
		res.RouteRules = append(res.RouteRules, O(
			"source_ip_cidr", jstrs(directV6), "outbound", "direct",
		))
		prov(O("kind", "terminal", "name", "终端直连 IPv6 补充策略"))
	}

	// Terminal rules: proxy policy -> source_ip_cidr to outbound.
	for _, tr := range p.TerminalRules {
		if tr.Policy != "proxy" || tr.Outbound == "" {
			continue
		}
		if len(tr.Cidrs) > 0 {
			res.RouteRules = append(res.RouteRules, O(
				"source_ip_cidr", jstrs(tr.Cidrs), "outbound", tr.Outbound,
			))
			prov(O("kind", "terminal", "name", "终端策略（"+tr.Outbound+"）"))
		}
		if tr.MatchBy == "mac" {
			var v6 []string
			for _, ip := range tr.V6Cidrs {
				if !containsStr(tr.Cidrs, ip) {
					v6 = append(v6, ip)
				}
			}
			if len(v6) > 0 {
				res.RouteRules = append(res.RouteRules, O(
					"source_ip_cidr", jstrs(v6), "outbound", tr.Outbound,
				))
				prov(O("kind", "terminal", "name", "终端 IPv6 补充策略（"+tr.Outbound+"）"))
			}
		}
	}

	// Content filter: DNS-layer interception when the apply flow
	// prepared kernel rule sets; otherwise fall back to the old
	// route-layer rule so blocking never stops.
	blocked := p.BlockedDomains
	var dfBlockTags []string
	dfAllowTag := ""
	for _, s := range p.DNSFilterRulesets {
		if s.Tag == kernelBlockTag || strings.HasPrefix(s.Tag, kernelBlockTag+"-") {
			dfBlockTags = append(dfBlockTags, s.Tag)
		}
		if s.Tag == kernelAllowTag && dfAllowTag == "" {
			dfAllowTag = s.Tag
		}
	}
	if len(blocked) > 0 && !(len(dfBlockTags) > 0 && dfAllowTag != "") {
		res.RouteRules = append(res.RouteRules, O(
			"domain_suffix", jstrs(blocked), "outbound", "block",
		))
		prov(O("kind", "content", "name", "内容过滤"))
	}

	// Front custom routing, evaluated before every site set.
	for frIdx, fr := range p.FrontRules {
		if fr == nil {
			continue
		}
		if !Truthy(GetOr(fr, "enabled", true)) {
			continue
		}
		rtype := strings.TrimSpace(Str(fr.Get("rtype")))
		if rtype == "" {
			rtype = "domain_suffix"
		}
		val := strings.TrimSpace(Str(fr.Get("domain")))
		if val == "" {
			continue
		}
		target := strings.TrimSpace(Str(fr.Get("target")))
		if target == "" {
			target = "所有-自动"
		}
		var rule, dnsSel *Obj
		switch rtype {
		case "domain":
			rule = O("domain", []JVal{val})
			dnsSel = O("domain", []JVal{val})
		case "domain_keyword":
			rule = O("domain_keyword", []JVal{val})
			dnsSel = O("domain_keyword", []JVal{val})
		case "ip_cidr":
			rule = O("ip_cidr", []JVal{val})
		case "geosite":
			rule = O("rule_set", []JVal{"geosite-" + val})
			dnsSel = O("rule_set", []JVal{"geosite-" + val})
		case "geoip":
			rule = O("rule_set", []JVal{"geoip-" + val})
		case "ruleset_url":
			if !strings.HasSuffix(strings.ToLower(val), ".srs") {
				continue // surfaced via front_rule_warnings()
			}
			tag := frontURLTag(val)
			rule = O("rule_set", []JVal{tag})
			dnsSel = O("rule_set", []JVal{tag})
			found := false
			for _, t := range res.FrontRemoteRS {
				if t.Tag == tag {
					found = true
				}
			}
			if !found {
				res.FrontRemoteRS = append(res.FrontRemoteRS, TagURL{Tag: tag, URL: val})
			}
		case "port":
			if strings.Contains(val, "-") {
				rule = O("port_range", []JVal{val})
			} else {
				n, err := strconv.Atoi(val)
				if err != nil {
					continue
				}
				rule = O("port", []JVal{float64(n)})
			}
		default: // domain_suffix (covers legacy rows)
			v := strings.TrimLeft(val, ".")
			rule = O("domain_suffix", []JVal{v})
			dnsSel = O("domain_suffix", []JVal{v})
		}
		dnsSrv := "dns-proxy"
		switch target {
		case "direct":
			rule.Set("outbound", "direct")
			dnsSrv = "dns-direct"
		case "reject":
			rule.Set("action", "reject")
			dnsSrv = "dns-direct"
		default:
			rule.Set("outbound", target)
			if p.DNSFakeIP() {
				dnsSrv = "dns-fakeip"
			}
		}
		res.RouteRules = append(res.RouteRules, rule)
		prov(O("kind", "front", "name", "前置自定义分流",
			"ref", float64(frIdx), "note", Str(fr.Get("note"))))
		if dnsSel != nil {
			dnsSel.Set("server", dnsSrv)
			res.DNSRules = append(res.DNSRules, dnsSel)
			dnsProv(O("kind", "front", "name", "前置自定义分流",
				"ref", float64(frIdx), "note", Str(fr.Get("note"))))
		}
	}

	// Subscription & node server domains go direct (obnode-direct sets).
	if p.SubNodeDirect {
		obDomains := append([]string(nil), p.ObnodeDomains...)
		obCidrs := append([]string(nil), p.ObnodeCidrs...)
		sort.Strings(obDomains)
		sort.Strings(obCidrs)
		res.ObnodeDirect = ObnodeDirect{Domains: obDomains, Cidrs: obCidrs}
		if len(obDomains) > 0 || len(obCidrs) > 0 {
			res.RouteRules = append(res.RouteRules, O(
				"rule_set", []JVal{"obnode-direct", "obnode-direct-ip"},
				"outbound", "direct",
			))
			prov(O("kind", "obnode", "name", "订阅与节点直连"))
			if len(obDomains) > 0 {
				res.DNSRules = append(res.DNSRules, O(
					"rule_set", []JVal{"obnode-direct"}, "server", "dns-direct",
				))
				dnsProv(O("kind", "obnode", "name", "订阅与节点直连"))
			}
		}
	}

	// Site sets, top-down, first hit wins.
	for _, s := range p.SiteSets {
		rule := O()
		if len(s.Domains) > 0 {
			rule.Set("domain", jstrs(s.Domains))
		}
		if len(s.DomainSuffix) > 0 {
			rule.Set("domain_suffix", jstrs(s.DomainSuffix))
		}
		if len(s.DomainKeyword) > 0 {
			rule.Set("domain_keyword", jstrs(s.DomainKeyword))
		}
		if len(s.IPCidr) > 0 {
			rule.Set("ip_cidr", jstrs(s.IPCidr))
		}
		if len(s.Ports) > 0 {
			rule.Set("port", s.Ports)
		}
		for _, url := range s.RulesetURLs {
			url = strings.TrimSpace(url)
			if url == "" {
				continue
			}
			tag := ""
			for _, t := range res.RemoteRulesets {
				if t.URL == url {
					tag = t.Tag
				}
			}
			if tag == "" {
				tag = fmt.Sprintf("url-%d", len(res.RemoteRulesets))
				res.RemoteRulesets = append(res.RemoteRulesets, TagURL{Tag: tag, URL: url})
			}
			existing := Arr(rule.Get("rule_set"))
			present := false
			for _, e := range existing {
				if Str(e) == tag {
					present = true
				}
			}
			if !present {
				existing = append(existing, tag)
			}
			rule.Set("rule_set", existing)
		}
		var rs []string
		for _, n := range s.RuleSets {
			if inline, ok := inlineRuleSets[n]; ok {
				// Fixed well-known ranges: expand inline.
				existing := Arr(rule.Get("ip_cidr"))
				for _, c := range inline {
					existing = append(existing, c)
				}
				rule.Set("ip_cidr", existing)
			} else if skipRuleSets == nil || !skipRuleSets[n] {
				rs = append(rs, n)
			}
		}
		if len(rs) > 0 {
			// NOTE: this overwrites any rule_set from ruleset_urls
			// above — faithful to the Python generator.
			rule.Set("rule_set", jstrs(rs))
		}
		if len(rule.Keys) == 0 {
			continue
		}
		var target *string
		if s.Action != "reject" {
			t := flipTag(s)
			target = &t
		}
		// Per-site-set QUIC blocking (obflip mechanism).
		eff := s.Flip
		if eff == "" {
			eff = s.Action
		}
		eff = strings.TrimSpace(eff)
		if p.QuicBlockOr() && eff == "proxy" {
			obTag := obflipTag(s)
			var obRules []*Obj
			for _, k := range []string{"domain", "domain_suffix", "domain_keyword", "ip_cidr"} {
				if v := rule.Get(k); v != nil {
					obRules = append(obRules, O(k, v))
				}
			}
			if len(obRules) > 0 {
				found := false
				for i, t := range res.ObflipRulesets {
					if t.Tag == obTag {
						res.ObflipRulesets[i].Rules = obRules
						found = true
					}
				}
				if !found {
					res.ObflipRulesets = append(res.ObflipRulesets, TagRules{Tag: obTag, Rules: obRules})
				}
				res.RouteRules = append(res.RouteRules, O(
					"rule_set", []JVal{obTag},
					"network", "udp", "port", float64(443), "action", "reject",
				))
				prov(O("kind", "quic", "name", "QUIC 拦截："+s.Name))
			} else if v := Arr(rule.Get("rule_set")); len(v) > 0 {
				res.RouteRules = append(res.RouteRules, O(
					"rule_set", v,
					"network", "udp", "port", float64(443), "action", "reject",
				))
				prov(O("kind", "quic", "name", "QUIC 拦截："+s.Name))
			}
		}
		routeRule := copyObj(rule)
		if target == nil {
			routeRule.Set("action", "reject")
		} else {
			routeRule.Set("outbound", *target)
		}
		res.RouteRules = append(res.RouteRules, routeRule)
		prov(O("kind", "siteset", "name", s.Name, "group", s.Group))
		// Companion DNS rule: domain-type matches only (sing-box
		// 1.14 FATALs on IP-type matches in a DNS table that also
		// has query_type rules).
		dnsServer := "dns-direct"
		if s.Action == "proxy" {
			if p.DNSFakeIP() {
				dnsServer = "dns-fakeip"
			} else {
				dnsServer = "dns-proxy"
			}
		}
		dnsRule := O()
		for _, k := range []string{"domain", "domain_suffix", "domain_keyword"} {
			if v := rule.Get(k); v != nil {
				dnsRule.Set(k, v)
			}
		}
		var dnsRS []string
		for _, e := range Arr(rule.Get("rule_set")) {
			if t := Str(e); t != "" && !strings.HasPrefix(t, "geoip-") {
				dnsRS = append(dnsRS, t)
			}
		}
		if len(dnsRS) > 0 {
			dnsRule.Set("rule_set", jstrs(dnsRS))
		}
		if len(dnsRule.Keys) > 0 {
			dnsRule.Set("server", dnsServer)
			res.DNSRules = append(res.DNSRules, dnsRule)
			dnsProv(O("kind", "siteset", "name", s.Name, "group", s.Group))
		}
	}

	// DNS-layer content filter (original shape): NOERROR for HTTPS/SVCB
	// first, then one NXDOMAIN logical rule per block shard, prepended
	// to the DNS rules.
	if len(blocked) > 0 && len(dfBlockTags) > 0 && dfAllowTag != "" {
		dfDNS := []*Obj{O(
			"action", "predefined",
			"query_type", []JVal{"HTTPS", "SVCB"},
			"rcode", "NOERROR",
		)}
		for _, tag := range dfBlockTags {
			dfDNS = append(dfDNS, O(
				"action", "predefined", "mode", "and", "rcode", "NXDOMAIN",
				"rules", []JVal{
					O("rule_set", []JVal{tag}),
					O("invert", true, "rule_set", []JVal{dfAllowTag}),
				},
				"type", "logical",
			))
		}
		res.DNSRules = append(dfDNS, res.DNSRules...)
		if dnsProvenance != nil {
			owners := make([]*Obj, 0, len(dfDNS))
			for range dfDNS {
				owners = append(owners, O("kind", "content", "name", "内容过滤"))
			}
			*dnsProvenance = append(owners, *dnsProvenance...)
		}
	}
	return res
}
