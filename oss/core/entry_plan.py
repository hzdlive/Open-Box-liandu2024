"""Entry bypass plan (入口绕过规划).

Clean-room implementation of the publicly observable behavior:
- Master switch: direct_bypass_kernel (default ON for new installs)
- Two auto modes:
  - blacklist (Default-release): FakeIP ON and final=direct.
    Proxied domains get FakeIP and must enter kernel; everything else
    bypasses at ingress unless in the "enter kernel" set.
  - whitelist (Default-enter): everything else.
    Only direct IP sets (default geoip-cn) bypass at ingress;
    overlapping ranges with proxy sets are subtracted.
- Mode switches only rewrite ruleset files, kernel does not restart.
- Rules page shows mode and reason.

Based on third-party behavioral reports (not reversed code).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EntryPlan:
    """Result of entry_plan()."""
    mode: str = "whitelist"  # "blacklist" | "whitelist"
    reason: str = ""  # human-readable reason for the mode
    reason_key: str = ""  # i18n key for the reason
    enabled: bool = True  # master switch
    # CIDRs that must enter kernel (blacklist mode: proxy/reject sets)
    need_cidrs: list[str] = field(default_factory=list)
    # Rule-set tags needed for nftables (whitelist mode: direct sets)
    need_sets: list[str] = field(default_factory=list)
    # Direct-answer release set info (blacklist mode only)
    direct_answer: bool = False


def entry_plan(
    *,
    enabled: bool,
    fakeip_enabled: bool,
    final_outbound: str,
    direct_cidrs: list[str] | None = None,
    proxy_cidrs: list[str] | None = None,
) -> EntryPlan:
    """Compute the entry bypass plan.

    Args:
        enabled: master switch (direct_bypass_kernel)
        fakeip_enabled: whether FakeIP is on for proxied domains
        final_outbound: the final outbound (e.g. "direct", "所有-自动")
        direct_cidrs: CIDRs of direct site sets (for whitelist mode)
        proxy_cidrs: CIDRs of proxy/reject site sets (for blacklist mode)

    Returns:
        EntryPlan with mode, reason, and required sets.
    """
    plan = EntryPlan(enabled=enabled)

    if not enabled:
        plan.mode = "whitelist"
        plan.reason_key = "entryBypassDisabled"
        plan.reason = "入口绕过已关闭，所有流量进内核"
        return plan

    # Blacklist condition: FakeIP ON and final=direct
    # (aligned with original: "FakeIP 开且兜底直连")
    is_final_direct = final_outbound.strip().lower() in ("direct", "直连", "direct-out")
    if fakeip_enabled and is_final_direct:
        plan.mode = "blacklist"
        plan.reason_key = "entryBypassBlacklist"
        plan.reason = "FakeIP 已开启且兜底为直连：代理域名经 FakeIP 必进内核，其余在入口放行"
        plan.need_cidrs = list(proxy_cidrs or [])
        plan.direct_answer = True
    else:
        plan.mode = "whitelist"
        plan.reason_key = "entryBypassWhitelist"
        if not fakeip_enabled:
            plan.reason = "FakeIP 未开启：仅直连 IP 集合在入口放行"
        else:
            plan.reason = "兜底非直连：仅直连 IP 集合在入口放行"
        # Subtract overlapping proxy ranges from direct sets
        # (simplified: return direct_cidrs, caller handles subtraction)
        plan.need_cidrs = list(direct_cidrs or [])

    return plan


def plan_to_dict(plan: EntryPlan) -> dict:
    """Serialize EntryPlan to dict for API."""
    return {
        "mode": plan.mode,
        "reason": plan.reason,
        "reason_key": plan.reason_key,
        "enabled": plan.enabled,
        "need_cidrs": plan.need_cidrs,
        "need_sets": plan.need_sets,
        "direct_answer": plan.direct_answer,
    }
