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

    assert conf["route"]["final"] == "auto"
    assert len(conf["route"]["rules"]) == 4  # 3 site sets + dns rule
    # proxy/direct site sets route through their hot-switch selector
    assert conf["route"]["rules"][0]["outbound"].startswith("flip-")
    assert conf["route"]["rules"][1]["outbound"].startswith("flip-")
    assert conf["route"]["rules"][2]["outbound"] == "block"
    flips = [o for o in conf["outbounds"] if o["tag"].startswith("flip-")]
    assert len(flips) == 2, [o["tag"] for o in flips]
    assert {o["tag"] for o in conf["outbounds"]} >= {"auto", "manual", "direct", "block", "dns-out"}
    assert conf["dns"]["servers"][0]["tag"] == "direct-dns"
    json.dumps(conf)  # must be serializable

    print(f"OK: {len(nodes)} nodes parsed, config has "
          f"{len(conf['outbounds'])} outbounds / {len(conf['route']['rules'])} route rules / "
          f"{len(conf['dns']['rules'])} dns rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
