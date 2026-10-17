"""Full-state backup / restore (config bundle import & export).

A backup is a single JSON document with a version marker and the contents
of every panel table. Restoring replaces the current state atomically.
"""

from __future__ import annotations

import json
import sqlite3

BACKUP_VERSION = 1


def export_backup(conn: sqlite3.Connection) -> dict:
    def rows(table: str) -> list[dict]:
        cur = conn.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # REA 26.4 #23: 导出绝不含面板密码（users 表不导出）；
    # 同时过滤 settings 中的密钥类字段
    _SENSITIVE_SETTINGS = {"clash_api_secret", "panel_password", "auth_secret"}
    settings_rows = [r for r in rows("settings")
                     if r.get("key") not in _SENSITIVE_SETTINGS]

    tables = {}
    for t in ("subscriptions", "nodes", "site_sets",
              "rule_sets", "chains", "groups", "node_health"):
        tables[t] = rows(t)
    tables["settings"] = settings_rows

    return {
        "format": "openbox-oss-backup",
        "version": BACKUP_VERSION,
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
            conn.execute(f"DELETE FROM {table}")
            counts[table] = 0
            for row in rows:
                cols = ", ".join(row.keys())
                ph = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})",
                             list(row.values()))
                counts[table] += 1
    return {"restored": True, "counts": counts}


def backup_to_json(conn: sqlite3.Connection) -> str:
    return json.dumps(export_backup(conn), ensure_ascii=False, indent=2)


def backup_from_json(conn: sqlite3.Connection, text: str) -> dict:
    return import_backup(conn, json.loads(text))
