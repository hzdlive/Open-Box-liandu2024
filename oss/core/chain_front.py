"""Resolve a chain's front tag into temp-config outbounds (speedtest).

This mirrors what the deployed config builds (see singbox.build_outbounds)
for the same front, so the speedtest measures the chain's real path:

- node tag -> the node outbound;
- selector group -> selector (deploy's default rule: persisted
  default_outbound if still a member, else first member);
- urltest / smart / loadbalance group -> urltest (deploy maps smart and
  loadbalance to urltest);
- failover group -> deploy's lane structure: single-node lanes used
  directly, manual multi-node lanes as selectors, auto multi-node lanes
  as urltests, topped by a selector defaulting to the primary lane.
  (Deploy's top is a selector controlled by the failover state machine;
  a speedtest through it therefore follows the primary lane, like
  production traffic, instead of the fastest lane member.)
- sub-<id> -> urltest over the subscription's nodes (deploy's sub groups);
- another chain's name -> that chain's outbound, with ITS front resolved
  recursively (bounded depth + visited set; validate_front already
  forbids cycles in new data, the guards cover legacy data).

Returns (front_ob, deps, gate_members, gate_group):
- front_ob: the outbound the chain detours through (natural tag; the
  caller renames it to "front"), or None if unresolvable;
- deps: outbounds front_ob references (member outbounds, lane
  outbounds, inner fronts);
- gate_members: node tags the urltest-readiness gate should wait for
  (empty when the front needs no convergence: direct members,
  selectors, single-node lanes);
- gate_group: natural tag of the urltest outbound whose SELECTION the
  gate must wait for (None when no convergence is needed). The gate
  waits for selection, not first-member delay: a 53-member sub group
  measured its first live member at ~1s but its urltest round (dead
  members each cost seconds) only produced a selection at ~115s, so
  probing on first-member delay ran through a selection-less group
  and failed with curl 97/52/28 artifacts.

Previously this lived as _resolve_chain_front in panel/app.py and only
handled nodes and flat groups: failover groups resolved to an empty
member list (their members live in lanes, not group.members), so a
failover-fronted chain silently measured the direct path; sub-<id>
and chain fronts were not resolved at all, leaving a dangling detour
that sing-box check does not catch (rc=0) and the probe failed with a
generic SOCKS error.
"""

from __future__ import annotations

from .failover_sm import failover_lane_tag
from .singbox import chain_to_outbound, node_to_outbound, resolve_group_members

MAX_DEPTH = 5


def resolve_chain_front(cfg, front_tag):
    """Resolve front_tag to (front_ob, deps, gate_members, gate_group)."""
    if not front_tag or front_tag in ("direct", "block"):
        return None, None, [], None
    ob, deps, gate, gate_group = _resolve(cfg, front_tag, 0, frozenset())
    if ob is None:
        return None, None, [], None
    # Duplicate outbound tags fail sing-box check; shared inner fronts
    # (two chains fronted by the same node) must appear once.
    seen = set()
    uniq = []
    for d in deps:
        if d.get("tag") not in seen:
            seen.add(d.get("tag"))
            uniq.append(d)
    return ob, uniq, gate, gate_group


def _node_map(cfg):
    return {n.tag: n for n in cfg.nodes}


def _group_map(cfg):
    return {g.name: g for g in (cfg.groups or [])}


def _chain_map(cfg):
    return {c.name: c for c in (cfg.chains or [])}


def _resolve(cfg, front_tag, depth, visited):
    if depth > MAX_DEPTH or front_tag in visited:
        return None, None, [], None
    visited = visited | {front_tag}
    nodes = _node_map(cfg)
    groups = _group_map(cfg)
    chains = _chain_map(cfg)

    # Single node
    if front_tag in nodes:
        return node_to_outbound(nodes[front_tag]), [], [], None

    # Subscription group (deploy's sub-<id> urltest)
    if front_tag.startswith("sub-") and front_tag[4:].isdigit():
        sid = int(front_tag[4:])
        subs = {s.get("id"): s for s in (cfg.subscriptions or [])}
        sub = subs.get(sid)
        if not sub or not sub.get("enabled", True):
            return None, None, [], None
        tags = [n.tag for n in cfg.nodes if n.sub_id == sid]
        if not tags:
            return None, None, [], None
        deps = [node_to_outbound(nodes[t]) for t in tags]
        ob = {"type": "urltest", "tag": front_tag, "outbounds": tags,
              "url": cfg.speedtest_url, "interval": "300s",
              "tolerance": 100}
        return ob, deps, tags, front_tag

    # Group
    if front_tag in groups:
        g = groups[front_tag]
        if not g.enabled:
            return None, None, [], None
        if g.type == "failover":
            return _resolve_failover(cfg, g, depth, visited)
        node_tags = [n.tag for n in cfg.nodes]
        chain_tags = [c.name for c in cfg.chains]
        members = resolve_group_members(g, node_tags, chain_tags)
        return _resolve_group_members(cfg, g, members, depth, visited)

    # Another chain: its outbound, with ITS front resolved recursively.
    if front_tag in chains:
        ch = chains[front_tag]
        if not ch.enabled:
            return None, None, [], None
        ob = chain_to_outbound(ch)
        inner_tag = ch.front
        if not inner_tag or inner_tag == "direct":
            ob["detour"] = "direct"
            return ob, [], [], None
        if inner_tag == "block":
            return None, None, [], None
        inner_ob, inner_deps, inner_gate, inner_group = _resolve(
            cfg, inner_tag, depth + 1, visited)
        if inner_ob is None:
            return None, None, [], None
        ob["detour"] = inner_ob["tag"]
        return ob, [inner_ob] + inner_deps, inner_gate, inner_group

    return None, None, [], None


def _resolve_group_members(cfg, g, members, depth, visited):
    """Build a selector/urltest front over resolved members.

    Chain members are resolved recursively (their outbounds join deps);
    an unresolvable member is skipped rather than left dangling. If no
    member resolves, the front is unresolvable.
    """
    nodes = _node_map(cfg)
    chains = _chain_map(cfg)
    deps = []
    tags = []
    gate = []
    for m in members:
        if m in nodes:
            deps.append(node_to_outbound(nodes[m]))
            tags.append(m)
            gate.append(m)
        elif m in chains:
            ob, sub_deps, _, _ = _resolve(cfg, m, depth + 1, visited)
            if ob is None:
                continue
            deps.append(ob)
            deps.extend(sub_deps)
            tags.append(m)
    if not tags:
        return None, None, [], None
    if g.type == "selector":
        default = g.default_outbound if g.default_outbound in tags \
            else tags[0]
        ob = {"type": "selector", "tag": g.name, "outbounds": tags,
              "default": default}
        return ob, deps, [], None
    # urltest / smart / loadbalance (deploy maps the latter two to urltest)
    ob = {"type": "urltest", "tag": g.name, "outbounds": tags,
          "url": g.test_url or cfg.speedtest_url,
          "interval": f"{g.interval_s}s",
          "tolerance": g.tolerance_ms,
          "idle_timeout": g.idle_timeout}
    if g.expected_status:
        ob["expected_status"] = g.expected_status
    return ob, deps, gate, g.name


def _resolve_failover(cfg, g, depth, visited):
    """Build a failover front mirroring deploy's lane structure."""
    nodes = _node_map(cfg)
    chains = _chain_map(cfg)
    node_tags = [n.tag for n in cfg.nodes]
    chain_tags = [c.name for c in cfg.chains]
    deps = []
    top_members = []
    gate = []
    primary_gate = None
    primary_gate_group = None
    for i, ln in enumerate(g.lanes or []):
        lane_members = [t for t in (ln.get("members") or [])
                        if t in node_tags or t in chain_tags]
        if not lane_members:
            continue
        lane_tag = failover_lane_tag(g.name, ln, i)
        # Only members that actually produced a dep count (chain
        # members that failed to resolve are skipped, not dangled).
        # Tags are unique, so a dep produced by an earlier lane serves
        # a later lane that references the same member.
        for m in lane_members:
            have = {d["tag"] for d in deps}
            if m in nodes:
                if m not in have:
                    deps.append(node_to_outbound(nodes[m]))
            elif m in chains:
                ob, sub_deps, _, _ = _resolve(cfg, m, depth + 1, visited)
                if ob is None:
                    continue
                if ob["tag"] not in have:
                    deps.append(ob)
                    deps.extend(sub_deps)
        have = {d["tag"] for d in deps}
        lane_members = [t for t in lane_members if t in have]
        if not lane_members:
            continue
        lane_gate = list(lane_members)
        if len(lane_members) == 1:
            top_members.append(lane_members[0])
            if primary_gate is None:
                primary_gate = []  # single node: no convergence needed
        elif (ln.get("mode") or "auto") == "manual":
            deps.append({"type": "selector", "tag": lane_tag,
                         "outbounds": lane_members,
                         "default": lane_members[0]})
            top_members.append(lane_tag)
            if primary_gate is None:
                primary_gate = []
        else:
            deps.append({"type": "urltest", "tag": lane_tag,
                         "outbounds": lane_members,
                         "url": g.test_url or cfg.speedtest_url,
                         "interval": f"{g.interval_s}s",
                         "tolerance": g.tolerance_ms,
                         "idle_timeout": g.idle_timeout})
            top_members.append(lane_tag)
            if primary_gate is None:
                primary_gate = lane_gate
                primary_gate_group = lane_tag
    if not top_members:
        return None, None, [], None
    ob = {"type": "selector", "tag": g.name, "outbounds": top_members,
          "default": top_members[0]}
    return ob, deps, primary_gate or [], primary_gate_group
