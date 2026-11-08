"""Shared comparison helpers for the core-go harnesses.

canon(): canonical form for semantic equality (sorted keys, numbers
as float). key_order(): the key order of every object, for
byte-equivalence checks. first_diff(): the first difference between
two parsed JSON values, with its path.
"""

from __future__ import annotations


def canon(v):
    if isinstance(v, dict):
        return tuple(sorted((k, canon(x)) for k, x in v.items()))
    if isinstance(v, list):
        return tuple(canon(x) for x in v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return ("__num__", float(v))
    return v


def key_order(v, path="$", out=None):
    if out is None:
        out = []
    if isinstance(v, dict):
        out.append((path, list(v.keys())))
        for k, x in v.items():
            key_order(x, f"{path}.{k}", out)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            key_order(x, f"{path}[{i}]", out)
    return out


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
                and not isinstance(a, bool) and not isinstance(b, bool):
            return None if float(a) == float(b) else f"{path}: {a!r} != {b!r}"
        return f"{path}: type {type(a).__name__} != {type(b).__name__} ({a!r} vs {b!r})"
    if isinstance(a, dict):
        if set(a) != set(b):
            return f"{path}: keys {sorted(set(a) ^ set(b))} differ"
        for k in a:
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if isinstance(a, float) and isinstance(b, float):
        return None if a == b else f"{path}: {a!r} != {b!r}"
    return None if a == b else f"{path}: {a!r} != {b!r}"


def compare(py, go, label=""):
    """Compare two parsed JSON values; print diffs; return True if equal."""
    ok = True
    if canon(py) != canon(go):
        ok = False
        print(f"SEMANTIC DIFF {label}:", first_diff(py, go))
    po, go_o = key_order(py), key_order(go)
    if po != go_o:
        ok = False
        for (pp, pk), (gp, gk) in zip(po, go_o):
            if pk != gk:
                print(f"KEY ORDER DIFF {label} at {pp}: python {pk} vs go {gk}")
                break
        else:
            print(f"KEY ORDER DIFF {label}: {len(po)} vs {len(go_o)} objects")
    return ok
