"""Local sing-box rule-set (.srs) management.

The default site sets reference geosite/geoip rule-sets (e.g. geosite-youtube,
geoip-cn). Like the original panel, we use LOCAL .srs files (type: local in
the generated config) rather than remote downloads at kernel start.

Data provenance (see THIRD_PARTY_NOTICES.md):
- geosite-*.srs: SagerNet/sing-geosite, data from v2fly/domain-list-community (MIT)
- geoip-*.srs:   SagerNet/sing-geoip, data from MaxMind GeoLite2 (attribution required)

Files are fetched from the public upstream CDN on demand / at install time.
Nothing is copied from the original panel's install tree.
"""

from __future__ import annotations

import os
import time
import urllib.request

# name -> (kind, file)
GEOSITE_BASE = "https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set"
GEOIP_BASE = "https://cdn.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set"
MIRROR_GEOSITE = "https://ghfast.top/https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set"
MIRROR_GEOIP = "https://ghfast.top/https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set"


def geodata_dir(db_path: str | None = None) -> str:
    """Directory holding the local .srs files."""
    override = os.environ.get("OBX_GEODATA")
    if override:
        return override
    dbp = db_path or os.environ.get("OBX_DB") or os.path.expanduser("~/.openbox-oss/panel.db")
    return os.path.join(os.path.dirname(os.path.abspath(dbp)), "geodata")


def _urls(name: str) -> list[str]:
    if name in INLINE_RULE_SETS:
        return []
    if name.startswith("geosite-"):
        return [f"{GEOSITE_BASE}/{name}.srs", f"{MIRROR_GEOSITE}/{name}.srs"]
    if name.startswith("geoip-"):
        return [f"{GEOIP_BASE}/{name}.srs", f"{MIRROR_GEOIP}/{name}.srs"]
    return []


#: Rule-sets expanded inline instead of downloaded (fixed, well-known ranges).
INLINE_RULE_SETS = {
    # RFC1918 + loopback + link-local + CGNAT; replaces the retired
    # upstream geoip-private.srs.
    "geoip-private": [
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
        "::1/128", "fc00::/7", "fe80::/10",
    ],
}


def referenced_rule_sets(app_cfg) -> list[str]:
    """All rule-set names referenced by site sets, in first-seen order.

    Inline-expanded names (INLINE_RULE_SETS) are excluded: they need no file.
    """
    out: list[str] = []
    for s in getattr(app_cfg, "site_sets", []) or []:
        for n in getattr(s, "rule_sets", []) or []:
            n = (n or "").strip()
            if n and n not in out and n not in INLINE_RULE_SETS:
                out.append(n)
    return out


def local_path(name: str, db_path: str | None = None) -> str:
    return os.path.join(geodata_dir(db_path), f"{name}.srs")


def is_available(name: str, db_path: str | None = None) -> bool:
    p = local_path(name, db_path)
    return os.path.isfile(p) and os.path.getsize(p) > 0


def _download(url: str, dest: str, timeout: int = 60) -> None:
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "openbox-oss-geodata/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
    if os.path.getsize(tmp) == 0:
        os.remove(tmp)
        raise OSError("empty download")
    os.replace(tmp, dest)


def ensure(names: list[str], db_path: str | None = None,
           timeout: int = 60) -> tuple[list[str], list[str]]:
    """Download missing .srs files. Returns (available, still_missing)."""
    d = geodata_dir(db_path)
    os.makedirs(d, exist_ok=True)
    ok, missing = [], []
    for name in names:
        if is_available(name, db_path):
            ok.append(name)
            continue
        fetched = False
        for url in _urls(name):
            try:
                _download(url, local_path(name, db_path), timeout)
                fetched = True
                break
            except Exception:
                continue
        (ok if fetched else missing).append(name)
    return ok, missing


def list_local(db_path: str | None = None) -> list[dict]:
    """Local .srs inventory for the ruleset page."""
    d = geodata_dir(db_path)
    out = []
    try:
        files = sorted(os.listdir(d))
    except OSError:
        return out
    for fn in files:
        if not fn.endswith(".srs"):
            continue
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        name = fn[:-4]
        kind = "geosite" if name.startswith("geosite-") else \
            "geoip" if name.startswith("geoip-") else "other"
        out.append({"name": name, "kind": kind, "size": st.st_size,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                                time.localtime(st.st_mtime))})
    return out
