"""Full-state backup / restore (config bundle import & export).

A backup is a single JSON document with a version marker and the contents
of every panel table. Restoring replaces the current state atomically.
"""

from __future__ import annotations

import json
import sqlite3

BACKUP_VERSION = 1


# 备份分组（对标原版 od 枚举 + behavior-spec §5.8）
# 必选分组：routing, groups, dns, panel
# 可选分组：subscriptions, chain, share, apps
BACKUP_GROUPS = {
    # 必选：路由与站点集
    "routing": ["site_sets", "front_rules", "rule_sets"],
    # 必选：出站分组
    "groups": ["groups"],
    # 必选：DNS 设置（从 settings 表提取 dns_ 前缀）
    "dns": ["settings:dns"],
    # 必选：面板设置（过滤敏感字段后）
    "panel": ["settings:panel"],
    # 可选：订阅与节点
    "subscriptions": ["subscriptions", "nodes"],
    # 可选：链式代理
    "chain": ["chains"],
    # 可选：分享（订阅分享）
    "share": ["subscription_shares"],
    # 可选：终端分流（per-device）
    "apps": ["terminal_rules", "terminals"],
}

# 必选分组（导出时总是包含）
REQUIRED_GROUPS = {"routing", "groups", "dns", "panel"}

# settings 表按前缀分组
_DNS_SETTING_PREFIXES = ("dns_", "fakeip")
_PANEL_SETTING_EXCLUDE_PREFIXES = ("dns_",)  # dns_ 开头的归 dns 组


def export_backup(conn: sqlite3.Connection,
                  groups: list[str] | None = None) -> dict:
    """选择性导出。groups 为 None 时导出全部（必选+可选）。
    传入 groups 列表时，只导出指定的分组（必选分组总是包含）。
    """
    def rows(table: str) -> list[dict]:
        # 检查表是否存在
        try:
            cur = conn.execute(f"SELECT * FROM {table}")
        except Exception:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # REA 26.4 #23: 导出绝不含面板密码（users 表不导出）；
    # 同时过滤 settings 中的密钥类字段
    _SENSITIVE_SETTINGS = {"clash_api_secret", "panel_password", "auth_secret"}

    # 确定要导出的分组
    if groups is None:
        wanted = set(BACKUP_GROUPS.keys())
    else:
        wanted = REQUIRED_GROUPS | (set(groups) & set(BACKUP_GROUPS.keys()))

    tables = {}
    settings_all = rows("settings")

    for g in sorted(wanted):
        for spec in BACKUP_GROUPS[g]:
            if spec == "settings:dns":
                # DNS 相关设置
                dns_rows = [r for r in settings_all
                            if r.get("key", "").startswith(_DNS_SETTING_PREFIXES)
                            and r.get("key") not in _SENSITIVE_SETTINGS]
                tables["settings_dns"] = dns_rows
            elif spec == "settings:panel":
                # 面板设置（排除 dns_ 前缀的）
                panel_rows = [r for r in settings_all
                              if not r.get("key", "").startswith(_PANEL_SETTING_EXCLUDE_PREFIXES)
                              and r.get("key") not in _SENSITIVE_SETTINGS]
                tables["settings_panel"] = panel_rows
            else:
                tables[spec] = rows(spec)

    return {
        "format": "openbox-oss-backup",
        "version": BACKUP_VERSION,
        "groups": sorted(wanted),
        "tables": tables,
    }


def import_backup(conn: sqlite3.Connection, data: dict) -> dict:
    if data.get("format") != "openbox-oss-backup":
        raise ValueError("not an openbox-oss backup")
    if data.get("version") != BACKUP_VERSION:
        raise ValueError(f"unsupported backup version: {data.get('version')}")
    tables = data.get("tables") or {}
    counts = {}
    with conn:  # atomic
        for table, rows in tables.items():
            # settings_dns / settings_panel 合并回 settings 表
            target = "settings" if table in ("settings_dns", "settings_panel") else table
            if table in ("settings_dns", "settings_panel"):
                # 只删除对应前缀的设置，避免误删其他分组的设置
                if table == "settings_dns":
                    for prefix in _DNS_SETTING_PREFIXES:
                        conn.execute("DELETE FROM settings WHERE key LIKE ?", (prefix + "%",))
                else:
                    # panel：删除非 dns_ 前缀的（保留 dns 设置）
                    conn.execute("DELETE FROM settings WHERE key NOT LIKE 'dns_%'")
            else:
                try:
                    conn.execute(f"DELETE FROM {target}")
                except Exception:
                    continue  # 表不存在则跳过
            counts[table] = 0
            for row in rows:
                cols = ", ".join(row.keys())
                ph = ", ".join("?" for _ in row)
                try:
                    conn.execute(f"INSERT OR REPLACE INTO {target} ({cols}) VALUES ({ph})",
                                 list(row.values()))
                    counts[table] += 1
                except Exception:
                    continue
    return {"restored": True, "counts": counts}


def backup_to_json(conn: sqlite3.Connection, groups: list[str] | None = None) -> str:
    return json.dumps(export_backup(conn, groups), ensure_ascii=False, indent=2)


def backup_from_json(conn: sqlite3.Connection, text: str) -> dict:
    return import_backup(conn, json.loads(text))
