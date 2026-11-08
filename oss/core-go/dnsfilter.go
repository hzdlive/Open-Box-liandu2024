// DNS-filter kernel rule sets: a Go port of the kernel-side half of
// oss/core/dnsfilter.py.
//
// The original does not block ad domains in route rules. It shards
// the blocklist into local rule-set files (dns-filter-anti-ad-block
// [-2..-4] + dns-filter-anti-ad-allow) and answers NXDOMAIN for them
// in the DNS module. Files are JSON source rule sets (format
// "source"; the original uses binary .srs, behaviorally identical
// for domain_suffix matching).
package main

import (
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// Kernel-side DNS-filter constants (oss/core/dnsfilter.py).
const (
	kernelRulesetDir = "dns-filter"
	kernelShardSize  = 25000
	allowSentinel    = "dns-filter-allow.invalid"
)

// normalizeDomains lowercases, strips dots and dedups, sorted.
// Mirrors Python: {x.lower().strip(".") for x in domains if x}.
func normalizeDomains(domains []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, x := range domains {
		if x == "" {
			continue
		}
		d := strings.Trim(strings.ToLower(x), ".")
		if !seen[d] {
			seen[d] = true
			out = append(out, d)
		}
	}
	sort.Strings(out)
	return out
}

// kernelShardTags returns the shard tags for a blocklist of n domains.
func kernelShardTags(n int) []string {
	if n <= 0 {
		return nil
	}
	count := (n + kernelShardSize - 1) / kernelShardSize
	tags := make([]string, 0, count)
	for i := 0; i < count; i++ {
		if i == 0 {
			tags = append(tags, kernelBlockTag)
		} else {
			tags = append(tags, kernelBlockTag+"-"+strconv.Itoa(i+1))
		}
	}
	return tags
}

// kernelRulesetEntries returns the deterministic [{tag, path}] for
// the kernel rule sets, without writing. Previews use this so the
// shown config matches what apply will emit.
func kernelRulesetEntries(workdir string, domains []string) []RulesetDecl {
	d := normalizeDomains(domains)
	tags := kernelShardTags(len(d))
	base := filepath.Join(workdir, kernelRulesetDir)
	out := make([]RulesetDecl, 0, len(tags)+1)
	for _, t := range tags {
		out = append(out, RulesetDecl{Tag: t, Path: filepath.Join(base, t+".json")})
	}
	out = append(out, RulesetDecl{Tag: kernelAllowTag, Path: filepath.Join(base, kernelAllowTag+".json")})
	return out
}

// writeIfChanged writes content unless the file already has it.
// Returns true when the file was written.
func writeIfChanged(path, content string) (bool, error) {
	if data, err := os.ReadFile(path); err == nil && string(data) == content {
		return false, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return false, err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(content), 0o644); err != nil {
		return false, err
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return false, err
	}
	return true, nil
}

// writeKernelRulesets writes the kernel-side DNS-filter rule-set
// files. domains is the blocked domain list (flat); allow is the
// optional allow list (nil = sentinel file). Returns [{tag, path}]
// for the block shards + the allow set, in declaration order
// (blocks first, allow last). Files are only rewritten when their
// content changed.
func writeKernelRulesets(workdir string, domains, allow []string) ([]RulesetDecl, error) {
	d := normalizeDomains(domains)
	entries := kernelRulesetEntries(workdir, domains)
	for i, entry := range entries {
		var chunk []string
		if entry.Tag == kernelAllowTag {
			chunk = normalizeDomains(allow)
			if len(chunk) == 0 {
				chunk = []string{allowSentinel}
			}
		} else {
			lo := i * kernelShardSize
			hi := lo + kernelShardSize
			if hi > len(d) {
				hi = len(d)
			}
			chunk = d[lo:hi]
		}
		content := marshalJSONCompact(O(
			"version", float64(3),
			"rules", []JVal{O("domain_suffix", jstrs(chunk))},
		))
		if _, err := writeIfChanged(entry.Path, content); err != nil {
			return nil, err
		}
	}
	return entries, nil
}

// marshalJSONCompact renders a value as compact JSON with no spaces,
// matching Python json.dumps(..., separators=(",", ":")).
func marshalJSONCompact(v JVal) string {
	b, err := marshalJVal(v)
	if err != nil {
		return ""
	}
	return string(b)
}
