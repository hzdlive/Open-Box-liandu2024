// Config assembly: a Go port of oss/core/singbox.py's build_config
// (plus _dns_server / _dns_servers / _share_server_inbound and the
// geodata helpers it uses). The dns-filter rule-set FILES are written
// by the dnsfilter slice; here only their declarations are emitted.
package main

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// dnsServer builds one sing-box >= 1.12 DNS server entry. A detour of
// "direct" is omitted: sing-box rejects DNS servers whose detour
// points at a plain direct outbound.
func dnsServer(tag, addr, detour string) *Obj {
	a := strings.TrimSpace(addr)
	low := strings.ToLower(a)
	var extra [][2]string
	if detour != "direct" {
		extra = append(extra, [2]string{"detour", detour})
	}
	mk := func(typ, server string) *Obj {
		o := O("type", typ, "tag", tag, "server", server)
		for _, kv := range extra {
			o.Set(kv[0], kv[1])
		}
		return o
	}
	if strings.HasPrefix(low, "https://") {
		return mk("https", a)
	}
	for _, s := range [][2]string{
		{"tls://", "tls"}, {"tcp://", "tcp"},
		{"quic://", "quic"}, {"dhcp://", "dhcp"},
	} {
		if strings.HasPrefix(low, s[0]) {
			return mk(s[1], a[len(s[0]):])
		}
	}
	return mk("udp", a)
}

// stripUpstreamLabel strips the frontend display label
// "上游 DNS [addr]". A bare label means system DNS ("wan").
func stripUpstreamLabel(addr string) string {
	a := strings.TrimSpace(addr)
	if strings.Contains(a, "上游 DNS") {
		parts := strings.SplitN(a, "上游 DNS", 2)
		a = strings.TrimSpace(parts[1])
		if a == "" {
			return "wan"
		}
		return a
	}
	return a
}

// dnsServers renders one entry per comma-separated upstream; the first
// keeps the canonical tag. "wan" resolves to the panel-supplied
// system/WAN servers. With latency measurements, the fastest upstream
// goes first (primary), the rest are backups.
func dnsServers(tag, addrs, detour string, latency map[string]JVal, wan []string) []*Obj {
	raw := strings.TrimSpace(addrs)
	var parts []string
	if strings.ToLower(raw) == "wan" {
		parts = append(parts, wan...)
	} else {
		for _, x := range strings.Split(raw, ",") {
			x = stripUpstreamLabel(x)
			if x == "" {
				continue
			}
			if strings.ToLower(x) == "wan" {
				parts = append(parts, wan...)
			} else {
				parts = append(parts, x)
			}
		}
	}
	if len(parts) == 0 {
		parts = []string{"223.5.5.5"}
	}
	if len(latency) > 0 {
		norm := map[string]float64{}
		for k, v := range latency {
			norm[stripUpstreamLabel(k)] = Num(v)
		}
		type indexed struct {
			addr string
			idx  int
			lat  float64
		}
		arr := make([]indexed, len(parts))
		for i, a := range parts {
			lat, ok := norm[a]
			if !ok {
				lat = math.Inf(1)
			}
			arr[i] = indexed{a, i, lat}
		}
		sort.SliceStable(arr, func(i, j int) bool {
			if arr[i].lat != arr[j].lat {
				return arr[i].lat < arr[j].lat
			}
			return arr[i].idx < arr[j].idx
		})
		parts = parts[:0]
		for _, e := range arr {
			parts = append(parts, e.addr)
		}
	}
	out := make([]*Obj, 0, len(parts))
	for i, a := range parts {
		t := tag
		if i != 0 {
			t = fmt.Sprintf("%s-%d", tag, i)
		}
		out = append(out, dnsServer(t, a, detour))
	}
	return out
}

// geodataDir returns the directory holding the local .srs files:
// $OBX_GEODATA, else <workdir>/geodata.
func geodataDir(workdir string) string {
	if v := os.Getenv("OBX_GEODATA"); v != "" {
		return v
	}
	return filepath.Join(workdir, "geodata")
}

// localPath returns the local .srs path for a rule-set name.
func localPath(workdir, name string) string {
	return filepath.Join(geodataDir(workdir), name+".srs")
}

// referencedRuleSets returns all rule-set names referenced by site
// sets and front rules, in first-seen order. Inline-expanded names
// need no file and are excluded.
func referencedRuleSets(p Profile) []string {
	var out []string
	add := func(names []string) {
		for _, n := range names {
			n = strings.TrimSpace(n)
			if n == "" || containsStr(out, n) {
				continue
			}
			if _, ok := inlineRuleSets[n]; ok {
				continue
			}
			out = append(out, n)
		}
	}
	for _, s := range p.SiteSets {
		add(s.RuleSets)
	}
	for _, fr := range p.FrontRules {
		if fr == nil {
			continue
		}
		rt := Str(fr.Get("rtype"))
		if rt == "" {
			rt = "domain_suffix"
		}
		val := strings.TrimSpace(Str(fr.Get("domain")))
		if (rt == "geosite" || rt == "geoip") && val != "" {
			add([]string{rt + "-" + val})
		}
	}
	return out
}

// shareServerInbound builds a sing-box inbound for a share server.
func shareServerInbound(s *Obj) *Obj {
	proto := Str(s.Get("protocol"))
	if proto == "" {
		proto = "shadowsocks"
	}
	idStr := func() string {
		switch v := s.Get("id").(type) {
		case float64:
			return strconv.FormatFloat(v, 'f', -1, 64)
		case string:
			return v
		default:
			return ""
		}
	}()
	port := 0
	switch v := s.Get("port").(type) {
	case float64:
		port = int(v)
	case string:
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			port = n
		}
	}
	params := ObjVal(s.Get("params"))
	if params == nil {
		if str, ok := s.Get("params").(string); ok && str != "" {
			if v, err := parseJVal([]byte(str)); err == nil {
				params = ObjVal(v)
			}
		}
	}
	if params == nil {
		params = O()
	}
	base := O("tag", "share-"+idStr, "listen", "0.0.0.0", "listen_port", float64(port))
	tlsObj := func() *Obj {
		return O("enabled", true,
			"server_name", Str(params.Get("sni")),
			"certificate_path", Str(params.Get("cert_path")),
			"key_path", Str(params.Get("key_path")))
	}
	switch proto {
	case "shadowsocks":
		base.Set("type", "shadowsocks")
		base.Set("method", GetOr(s, "method", "aes-256-gcm"))
		base.Set("password", GetOr(s, "password", ""))
	case "vless":
		tls := tlsObj()
		if Str(tls.Get("server_name")) == "" {
			removeKey(tls, "server_name")
		}
		base.Set("type", "vless")
		base.Set("users", []JVal{O("uuid", GetOr(s, "password", ""), "flow", GetOr(params, "flow", ""))})
		base.Set("tls", tls)
	case "tuic":
		base.Set("type", "tuic")
		base.Set("users", []JVal{O("uuid", GetOr(s, "password", ""), "password", GetOr(s, "password", ""))})
		base.Set("congestion_control", GetOr(params, "congestion_control", "bbr"))
		base.Set("tls", tlsObj())
	case "hysteria2":
		base.Set("type", "hysteria2")
		base.Set("users", []JVal{O("password", GetOr(s, "password", ""))})
		base.Set("tls", tlsObj())
		if v := params.Get("obfs"); Truthy(v) {
			base.Set("obfs", v)
		}
	case "socks5http":
		base.Set("type", "mixed")
		var users []JVal
		if Truthy(params.Get("username")) {
			users = []JVal{O("username", GetOr(params, "username", ""), "password", GetOr(s, "password", ""))}
		} else {
			users = []JVal{}
		}
		base.Set("users", users)
	default:
		base.Set("type", "shadowsocks")
		base.Set("method", GetOr(s, "method", "aes-256-gcm"))
		base.Set("password", GetOr(s, "password", ""))
	}
	return base
}

// reorderRulesForOriginal reorders route rules to match the original:
// logical bypass first, then sniff, then the two hijack-dns rules,
// then everything else.
func reorderRulesForOriginal(rules []*Obj) []*Obj {
	var logical, other []*Obj
	for _, r := range rules {
		if Str(r.Get("type")) == "logical" {
			logical = append(logical, r)
		} else {
			other = append(other, r)
		}
	}
	out := append([]*Obj{}, logical...)
	out = append(out,
		O("action", "sniff"),
		O("protocol", "dns", "action", "hijack-dns"),
		O("inbound", []JVal{"dns-in"}, "action", "hijack-dns"),
	)
	return append(out, other...)
}

// buildConfig builds the full sing-box config dict. workdir is the
// panel data directory (geodata lives under <workdir>/geodata).
// provenance, when non-nil, receives the route-rule owner records;
// dnsProvenance the DNS-rule owner records.
func buildConfig(p Profile, skipRuleSets map[string]bool, workdir string, provenance, dnsProvenance *[]*Obj) (*Obj, RouteResult, error) {
	outbounds, err := buildOutbounds(p)
	if err != nil {
		return nil, RouteResult{}, err
	}
	endpoints := buildEndpoints(p)
	rr := buildRouteRules(p, skipRuleSets, provenance, dnsProvenance)
	routeRules, dnsRules := rr.RouteRules, rr.DNSRules

	dns := p.DNS
	split := true
	if dns != nil {
		split = dns.SplitOr()
	}
	dnsFinal := "dns-direct"
	if !split {
		// All DNS via the proxy upstream (no direct/proxy split).
		rewritten := make([]*Obj, 0, len(dnsRules))
		for _, r := range dnsRules {
			if Str(r.Get("server")) == "dns-direct" {
				c := copyObj(r)
				c.Set("server", "dns-proxy")
				rewritten = append(rewritten, c)
			} else {
				rewritten = append(rewritten, r)
			}
		}
		dnsRules = rewritten
		dnsFinal = "dns-proxy"
	}
	// Effective region: outside mainland there is no GFW, so proxy
	// DNS goes direct instead of through the proxy.
	effRegion := "cn"
	if dns != nil {
		if dns.RegionOr() != "auto" {
			effRegion = dns.RegionOr()
		} else if dns.RegionDetected != "" {
			effRegion = dns.RegionDetected
		}
	}
	proxyDetour := "所有-自动"
	if effRegion == "outside" {
		proxyDetour = "direct"
	}

	// Rule-set declarations, in declaration order.
	var decls []*Obj
	for _, name := range referencedRuleSets(p) {
		if skipRuleSets != nil && skipRuleSets[name] {
			continue
		}
		decls = append(decls, O(
			"type", "local", "tag", name, "format", "binary",
			"path", localPath(workdir, name),
		))
	}
	for _, t := range rr.RemoteRulesets {
		decls = append(decls, O(
			"type", "remote", "tag", t.Tag, "format", "binary", "url", t.URL,
		))
	}
	for _, t := range frontRemoteRuleSets(p) {
		declared := false
		for _, d := range decls {
			if Str(d.Get("tag")) == t.Tag {
				declared = true
			}
		}
		if !declared {
			decls = append(decls, O(
				"type", "remote", "tag", t.Tag, "format", "binary", "url", t.URL,
			))
		}
	}
	for _, t := range rr.ObflipRulesets {
		rules := make([]JVal, 0, len(t.Rules))
		for _, r := range t.Rules {
			rules = append(rules, r)
		}
		decls = append(decls, O("type", "inline", "tag", t.Tag, "rules", rules))
	}
	for _, s := range p.DNSFilterRulesets {
		decls = append(decls, O(
			"type", "local", "tag", s.Tag, "format", "source", "path", s.Path,
		))
	}
	// obnode-direct / obnode-direct-ip: sentinel values when empty.
	obDomains := rr.ObnodeDirect.Domains
	if len(obDomains) == 0 {
		obDomains = []string{"obnode-direct.invalid"}
	}
	obCidrs := rr.ObnodeDirect.Cidrs
	if len(obCidrs) == 0 {
		obCidrs = []string{"192.0.2.255/32"}
	}
	decls = append(decls,
		O("type", "inline", "tag", "obnode-direct",
			"rules", []JVal{O("domain", jstrs(obDomains))}),
		O("type", "inline", "tag", "obnode-direct-ip",
			"rules", []JVal{O("ip_cidr", jstrs(obCidrs))}),
	)

	// DNS servers.
	var servers []*Obj
	if p.DNSFakeIP() {
		servers = append(servers, O(
			"type", "fakeip", "tag", "dns-fakeip", "inet4_range", "198.19.0.0/16",
		))
	}
	var latency map[string]JVal
	if dns != nil {
		latency = dns.UpstreamLatency
	}
	servers = append(servers, dnsServers("dns-direct", dns.DirectDNSOr(), "direct", latency, p.WanDNSServers)...)
	servers = append(servers, dnsServers("dns-proxy", dns.ProxyDNSOr(), proxyDetour, latency, p.WanDNSServers)...)

	// Inbounds.
	inbounds := []*Obj{
		O("type", "tun", "tag", "tun-in", "stack", p.TunStackOr(),
			"mtu", float64(p.TunMtuOr()), "address", p.TunAddressOr(),
			"auto_route", true, "strict_route", false),
		O("type", "mixed", "tag", "panel-in", "listen", "127.0.0.1", "listen_port", float64(7891)),
		O("type", "direct", "tag", "dns-in", "listen", "0.0.0.0", "listen_port", float64(7853)),
	}
	if p.ShareLANEnabled {
		inbounds = append(inbounds, O(
			"type", "mixed", "tag", "lan-share-in", "listen", "0.0.0.0",
			"listen_port", float64(p.ShareLANPort),
		))
	}
	for _, s := range p.ShareServers {
		if s == nil {
			continue
		}
		if !Truthy(GetOr(s, "enabled", float64(1))) {
			continue
		}
		inbounds = append(inbounds, shareServerInbound(s))
	}

	// Route section.
	declVals := make([]JVal, 0, len(decls))
	for _, d := range decls {
		declVals = append(declVals, d)
	}
	routeRules = reorderRulesForOriginal(routeRules)
	routeRuleVals := make([]JVal, 0, len(routeRules))
	for _, r := range routeRules {
		routeRuleVals = append(routeRuleVals, r)
	}
	route := O("rules", routeRuleVals)
	if len(declVals) > 0 {
		route.Set("rule_set", declVals)
	}
	route.Set("final", "其他")
	route.Set("auto_detect_interface", true)
	route.Set("default_domain_resolver", dnsFinal)

	// DNS section.
	dnsRuleVals := make([]JVal, 0, len(dnsRules))
	for _, r := range dnsRules {
		dnsRuleVals = append(dnsRuleVals, r)
	}
	serverVals := make([]JVal, 0, len(servers))
	for _, s := range servers {
		serverVals = append(serverVals, s)
	}
	dnsSection := O(
		"servers", serverVals,
		"rules", dnsRuleVals,
		"final", dnsFinal,
		"strategy", "ipv4_only",
		"reverse_mapping", true,
	)

	// Outbounds / endpoints.
	outVals := make([]JVal, 0, len(outbounds))
	for _, o := range outbounds {
		outVals = append(outVals, o)
	}

	clashAPI := O("external_controller",
		fmt.Sprintf("%s:%d", p.ClashAPIListenOr(), p.ClashAPIPortOr()))
	if p.ClashAPISecret != "" {
		clashAPI.Set("secret", p.ClashAPISecret)
	}
	cfg := O(
		"log", O("level", "warn"),
		"dns", dnsSection,
		"inbounds", inbounds,
		"outbounds", outVals,
	)
	if len(endpoints) > 0 {
		epVals := make([]JVal, 0, len(endpoints))
		for _, e := range endpoints {
			epVals = append(epVals, e)
		}
		cfg.Set("endpoints", epVals)
	}
	cfg.Set("route", route)
	cfg.Set("experimental", O(
		"clash_api", clashAPI,
		"cache_file", O("enabled", true),
	))
	return cfg, rr, nil
}

// jstrs converts a string slice to a JVal slice.
func jstrs(ss []string) []JVal {
	a := make([]JVal, 0, len(ss))
	for _, s := range ss {
		a = append(a, s)
	}
	return a
}
