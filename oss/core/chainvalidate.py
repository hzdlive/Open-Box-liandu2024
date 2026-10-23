"""Chain front validation (v6 #12 deploy-leaves 对照，面板 API 边界版).

A chain's ``front`` is the outbound its traffic detours through. Until now
create/update only validated ``exit_protocol``: any string was accepted as
a front, so a typo, a deleted target, a self-reference or a detour cycle
would sail into the config. sing-box check does NOT catch dangling detour
references (rc=0, verified live), so the failure would surface only at
runtime, per connection, with no pointer at the cause.

This module fails fast at the API boundary instead. v6 #12's drop
semantics (self-reference reported as ``upstream``, a mutual pair as a
single ``cycle``, one drop per round) describe their deploy-time *drop
reporting*; a panel API can do better and simply refuse to store an
unusable front. The resolution order below (node, then group, then
subscription, then chain) matches the order the panel itself resolves a
front tag (see ``_resolve_chain_front``); a name colliding across tables
is a duplicate-outbound-tag hazard of its own and is left to config check.

Valid fronts:
- ``direct`` / ``block`` (builtins, always valid);
- an enabled node tag (load_app_config's node filter: subscription enabled
  and node not disabled);
- an enabled group name;
- ``sub-<id>`` for an enabled subscription (built as a urltest group);
- the name of another, enabled chain.

Rejected (ValueError, user-facing Chinese message):
- empty front; unknown name; a disabled node/group/subscription/chain
  (distinguished from unknown, so the user knows to re-enable it);
- self-reference (front == own name);
- a detour cycle through enabled chains (the walk follows only enabled
  chains: a disabled chain is not built, so no runtime loop can pass
  through it, and its own front is inert until re-enabled).

Only the fields that change are validated: an update that touches neither
name nor front (e.g. toggling enabled) never fails on a legacy bad front,
except re-enabling, which makes the front live again. An update that
disables the chain skips front validation entirely.
"""

from __future__ import annotations

import sqlite3

BUILTINS = ("direct", "block")


def _all(conn: sqlite3.Connection):
    nodes = {r[0]: bool(r[1]) for r in conn.execute(
        "SELECT n.tag, (s.enabled = 1 AND n.disabled = 0) FROM nodes n"
        " JOIN subscriptions s ON s.id = n.sub_id")}
    groups = {r[0]: bool(r[1]) for r in conn.execute(
        "SELECT name, enabled FROM groups")}
    subs = {r[0]: bool(r[1]) for r in conn.execute(
        "SELECT id, enabled FROM subscriptions")}
    chains = {r[0]: (r[1], bool(r[2])) for r in conn.execute(
        "SELECT name, front, enabled FROM chains")}
    return nodes, groups, subs, chains


def validate_front(conn: sqlite3.Connection, name: str, front: str,
                   old_name: str | None = None) -> None:
    """Raise ValueError if (name, front) cannot be stored. Else return None.

    old_name: when renaming, the previous name is dropped from the walk
    graph (chains pointing at it dangle after the rename; they are not
    edges of the new name).
    """
    front = (front or "").strip()
    if not front:
        raise ValueError("前置不能为空")
    if front in BUILTINS:
        return
    if front == name:
        # Self-reference, checked before existence: on create the chain
        # does not exist yet, so an existence-first order would misreport
        # it as unknown instead of self-referential.
        raise ValueError("前置不能是自身")
    nodes, groups, subs, chains = _all(conn)
    if old_name is not None and old_name != name:
        # Post-update world: the old name no longer exists.
        chains.pop(old_name, None)
    if front.startswith("sub-"):
        try:
            sid = int(front[4:])
        except ValueError:
            raise ValueError(f"前置 {front} 不存在") from None
        if subs.get(sid):
            return
        if sid in subs:
            raise ValueError(f"前置订阅 {front} 已停用")
        raise ValueError(f"前置 {front} 不存在")
    if nodes.get(front) or groups.get(front):
        return
    if front in nodes or front in groups:
        raise ValueError(f"前置 {front} 已停用")
    if front in chains:
        chain_front, chain_enabled = chains[front]
        if not chain_enabled:
            raise ValueError(f"前置链 {front} 已停用")
        # Cycle walk through enabled chains only, candidate included.
        graph = {n: f for n, (f, e) in chains.items() if e}
        graph[name] = front
        path = [name]
        cur = front
        while cur in graph:
            if cur in path:
                raise ValueError(
                    f"前置成环：{' → '.join(path + [cur])}")
            path.append(cur)
            cur = graph[cur]
        return
    raise ValueError(f"前置 {front} 不存在（节点/分组/链/订阅均无此名称）")
