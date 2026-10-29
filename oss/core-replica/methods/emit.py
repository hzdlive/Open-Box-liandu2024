"""emitGroups: groups + all outbounds -> sing-box outbounds + metadata.

Derived from core-golden.json (121 cases). Output shape (always):

    {builtin, dropped, failover, internalTags, outbounds,
     placeholders, publicTags}

Pipeline (measured):

- Groups are normalized in emitGroups' own pass, which overlaps
  normalizeGroups but differs in three measured ways: urltest
  intervals are kept RAW (no duration validation: "abc" stays "abc"),
  failover intervals go through strict+salvage validation (below),
  and lane ids are generated positionally ("lane-1", "lane-2").
- Builtins (by id) short-circuit to {tag, type: direct|block}
  outbounds; they always emit (no case covers a disabled builtin —
  INFERRED, since placeholders and failover rejectTags reference
  them unconditionally).
- A disabled user group is skipped entirely (disabled case).
- selector/urltest: members resolve against allOutbounds tags,
  in group order; a group with no resolvable member becomes a
  placeholder (outbounds [directTag], name in placeholders).
  Member dedup is INFERRED (only lane dedup is measured).
- A group with mode "dynamic" (the 所有-自动 / 所有-手动 groups)
  resolves to ALL allOutbounds tags in ALL order, ignoring its
  listed members (real + allAutoRealGroupsSynthNodes cases); the
  empty-resolved placeholder rule then applies uniformly if ALL is
  empty (unprobed). Dynamic expansion applies to selector/urltest
  member resolution only, not to failover lanes (no case covers a
  dynamic failover group — INFERRED).
- urltest outbound: {idle_timeout, interval, outbounds, tag,
  tolerance, type: urltest, url}; url = testUrl or the google
  generate_204 default; interval = raw string or "300s";
  idle_timeout = the winning input string of max(interval,
  idleTimeout), where idleTimeout defaults to "12h" and an
  unparseable interval counts as 0.
- failover group: lane sub-urltests (for lanes with >= 2 valid
  members) are emitted before the group selector; the selector is
  {default: first valid lane ref or rejectTag,
  interrupt_exist_connections: true, outbounds: [valid refs...] +
  [rejectTag], tag, type: selector}; the failover entry carries the
  lane table and settings; sub-urltest idle_timeout =
  max(validated interval, 12h) and the group's idleTimeout field is
  IGNORED (failover-sub/idle-ignored case).
- publicTags are the emitted outbound tags in order, excluding the
  internal __fo: sub-tags (which go to internalTags).
- dropped is [] in all 121 cases; emitted unconditionally (no case
  populates it — INFERRED as always-empty here).
- args[2] (chain outbounds, or {}) has no measured effect on
  validity (valid = members ∩ allOutbounds tags; no case puts a
  chain tag in allOutbounds or resolves one) and is ignored.

Failover interval validation (failover-interval + failover-sub
families, 48 cases):

- STRICT: anchored ^\\+?(\\d+(\\.\\d+)?(ns|us|µs|μs|ms|s|m|h))+$,
  parsed to ms; in [5000, 86400000] -> OK (verbatim string, ms).
  Note the strict form allows a leading "+" and repeated terms
  ("1h1h", "5s5s") but NOT a leading "-" or a leading dot.
- Else SALVAGE: if the string contains whitespace -> BAD (the two
  space cases are bad, not salvaged); else the first
  digits(+fraction)+unit token anywhere ("abc5s" -> "5s",
  "5m3" -> "5m", "-5s" -> "5s", ".5s" -> "5s"), or a bare digit
  string as seconds ("5" -> 5s, "86400" -> 86400s); if the salvaged
  ms is in [5000, 86400000] -> SALVAGE (verbatim original string,
  ms); else BAD.
- BAD (including non-string intervals) -> interval "300s",
  intervalMs 300000.
"""

import re
from decimal import Decimal, InvalidOperation

from .normalize import _bool, _num, _str, _str_list

DEFAULT_TEST_URL = "http://www.gstatic.com/generate_204"
FAILOVER_MIN_MS = 5000
FAILOVER_MAX_MS = 86400000

_UNIT_MS = {
    "ns": Decimal("0.000001"),
    "us": Decimal("0.001"),
    "µs": Decimal("0.001"),
    "μs": Decimal("0.001"),
    "ms": Decimal("1"),
    "s": Decimal("1000"),
    "m": Decimal("60000"),
    "h": Decimal("3600000"),
}

_STRICT_RE = re.compile(
    r"^\+?(\d+(\.\d+)?(ns|us|µs|μs|ms|s|m|h))+$")
_SALVAGE_RE = re.compile(r"(\d+(\.\d+)?)(ns|us|µs|μs|ms|s|m|h)")
_BARE_DIGITS_RE = re.compile(r"^\d+$")
_DURATION_RE = re.compile(
    r"^(\d+(\.\d+)?(ns|us|µs|μs|ms|s|m|h))+$")


def _parse_duration_ms(text):
    """Parse a strict duration string to ms (int, truncated), or None."""
    if not isinstance(text, str) or not _STRICT_RE.match(text):
        return None
    total = Decimal("0")
    for number, _frac, unit in re.findall(
            r"(\d+(\.\d+)?)(ns|us|µs|μs|ms|s|m|h)", text):
        try:
            total += Decimal(number) * _UNIT_MS[unit]
        except (InvalidOperation, KeyError):
            return None
    return int(total)


def _parse_lenient_ms(text):
    """Parse any duration-like string to ms, or None (for max())."""
    ms = _parse_duration_ms(text)
    if ms is not None:
        return ms
    if isinstance(text, str):
        m = _SALVAGE_RE.search(text)
        if m:
            try:
                return int(Decimal(m.group(1)) * _UNIT_MS[m.group(3)])
            except (InvalidOperation, KeyError):
                return None
    return None


def _validate_failover_interval(value):
    """Return (interval_string, interval_ms) per the strict+salvage rules."""
    if isinstance(value, str) and value:
        if not any(ch.isspace() for ch in value):
            ms = _parse_duration_ms(value)
            if ms is not None and FAILOVER_MIN_MS <= ms <= FAILOVER_MAX_MS:
                return value, ms
            salvaged = None
            m = _SALVAGE_RE.search(value)
            if m:
                try:
                    salvaged = int(
                        Decimal(m.group(1)) * _UNIT_MS[m.group(3)])
                except (InvalidOperation, KeyError):
                    salvaged = None
            elif _BARE_DIGITS_RE.match(value):
                salvaged = int(value) * 1000
            if (salvaged is not None
                    and FAILOVER_MIN_MS <= salvaged <= FAILOVER_MAX_MS):
                return value, salvaged
    return "300s", 300000


def _duration_or_default(value, default):
    if isinstance(value, str) and value and _DURATION_RE.match(value):
        return value
    return default


def _dedup(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _normalize_emit_group(group, index):
    """Emit-pass group normalization (see module docstring)."""
    g = group if isinstance(group, dict) else {}
    gid = g.get("id")
    gid = gid if isinstance(gid, str) else "group-%d" % index
    if gid == "builtin-direct":
        icon_default, name_default = "misc:dart", "直连"
    elif gid == "builtin-block":
        icon_default, name_default = "misc:cross", "拒绝"
    else:
        icon_default, name_default = "", "分组-%d" % (index + 1)
    t = g.get("type")
    t = t if isinstance(t, str) and t in ("selector", "urltest",
                                          "failover") else "selector"
    out = {
        "enabled": _bool(g.get("enabled"), True),
        "icon": _str(g.get("icon"), icon_default),
        "iconScale": _num(g.get("iconScale"), 0),
        "id": gid,
        "keywords": _str_list(g.get("keywords")),
        "members": _str_list(g.get("members")),
        "mode": _str(g.get("mode"), "static"),
        "name": _str(g.get("name"), name_default),
        "type": t,
    }
    if isinstance(g.get("kind"), str):
        out["kind"] = g["kind"]
    if t == "urltest":
        out["expectedStatus"] = _str(g.get("expectedStatus"), "")
        # RAW interval: a non-empty string is kept verbatim
        # (urltest-raw-interval family); anything else -> "300s".
        iv = g.get("interval")
        out["interval"] = iv if isinstance(iv, str) and iv else "300s"
        out["idleTimeout"] = _duration_or_default(g.get("idleTimeout"),
                                                  "12h")
        out["testUrl"] = _str(g.get("testUrl"), "")
        if not out["testUrl"]:
            out["testUrl"] = DEFAULT_TEST_URL
        out["tolerance"] = _num(g.get("tolerance"), 100)
    elif t == "failover":
        out["expectedStatus"] = _str(g.get("expectedStatus"), "")
        fo = g.get("failover") if isinstance(g.get("failover"), dict) else {}
        if "recoveryHoldMs" in fo and fo["recoveryHoldMs"] is None:
            recovery = 0
        else:
            recovery = _num(fo.get("recoveryHoldMs"), 60000)
        out["failover"] = {
            "failureThreshold": _num(fo.get("failureThreshold"), 2),
            "recoveryHoldMs": recovery,
            "restorePrimary": _bool(fo.get("restorePrimary"), True),
            "timeoutMs": _num(fo.get("timeoutMs"), 5000),
        }
        out["interval"], out["intervalMs"] = _validate_failover_interval(
            g.get("interval"))
        lanes = []
        raw_lanes = g.get("lanes") if isinstance(g.get("lanes"),
                                                 list) else []
        for i, lane in enumerate(raw_lanes):
            ln = lane if isinstance(lane, dict) else {}
            lid = ln.get("id")
            if not isinstance(lid, str) or not lid:
                lid = "lane-%d" % (i + 1)
            lanes.append({
                "icon": _str(ln.get("icon"), ""),
                "id": lid,
                "members": _dedup(_str_list(ln.get("members"))),
                "name": _str(ln.get("name"), ""),
            })
        out["lanes"] = lanes
        out["testUrl"] = _str(g.get("testUrl"), "")
        if not out["testUrl"]:
            out["testUrl"] = DEFAULT_TEST_URL
        out["tolerance"] = _num(g.get("tolerance"), 100)
    return out


def _ensure_builtins(groups):
    ids = {g["id"] for g in groups}
    out = list(groups)
    if "builtin-direct" not in ids:
        out.insert(0, {
            "enabled": True, "icon": "misc:dart", "id": "builtin-direct",
            "keywords": [], "kind": "direct", "members": [],
            "mode": "static", "name": "直连", "type": "selector",
        })
    if "builtin-block" not in ids:
        out.append({
            "enabled": True, "icon": "misc:cross", "id": "builtin-block",
            "keywords": [], "kind": "block", "members": [],
            "mode": "static", "name": "拒绝", "type": "selector",
        })
    return out


def emit_groups_value(groups_in, all_in):
    raw_groups = groups_in if isinstance(groups_in, list) else []
    groups = _ensure_builtins(
        [_normalize_emit_group(g, i) for i, g in enumerate(raw_groups)])
    all_tags = set()
    all_ordered = []
    if isinstance(all_in, list):
        for o in all_in:
            if isinstance(o, dict) and isinstance(o.get("tag"), str):
                if o["tag"] not in all_tags:
                    all_tags.add(o["tag"])
                    all_ordered.append(o["tag"])
    builtin = {"block": "拒绝", "blockEnabled": True,
               "direct": "直连", "directEnabled": True}
    for g in groups:
        if g["id"] == "builtin-direct":
            builtin["direct"] = g["name"]
            builtin["directEnabled"] = g["enabled"]
        elif g["id"] == "builtin-block":
            builtin["block"] = g["name"]
            builtin["blockEnabled"] = g["enabled"]
    direct_tag = builtin["direct"]
    reject_tag = builtin["block"]
    outbounds = []
    public_tags = []
    internal_tags = []
    placeholders = []
    failover_entries = []
    for g in groups:
        gid = g["id"]
        if gid == "builtin-direct":
            outbounds.append({"tag": g["name"], "type": "direct"})
            public_tags.append(g["name"])
            continue
        if gid == "builtin-block":
            outbounds.append({"tag": g["name"], "type": "block"})
            public_tags.append(g["name"])
            continue
        if not g["enabled"]:
            continue
        name = g["name"]
        t = g["type"]
        if t == "selector":
            if g["mode"] == "dynamic":
                resolved = list(all_ordered)
            else:
                resolved = _dedup(
                    [m for m in g["members"] if m in all_tags])
            if not resolved:
                outbounds.append({"outbounds": [direct_tag], "tag": name,
                                  "type": "selector"})
                placeholders.append(name)
            else:
                outbounds.append({"outbounds": resolved, "tag": name,
                                  "type": "selector"})
            public_tags.append(name)
        elif t == "urltest":
            if g["mode"] == "dynamic":
                resolved = list(all_ordered)
            else:
                resolved = _dedup(
                    [m for m in g["members"] if m in all_tags])
            iv_ms = _parse_lenient_ms(g["interval"])
            if iv_ms is None:
                iv_ms = 0
            idle_ms = _parse_lenient_ms(g["idleTimeout"])
            if idle_ms is None:
                idle_ms = 0
            idle_timeout = (g["interval"] if iv_ms >= idle_ms
                            else g["idleTimeout"])
            ob = {"idle_timeout": idle_timeout, "interval": g["interval"],
                  "outbounds": resolved if resolved else [direct_tag],
                  "tag": name, "tolerance": g["tolerance"],
                  "type": "urltest", "url": g["testUrl"]}
            outbounds.append(ob)
            if not resolved:
                placeholders.append(name)
            public_tags.append(name)
        elif t == "failover":
            lanes_out = []
            refs = []
            for i, lane in enumerate(g["lanes"]):
                valid = [m for m in lane["members"] if m in all_tags]
                if not valid:
                    mode, ref, sub_tag = "empty", None, None
                elif len(valid) == 1:
                    mode, ref, sub_tag = "single", valid[0], None
                else:
                    sub_tag = "__fo:%s:%s" % (gid, lane["id"])
                    mode, ref = "urltest", sub_tag
                lanes_out.append({
                    "icon": lane["icon"], "id": lane["id"], "index": i,
                    "members": lane["members"], "mode": mode,
                    "name": lane["name"], "ref": ref, "subTag": sub_tag,
                    "valid": valid,
                })
                if mode == "urltest":
                    iv_ms = g["intervalMs"]
                    idle_timeout = (g["interval"] if iv_ms >= 43200000
                                    else "12h")
                    outbounds.append({
                        "idle_timeout": idle_timeout,
                        "interval": g["interval"], "outbounds": valid,
                        "tag": sub_tag, "tolerance": g["tolerance"],
                        "type": "urltest", "url": g["testUrl"]})
                    internal_tags.append(sub_tag)
                if ref is not None:
                    refs.append(ref)
            default = refs[0] if refs else reject_tag
            outbounds.append({
                "default": default, "interrupt_exist_connections": True,
                "outbounds": refs + [reject_tag], "tag": name,
                "type": "selector"})
            public_tags.append(name)
            failover_entries.append({
                "id": gid, "lanes": lanes_out, "rejectTag": reject_tag,
                "settings": {
                    "failureThreshold": g["failover"]["failureThreshold"],
                    "interval": g["interval"],
                    "intervalMs": g["intervalMs"],
                    "recoveryHoldMs": g["failover"]["recoveryHoldMs"],
                    "restorePrimary": g["failover"]["restorePrimary"],
                    "testUrl": g["testUrl"],
                    "timeoutMs": g["failover"]["timeoutMs"],
                    "tolerance": g["tolerance"],
                },
                "tag": name,
            })
    return {
        "builtin": builtin,
        "dropped": [],
        "failover": failover_entries,
        "internalTags": internal_tags,
        "outbounds": outbounds,
        "placeholders": placeholders,
        "publicTags": public_tags,
    }


def emit_groups(args):
    groups = args[0] if len(args) > 0 else None
    all_obs = args[1] if len(args) > 1 else None
    return emit_groups_value(groups, all_obs)
