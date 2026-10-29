"""normalizeRouting / normalizeGroups / normalizePolicy / normalizeCustom.

Derived from core-golden.json (normalizeRouting 8, normalizeGroups 9,
normalizePolicy 2, normalizeCustom 2 cases). Conventions observed
across all four:

- Lenient coercion, never a hard error: a mistyped field falls back
  to its default (routing garbage case: policies "not-an-array" and
  fallbackName 42 both answer defaults).
- Unknown fields are dropped: every output has exactly its known
  shape (a policy's "outbound" key does not survive).
- Defaults are positional where an index exists: groups get
  id "group-{i}" / name "分组-{i+1}" (malformed case: null -> group-0,
  {} -> group-1); standalone normalizePolicy uses index 0
  ("policy-0" / "策略-1").
- Output keys sort alphabetically (Go json.Marshal on maps); main.py
  dumps with sort_keys=True for byte fidelity.

Rules marked INFERRED below are consistent with the measured cases
but have no direct case of their own; they are listed so a future
golden case can confirm or correct them.
"""

import re

# ---------------------------------------------------------------- helpers

def _str(v, default):
    return v if isinstance(v, str) else default


def _bool(v, default):
    return v if isinstance(v, bool) else default


def _num(v, default):
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return default
    return default


def _str_list(v):
    # INFERRED: non-string elements are filtered (a member/tag must be
    # a string); only whole-field mistyping is measured (-> []).
    if not isinstance(v, list):
        return []
    return [x for x in v if isinstance(x, str)]


_DURATION_RE = re.compile(
    r"^(\d+(\.\d+)?(ns|us|µs|ms|s|m|h))+$")


def _duration(v, default):
    # INFERRED as a Go time.ParseDuration approximation: "abc" answers
    # the default (measured), "300s"/"5m"/"1h30m"/"500ms" are kept.
    if isinstance(v, str) and _DURATION_RE.match(v):
        return v
    return default


def _dict(v):
    return v if isinstance(v, dict) else {}


# ------------------------------------------------------------------- policy

_POLICY_FIELDS = (
    "default", "domain", "domainKeyword", "domainSuffix", "enabled",
    "icon", "id", "ipCidr", "name", "notes", "ruleUrls", "rulesets",
)

_POLICY_RULE_FIELDS = (
    "domain", "domainKeyword", "domainSuffix", "ipCidr", "rulesets",
    "ruleUrls",
)


def normalize_policy_value(policy, index):
    """Normalize one policy. Returns the policy unconditionally (the
    no-rules drop lives in normalizeRouting, not here: the standalone
    empty case answers the default policy, it does not drop it)."""
    p = _dict(policy)
    out = {
        "default": _str(p.get("default"), ""),
        "domain": _str_list(p.get("domain")),
        "domainKeyword": _str_list(p.get("domainKeyword")),
        "domainSuffix": _str_list(p.get("domainSuffix")),
        # INFERRED: a non-bool enabled answers true (only absence is
        # measured, and it answers true).
        "enabled": _bool(p.get("enabled"), True),
        "icon": _str(p.get("icon"), ""),
        "id": _str(p.get("id"), "policy-%d" % index),
        "ipCidr": _str_list(p.get("ipCidr")),
        "name": _str(p.get("name"), "策略-%d" % (index + 1)),
        "notes": p.get("notes") if isinstance(p.get("notes"), dict) else {},
        "ruleUrls": _str_list(p.get("ruleUrls")),
        "rulesets": _str_list(p.get("rulesets")),
    }
    return out


def _policy_has_rules(policy):
    # A policy with no rule content anywhere is dropped by
    # normalizeRouting (policyWithoutRules case: {"name", "outbound"}
    # answers zero policies). INFERRED: ruleUrls count as rule content
    # (a remote rule list is a rule source); no case isolates them.
    return any(policy.get(f) for f in _POLICY_RULE_FIELDS)


def normalize_policy(args):
    p = args[0] if args else None
    return normalize_policy_value(p, 0)


# ------------------------------------------------------------------- custom

def normalize_custom_value(custom):
    c = _dict(custom)
    rules = []
    if isinstance(c.get("rules"), list):
        for r in c["rules"]:
            if not isinstance(r, dict):
                continue
            t = r.get("type")
            v = r.get("value")
            o = r.get("outbound")
            # A rule survives only with type+value+outbound as strings;
            # the withRules case (action instead of outbound) is dropped.
            # INFERRED: empty strings do not count (a rule with an
            # empty outbound is malformed, not a rule).
            if (isinstance(t, str) and t
                    and isinstance(v, str) and v
                    and isinstance(o, str) and o):
                rules.append({"outbound": o, "type": t, "value": v})
    return {
        "enabled": _bool(c.get("enabled"), True),
        "icon": _str(c.get("icon"), "misc:pin"),
        "iconScale": _num(c.get("iconScale"), 0),
        "name": _str(c.get("name"), "前置自定义分流"),
        "rules": rules,
    }


def normalize_custom(args):
    return normalize_custom_value(args[0] if args else None)


# ------------------------------------------------------------------ routing

def normalize_routing_value(routing):
    r = _dict(routing)
    policies = []
    if isinstance(r.get("policies"), list):
        for i, p in enumerate(r["policies"]):
            np = normalize_policy_value(p, i)
            if _policy_has_rules(np):
                policies.append(np)
    # INFERRED: activePolicies are the enabled policies, in order.
    # Every measured case has all policies enabled, so active ==
    # policies there; an enabled:false policy is the unmeasured case.
    active = [p for p in policies if p["enabled"]]
    return {
        "activePolicies": active,
        "custom": normalize_custom_value(r.get("custom")),
        "fallback": {
            "default": _str(r.get("fallbackDefault"), ""),
            "icon": _str(r.get("fallbackIcon"), "globe:earth-meridians"),
            "name": _str(r.get("fallbackName"), "其他"),
        },
        "policies": policies,
    }


def normalize_routing(args):
    return normalize_routing_value(args[0] if args else None)


# ------------------------------------------------------------------- groups

_BUILTIN_DIRECT = {
    "enabled": True,
    "icon": "misc:dart",
    "id": "builtin-direct",
    "keywords": [],
    "kind": "direct",
    "members": [],
    "mode": "static",
    "name": "直连",
    "type": "selector",
}

_BUILTIN_BLOCK = {
    "enabled": True,
    "icon": "misc:cross",
    "id": "builtin-block",
    "keywords": [],
    "kind": "block",
    "members": [],
    "mode": "static",
    "name": "拒绝",
    "type": "selector",
}

# Types observed in golden groups. INFERRED: anything else answers
# "selector" (measured for "nope"); whether the original also keeps
# e.g. "loadbalance" is unmeasured.
_GROUP_TYPES = {"selector", "urltest", "failover"}


def _failover_value(f):
    f = _dict(f)
    # recoveryHoldMs is special (measured): absent -> 60000, null -> 0,
    # unparseable string -> 60000, parseable string -> int. The other
    # three answer their defaults for null just as for absence.
    if "recoveryHoldMs" in f and f["recoveryHoldMs"] is None:
        recovery = 0
    else:
        recovery = _num(f.get("recoveryHoldMs"), 60000)
    return {
        "failureThreshold": _num(f.get("failureThreshold"), 2),
        "recoveryHoldMs": recovery,
        "restorePrimary": _bool(f.get("restorePrimary"), True),
        "timeoutMs": _num(f.get("timeoutMs"), 5000),
    }


def _lane_value(lane):
    l = _dict(lane)
    return {
        "icon": _str(l.get("icon"), ""),
        "id": _str(l.get("id"), ""),
        "members": _str_list(l.get("members")),
        "name": _str(l.get("name"), ""),
    }


def normalize_group_value(group, index):
    g = _dict(group)
    gid = g.get("id")
    gid = gid if isinstance(gid, str) else "group-%d" % index
    # INFERRED: builtin ids carry their fixed icon/name defaults (the
    # malformed case measures the icon fill for builtin-direct; the
    # name fill for a nameless builtin is by the same identity logic).
    if gid == "builtin-direct":
        icon_default, name_default = "misc:dart", "直连"
    elif gid == "builtin-block":
        icon_default, name_default = "misc:cross", "拒绝"
    else:
        icon_default, name_default = "", "分组-%d" % (index + 1)
    t = g.get("type")
    t = t if isinstance(t, str) and t in _GROUP_TYPES else "selector"
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
    # kind passes through when present (builtins carry it); it is
    # never defaulted for user groups.
    if isinstance(g.get("kind"), str):
        out["kind"] = g["kind"]
    if t == "urltest":
        out["expectedStatus"] = _str(g.get("expectedStatus"), "")
        # INFERRED: idleTimeout absent answers "12h" (the only observed
        # value; no synthetic urltest case isolates its default).
        out["idleTimeout"] = _duration(g.get("idleTimeout"), "12h")
        out["interval"] = _duration(g.get("interval"), "300s")
        out["testUrl"] = _str(g.get("testUrl"), "")
        out["tolerance"] = _num(g.get("tolerance"), 100)
    elif t == "failover":
        out["expectedStatus"] = _str(g.get("expectedStatus"), "")
        out["failover"] = _failover_value(g.get("failover"))
        out["interval"] = _duration(g.get("interval"), "300s")
        out["lanes"] = [_lane_value(x) for x in g["lanes"]
                        ] if isinstance(g.get("lanes"), list) else []
        out["testUrl"] = _str(g.get("testUrl"), "")
        out["tolerance"] = _num(g.get("tolerance"), 100)
    return out


def normalize_groups_value(groups):
    gs = groups if isinstance(groups, list) else []
    out = [normalize_group_value(g, i) for i, g in enumerate(gs)]
    ids = {g["id"] for g in out}
    if "builtin-direct" not in ids:
        out.insert(0, dict(_BUILTIN_DIRECT))
    if "builtin-block" not in ids:
        out.append(dict(_BUILTIN_BLOCK))
    return out


def normalize_groups(args):
    return normalize_groups_value(args[0] if args else None)
