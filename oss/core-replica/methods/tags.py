"""builtinTags: reserved internal tags for the direct/block groups.

Derived from core-golden.json (2 cases). Returns the builtin
groups' names and enabled flags:

    {"block": "<name>", "blockEnabled": <bool>,
     "direct": "<name>", "directEnabled": <bool>}

- Identification is by group id (builtin-direct / builtin-block),
  the same identity normalizeGroups' builtin ensure uses. (Kind-based
  matching is unprobed; see INFERRED below.)
- Absent builtins answer the defaults (直连 / 拒绝, both enabled),
  which is why the empty case answers the same value as the real one.
- INFERRED: a present builtin's name/enabled are passed through
  (both measured cases have the default names and enabled true, so
  a renamed or disabled builtin is unmeasured); a non-string name
  answers the default name and a non-bool enabled answers true,
  following the normalizers' lenient coercion.
"""

_BUILTINS = (
    ("builtin-direct", "direct", "directEnabled", "直连"),
    ("builtin-block", "block", "blockEnabled", "拒绝"),
)


def builtin_tags_value(groups):
    gs = groups if isinstance(groups, list) else []
    found = {}
    for g in gs:
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        if gid in ("builtin-direct", "builtin-block") and gid not in found:
            found[gid] = g
    out = {}
    for gid, name_key, enabled_key, default_name in _BUILTINS:
        g = found.get(gid)
        if g is None:
            out[name_key] = default_name
            out[enabled_key] = True
        else:
            name = g.get("name")
            out[name_key] = name if isinstance(name, str) else default_name
            enabled = g.get("enabled")
            out[enabled_key] = enabled if isinstance(enabled, bool) else True
    return out


def builtin_tags(args):
    return builtin_tags_value(args[0] if args else None)
