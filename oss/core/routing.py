"""Route preview: which site set a domain/IP hits, top-down first match.

Semantics follow the publicly documented behavior:
- site sets are evaluated top-down, first hit wins;
- a domain target is only tested against domain conditions
  (exact / suffix / keyword); an IP target only against ip_cidr.
"""

from __future__ import annotations

import ipaddress

from .models import SiteSet


def _is_ip(target: str):
    try:
        return ipaddress.ip_address(target)
    except ValueError:
        return None


def preview_route(site_sets: list[SiteSet], target: str) -> dict:
    """Return {site_set, action, outbound} for a domain or IP target."""
    t = target.strip().lower().rstrip(".")
    if not t:
        return {"site_set": None, "action": "final", "outbound": None}
    ip = _is_ip(t)
    for s in site_sets:
        hit = False
        if ip is not None:
            for cidr in s.ip_cidr:
                try:
                    if ip in ipaddress.ip_network(cidr, strict=False):
                        hit = True
                        break
                except ValueError:
                    continue
        else:
            if any(t == d.lower() for d in s.domains):
                hit = True
            elif any(t == suf.lower() or t.endswith("." + suf.lower()) for suf in s.domain_suffix):
                hit = True
            elif any(kw.lower() in t for kw in s.domain_keyword):
                hit = True
        if hit:
            # Resolve through the hot-switch state: flip overrides action.
            eff = s.flip if s.flip in ("direct", "proxy") else s.action
            outbound = {"proxy": s.group, "direct": "direct", "reject": "block"}.get(eff, s.group)
            return {"site_set": s.name, "action": s.action, "outbound": outbound,
                    "flip": s.flip or None}
    return {"site_set": None, "action": "final", "outbound": None}
