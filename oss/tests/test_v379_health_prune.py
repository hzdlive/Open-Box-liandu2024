"""v0.1.379: sync must not leave stale speedtest rows behind.

node_health is keyed by bare tag and was never touched by refresh /
reimport / delete, so a removed node's row survived and was inherited
by any later node reusing the tag (stale latency on a different, or
dead, node). After a replace, orphan rows and rows for nodes whose
server changed are dropped; the next speedtest repopulates them.
"""
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from panel import db as dbmod  # noqa: E402


def fresh_db():
    conn = sqlite3.connect(":memory:")
    dbmod.init_db(conn)
    return conn


def add_sub(conn, name):
    cur = conn.execute(
        "INSERT INTO subscriptions(name, created_at) VALUES (?, '2026-01-01')",
        (name,))
    return cur.lastrowid


def add_node(conn, sid, tag, server="10.0.0.1", protocol="vless"):
    conn.execute(
        "INSERT INTO nodes(sub_id, tag, protocol, server, port, params,"
        " orig_tag) VALUES (?, ?, ?, ?, 443, '{}', ?)",
        (sid, tag, protocol, server, tag))
    conn.commit()


def add_health(conn, tag, ok, latency):
    conn.execute(
        "INSERT INTO node_health(tag, ok, latency_ms, error, error_kind,"
        " checked_at) VALUES (?, ?, ?, '', '', '2026-01-01')",
        (tag, ok, latency))
    conn.commit()


def health_tags(conn):
    return {r[0] for r in conn.execute("SELECT tag FROM node_health")}


def node(tag, server="10.0.0.1", protocol="vless"):
    return SimpleNamespace(tag=tag, protocol=protocol, server=server,
                          server_port=443, params={})


def test_replace_prunes_orphans_and_changed_servers():
    conn = fresh_db()
    sid = add_sub(conn, "s1")
    add_node(conn, sid, "A", server="10.0.0.1")
    add_node(conn, sid, "B", server="10.0.0.2")
    add_health(conn, "A", 1, 120)   # same tag, server changes -> drop
    add_health(conn, "B", 1, 130)   # node removed by replace -> drop
    add_health(conn, "X", 1, 50)    # never a node -> drop
    add_health(conn, "keep", 1, 60)  # belongs to another sub -> keep
    sid2 = add_sub(conn, "s2")
    add_node(conn, sid2, "keep", server="10.0.0.9")

    dbmod._replace_nodes(conn, sid, "s1",
                         [node("A", server="10.0.0.99"), node("D")])
    assert health_tags(conn) == {"keep"}


def test_replace_keeps_unchanged_node_health():
    conn = fresh_db()
    sid = add_sub(conn, "s1")
    add_node(conn, sid, "A", server="10.0.0.1")
    add_health(conn, "A", 1, 120)
    dbmod._replace_nodes(conn, sid, "s1", [node("A", server="10.0.0.1")])
    assert health_tags(conn) == {"A"}


def test_delete_subscription_prunes_health():
    conn = fresh_db()
    sid = add_sub(conn, "s1")
    add_node(conn, sid, "E")
    add_health(conn, "E", 1, 70)
    assert dbmod.delete_subscription(conn, sid) is True
    assert health_tags(conn) == set()
