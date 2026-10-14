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

    return {
        "format": "openbox-oss-backup",
        "version": BACKUP_VERSION,
        "tables": {
            t: rows(t) for t in (
                "subscriptions", "nodes", "site_sets", "settings",
                "rule_sets", "chains", "groups", "node_health",
            )
        },
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
