"""Bad-node location for failed config validation (v5 config-validate 对照).

When ``sing-box check`` rejects a generated config, its message names the
failing outbound by INDEX (``outbounds[N].field: ...`` or
``outbounds[N]: ...``). This module maps that index back to the node /
group / subscription the user actually manages, so an apply failure can
say *which* node is bad instead of only quoting the kernel error.

Scope notes (all verified against sing-box 1.14.1-openbox-tcp28):

- The index is direct: our check runs on the real config, so kernel
  ``outbounds[N]`` IS ``config["outbounds"][N]``. v5's "-1" rule is an
  artifact of *their vet probe configs* (a ``__openbox_vet_direct`` outbound
  injected at position 0) and does NOT apply here.
- check does NOT catch everything: dangling selector/route references and
  malformed uuids pass check (rc=0) and fail only at runtime. Those are
  the vet-probe harness's job (deferred); this module only locates
  check-time failures, and returns None when the message carries no
  outbound index.
- One failure is located per apply (check stops at the first decode
  error); fixing it and re-applying surfaces the next one. Iterative
  removal (vetOutbounds) is deferred, not attempted here.
"""

from __future__ import annotations

import re

OUTBOUND_RE = re.compile(r"outbounds\[(\d+)\]")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

BUILTIN_TAGS = {"direct", "block", "dns-out"}


class ValidationError(RuntimeError):
    """Config validation failure, carrying the located bad node (if any)."""

    def __init__(self, message: str, bad: dict | None = None):
        self.bad = bad
        super().__init__(message)


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def find_outbound_index(message: str) -> int | None:
    """First ``outbounds[N]`` index in the message, or None."""
    m = OUTBOUND_RE.search(_strip_ansi(message or ""))
    return int(m.group(1)) if m else None


def resolve_tag(tag: str, nodes: dict, sub_names: dict,
                groups: set, site_sets: dict) -> dict:
    """Resolve a config outbound tag to what the user manages.

    nodes: {tag: {"sub_id", "protocol", "server"}};
    sub_names: {sub_id: name}; groups: {group name};
    site_sets: {site_set_id: name}.
    """
    if tag in nodes:
        node = nodes[tag]
        sub = sub_names.get(node.get("sub_id"), "")
        return {"kind": "node", "tag": tag, "node": tag,
                "subscription": sub, "protocol": node.get("protocol", ""),
                "server": node.get("server", "")}
    if tag in groups:
        return {"kind": "group", "tag": tag, "name": tag}
    if tag.startswith("sub-"):
        try:
            sub = sub_names.get(int(tag[4:]), "")
        except ValueError:
            sub = ""
        return {"kind": "subscription_group", "tag": tag, "subscription": sub}
    if tag.startswith("flip-"):
        try:
            name = site_sets.get(int(tag[5:]), "")
        except ValueError:
            name = ""
        return {"kind": "site_set", "tag": tag, "name": name}
    if tag == "其他":
        return {"kind": "final", "tag": tag, "name": "其他"}
    if tag in BUILTIN_TAGS:
        return {"kind": "builtin", "tag": tag}
    return {"kind": "unknown", "tag": tag}


def _summary(resolved: dict, index: int) -> str:
    kind = resolved["kind"]
    if kind == "node":
        parts = []
        if resolved.get("subscription"):
            parts.append(f"订阅 {resolved['subscription']}")
        if resolved.get("protocol"):
            parts.append(resolved["protocol"])
        if resolved.get("server"):
            parts.append(resolved["server"])
        tail = f"（{'，'.join(parts)}）" if parts else ""
        return f"节点 {resolved['tag']}{tail}导致配置校验失败"
    if kind == "group":
        return f"分组 {resolved['name']}导致配置校验失败"
    if kind == "subscription_group":
        sub = resolved.get("subscription")
        return f"订阅组 {sub or resolved['tag']}导致配置校验失败"
    if kind == "site_set":
        name = resolved.get("name")
        return f"站点集 {name or resolved['tag']}的切换器导致配置校验失败"
    if kind == "final":
        return "兜底策略（其他）导致配置校验失败"
    if kind == "builtin":
        return f"内置出站 {resolved['tag']}导致配置校验失败"
    return f"出站 {resolved['tag']}（配置中第 {index} 个）导致配置校验失败"


def locate(message: str, cfg: dict, nodes: dict, sub_names: dict,
           groups: set, site_sets: dict) -> dict | None:
    """Locate the failing outbound in a check message. None if not locatable."""
    index = find_outbound_index(message)
    if index is None:
        return None
    outbounds = (cfg or {}).get("outbounds") or []
    if index >= len(outbounds):
        return None
    tag = (outbounds[index] or {}).get("tag")
    if not tag:
        return None
    resolved = resolve_tag(tag, nodes, sub_names, groups, site_sets)
    detail = _strip_ansi(message or "").strip().splitlines()
    result = {"index": index, "tag": tag, **resolved,
              "kernel_detail": (detail[0][:300] if detail else "")}
    result["summary"] = _summary(resolved, index)
    return result


def locate_from_db(message: str, cfg: dict, conn) -> dict | None:
    """locate() with node/group/subscription data read from the panel DB."""
    try:
        nodes = {}
        for tag, protocol, server, sub_id in conn.execute(
                "SELECT tag, protocol, server, sub_id FROM nodes"):
            nodes[tag] = {"protocol": protocol, "server": server,
                          "sub_id": sub_id}
        sub_names = {r[0]: r[1] for r in
                     conn.execute("SELECT id, name FROM subscriptions")}
        groups = {r[0] for r in conn.execute("SELECT name FROM groups")}
        site_sets = {r[0]: r[1] for r in
                     conn.execute("SELECT id, name FROM site_sets")}
    except Exception:
        return None
    return locate(message, cfg, nodes, sub_names, groups, site_sets)
