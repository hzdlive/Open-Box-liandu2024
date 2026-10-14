"""CLI: subscription -> sing-box config.json.

Usage:
    python3 -m core.cli build --sub SUB_FILE --sites SITES_JSON -o config.json
    python3 -m core.cli parse --sub SUB_FILE
"""

from __future__ import annotations

import argparse
import json
import sys

from .models import AppConfig, DnsConfig, SiteSet
from .singbox import build_config
from .subscription import parse_subscription


def cmd_parse(args: argparse.Namespace) -> int:
    text = open(args.sub, encoding="utf-8").read()
    nodes = parse_subscription(text)
    for n in nodes:
        print(f"{n.protocol:12} {n.server}:{n.server_port}  {n.tag}")
    print(f"total: {len(nodes)}", file=sys.stderr)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    text = open(args.sub, encoding="utf-8").read()
    nodes = parse_subscription(text)
    if not nodes:
        print("error: no nodes parsed from subscription", file=sys.stderr)
        return 1
    site_sets = []
    if args.sites:
        for d in json.load(open(args.sites, encoding="utf-8")):
            site_sets.append(SiteSet.from_dict(d))
    cfg = AppConfig(
        nodes=nodes,
        site_sets=site_sets,
        dns=DnsConfig(direct_dns=args.dns_direct, proxy_dns=args.dns_proxy),
        final_outbound=args.final,
        tun_stack=args.tun_stack,
    )
    out = json.dumps(build_config(cfg), ensure_ascii=False, indent=2)
    if args.o:
        open(args.o, "w", encoding="utf-8").write(out + "\n")
        print(f"wrote {args.o} ({len(nodes)} nodes, {len(site_sets)} site sets)")
    else:
        print(out)
    return 0


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="openbox-oss")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="list parsed nodes")
    p.add_argument("--sub", required=True)

    b = sub.add_parser("build", help="build sing-box config.json")
    b.add_argument("--sub", required=True, help="subscription file (base64 or plain links)")
    b.add_argument("--sites", default=None, help="site sets JSON file")
    b.add_argument("--dns-direct", default="223.5.5.5")
    b.add_argument("--dns-proxy", default="tcp://1.1.1.1")
    b.add_argument("--final", default="auto", help="final outbound tag")
    b.add_argument("--tun-stack", default="mixed", choices=["mixed", "gvisor", "system"])
    b.add_argument("-o", default=None, help="output file (default: stdout)")

    args = ap.parse_args(argv)
    return cmd_parse(args) if args.cmd == "parse" else cmd_build(args)


if __name__ == "__main__":
    raise SystemExit(main())
