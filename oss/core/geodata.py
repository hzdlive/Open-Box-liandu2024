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
    """All rule-set names referenced by site sets and front rules,
    in first-seen order. Inline-expanded names (INLINE_RULE_SETS) are
    excluded: they need no file.
    """
    out: list[str] = []

    def _add(names):
        for n in names or []:
            n = (n or "").strip()
            if n and n not in out and n not in INLINE_RULE_SETS:
                out.append(n)

    for s in getattr(app_cfg, "site_sets", []) or []:
        _add(getattr(s, "rule_sets", []))
    for fr in getattr(app_cfg, "front_rules", []) or []:
        rt = (fr.get("rtype") or "domain_suffix") if isinstance(fr, dict) else "domain_suffix"
        val = (fr.get("domain") or "").strip() if isinstance(fr, dict) else ""
        if rt in ("geosite", "geoip") and val:
            _add([f"{rt}-{val}"])
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


# ---------------------------------------------------------------------------
# Deploy-time refresh (v6 #14 deploy-rulesets 对照，适配本地 .srs 模型)
#
# v6 的 Oi 是部署前的规则集阶段：24h TTL + URL 匹配 + 文件在盘上才复用；
# 失败三支（无本地副本 → 致命、无本地副本 + optional → 跳过、有本地副本 →
# 沿用旧记录）；keepOthers 默认 false（表只描述刚部署的 profile）；
# 只有字符串化形式变了才写表。
#
# 适配点（与原版不同处，均有意）：
# - 原版的表是 rule-lists.json；我们用 DB 表 geodata_state(name, url, at)。
# - 原版的“两个半边”(<tag>.srs / <tag>-ip.srs)不适用：上游 geo 二进制
#   本来就是按名分文件的（geosite-*.srs 域名、geoip-*.srs IP），每名一文件。
# - 原版的“老版式离线重编”不适用：我们不从文本本地编译 geo 文件，
#   上游 .srs 即二进制成品；损坏文件由启动验证的 FATAL 兜底。
# - 原版失败无副本是致命；我们沿用既有降级语义：缺失只进 missing，
#   build 跳过该规则集并告警，绝不让一次上游不通打断 apply。
# - 首次刷新没有记录时，用文件 mtime 认作 at（文件就是我们 ensure 写下的，
#   mtime 即下载时间），避免全量重下一遍；mtime 也超 24h 的照常重下。
# ---------------------------------------------------------------------------

TTL_SECONDS = 24 * 3600
REFRESH_WORKERS = 8


def ensure_state_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS geodata_state("
        " name TEXT PRIMARY KEY,"
        " url TEXT NOT NULL DEFAULT '',"
        " at INTEGER NOT NULL DEFAULT 0)")


def read_states(conn, names: list[str] | None = None) -> dict:
    """{name: {"url": str, "at": int}} for recorded names (all if names None)."""
    ensure_state_table(conn)
    if names is None:
        rows = conn.execute("SELECT name, url, at FROM geodata_state")
    else:
        rows = conn.execute(
            "SELECT name, url, at FROM geodata_state WHERE name IN (%s)"
            % ",".join("?" * len(names)), list(names)) if names else []
    return {r[0]: {"url": r[1], "at": r[2] or 0} for r in rows}


def _try_download(name: str, urls: list[str], timeout: int) -> tuple[bool, str]:
    """Try candidate URLs in order. Returns (ok, used_url_or_error)."""
    last_err = "no candidate url"
    for url in urls:
        try:
            _download(url, local_path(name), timeout)
            return True, url
        except Exception as e:
            last_err = str(e) or e.__class__.__name__
    return False, last_err


def refresh_names(conn, names: list[str], keep_others: bool = False,
                  timeout: int = 30, now: float | None = None) -> dict:
    """TTL-aware refresh of local .srs files, v6 #14 semantics.

    Returns {"reused", "downloaded", "kept_old" ([{name, error}]),
    "missing", "local", "pruned"}. Per-file failures never raise:
    a stale file that cannot be re-downloaded is kept as-is (kept_old)
    and only a file missing entirely lands in missing.
    """
    from concurrent.futures import ThreadPoolExecutor

    now = time.time() if now is None else now
    ensure_state_table(conn)
    os.makedirs(geodata_dir(), exist_ok=True)
    ordered = list(dict.fromkeys(n for n in (names or []) if n))
    states = read_states(conn, ordered)
    reused, downloaded, kept_old, missing, local = [], [], [], [], []
    stale: list[str] = []
    for name in ordered:
        if name in INLINE_RULE_SETS:
            continue
        urls = _urls(name)
        path = local_path(name)
        present = os.path.isfile(path) and os.path.getsize(path) > 0
        if not urls:
            # Not downloadable by us (custom local name): present = usable.
            (local if present else missing).append(name)
            continue
        row = states.get(name)
        if row is None and present:
            # First refresh: adopt the file mtime as provenance (see header).
            try:
                row = {"url": urls[0],
                       "at": int(os.stat(path).st_mtime)}
            except OSError:
                row = None
            if row is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO geodata_state(name, url, at)"
                    " VALUES (?, ?, ?)", (name, row["url"], row["at"]))
        if (present and row is not None and row["url"] in urls
                and now - row["at"] < TTL_SECONDS):
            reused.append(name)  # fresh: zero further writes for this name
        else:
            stale.append(name)
    if stale:
        with ThreadPoolExecutor(max_workers=REFRESH_WORKERS) as pool:
            results = list(pool.map(
                lambda n: (n, _try_download(n, _urls(n), timeout)), stale))
        for name, (ok, info) in results:
            present = os.path.isfile(local_path(name)) \
                and os.path.getsize(local_path(name)) > 0
            if ok:
                conn.execute(
                    "INSERT OR REPLACE INTO geodata_state(name, url, at)"
                    " VALUES (?, ?, ?)", (name, info, int(now)))
                downloaded.append(name)
            elif present:
                kept_old.append({"name": name, "error": info})
            else:
                missing.append(name)
    pruned: list[str] = []
    if not keep_others:
        keep = set(ordered)
        for row_name in list(read_states(conn).keys()):
            if row_name not in keep:
                conn.execute("DELETE FROM geodata_state WHERE name=?",
                             (row_name,))
                pruned.append(row_name)
    conn.commit()
    return {"reused": reused, "downloaded": downloaded,
            "kept_old": kept_old, "missing": missing, "local": local,
            "pruned": pruned}


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


def get_rule_set_detail(name: str) -> dict:
    """获取规则集的详细条目（1:1 对标原版详情弹窗）。
    
    返回格式: {"name": "geosite-115", "title": "115 网盘云存储服务域名",
               "items": [{"type": "域名后缀", "value": "115.com"}, ...],
               "total": 14}
    """
    import json
    import subprocess
    import tempfile

    kind = "geosite" if name.startswith("geosite-") else \
           "geoip" if name.startswith("geoip-") else "other"
    code = name.split("-", 1)[1] if "-" in name else name

    # 找 .srs 文件（先查实例目录，再查默认共享目录）
    srs_path = os.path.join(geodata_dir(), f"{name}.srs")
    if not os.path.exists(srs_path):
        # 回退到默认位置（VPS 上 8080 主实例的 geodata）
        for alt in ("/root/.openbox-oss/geodata", os.path.expanduser("~/.openbox-oss/geodata")):
            cand = os.path.join(alt, f"{name}.srs")
            if os.path.exists(cand):
                srs_path = cand
                break
    if not os.path.exists(srs_path):
        return {
            "name": name, "kind": kind, "code": code, "title": code,
            "items": [], "total": 0, "message": "本地无此规则集文件",
        }

    # 用 sing-box decompile 解析
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            json_path = tf.name
        result = subprocess.run(
            ["sing-box", "rule-set", "decompile", srs_path, "-o", json_path],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            return {
                "name": name, "kind": kind, "code": code, "title": code,
                "items": [], "total": 0,
                "message": f"解析失败: {result.stderr.decode()[:200]}",
            }
        with open(json_path) as f:
            data = json.load(f)
        os.unlink(json_path)
    except Exception as e:
        return {
            "name": name, "kind": kind, "code": code, "title": code,
            "items": [], "total": 0, "message": f"解析异常: {e}",
        }

    # 转换为前端需要的格式
    items = []
    type_map = {
        "domain": "域名",
        "domain_suffix": "域名后缀",
        "domain_keyword": "域名关键词",
        "domain_regex": "域名正则",
        "ip_cidr": "IP 段",
        "ip_is_private": "私有 IP",
    }
    for rule in data.get("rules", []):
        for key, label in type_map.items():
            v = rule.get(key)
            if not v:
                continue
            if isinstance(v, list):
                for val in v:
                    items.append({"type": label, "value": val})
            elif isinstance(v, str):
                items.append({"type": label, "value": v})
            elif isinstance(v, bool) and v:
                items.append({"type": label, "value": "是"})

    return {
        "name": name,
        "kind": kind,
        "code": code,
        "title": code,
        "items": items,
        "total": len(items),
    }
