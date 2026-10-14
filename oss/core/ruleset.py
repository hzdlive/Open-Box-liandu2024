"""Rule set support: parse remote rule lists and merge them into site sets.

Formats:
- clash-classical: lines like ``DOMAIN-SUFFIX,google.com`` / ``IP-CIDR,1.1.0.0/16``
- domain-list: bare domains (one per line) -> treated as domain suffix matches;
  lines starting with ``+.`` are explicit suffixes; CIDR-looking lines go to ip_cidr.
- auto: detected from content.
"""

from __future__ import annotations

import re
import urllib.request

_CLASSICAL_RE = re.compile(r"^([A-Z0-9-]+),([^,]+)")


def parse_ruleset_text(text: str, fmt: str = "auto") -> dict:
    out = {"domains": [], "domain_suffix": [], "domain_keyword": [], "ip_cidr": []}
    lines = [ln.strip() for ln in text.splitlines()]
    if fmt == "auto":
        fmt = "clash-classical" if any(_CLASSICAL_RE.match(ln) for ln in lines if ln) else "domain-list"
    for ln in lines:
        if not ln or ln.startswith(("#", "!", "[", ";")):
            continue
        if fmt == "clash-classical":
            m = _CLASSICAL_RE.match(ln)
            if not m:
                continue
            kind, value = m.group(1), m.group(2).strip().strip("'\"")
            if kind == "DOMAIN":
                out["domains"].append(value)
            elif kind == "DOMAIN-SUFFIX":
                out["domain_suffix"].append(value)
            elif kind == "DOMAIN-KEYWORD":
                out["domain_keyword"].append(value)
            elif kind in ("IP-CIDR", "IP-CIDR6"):
                out["ip_cidr"].append(value)
            # DST-PORT / PROCESS-NAME / other match types are out of scope
        else:
            v = ln.lstrip("+.")
            if re.match(r"^[0-9a-fA-F:.]+/\d+$", v):
                out["ip_cidr"].append(v)
            elif "." in v and " " not in v and "/" not in v:
                out["domain_suffix"].append(v.lower())
    # de-dup, preserve order
    for k in out:
        out[k] = list(dict.fromkeys(out[k]))
    return out


def fetch_ruleset(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "openbox-oss/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")
