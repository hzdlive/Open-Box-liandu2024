"""Profile serialization: AppConfig -> the oss-core profile JSON.

The Go core takes one JSON document (the "profile") plus a workdir
and produces the sing-box config. This module builds that document
from the panel's AppConfig, including the pre-computed fields the
panel derives at deploy time (terminal expansions, obnode sets, WAN
DNS servers, dns-filter rule-set entries).

The pre-computed derivation lives here (not in the harness) so the
panel and the core-go harness share one implementation.
"""

from __future__ import annotations

import copy
import dataclasses
import ipaddress

from core import arp as _arp
from core import dnstest as _dnstest
from core import singbox as _sb


def derive_precomputed(profile: dict) -> dict:
    """Fill the pre-computed profile fields the panel derives.

    Terminal direct sets come from the live ARP/neighbour tables;
    obnode sets come from subscription domains + node servers, with
    the domains resolved through the host's own resolvers.
    """
    out = copy.deepcopy(profile)
    terminals = profile.get("terminals", [])
    out["terminal_direct_cidrs"] = _arp.expand_terminal_idents(
        [t["ident"] for t in terminals if t.get("policy") == "direct"])
    out["terminal_direct_v6"] = _arp.expand_terminal_supplement_v6(
        [t["ident"] for t in terminals
         if t.get("policy") == "direct" and _arp.is_mac(t.get("ident", ""))])
    for tr in out.get("terminal_rules", []):
        if tr.get("match_by") == "mac":
            tr["cidrs"] = _arp.expand_terminal_idents(tr.get("targets", []))
            tr["v6_cidrs"] = _arp.expand_terminal_supplement_v6(
                [t for t in tr.get("targets", []) if _arp.is_mac(t)])
        else:
            cidrs = []
            for t in tr.get("targets", []):
                t = str(t).strip()
                if t:
                    cidrs.append(t if "/" in t else f"{t}/32")
            tr["cidrs"] = cidrs
            tr["v6_cidrs"] = []
    if profile.get("sub_node_direct"):
        snd = set(profile.get("sub_domains", []))
        cidrs: set[str] = set()
        for n in profile.get("nodes", []):
            srv = (n.get("server") or "").strip().lower()
            if not srv:
                continue
            if _sb._is_ip_literal(srv):
                ip = ipaddress.ip_address(srv)
                cidrs.add(f"{ip}/{'128' if ip.version == 6 else '32'}")
            else:
                snd.add(srv)
        if snd:
            for ip in _sb.resolve_host_ips(sorted(snd)):
                cidrs.add(f"{ip}/{'128' if ':' in ip else '32'}")
        out["obnode_domains"] = sorted(snd)
        out["obnode_cidrs"] = sorted(cidrs)
    else:
        out["obnode_domains"] = []
        out["obnode_cidrs"] = []
    return out


def app_config_to_profile(app_cfg, workdir: str) -> dict:
    """Serialize an AppConfig to the oss-core profile document.

    workdir is the panel data directory (used for the dns-filter
    rule-set entry paths; the core rewrites them on `config`).
    """
    profile = dataclasses.asdict(app_cfg)
    profile["wan_dns_servers"] = list(_dnstest.system_upstreams())
    rulesets = getattr(app_cfg, "_dns_filter_rulesets", None)
    if rulesets:
        profile["dns_filter_rulesets"] = [
            {"tag": e["tag"], "path": e["path"]} for e in rulesets]
    else:
        profile["dns_filter_rulesets"] = []
    return derive_precomputed(profile)
