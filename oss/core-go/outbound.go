// Outbound generation: a Go port of oss/core/singbox.py's
// node_to_outbound / chain_to_outbound / build_outbounds (plus the
// helpers they use). Key order mirrors the Python dict insertion
// order so output can be compared byte-for-byte.
package main

import (
	"crypto/sha256"
	"fmt"
	"strconv"
	"strings"
	"unicode"
)

// utlsFingerprints are the uTLS fingerprint names sing-box 1.14
// accepts. Unknown values (e.g. a sha256 smuggled in as a fingerprint)
// are dropped from the emitted config, or the whole build fails
// validation and the kernel never starts.
var utlsFingerprints = map[string]bool{
	"chrome": true, "firefox": true, "safari": true, "ios": true,
	"android": true, "edge": true, "360": true, "qq": true, "random": true,
}

// durationStr renders a Go duration for sing-box: bare numbers mean
// seconds ("30" -> "30s"). Values that already carry a unit pass
// through untouched.
func durationStr(v JVal) string {
	switch t := v.(type) {
	case float64:
		return strconv.FormatFloat(t, 'g', 6, 64) + "s"
	case string:
		s := strings.TrimSpace(t)
		if s != "" && isBareNumber(s) {
			return s + "s"
		}
		return s
	default:
		return ""
	}
}

// isBareNumber reports whether s is digits with at most one dot
// (mirrors Python s.replace(".", "", 1).isdigit()).
func isBareNumber(s string) bool {
	dots := 0
	for _, r := range s {
		if r == '.' {
			dots++
			if dots > 1 {
				return false
			}
		} else if r < '0' || r > '9' {
			return false
		}
	}
	return len(s) > 0 && dots <= 1
}

// tlsBlock renders the TLS block for a node's params, or nil when the
// node has no TLS. Mirrors _tls_block, including the two branches:
// native sing-box format (utls dict with fingerprint) is copied
// verbatim (with enabled forced), unknown fingerprints drop the utls
// section; the legacy shape is rebuilt field by field.
func tlsBlock(params *Obj) *Obj {
	tls := ObjVal(params.Get("tls"))
	if tls == nil || len(tls.Keys) == 0 {
		return nil
	}
	// Native sing-box format: utls is a dict with a truthy fingerprint.
	if utls := ObjVal(tls.Get("utls")); utls != nil {
		if fp, ok := utls.Get("fingerprint").(string); ok && fp != "" {
			out := copyObj(tls)
			out.Set("enabled", true)
			u := copyObj(utls)
			u.Set("enabled", true)
			if !utlsFingerprints[fp] {
				// Unknown fingerprint: drop the whole utls section.
				removeKey(out, "utls")
			} else {
				out.Set("utls", u)
			}
			if reality := ObjVal(out.Get("reality")); reality != nil {
				r := copyObj(reality)
				r.Set("enabled", true)
				out.Set("reality", r)
			}
			return out
		}
	}
	// Legacy shape: rebuild field by field.
	out := O("enabled", true)
	if s := Str(tls.Get("server_name")); s != "" {
		out.Set("server_name", s)
	}
	if Truthy(tls.Get("insecure")) {
		out.Set("insecure", true)
	}
	if v := tls.Get("alpn"); Truthy(v) {
		out.Set("alpn", v)
	}
	if fp, ok := tls.Get("fingerprint").(string); ok && utlsFingerprints[fp] {
		out.Set("utls", O("enabled", true, "fingerprint", fp))
	}
	if reality := ObjVal(tls.Get("reality")); reality != nil && Truthy(reality) {
		r := O("enabled", true)
		for _, k := range reality.Keys {
			if k == "enabled" {
				continue
			}
			r.Set(k, reality.M[k])
		}
		out.Set("reality", r)
	}
	return out
}

// copyObj returns a shallow copy preserving key order.
func copyObj(o *Obj) *Obj {
	if o == nil {
		return nil
	}
	c := &Obj{M: make(map[string]JVal, len(o.M))}
	c.Keys = append(c.Keys, o.Keys...)
	for k, v := range o.M {
		c.M[k] = v
	}
	return c
}

// removeKey deletes k from an Obj (order list and map).
func removeKey(o *Obj, k string) {
	if _, ok := o.M[k]; !ok {
		return
	}
	delete(o.M, k)
	for i, key := range o.Keys {
		if key == k {
			o.Keys = append(o.Keys[:i], o.Keys[i+1:]...)
			return
		}
	}
}

// transportBlock renders the transport block, or nil for tcp/none.
func transportBlock(params *Obj) *Obj {
	t := ObjVal(params.Get("transport"))
	if t == nil || len(t.Keys) == 0 {
		return nil
	}
	typ := Str(t.Get("type"))
	if typ == "" || typ == "tcp" || typ == "none" {
		return nil
	}
	out := O("type", typ)
	if v := Str(t.Get("path")); v != "" {
		out.Set("path", v)
	}
	if v := t.Get("headers"); Truthy(v) {
		out.Set("headers", v)
	}
	if v := Str(t.Get("service_name")); v != "" {
		out.Set("service_name", v)
	}
	return out
}

// nodeToEndpoint renders a wireguard node as a sing-box 1.13+ endpoint.
func nodeToEndpoint(n Node) *Obj {
	p := n.Params
	if p == nil {
		p = O()
	}
	peer := O(
		"public_key", Str(p.Get("peer_public_key")),
		"address", n.Server,
		"port", float64(n.ServerPort),
		"allowed_ips", []JVal{"0.0.0.0/0", "::/0"},
	)
	if v := Str(p.Get("pre_shared_key")); v != "" {
		peer.Set("pre_shared_key", v)
	}
	ep := O(
		"type", "wireguard",
		"tag", n.Tag,
		"private_key", Str(p.Get("private_key")),
		"peers", []JVal{peer},
	)
	if v := p.Get("local_address"); Truthy(v) {
		ep.Set("address", v)
	}
	if v := p.Get("mtu"); v != nil && Num(v) != 0 {
		ep.Set("mtu", v)
	}
	return ep
}

// nodeToOutbound maps a Node to a sing-box outbound object.
// Protocol names are normalized to sing-box's own outbound types
// (socks5 -> socks, https -> http + tls). Wireguard is an error:
// WG nodes are endpoints, not outbounds.
func nodeToOutbound(n Node) (*Obj, error) {
	proto := n.Protocol
	if proto == "socks5" {
		proto = "socks"
	} else if proto == "https" {
		proto = "http"
	}
	p := n.Params
	if p == nil {
		p = O()
	}
	ob := O(
		"type", proto,
		"tag", n.Tag,
		"server", n.Server,
		"server_port", float64(n.ServerPort),
	)
	if n.Protocol == "https" {
		ob.Set("tls", O("enabled", true))
	}
	switch n.Protocol {
	case "vmess":
		ob.Set("uuid", GetOr(p, "uuid", ""))
		ob.Set("alter_id", GetOr(p, "alter_id", float64(0)))
		ob.Set("security", GetOr(p, "security", "auto"))
	case "vless":
		ob.Set("uuid", GetOr(p, "uuid", ""))
		if v := p.Get("flow"); Truthy(v) {
			ob.Set("flow", v)
		}
	case "trojan":
		ob.Set("password", GetOr(p, "password", ""))
	case "shadowsocks":
		ob.Set("method", GetOr(p, "method", ""))
		ob.Set("password", GetOr(p, "password", ""))
		if v := p.Get("plugin"); Truthy(v) {
			ob.Set("plugin", v)
		}
		if v := p.Get("plugin_opts"); Truthy(v) {
			ob.Set("plugin_opts", v)
		}
	case "tuic":
		ob.Set("uuid", GetOr(p, "uuid", ""))
		ob.Set("password", GetOr(p, "password", ""))
		if _, has := p.M["congestion_control"]; has {
			ob.Set("congestion_control", p.Get("congestion_control"))
		} else {
			ob.Set("congestion_control", "bbr")
		}
	case "hysteria2":
		ob.Set("password", GetOr(p, "password", ""))
		if v := p.Get("obfs"); Truthy(v) {
			ob.Set("obfs", v)
		}
	case "anytls":
		ob.Set("password", GetOr(p, "password", ""))
		for _, key := range []string{"idle_session_check_interval", "idle_session_timeout"} {
			if v := p.Get(key); v != nil {
				ob.Set(key, durationStr(v))
			}
		}
		for _, key := range []string{"min_idle_session", "client_metadata"} {
			if v := p.Get(key); v != nil {
				ob.Set(key, v)
			}
		}
	case "wireguard":
		return nil, fmt.Errorf("wireguard nodes are endpoints, not outbounds (use node_to_endpoint)")
	default:
		if proto == "socks" {
			if v := p.Get("username"); v != nil {
				ob.Set("username", v)
			}
			if v := p.Get("password"); v != nil {
				ob.Set("password", v)
			}
			if v := p.Get("version"); v != nil {
				if s, ok := v.(string); !ok || s != "5" {
					ob.Set("version", v)
				}
			}
		} else if proto == "http" {
			if v := p.Get("username"); v != nil {
				ob.Set("username", v)
			}
			if v := p.Get("password"); v != nil {
				ob.Set("password", v)
			}
		}
	}
	if tls := tlsBlock(p); tls != nil {
		ob.Set("tls", tls)
	}
	if tr := transportBlock(p); tr != nil {
		ob.Set("transport", tr)
	}
	return ob, nil
}

// chainToOutbound renders a chain proxy as an exit outbound dialing
// through a front.
func chainToOutbound(c Chain) (*Obj, error) {
	ob, err := nodeToOutbound(Node{
		Tag: c.Name, Protocol: c.ExitProtocol,
		Server: c.Server, ServerPort: c.ServerPort, Params: c.Params,
	})
	if err != nil {
		return nil, err
	}
	ob.Set("detour", c.Front)
	return ob, nil
}

// defaultGroups returns the two built-in groups.
func defaultGroups() []Group {
	return []Group{
		{Name: "所有-自动", Type: "urltest", Members: []string{"*nodes*"}, Position: 0},
		{Name: "所有-手动", Type: "selector", Members: []string{"*all*"}, Position: 1},
	}
}

// resolveGroupMembers expands *nodes* / *all* and dynamic keywords.
func resolveGroupMembers(g Group, nodeTags, chainTags []string) []string {
	var tags []string
	contains := func(list []string, s string) bool {
		for _, x := range list {
			if x == s {
				return true
			}
		}
		return false
	}
	for _, m := range g.Members {
		switch m {
		case "*nodes*":
			tags = append(tags, nodeTags...)
		case "*all*":
			tags = append(tags, nodeTags...)
			tags = append(tags, chainTags...)
		default:
			if (contains(nodeTags, m) || contains(chainTags, m)) && !contains(tags, m) {
				tags = append(tags, m)
			}
		}
	}
	for _, kw := range g.DynamicKeywords {
		kl := strings.ToLower(kw)
		for _, t := range nodeTags {
			if strings.Contains(strings.ToLower(t), kl) && !contains(tags, t) {
				tags = append(tags, t)
			}
		}
	}
	return tags
}

// laneDisplayName returns a lane's display name: custom name if set,
// else Primary/Backup n.
func laneDisplayName(lane Lane, index int) string {
	name := strings.TrimSpace(lane.Name)
	if name != "" {
		return name
	}
	if index == 0 {
		return "主用"
	}
	return fmt.Sprintf("备用%d", index)
}

// failoverLaneTag is the single source of truth for lane tags.
func failoverLaneTag(groupName string, lane Lane, index int) string {
	if len(lane.Members) == 1 {
		return lane.Members[0]
	}
	return groupName + "#" + laneDisplayName(lane, index)
}

// flipTag is the outbound tag of the hot-switch selector for a site set.
func flipTag(s SiteSet) string {
	if s.Sid != 0 {
		return "flip-" + strconv.Itoa(s.Sid)
	}
	key := cleanWordRuns(s.Name)
	if key == "" {
		key = "x"
	}
	return "flip-" + key
}

// cleanWordRuns replaces runs of non-word characters with a single "-"
// and strips leading/trailing "-" (mirrors Python re.sub(r"\W+", "-",
// name).strip("-"); \w is Unicode word characters).
func cleanWordRuns(s string) string {
	var b strings.Builder
	inRun := false
	for _, r := range s {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_' {
			if inRun {
				b.WriteByte('-')
				inRun = false
			}
			b.WriteRune(r)
		} else {
			inRun = true
		}
	}
	// A trailing run writes no "-" (only written when a word char
	// follows), so strip is only needed for a leading run.
	out := b.String()
	return strings.Trim(out, "-")
}

// obflipTag is the rule-set tag for per-site-set QUIC blocking:
// obflip-<sha256(sid|name)[0:12]>.
func obflipTag(s SiteSet) string {
	sid := ""
	if s.Sid != 0 {
		sid = strconv.Itoa(s.Sid)
	}
	sum := sha256.Sum256([]byte(sid + "|" + s.Name))
	return "obflip-" + fmt.Sprintf("%x", sum)[:12]
}

// flipOutbound builds the per-policy selector for a site set.
func flipOutbound(s SiteSet, members []string) *Obj {
	if len(members) == 0 {
		return nil
	}
	contains := func(x string) bool {
		for _, m := range members {
			if m == x {
				return true
			}
		}
		return false
	}
	grp := s.Group
	if !contains(grp) {
		if contains("所有-自动") {
			grp = "所有-自动"
		} else {
			grp = members[0]
		}
	}
	var def string
	switch {
	case s.Action == "reject":
		if contains("block") {
			def = "block"
		} else {
			def = members[0]
		}
	case s.Flip == "direct":
		if contains("direct") {
			def = "direct"
		} else {
			def = members[0]
		}
	case s.Flip == "proxy":
		def = grp
	case s.Action == "direct":
		if contains("direct") {
			def = "direct"
		} else {
			def = members[0]
		}
	default:
		def = grp
	}
	outs := make([]JVal, 0, len(members))
	for _, m := range members {
		outs = append(outs, m)
	}
	return O("type", "selector", "tag", flipTag(s), "outbounds", outs, "default", def)
}

// buildEndpoints renders wireguard nodes as endpoints.
func buildEndpoints(p Profile) []*Obj {
	var eps []*Obj
	for _, n := range p.Nodes {
		if n.Protocol == "wireguard" {
			eps = append(eps, nodeToEndpoint(n))
		}
	}
	return eps
}

// buildOutbounds builds the outbound list (nodes + chains + groups +
// builtins + hot-switch selectors + the fallback policy card).
func buildOutbounds(p Profile) ([]*Obj, error) {
	var nodeTags []string
	for _, n := range p.Nodes {
		nodeTags = append(nodeTags, n.Tag)
	}
	var chainTags []string
	for _, c := range p.Chains {
		chainTags = append(chainTags, c.Name)
	}
	groups := p.Groups
	if len(groups) == 0 {
		groups = defaultGroups()
	}

	var outbounds []*Obj
	for _, n := range p.Nodes {
		if n.Protocol == "wireguard" {
			continue
		}
		ob, err := nodeToOutbound(n)
		if err != nil {
			return nil, err
		}
		outbounds = append(outbounds, ob)
	}
	for _, c := range p.Chains {
		ob, err := chainToOutbound(c)
		if err != nil {
			return nil, err
		}
		outbounds = append(outbounds, ob)
	}
	// Subscription groups: one urltest per enabled subscription.
	subNodeTags := map[int][]string{}
	for _, n := range p.Nodes {
		if n.SubID != nil {
			subNodeTags[*n.SubID] = append(subNodeTags[*n.SubID], n.Tag)
		}
	}
	for _, sub := range p.Subscriptions {
		if !sub.EnabledOr() {
			continue
		}
		tags := subNodeTags[sub.ID]
		if len(tags) == 0 {
			continue
		}
		outs := make([]JVal, 0, len(tags))
		for _, t := range tags {
			outs = append(outs, t)
		}
		outbounds = append(outbounds, O(
			"type", "urltest",
			"tag", fmt.Sprintf("sub-%d", sub.ID),
			"outbounds", outs,
			"url", p.SpeedtestURL,
			"interval", "300s",
			"tolerance", float64(100),
		))
	}
	for _, g := range groups {
		if !g.EnabledOr() {
			continue
		}
		tags := resolveGroupMembers(g, nodeTags, chainTags)
		outs := func(ts []string) []JVal {
			a := make([]JVal, 0, len(ts))
			for _, t := range ts {
				a = append(a, t)
			}
			return a
		}
		firstOrDirect := func() string {
			if len(tags) > 0 {
				return tags[0]
			}
			return "direct"
		}
		orDirect := func() []JVal {
			if len(tags) > 0 {
				return outs(tags)
			}
			return []JVal{"direct"}
		}
		switch g.Type {
		case "selector":
			def := g.DefaultOutbound
			found := false
			for _, t := range tags {
				if t == def {
					found = true
				}
			}
			if !found {
				def = firstOrDirect()
			}
			outbounds = append(outbounds, O(
				"type", "selector", "tag", g.Name,
				"outbounds", orDirect(), "default", def,
			))
		case "failover":
			if len(g.Lanes) > 0 {
				var allMembers []string
				for i, ln := range g.Lanes {
					laneTag := failoverLaneTag(g.Name, ln, i)
					var laneMembers []string
					for _, t := range ln.Members {
						if containsStr(nodeTags, t) || containsStr(chainTags, t) {
							laneMembers = append(laneMembers, t)
						}
					}
					if len(laneMembers) == 0 {
						continue
					}
					mode := ln.Mode
					if mode == "" {
						mode = "auto"
					}
					if len(laneMembers) == 1 {
						if !containsStr(allMembers, laneMembers[0]) {
							allMembers = append(allMembers, laneMembers[0])
						}
					} else if mode == "manual" {
						outbounds = append(outbounds, O(
							"type", "selector", "tag", laneTag,
							"outbounds", outs(laneMembers),
							"default", laneMembers[0],
						))
						allMembers = append(allMembers, laneTag)
					} else {
						outbounds = append(outbounds, O(
							"type", "urltest", "tag", laneTag,
							"outbounds", outs(laneMembers),
							"url", firstNonEmpty(g.TestURL, p.SpeedtestURL),
							"interval", fmt.Sprintf("%ds", g.IntervalSOr()),
							"tolerance", float64(g.ToleranceMsOr()),
							"idle_timeout", g.IdleTimeoutOr(),
						))
						allMembers = append(allMembers, laneTag)
					}
				}
				def := "direct"
				if len(allMembers) > 0 {
					def = allMembers[0]
				}
				o := O(
					"type", "selector", "tag", g.Name,
					"outbounds", orDirectSlice(allMembers),
					"default", def,
				)
				o.Set("interrupt_exist_connections", true)
				outbounds = append(outbounds, o)
			} else {
				outbounds = append(outbounds, O(
					"type", "urltest", "tag", g.Name,
					"outbounds", orDirect(),
					"tolerance", float64(g.ToleranceMsOr()),
					"url", firstNonEmpty(g.TestURL, p.SpeedtestURL),
					"interval", fmt.Sprintf("%ds", g.IntervalSOr()),
				))
			}
		case "loadbalance":
			// Load balance: emit the kernel-native loadbalance outbound
			// (v0.1.384+, round-robin over healthy members, verified
			// against the lab kernel 2026-11-14). Members must be real
			// proxy nodes only: the kernel refuses direct/block/group/
			// chain members at startup ("load balance requires real
			// proxy nodes"), and sing-box check does NOT catch it, so
			// filter the resolved tags to node tags here; the panel
			// also validates members at save time.
			var members []string
			for _, t := range tags {
				if containsStr(nodeTags, t) {
					members = append(members, t)
				}
			}
			intervalS := g.IntervalS
			if intervalS == 0 {
				intervalS = 120 // panel default for loadbalance groups
			}
			outbounds = append(outbounds, O(
				"type", "loadbalance", "tag", g.Name,
				"outbounds", outs(members),
				"interval", fmt.Sprintf("%ds", intervalS),
				"url", firstNonEmpty(g.TestURL, p.SpeedtestURL),
			))
		case "urltest", "smart":
			ob := O(
				"type", "urltest", "tag", g.Name,
				"outbounds", orDirect(),
				"url", firstNonEmpty(g.TestURL, p.SpeedtestURL),
				"interval", fmt.Sprintf("%ds", g.IntervalSOr()),
				"tolerance", float64(g.ToleranceMsOr()),
				"idle_timeout", g.IdleTimeoutOr(),
			)
			if g.ExpectedStatus != "" {
				ob.Set("expected_status", g.ExpectedStatus)
			}
			outbounds = append(outbounds, ob)
		}
	}
	outbounds = append(outbounds,
		O("type", "direct", "tag", "direct"),
		O("type", "block", "tag", "block"),
		O("type", "block", "tag", "__fo:reject"),
	)
	// Hot-switch selectors, one per site set.
	flipMembers := []string{"direct"}
	for _, g := range groups {
		if !g.EnabledOr() {
			continue
		}
		if g.Name == "所有-自动" || g.Name == "所有-手动" || g.Name == "direct" || g.Name == "block" {
			continue
		}
		if !containsStr(flipMembers, g.Name) {
			flipMembers = append(flipMembers, g.Name)
		}
	}
	for _, builtin := range []string{"所有-自动", "所有-手动"} {
		for _, g := range groups {
			if g.Name == builtin && g.EnabledOr() {
				flipMembers = append(flipMembers, builtin)
				break
			}
		}
	}
	flipMembers = append(flipMembers, "block")
	for _, s := range p.SiteSets {
		if fo := flipOutbound(s, flipMembers); fo != nil {
			outbounds = append(outbounds, fo)
		}
	}
	finalDefault := p.RoutingFallback
	if finalDefault == "" {
		finalDefault = p.FinalOutbound
	}
	if !containsStr(flipMembers, finalDefault) {
		if containsStr(flipMembers, "所有-自动") {
			finalDefault = "所有-自动"
		} else {
			finalDefault = flipMembers[0]
		}
	}
	outs := make([]JVal, 0, len(flipMembers))
	for _, m := range flipMembers {
		outs = append(outs, m)
	}
	outbounds = append(outbounds, O(
		"type", "selector", "tag", "其他",
		"outbounds", outs, "default", finalDefault,
	))
	return outbounds, nil
}

func containsStr(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func orDirectSlice(members []string) []JVal {
	if len(members) == 0 {
		return []JVal{"direct"}
	}
	outs := make([]JVal, 0, len(members))
	for _, m := range members {
		outs = append(outs, m)
	}
	return outs
}

// buildGroupOutbounds returns the group-derived outbounds only
// (subscription groups, user groups, builtins, hot-switch selectors,
// the fallback card) — the emitGroups value. buildOutbounds emits
// nodes and chains first, in order, so the group part is the tail
// after that prefix.
func buildGroupOutbounds(p Profile) ([]*Obj, error) {
	all, err := buildOutbounds(p)
	if err != nil {
		return nil, err
	}
	prefix := 0
	for _, n := range p.Nodes {
		if n.Protocol != "wireguard" {
			prefix++
		}
	}
	prefix += len(p.Chains)
	return all[prefix:], nil
}
