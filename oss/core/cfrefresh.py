"""Content-filter refresh, retry cooldown and matcher caps
(v6 #18 dns-filter-artifacts 对照，面板存储模型版).

v6 的 dns-filter-artifacts 是部署时把域名名单编译成 .srs 的三道闸门：
key+hash+文件还在 → 每条名单 10 分钟失败重试冷却 → 160MB 内存下限；
单条 250k matcher、合计 400k；失败名单有旧副本记 missing+error 继续，
无副本+无 force 记 missing 继续，无副本+有 force 抛给用户。

我们的模型不同：规则集以解析后的 JSON 存在 cf_rulesets 表里，
apply 时直接展开成 domain_suffix block 规则，不经过 .srs 编译。
因此映射如下（差异均有意）：

- 三道闸门之一（key+hash+文件）：拉到的文本与存量 sha256 相同 →
  status unchanged，不动 updated_at（下游 get_blocked_domains 缓存键不变，
  等于零副作用）。没有 .srs 文件可比，文本哈希即是 hash 门。
- 10 分钟冷却：按规则集记录上次拉取尝试（last_attempt_at + last_error）；
  上次失败且未满 600 秒时刷新直接返回 cooldown（旧规则继续用），
  force=true 可绕过检查；失败的尝试（含 force）都会重新开始冷却。
  冷却只针对拉取失败：上限拒绝是确定性的，不进冷却。
- 160MB 内存下限不适用：我们没有 .srs 编译步骤；工作量由下面两条
  上限直接封顶，解析本身又是 5 分钟缓存的。
- 单条 250k / 合计 400k：以 rules_to_domains 产出的域名数为 matcher 数。
  上限只在入口（创建、刷新）执行，不在消费侧截断——消费侧截断会
  静默改变路由，存量超限规则集在下次编辑/刷新前保持原样工作。
- 失败分支：刷新失败永远保留旧规则（kept_old），端点以 502 報錯；
  这对应 v6 的“有旧副本记 missing+error 继续”。无旧副本的情况
  在我们这里不存在（规则集创建时就已存下规则）。

注意：刷新是显式动作（端点 + UI 按钮），apply 不拉取——apply 时
拉网会让每次配置应用都依赖上游可用性，这是不能接受的。
自动定时刷新不在本项范围（那是新增的后台联网行为，需另行拍板）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.request

SINGLE_CAP = 250_000
TOTAL_CAP = 400_000
COOLDOWN_SECONDS = 600
FETCH_TIMEOUT = 30
TEXT_CAP_BYTES = 524_288


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cf_rulesets)")}
    if "last_attempt_at" not in cols:
        conn.execute("ALTER TABLE cf_rulesets"
                     " ADD COLUMN last_attempt_at INTEGER NOT NULL DEFAULT 0")
    if "last_error" not in cols:
        conn.execute("ALTER TABLE cf_rulesets"
                     " ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")
    if "domain_count" not in cols:
        conn.execute("ALTER TABLE cf_rulesets"
                     " ADD COLUMN domain_count INTEGER DEFAULT NULL")
    conn.commit()


def fetch_text(url: str, timeout: int = FETCH_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenBox/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def domain_count_of_rules(rules) -> int:
    from core.cf_parser import rules_to_domains
    return len(rules_to_domains(rules or []))


def check_caps(conn: sqlite3.Connection, new_domains: int,
               exclude_rid: str | None = None) -> tuple[bool, str]:
    """Return (ok, message). exclude_rid: its old contribution is not counted."""
    if new_domains > SINGLE_CAP:
        return False, f"单规则集域名数 {new_domains} 超过上限 {SINGLE_CAP}"
    from panel.db import get_blocked_domains
    total = len(get_blocked_domains(conn))
    if exclude_rid is not None:
        row = conn.execute("SELECT rules, enabled FROM cf_rulesets"
                           " WHERE id = ?", (exclude_rid,)).fetchone()
        if row and row[1]:
            try:
                total -= domain_count_of_rules(json.loads(row[0] or "[]"))
            except Exception:
                pass
    new_total = total + new_domains
    if new_total > TOTAL_CAP:
        return False, f"合计域名数 {new_total} 超过上限 {TOTAL_CAP}"
    return True, ""


def refresh_ruleset(conn: sqlite3.Connection, rid: str,
                    force: bool = False, now: float | None = None) -> dict:
    """Refresh one URL ruleset. Never deletes stored rules on failure."""
    from core.cf_parser import parse_ruleset

    now = time.time() if now is None else now
    ensure_columns(conn)
    row = conn.execute("SELECT name, dialect, source_url, text, rules,"
                       " enabled, last_attempt_at, last_error"
                       " FROM cf_rulesets WHERE id = ?", (rid,)).fetchone()
    if row is None:
        raise KeyError("not found")
    name, dialect, source_url, old_text, old_rules, enabled, last_at, last_err = row
    if not source_url:
        raise ValueError("rule set has no source_url")
    if (last_err and last_at and now - last_at < COOLDOWN_SECONDS
            and not force):
        return {"status": "cooldown",
                "retry_after": int(COOLDOWN_SECONDS - (now - last_at)),
                "last_error": last_err, "kept_old": True}
    try:
        text = fetch_text(source_url)
    except Exception as e:
        msg = f"fetch failed: {e}"
        conn.execute("UPDATE cf_rulesets SET last_attempt_at=?, last_error=?"
                     " WHERE id = ?", (int(now), msg, rid))
        conn.commit()
        return {"status": "failed", "error": msg, "kept_old": True}
    if hashlib.sha256(text.encode()).hexdigest() == \
            hashlib.sha256((old_text or "").encode()).hexdigest():
        conn.execute("UPDATE cf_rulesets SET last_attempt_at=?, last_error=''"
                     " WHERE id = ?", (int(now), rid))
        conn.commit()
        return {"status": "unchanged"}
    try:
        parsed = parse_ruleset(text, dialect)
    except ValueError as e:
        msg = f"parse failed: {e}"
        conn.execute("UPDATE cf_rulesets SET last_attempt_at=?, last_error=?"
                     " WHERE id = ?", (int(now), msg, rid))
        conn.commit()
        return {"status": "failed", "error": msg, "kept_old": True}
    new_domains = domain_count_of_rules(parsed["rules"])
    ok, msg = check_caps(conn, new_domains, exclude_rid=rid) \
        if enabled else (True, "")
    if not ok:
        return {"status": "rejected", "reason": msg, "kept_old": True}
    conn.execute(
        """UPDATE cf_rulesets SET text=?, rules=?, hostnames=?, arguments=?,
           scripts=?, updated_at=?, skipped_scripts=?, skipped_unsupported=?,
           skipped_routing=?, skipped_unrepresentable=?, last_attempt_at=?,
           last_error='', domain_count=? WHERE id=?""",
        (text[:TEXT_CAP_BYTES],
         json.dumps(parsed["rules"], ensure_ascii=False),
         json.dumps(parsed["hostnames"], ensure_ascii=False),
         json.dumps(parsed["arguments"], ensure_ascii=False),
         json.dumps(parsed["scripts"], ensure_ascii=False),
         time.strftime("%Y-%m-%dT%H:%M:%S"),
         parsed["skipped_scripts"], parsed["skipped_unsupported"],
         parsed["skipped_routing"], parsed["skipped_unrepresentable"],
         int(now), new_domains, rid))
    conn.commit()
    return {"status": "updated", "domains": new_domains}
