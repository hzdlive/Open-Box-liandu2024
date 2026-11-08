// Profile types: the JSON the panel passes to the core.
//
// Field names mirror the Python dataclasses in oss/core/models.py
// (snake_case), so the panel can serialize AppConfig with the same
// names. Params is an order-preserving object: the native TLS branch
// of _tls_block copies the params dict verbatim, key order included.
package main

// Node is a single proxy node parsed from a subscription link.
type Node struct {
	Tag        string `json:"tag"`
	Protocol   string `json:"protocol"`
	Server     string `json:"server"`
	ServerPort int    `json:"server_port"`
	Params     *Obj   `json:"params"`
	SubID      *int   `json:"sub_id"`
}

// Lane is one failover lane: [{name, members[]}] (1:1 with the original).
type Lane struct {
	Name    string   `json:"name"`
	Members []string `json:"members"`
	Mode    string   `json:"mode"`
}

// Group is an outbound group. Members resolve at build time.
type Group struct {
	Name            string   `json:"name"`
	Type            string   `json:"type"`
	Members         []string `json:"members"`
	DynamicKeywords []string `json:"dynamic_keywords"`
	Position        int      `json:"position"`
	Enabled         *bool    `json:"enabled"`
	IntervalS       int      `json:"interval_s"`
	ToleranceMs     int      `json:"tolerance_ms"`
	IdleTimeout     string   `json:"idle_timeout"`
	ExpectedStatus  string   `json:"expected_status"`
	TestURL         string   `json:"test_url"`
	DefaultOutbound string   `json:"default_outbound"`
	Lanes           []Lane   `json:"lanes"`
}

// EnabledOr returns the group's enabled flag, defaulting to true when
// the profile omits it (mirrors Python `g.enabled`, default True).
func (g *Group) EnabledOr() bool {
	if g.Enabled == nil {
		return true
	}
	return *g.Enabled
}

// IntervalSOr returns the urltest interval, defaulting to 300s
// (Python dataclass default) when the profile omits it.
func (g *Group) IntervalSOr() int {
	if g.IntervalS == 0 {
		return 300
	}
	return g.IntervalS
}

// ToleranceMsOr returns the urltest tolerance, defaulting to 100ms.
func (g *Group) ToleranceMsOr() int {
	if g.ToleranceMs == 0 {
		return 100
	}
	return g.ToleranceMs
}

// IdleTimeoutOr returns the urltest idle timeout, defaulting to 12h.
func (g *Group) IdleTimeoutOr() string {
	if g.IdleTimeout == "" {
		return "12h"
	}
	return g.IdleTimeout
}

// Chain is a chain proxy: exit reached through a front node/group.
type Chain struct {
	Name         string `json:"name"`
	ExitProtocol string `json:"exit_protocol"`
	Server       string `json:"server"`
	ServerPort   int    `json:"server_port"`
	Params       *Obj   `json:"params"`
	Front        string `json:"front"`
	Enabled      *bool  `json:"enabled"`
}

// EnabledOr returns the chain's enabled flag, defaulting to true.
func (c *Chain) EnabledOr() bool {
	if c.Enabled == nil {
		return true
	}
	return *c.Enabled
}

// SiteSet is a named routing rule set, matched top-down, first hit wins.
type SiteSet struct {
	Name         string   `json:"name"`
	Action       string   `json:"action"`
	Domains      []string `json:"domains"`
	DomainSuffix []string `json:"domain_suffix"`
	DomainKeyword []string `json:"domain_keyword"`
	IPCidr       []string `json:"ip_cidr"`
	Ports        []JVal   `json:"ports"`
	RuleSets     []string `json:"rule_sets"`
	RulesetURLs  []string `json:"ruleset_urls"`
	Group        string   `json:"group"`
	Flip         string   `json:"flip"`
	Sid          int      `json:"sid"`
	// Geosite is the site set's geosite list, if the panel ever carries
	// one (the Python generator reads s.geosite, which is never
	// assigned today, so the bypass rule never excludes proxy
	// geosites; the field is kept so the behavior stays faithful
	// if the panel starts sending it).
	Geosite []string `json:"geosite"`
}

// RuleSet is a remote/local rule list referenced by site sets.
type RuleSet struct {
	Name      string `json:"name"`
	URL       string `json:"url"`
	Format    string `json:"format"`
	Content   string `json:"content"`
	UpdatedAt string `json:"updated_at"`
}

// DnsConfig holds the DNS settings.
type DnsConfig struct {
	DirectDNS      string           `json:"direct_dns"`
	ProxyDNS       string           `json:"proxy_dns"`
	EnableFakeIP   bool             `json:"enable_fakeip"`
	Mode           string           `json:"mode"`
	Split          *bool            `json:"split"`
	Region         string           `json:"region"`
	RegionDetected string           `json:"region_detected"`
	UpstreamLatency map[string]JVal `json:"upstream_latency"`
}

// SplitOr returns the split flag, defaulting to true.
func (d *DnsConfig) SplitOr() bool {
	if d == nil || d.Split == nil {
		return true
	}
	return *d.Split
}

// RegionOr returns the region, defaulting to "auto".
func (d *DnsConfig) RegionOr() string {
	if d == nil || d.Region == "" {
		return "auto"
	}
	return d.Region
}

// DirectDNSOr returns the direct upstream, defaulting to 223.5.5.5.
func (d *DnsConfig) DirectDNSOr() string {
	if d == nil || d.DirectDNS == "" {
		return "223.5.5.5"
	}
	return d.DirectDNS
}

// ProxyDNSOr returns the proxy upstream, defaulting to tcp://1.1.1.1.
func (d *DnsConfig) ProxyDNSOr() string {
	if d == nil || d.ProxyDNS == "" {
		return "tcp://1.1.1.1"
	}
	return d.ProxyDNS
}

// ModeOr returns the hijack mode, defaulting to "dnsmasq".
func (d *DnsConfig) ModeOr() string {
	if d == nil || d.Mode == "" {
		return "dnsmasq"
	}
	return d.Mode
}

// DnsRewrite is one DNS rewrite rule.
type DnsRewrite struct {
	Domain string `json:"domain"`
	Target string `json:"target"`
	ID     int    `json:"id"`
}

// TerminalPolicy is one ingress terminal policy.
type TerminalPolicy struct {
	Ident  string `json:"ident"`
	Name   string `json:"name"`
	Policy string `json:"policy"`
	ID     int    `json:"id"`
}

// TerminalRule is one terminal match rule.
type TerminalRule struct {
	ID       int      `json:"id"`
	Name     string   `json:"name"`
	MatchBy  string   `json:"match_by"`
	Targets  []string `json:"targets"`
	Policy   string   `json:"policy"`
	Outbound string   `json:"outbound"`
	Enabled  bool     `json:"enabled"`
	Position int      `json:"position"`
	// Cidrs and V6Cidrs are pre-expanded by the panel (ARP table reads
	// for MAC targets, CIDR normalization for IP targets): the core is
	// a pure function and never reads live system state.
	Cidrs   []string `json:"cidrs"`
	V6Cidrs []string `json:"v6_cidrs"`
}

// RulesetDecl is one rule-set declaration the panel prepared
// (content-filter kernel rule sets, dnsfilter.kernel_ruleset_entries).
type RulesetDecl struct {
	Tag  string `json:"tag"`
	Path string `json:"path"`
}

// Subscription is one subscription entry (panel-side metadata).
type Subscription struct {
	ID      int    `json:"id"`
	Name    string `json:"name"`
	Enabled *bool  `json:"enabled"`
}

// EnabledOr returns the subscription's enabled flag, defaulting to true.
func (s *Subscription) EnabledOr() bool {
	if s.Enabled == nil {
		return true
	}
	return *s.Enabled
}

// Profile is the whole input: the panel's AppConfig serialized as JSON.
type Profile struct {
	Nodes               []Node          `json:"nodes"`
	SiteSets            []SiteSet       `json:"site_sets"`
	Groups              []Group         `json:"groups"`
	Chains              []Chain         `json:"chains"`
	DNS                 *DnsConfig      `json:"dns"`
	DNSRewrites         []DnsRewrite    `json:"dns_rewrites"`
	Terminals           []TerminalPolicy `json:"terminals"`
	TerminalRules       []TerminalRule  `json:"terminal_rules"`
	FinalOutbound       string          `json:"final_outbound"`
	RoutingFallback     string          `json:"routing_fallback"`
	TunStack            string          `json:"tun_stack"`
	TunMtu              int             `json:"tun_mtu"`
	TunAddress          string          `json:"tun_address"`
	QuicBlock           *bool           `json:"quic_block"`
	DirectBypassEnabled *bool           `json:"direct_bypass_enabled"`
	BlockedDomains      []string        `json:"blocked_domains"`
	// AllowDomains is the content-filter allow list (nil = sentinel
	// file; the panel currently never passes one).
	AllowDomains        []string        `json:"allow_domains"`
	ClashAPIPort        int             `json:"clash_api_port"`
	ClashAPIListen      string          `json:"clash_api_listen"`
	ClashAPISecret      string          `json:"clash_api_secret"`
	ShareLANEnabled     bool            `json:"share_lan_enabled"`
	ShareLANPort        int             `json:"share_lan_port"`
	ShareServers        []*Obj          `json:"share_servers"`
	FrontRules          []*Obj          `json:"front_rules"`
	Subscriptions       []Subscription  `json:"subscriptions"`
	SpeedtestURL        string          `json:"speedtest_url"`
	SubNodeDirect       bool            `json:"sub_node_direct"`
	SubDomains          []string        `json:"sub_domains"`
	// DirectHostIPs carries hostnames the panel already resolved at
	// deploy time (the core is a pure function: it does no DNS).
	DirectHostIPs []string `json:"direct_host_ips"`
	// DNSFilterRulesets are the content-filter kernel rule sets the
	// panel prepared (dnsfilter.kernel_ruleset_entries).
	DNSFilterRulesets []RulesetDecl `json:"dns_filter_rulesets"`
	// TerminalDirectCidrs / TerminalDirectV6 are the pre-expanded
	// direct terminal idents and their IPv6 supplement (panel-side
	// ARP reads; the core never reads live system state).
	TerminalDirectCidrs []string `json:"terminal_direct_cidrs"`
	TerminalDirectV6    []string `json:"terminal_direct_v6"`
	// ObnodeDomains / ObnodeCidrs are the direct-host domains and
	// CIDRs the panel pre-computed when sub_node_direct is on
	// (subscription domains + node server domains/IPs, resolved).
	ObnodeDomains []string `json:"obnode_domains"`
	ObnodeCidrs   []string `json:"obnode_cidrs"`
	// WanDNSServers are the system/WAN DNS servers the panel read
	// (resolv.conf / OpenWrt DHCP) for direct_dns/proxy_dns "wan".
	WanDNSServers []string `json:"wan_dns_servers"`
}

// QuicBlockOr returns the QUIC-block switch, defaulting to true
// (Python getattr default) when the profile omits it.
func (p *Profile) QuicBlockOr() bool {
	if p.QuicBlock == nil {
		return true
	}
	return *p.QuicBlock
}

// DirectBypassEnabledOr returns the ingress bypass switch, defaulting
// to true when the profile omits it.
func (p *Profile) DirectBypassEnabledOr() bool {
	if p.DirectBypassEnabled == nil {
		return true
	}
	return *p.DirectBypassEnabled
}

func (p *Profile) DNSFakeIP() bool {
	return p.DNS != nil && p.DNS.EnableFakeIP
}

// TunStackOr returns the TUN stack, defaulting to "mixed".
func (p *Profile) TunStackOr() string {
	if p.TunStack == "" {
		return "mixed"
	}
	return p.TunStack
}

// TunMtuOr returns the TUN MTU, defaulting to 9000.
func (p *Profile) TunMtuOr() int {
	if p.TunMtu == 0 {
		return 9000
	}
	return p.TunMtu
}

// TunAddressOr returns the TUN address, defaulting to 172.19.0.1/30.
func (p *Profile) TunAddressOr() string {
	if p.TunAddress == "" {
		return "172.19.0.1/30"
	}
	return p.TunAddress
}

// ClashAPIListenOr returns the Clash API listen address.
func (p *Profile) ClashAPIListenOr() string {
	if p.ClashAPIListen == "" {
		return "127.0.0.1"
	}
	return p.ClashAPIListen
}

// ClashAPIPortOr returns the Clash API port, defaulting to 9090.
func (p *Profile) ClashAPIPortOr() int {
	if p.ClashAPIPort == 0 {
		return 9090
	}
	return p.ClashAPIPort
}
