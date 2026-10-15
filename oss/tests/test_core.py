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

    assert conf["route"]["final"] == "所有-自动"
    # sniff action + 3 site sets + dns rule
    assert len(conf["route"]["rules"]) == 5
    assert conf["route"]["rules"][0] == {"action": "sniff"}
    # proxy/direct site sets route through their hot-switch selector
    assert conf["route"]["rules"][1]["outbound"].startswith("flip-")
    assert conf["route"]["rules"][2]["outbound"].startswith("flip-")
    assert conf["route"]["rules"][3]["outbound"] == "block"
    flips = [o for o in conf["outbounds"] if o["tag"].startswith("flip-")]
    assert len(flips) == 2, [o["tag"] for o in flips]
    assert {o["tag"] for o in conf["outbounds"]} >= {"所有-自动", "所有-手动", "direct", "block"}
    assert "dns-out" not in {o["tag"] for o in conf["outbounds"]}
    assert conf["dns"]["servers"][0]["tag"] == "direct-dns"
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
    assert set(decls) == {"geosite-youtube", "geosite-cn", "geoip-cn"}, decls
    assert all(d["type"] == "local" and d["format"] == "binary"
               and d["path"].endswith(f"{t}.srs") for t, d in decls.items()), decls
    matched = [r for r in rc["route"]["rules"] if "rule_set" in r]
    assert len(matched) == 2, matched
    assert matched[0]["rule_set"] == ["geosite-youtube"]
    assert matched[0]["outbound"].startswith("flip-")
    rc2 = build_config(rss_cfg, skip_rule_sets={"geosite-youtube"})
    decls2 = {d["tag"] for d in rc2["route"].get("rule_set", [])}
    assert decls2 == {"geosite-cn", "geoip-cn"}, decls2
    assert not [r for r in rc2["route"]["rules"] if r.get("rule_set") == ["geosite-youtube"]]
    # site set with ONLY rule_sets still produces a rule (was silently dropped)
    assert any(r.get("rule_set") == ["geosite-cn", "geoip-cn"] for r in rc["route"]["rules"])

    print(f"OK: {len(nodes)} nodes parsed, config has "
          f"{len(conf['outbounds'])} outbounds / {len(conf['route']['rules'])} route rules / "
          f"{len(conf['dns']['rules'])} dns rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
