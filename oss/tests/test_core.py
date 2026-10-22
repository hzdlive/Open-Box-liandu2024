"""Self-test for core: parse sample subscription, build sing-box config."""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import AppConfig, DnsConfig, SiteSet  # noqa: E402
from core.singbox import build_config  # noqa: E402
from core.subscription import parse_subscription  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main() -> int:
    text = (ROOT / "sample-sub.txt").read_text(encoding="utf-8")
    nodes = parse_subscription(text)
    assert len(nodes) == 5, f"expected 5 nodes, got {len(nodes)}"
    protos = sorted(n.protocol for n in nodes)
    assert protos == ["shadowsocks", "trojan", "vless", "vless", "vmess"], protos
    tags = [n.tag for n in nodes]
    assert len(set(tags)) == len(tags), "tags must be unique"

    site_sets = [SiteSet.from_dict(d) for d in json.loads((ROOT / "sample-sites.json").read_text())]
    cfg = AppConfig(nodes=nodes, site_sets=site_sets, dns=DnsConfig())
    conf = build_config(cfg)

    # 4a932e6: route.final is now the 其他 fallback selector; its default
    # preserves the previous effective final (routing_fallback = direct).
    assert conf["route"]["final"] == "其他"
    _fallback = [o for o in conf["outbounds"] if o["tag"] == "其他"]
    assert len(_fallback) == 1 and _fallback[0]["default"] == "direct", _fallback
    # Rule order (documented features, not test drift): logical entry
    # bypass #0, sniff #1, hijack-dns #2, QUIC obflip block #3, then the
    # 3 site-set rules. The old "sniff + 3 sets + dns = 5" count predates
    # the entry-bypass and obflip rules.
    assert len(conf["route"]["rules"]) == 7
    assert conf["route"]["rules"][1] == {"action": "sniff"}
    # proxy/direct site sets route through their hot-switch selector
    assert conf["route"]["rules"][4]["outbound"].startswith("flip-")
    assert conf["route"]["rules"][5]["outbound"].startswith("flip-")
    assert conf["route"]["rules"][6]["outbound"] == "block"
    flips = [o for o in conf["outbounds"] if o["tag"].startswith("flip-")]
    # proxy + direct + reject site sets each get a selector (reject defaults
    # to block so the card can switch it back); rules still route reject
    # site sets to block directly.
    assert len(flips) == 3, [o["tag"] for o in flips]
    # policy selector members = all user-facing groups (1:1 with original)
    assert flips[0]["outbounds"] == ["direct", "所有-自动", "所有-手动", "block"], flips[0]
    assert {o["tag"] for o in conf["outbounds"]} >= {"所有-自动", "所有-手动", "direct", "block"}
    assert "dns-out" not in {o["tag"] for o in conf["outbounds"]}
    assert conf["dns"]["servers"][0]["tag"] == "dns-direct"
    json.dumps(conf)  # must be serializable

    # rule_set references: site sets with rule_sets emit route.rule_set
    # (type: local) and per-rule "rule_set" matchers; skipped ones are dropped.
    rss_cfg = AppConfig(
        nodes=nodes, dns=DnsConfig(),
        site_sets=[SiteSet(name="yt", action="proxy", rule_sets=["geosite-youtube"]),
                   SiteSet(name="cn", action="direct",
                           rule_sets=["geosite-cn", "geoip-cn"])])
    rc = build_config(rss_cfg)
    decls = {d["tag"]: d for d in rc["route"].get("rule_set", [])}
    # Superset, not exact: the entry-bypass work also declares the inline
    # obnode-direct / obnode-direct-ip sets alongside the site-set ones.
    assert {"geosite-youtube", "geosite-cn", "geoip-cn"} <= set(decls), decls
    assert all(decls[t]["type"] == "local" and decls[t]["format"] == "binary"
               and decls[t]["path"].endswith(f"{t}.srs")
               for t in ("geosite-youtube", "geosite-cn", "geoip-cn")), decls
    matched = [r for r in rc["route"]["rules"] if "rule_set" in r]
    # 3, not 2: the obflip QUIC rule also references geosite-youtube
    # (udp/443 -> block) on top of the two site-set rules.
    assert len(matched) == 3, matched
    _quic = [r for r in matched if r.get("network") == "udp" and r.get("port") == 443]
    assert len(_quic) == 1 and _quic[0]["rule_set"] == ["geosite-youtube"] and _quic[0]["outbound"] == "block", _quic
    matched = [r for r in matched if r not in _quic]
    assert len(matched) == 2, matched
    assert matched[0]["rule_set"] == ["geosite-youtube"]
    assert matched[0]["outbound"].startswith("flip-")
    rc2 = build_config(rss_cfg, skip_rule_sets={"geosite-youtube"})
    decls2 = {d["tag"] for d in rc2["route"].get("rule_set", [])}
    assert {"geosite-cn", "geoip-cn"} <= decls2 and "geosite-youtube" not in decls2, decls2
    assert not [r for r in rc2["route"]["rules"] if r.get("rule_set") == ["geosite-youtube"]]
    # site set with ONLY rule_sets still produces a rule (was silently dropped)
    assert any(r.get("rule_set") == ["geosite-cn", "geoip-cn"] for r in rc["route"]["rules"])
    # geoip-private expands inline (no download needed)
    priv_cfg = AppConfig(nodes=nodes, dns=DnsConfig(),
                         site_sets=[SiteSet(name="lan", action="direct",
                                            rule_sets=["geoip-private"])])
    rp = build_config(priv_cfg)
    # geoip-private expands inline: no *local* (downloaded) rule_set decls.
    # The inline obnode-direct* sets from the entry-bypass work are always
    # present and are not a download.
    assert not [d for d in rp["route"].get("rule_set", []) if d["type"] == "local"], rp["route"].get("rule_set")
    pr = [r for r in rp["route"]["rules"] if "10.0.0.0/8" in (r.get("ip_cidr") or [])]
    assert pr and pr[0]["outbound"] == "flip-lan", pr  # via hot-switch selector

    print(f"OK: {len(nodes)} nodes parsed, config has "
          f"{len(conf['outbounds'])} outbounds / {len(conf['route']['rules'])} route rules / "
          f"{len(conf['dns']['rules'])} dns rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
