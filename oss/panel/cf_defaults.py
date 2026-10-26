"""内容过滤默认规则集预置（对标原版默认的 3 条）。

来源策略：优先拉 source_url（公开规则集）；拉取失败时读随仓库的
种子文件（oss/panel/defaults/，与原版 defaults/ 目录同构，附来源署名）；
两者都无的条目不建空壳，上报 failed 由用户手动导入。

注意：Youtube-补丁是原版自有补丁、无公开来源，且为脚本规则（我们
暂不执行脚本），故预置时跳过，仅在结果中说明。
"""
import json
import os
import time
import urllib.request

DEFAULT_CF_RULESETS = [
    {
        "id": "2aec6f268d71d8f4",
        "name": "综合省流",
        "dialect": "quantumultx",
        "source_url": "https://yfamilys.com/rewrite/adlite.conf",
        "seed_file": "cf-adlite.conf",
        "note": "APP 启动页去广告 lite（yfamilys，ddgksf2013）",
    },
    {
        "id": "7f19db176d8f1d7b",
        "name": "Youtube-Surge",
        "dialect": "surge",
        "source_url": "https://raw.githubusercontent.com/Maasea/sgmodule/master/YouTube.Enhance.sgmodule",
        "seed_file": "cf-youtube-enhance.sgmodule",
        "note": "Youtube (Music) Enhance（Maasea sgmodule）",
    },
    {
        "id": "a08ac43e05eb8590",
        "name": "Youtube-补丁",
        "dialect": "surge",
        "source_url": "",
        "seed_file": None,
        "note": "原版自有补丁，无公开来源；且为脚本规则（暂不执行），预置时跳过",
    },
]

_SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "defaults")


def _fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenBox/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _seed_text(seed_file: str) -> str:
    with open(os.path.join(_SEED_DIR, seed_file), encoding="utf-8") as f:
        return f.read()


def preset_default_rulesets(conn, force: bool = False) -> dict:
    """预置默认规则集。force=True 时先删同名条目再重建。

    返回 {"created": [name...], "skipped": [name...], "failed": [{name, reason}...]}。
    """
    from core.cf_parser import parse_content_filter_text

    results: dict = {"created": [], "skipped": [], "failed": []}
    for d in DEFAULT_CF_RULESETS:
        existing = conn.execute(
            "SELECT id FROM cf_rulesets WHERE name=?", (d["name"],)
        ).fetchone()
        if existing and not force:
            results["skipped"].append(d["name"])
            continue
        if existing and force:
            conn.execute("DELETE FROM cf_rulesets WHERE name=?", (d["name"],))
        text = ""
        if d["source_url"]:
            try:
                text = _fetch_text(d["source_url"])
            except Exception:
                text = ""
        if not text and d["seed_file"]:
            try:
                text = _seed_text(d["seed_file"])
            except OSError:
                text = ""
        if not text:
            results["failed"].append(
                {"name": d["name"], "reason": "无公开来源，需手动导入"})
            continue
        parsed = parse_content_filter_text(text, d["dialect"])
        try:
            conn.execute(
                """INSERT INTO cf_rulesets
                (id, name, dialect, source_url, text, rules, hostnames, arguments, scripts,
                 enabled, updated_at, skipped_scripts, skipped_unsupported, skipped_routing,
                 skipped_unrepresentable)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                (d["id"], d["name"], d["dialect"], d["source_url"], text[:524288],
                 json.dumps(parsed["rules"], ensure_ascii=False),
                 json.dumps(parsed["hostnames"], ensure_ascii=False),
                 json.dumps(parsed["arguments"], ensure_ascii=False),
                 json.dumps(parsed["scripts"], ensure_ascii=False),
                 time.strftime("%Y-%m-%dT%H:%M:%S"),
                 parsed["skipped_scripts"], parsed["skipped_unsupported"],
                 parsed["skipped_routing"], parsed["skipped_unrepresentable"]))
        except Exception as e:  # id 冲突等
            results["failed"].append({"name": d["name"], "reason": str(e)})
            continue
        results["created"].append(d["name"])
    conn.commit()
    return results


def restore_defaults(conn) -> dict:
    """恢复默认：仅重建 3 条默认规则集，用户自加的规则集保留。"""
    return preset_default_rulesets(conn, force=True)
