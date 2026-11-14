// Command oss-core is the standalone config core for openbox-oss.
//
// It is the middle layer of the three-layer structure: the Flask panel
// calls it to compile a profile (the panel's AppConfig serialized as
// JSON) into a sing-box config, and the panel then deploys that config
// to the sing-box kernel. It is a pure function of (profile, workdir):
// no database access, no network access.
//
// Contract: see CONTRACT.md. Methods mirror the original openbox-core
// (emitGroups, configDetailed) where they are implementable;
// routingFingerprint is explicitly not implemented and never guessed.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

const (
	coreName    = "oss-core"
	coreVersion = "0.1.0"
	// sing-box version the generated config targets.
	// 1.14.4: the loadbalance outbound (v0.1.384+) needs the modified
	// kernel 1.14.4-openbox-38+; stock 1.14.x and the 1.14.1-openbox
	// tcp28 kernel reject type: loadbalance.
	singboxVersion = "1.14.4"
)

var supportedMethods = []string{"emitGroups", "configDetailed", "config"}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "version":
		emitJSON(map[string]any{
			"name":    coreName,
			"version": coreVersion,
			"singbox": singboxVersion,
			"methods": supportedMethods,
		})
	case "config":
		// Full sing-box config for one profile. The kernel rule-set
		// files are written first (from the blocked domains), so the
		// generated config can reference them; a write failure never
		// breaks the apply — the config falls back to the route-layer
		// block rule (mirrors apply.build_and_validate).
		profilePath := flagValue(os.Args[2:], "--profile")
		workdir := flagValue(os.Args[2:], "--workdir")
		if profilePath == "" || workdir == "" {
			fmt.Fprintln(os.Stderr, "oss-core: config requires --profile <file> --workdir <dir>")
			os.Exit(2)
		}
		profile, err := loadProfile(profilePath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: load profile: %v\n", err)
			os.Exit(2)
		}
		if len(profile.BlockedDomains) > 0 {
			entries, werr := writeKernelRulesets(workdir, profile.BlockedDomains, profile.AllowDomains)
			if werr != nil {
				fmt.Fprintf(os.Stderr, "oss-core: warning: write kernel rule sets: %v (falling back to route-layer block)\n", werr)
				profile.DNSFilterRulesets = nil
			} else {
				profile.DNSFilterRulesets = entries
			}
		} else {
			profile.DNSFilterRulesets = nil
		}
		skip := parseSkipRuleSets(flagValue(os.Args[2:], "--skip-rule-sets"))
		cfg, _, err := buildConfig(profile, skip, workdir, nil, nil)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: build config: %v\n", err)
			os.Exit(3)
		}
		emitJSON(cfg)
	case "debug-dnsfilter":
		// Dev-only: write the kernel rule sets for one profile and
		// emit the entries, for the harness diff.
		profilePath := flagValue(os.Args[2:], "--profile")
		workdir := flagValue(os.Args[2:], "--workdir")
		if profilePath == "" || workdir == "" {
			fmt.Fprintln(os.Stderr, "oss-core: debug-dnsfilter requires --profile <file> --workdir <dir>")
			os.Exit(2)
		}
		profile, err := loadProfile(profilePath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: load profile: %v\n", err)
			os.Exit(2)
		}
		entries, err := writeKernelRulesets(workdir, profile.BlockedDomains, profile.AllowDomains)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: write kernel rule sets: %v\n", err)
			os.Exit(3)
		}
		vals := make([]JVal, 0, len(entries))
		for _, e := range entries {
			vals = append(vals, O("tag", e.Tag, "path", e.Path))
		}
		emitJSON(O("entries", vals))
	case "configDetailed":
		// Preview: the config plus the detail the panel shows
		// alongside it. Does NOT write the dns-filter files (the
		// profile carries the entries the panel computed).
		profilePath := flagValue(os.Args[2:], "--profile")
		workdir := flagValue(os.Args[2:], "--workdir")
		if profilePath == "" || workdir == "" {
			fmt.Fprintln(os.Stderr, "oss-core: configDetailed requires --profile <file> --workdir <dir>")
			os.Exit(2)
		}
		profile, err := loadProfile(profilePath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: load profile: %v\n", err)
			os.Exit(2)
		}
		skip := parseSkipRuleSets(flagValue(os.Args[2:], "--skip-rule-sets"))
		var provenance, dnsProvenance []*Obj
		cfg, rr, err := buildConfig(profile, skip, workdir, &provenance, &dnsProvenance)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: build config: %v\n", err)
			os.Exit(3)
		}
		owners := make([]JVal, 0, len(dnsProvenance))
		for _, rec := range dnsProvenance {
			owners = append(owners, rec)
		}
		emitJSON(O(
			"config", cfg,
			"directHosts", O("cidrs", jstrs(rr.ObnodeDirect.Cidrs),
				"domains", jstrs(rr.ObnodeDirect.Domains)),
			"dnsRuleOwners", owners,
			"failover", failoverValue(profile),
		))
	case "emitGroups":
		// The normalized groups: builtin labels + the group-derived
		// outbounds (subscription groups, user groups, builtins,
		// hot-switch selectors, the fallback card).
		profilePath := flagValue(os.Args[2:], "--profile")
		if profilePath == "" {
			fmt.Fprintln(os.Stderr, "oss-core: emitGroups requires --profile <file>")
			os.Exit(2)
		}
		profile, err := loadProfile(profilePath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: load profile: %v\n", err)
			os.Exit(2)
		}
		groups, err := buildGroupOutbounds(profile)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: build groups: %v\n", err)
			os.Exit(3)
		}
		vals := make([]JVal, 0, len(groups))
		for _, g := range groups {
			vals = append(vals, g)
		}
		emitJSON(O(
			"builtin", O(
				// direct/block are sing-box builtins, always enabled.
				"direct", "直连", "directEnabled", true,
				"block", "拒绝", "blockEnabled", true,
			),
			"groups", vals,
		))
	case "debug-outbounds":
		// Dev-only: emit {outbounds, endpoints} for one profile so
		// the harness can diff the outbound slice against Python.
		profilePath := flagValue(os.Args[2:], "--profile")
		if profilePath == "" {
			fmt.Fprintln(os.Stderr, "oss-core: debug-outbounds requires --profile <file>")
			os.Exit(2)
		}
		profile, err := loadProfile(profilePath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: load profile: %v\n", err)
			os.Exit(2)
		}
		outbounds, err := buildOutbounds(profile)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: build outbounds: %v\n", err)
			os.Exit(3)
		}
		emitJSON(O("outbounds", outbounds, "endpoints", buildEndpoints(profile)))
	case "debug-route-rules":
		// Dev-only: emit route_rules + dns_rules + provenance + the
		// side-effect collections, for the harness diff.
		profilePath := flagValue(os.Args[2:], "--profile")
		if profilePath == "" {
			fmt.Fprintln(os.Stderr, "oss-core: debug-route-rules requires --profile <file>")
			os.Exit(2)
		}
		profile, err := loadProfile(profilePath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "oss-core: load profile: %v\n", err)
			os.Exit(2)
		}
		skip := parseSkipRuleSets(flagValue(os.Args[2:], "--skip-rule-sets"))
		var provenance, dnsProvenance []*Obj
		res := buildRouteRules(profile, skip, &provenance, &dnsProvenance)
		var groupNames []string
		for n := range res.GroupNames {
			groupNames = append(groupNames, n)
		}
		sortStrings(groupNames)
		remote := make([]JVal, 0, len(res.RemoteRulesets))
		for _, t := range res.RemoteRulesets {
			remote = append(remote, O("tag", t.Tag, "url", t.URL))
		}
		obflip := make([]JVal, 0, len(res.ObflipRulesets))
		for _, t := range res.ObflipRulesets {
			rules := make([]JVal, 0, len(t.Rules))
			for _, r := range t.Rules {
				rules = append(rules, r)
			}
			obflip = append(obflip, O("tag", t.Tag, "rules", rules))
		}
		frontRS := make([]JVal, 0, len(res.FrontRemoteRS))
		for _, t := range res.FrontRemoteRS {
			frontRS = append(frontRS, O("tag", t.Tag, "url", t.URL))
		}
		obDomains := make([]JVal, 0, len(res.ObnodeDirect.Domains))
		for _, d := range res.ObnodeDirect.Domains {
			obDomains = append(obDomains, d)
		}
		obCidrs := make([]JVal, 0, len(res.ObnodeDirect.Cidrs))
		for _, c := range res.ObnodeDirect.Cidrs {
			obCidrs = append(obCidrs, c)
		}
		prov := make([]JVal, 0, len(provenance))
		for _, rec := range provenance {
			prov = append(prov, rec)
		}
		dnsProv := make([]JVal, 0, len(dnsProvenance))
		for _, rec := range dnsProvenance {
			dnsProv = append(dnsProv, rec)
		}
		emitJSON(O(
			"route_rules", res.RouteRules,
			"dns_rules", res.DNSRules,
			"provenance", prov,
			"dns_provenance", dnsProv,
			"group_names", groupNames,
			"remote_rulesets", remote,
			"obflip_rulesets", obflip,
			"obnode_direct", O("domains", obDomains, "cidrs", obCidrs),
			"front_remote_rs", frontRS,
		))
	case "routingFingerprint":
		fatalNotImplemented("routingFingerprint")
	default:
		fmt.Fprintf(os.Stderr, "oss-core: unknown command %q\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: oss-core <version|config|configDetailed|emitGroups|routingFingerprint> [flags]")
	fmt.Fprintln(os.Stderr, "  version        print handshake JSON")
	fmt.Fprintln(os.Stderr, "  config         --profile <file> --workdir <dir> [--skip-rule-sets a,b]")
	fmt.Fprintln(os.Stderr, "  configDetailed --profile <file> --workdir <dir>")
	fmt.Fprintln(os.Stderr, "  emitGroups     --profile <file>")
	fmt.Fprintln(os.Stderr, "  debug-outbounds --profile <file>  (dev: emit outbounds+endpoints only)")
	fmt.Fprintln(os.Stderr, "  debug-route-rules --profile <file> [--skip-rule-sets a,b]  (dev: emit route/dns rules + side effects)")
}

// flagValue returns the value of a --name <value> flag.
func flagValue(args []string, name string) string {
	for i, a := range args {
		if a == name && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}

// parseSkipRuleSets parses a comma-separated --skip-rule-sets value.
func parseSkipRuleSets(v string) map[string]bool {
	if v == "" {
		return nil
	}
	m := map[string]bool{}
	for _, s := range strings.Split(v, ",") {
		s = strings.TrimSpace(s)
		if s != "" {
			m[s] = true
		}
	}
	return m
}

// sortStrings sorts a string slice in place.
func sortStrings(ss []string) {
	sort.Strings(ss)
}

// loadProfile reads and decodes a profile JSON file.
func loadProfile(path string) (Profile, error) {
	var p Profile
	data, err := os.ReadFile(path)
	if err != nil {
		return p, err
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	if err := dec.Decode(&p); err != nil {
		return p, err
	}
	// Normalize nil params to an empty object (Python defaults to {}).
	for i := range p.Nodes {
		if p.Nodes[i].Params == nil {
			p.Nodes[i].Params = O()
		}
	}
	for i := range p.Chains {
		if p.Chains[i].Params == nil {
			p.Chains[i].Params = O()
		}
	}
	return p, nil
}

func emitJSON(v any) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		fmt.Fprintf(os.Stderr, "oss-core: encode output: %v\n", err)
		os.Exit(3)
	}
}

// failoverValue returns the enabled failover groups with their lanes
// (display name, resolved members, mode) for configDetailed.
func failoverValue(p Profile) []JVal {
	groups := p.Groups
	if len(groups) == 0 {
		groups = defaultGroups()
	}
	var nodeTags, chainTags []string
	for _, n := range p.Nodes {
		nodeTags = append(nodeTags, n.Tag)
	}
	for _, c := range p.Chains {
		chainTags = append(chainTags, c.Name)
	}
	out := []JVal{}
	for _, g := range groups {
		if g.Type != "failover" || !g.EnabledOr() {
			continue
		}
		lanes := make([]JVal, 0, len(g.Lanes))
		for i, ln := range g.Lanes {
			var members []string
			for _, t := range ln.Members {
				if containsStr(nodeTags, t) || containsStr(chainTags, t) {
					members = append(members, t)
				}
			}
			mode := ln.Mode
			if mode == "" {
				mode = "auto"
			}
			lanes = append(lanes, O(
				"name", laneDisplayName(ln, i),
				"members", jstrs(members),
				"mode", mode,
			))
		}
		out = append(out, O("name", g.Name, "lanes", lanes))
	}
	return out
}

// fatalNotImplemented reports a known-but-unimplemented method the way the
// Python replica does: exit 4, never a guessed value.
func fatalNotImplemented(method string) {
	fmt.Fprintf(os.Stderr, "oss-core: %s: not implemented yet\n", method)
	os.Exit(4)
}
