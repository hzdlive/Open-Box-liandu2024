"""Node rename rules for subscriptions.

Mirrors the publicly documented behavior of per-subscription rename rules:
region keywords -> region label, feature keywords -> uppercase feature tag,
sequence numbers, prefix with subscription name, filter keywords exclude nodes.
"""

from __future__ import annotations


# 1:1 对标原版预置地区关键词（见原版订阅弹窗规则 tab 截图）
DEFAULT_REGIONS = [
    {"name": "美国", "flag": "🇺🇸",
     "keywords": "us,united states,america,美国,美國,洛杉矶,硅谷,圣何塞,西雅图"},
    {"name": "香港", "flag": "🇭🇰",
     "keywords": "hk,hong kong,hongkong,香港,深港"},
    {"name": "日本", "flag": "🇯🇵",
     "keywords": "jp,japan,日本,东京,東京,大阪"},
    {"name": "新加坡", "flag": "🇸🇬",
     "keywords": "sg,singapore,新加坡,狮城,獅城"},
    {"name": "台湾", "flag": "🇹🇼",
     "keywords": "tw,taiwan,台湾,臺灣,台北,台中"},
    {"name": "韩国", "flag": "🇰🇷",
     "keywords": "kr,korea,韩国,韓國,首尔,首爾"},
    {"name": "英国", "flag": "🇬🇧",
     "keywords": "uk,gb,united kingdom,britain,英国,英國,伦敦,倫敦"},
    {"name": "德国", "flag": "🇩🇪",
     "keywords": "de,germany,德国,德國,法兰克福,法蘭克福"},
    {"name": "中国", "flag": "🇨🇳",
     "keywords": "cn,china,中国,中國,回国,回國,back to china"},
]

DEFAULT_FEATURES = "iepl,iplc,ipv6,专线,家宽,2x"
DEFAULT_FILTER = "官网,工单,客服"


def _kw_list(s: str) -> list[str]:
    return [k.strip().lower() for k in (s or "").split(",") if k.strip()]


def match_region(orig_tag: str, regions: list[dict], fallback: str) -> str:
    low = orig_tag.lower()
    for r in regions:
        kws = r.get("keywords", "") if isinstance(r.get("keywords"), str) \
            else ",".join(r.get("keywords", []))
        for kw in _kw_list(kws):
            if kw and kw in low:
                return r["name"]
    return fallback or "其他"


def match_features(orig_tag: str, features: str) -> list[str]:
    low = orig_tag.lower()
    out = []
    for kw in _kw_list(features):
        if kw and kw in low and kw.upper() not in out:
            out.append(kw.upper())
    return out


def is_filtered(orig_tag: str, filter_kws: str) -> bool:
    low = orig_tag.lower()
    return any(kw and kw in low for kw in _kw_list(filter_kws))


def build_name(region: str, features: list[str], seq: int, seq_digits: int,
               order: list[str]) -> str:
    parts = []
    for slot in order or ["region", "feature", "seq"]:
        if slot == "region":
            parts.append(region)
        elif slot == "feature":
            parts.extend(features)
        elif slot == "seq":
            parts.append(str(seq).zfill(max(1, seq_digits)))
    return "-".join(p for p in parts if p)


def rename_nodes(orig_tags: list[str], cfg: dict) -> list[dict]:
    """Apply rename rules to a list of original tags.

    cfg keys: enabled, prefix(bool), sub_name, order, seq_digits, regions,
    fallback, features, filter.
    Returns [{orig, new, filtered}]. Sequence numbers are per-region.
    """
    out = []
    seq_count: dict[str, int] = {}
    filter_kws = cfg.get("filter", "")
    for orig in orig_tags:
        if is_filtered(orig, filter_kws):
            out.append({"orig": orig, "new": orig, "filtered": True})
            continue
        region = match_region(orig, cfg.get("regions") or [], cfg.get("fallback", "其他"))
        features = match_features(orig, cfg.get("features", ""))
        seq_count[region] = seq_count.get(region, 0) + 1
        name = build_name(region, features, seq_count[region],
                          int(cfg.get("seq_digits", 2) or 2),
                          cfg.get("order") or ["region", "feature", "seq"])
        if cfg.get("prefix", True) and cfg.get("sub_name"):
            name = f"{cfg['sub_name']} | {name}"
        out.append({"orig": orig, "new": name, "filtered": False})
    return out


def rename_config_from_row(row: dict) -> dict:
    """Build the rename cfg dict from a subscription DB row dict."""
    import json as _json

    def _jl(s, default):
        try:
            v = _json.loads(s or "")
            return v if isinstance(v, list) else default
        except ValueError:
            return default

    return {
        "enabled": bool(row.get("rename_enabled")),
        "prefix": bool(row.get("rename_prefix", 1)),
        "sub_name": row.get("name", ""),
        "order": _jl(row.get("rename_order"), ["region", "feature", "seq"]),
        "seq_digits": row.get("rename_seq_digits", 2) or 2,
        "regions": _jl(row.get("rename_regions"), DEFAULT_REGIONS),
        "fallback": row.get("rename_fallback", "其他") or "其他",
        "features": row.get("rename_features", DEFAULT_FEATURES),
        "filter": row.get("rename_filter", DEFAULT_FILTER),
    }
