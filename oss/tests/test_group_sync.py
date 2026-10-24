"""Regression: same-name groups must mirror their subscription's nodes.

2026-10-24: JPAC直连 / BWG groups showed 3 members while their
subscriptions had 5 nodes (the two anytls nodes were missing). Cause:
groups are static member lists and subscription refresh never touched
them. Fix: _replace_nodes now calls sync_subscription_groups, which
rewrites a same-name plain-member group's members to the subscription's
current node tags, guarded so mixed/keyword/failover/disabled groups
are never wiped.
"""
import json
import sqlite3
import sys
from types import SimpleNamespace
from pathlib import Path

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


def add_nodes(conn, sid, tags):
    for t in tags:
        conn.execute(
            "INSERT INTO nodes(sub_id, tag, protocol, server, port, params,"
            " orig_tag) VALUES (?, ?, 'vless', 'example.com', 443, '{}', ?)",
            (sid, t, t))
    conn.commit()


def add_group(conn, name, gtype="urltest", members=None, keywords=None,
              enabled=1):
    conn.execute(
        "INSERT INTO groups(name, type, members, dynamic_keywords, enabled)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, gtype, json.dumps(members or [], ensure_ascii=False),
         json.dumps(keywords or [], ensure_ascii=False), enabled))
    conn.commit()


def group_members(conn, name):
    row = conn.execute("SELECT members FROM groups WHERE name=?",
                       (name,)).fetchone()
    return json.loads(row[0])


def fake_nodes(tags):
    return [SimpleNamespace(tag=t, protocol="vless", server="example.com",
                            server_port=443, params={}) for t in tags]


def test_sync_subset_group_via_replace():
    conn = fresh_db()
    sid = add_sub(conn, "JPAC直连")
    add_nodes(conn, sid, ["vless-22100", "tuic-22100", "hysteria2-22102"])
    add_group(conn, "JPAC直连", members=["vless-22100", "tuic-22100",
                                         "hysteria2-22102"])
    out = dbmod._replace_nodes(
        conn, sid, "JPAC直连",
        fake_nodes(["vless-22100", "tuic-22100", "anytls-22102 #2",
                    "hysteria2-22102", "anytls-22103 #2"]))
    assert out["synced_groups"] == ["JPAC直连"]
    assert group_members(conn, "JPAC直连") == [
        "vless-22100", "tuic-22100", "anytls-22102 #2",
        "hysteria2-22102", "anytls-22103 #2"]


def test_sync_skips_mixed_group():
    conn = fresh_db()
    sid_a = add_sub(conn, "JPAC直连")
    sid_b = add_sub(conn, "BWG")
    add_nodes(conn, sid_a, ["a1", "a2"])
    add_nodes(conn, sid_b, ["b1"])
    # group named JPAC直连 but holding another subscription's node
    add_group(conn, "JPAC直连", members=["a1", "b1"])
    synced = dbmod.sync_subscription_groups(conn, sid_a, "JPAC直连")
    assert synced == []
    assert group_members(conn, "JPAC直连") == ["a1", "b1"]


def test_sync_skips_failover_group():
    # failover groups keep members in lanes; the members field must stay
    # empty even when a subscription of the same name refreshes.
    conn = fresh_db()
    sid = add_sub(conn, "BWG")
    add_nodes(conn, sid, ["v1", "v2"])
    add_group(conn, "BWG", gtype="failover", members=[])
    synced = dbmod.sync_subscription_groups(conn, sid, "BWG")
    assert synced == []
    assert group_members(conn, "BWG") == []


def test_sync_skips_keyword_group():
    conn = fresh_db()
    sid = add_sub(conn, "KW直连")
    add_nodes(conn, sid, ["v1", "v2"])
    add_group(conn, "KW直连", members=["v1"], keywords=["KW"])
    synced = dbmod.sync_subscription_groups(conn, sid, "KW直连")
    assert synced == []
    assert group_members(conn, "KW直连") == ["v1"]


def test_sync_skips_disabled_group():
    conn = fresh_db()
    sid = add_sub(conn, "BWG")
    add_nodes(conn, sid, ["v1", "v2"])
    add_group(conn, "BWG", members=["v1"], enabled=0)
    synced = dbmod.sync_subscription_groups(conn, sid, "BWG")
    assert synced == []
    assert group_members(conn, "BWG") == ["v1"]


def test_sync_noop_when_already_in_sync():
    conn = fresh_db()
    sid = add_sub(conn, "ALIHK直连")
    add_nodes(conn, sid, ["x1", "x2"])
    add_group(conn, "ALIHK直连", members=["x1", "x2"])
    synced = dbmod.sync_subscription_groups(conn, sid, "ALIHK直连")
    assert synced == []
    assert group_members(conn, "ALIHK直连") == ["x1", "x2"]


def test_sync_ignores_other_names():
    conn = fresh_db()
    sid = add_sub(conn, "JPAC直连")
    add_nodes(conn, sid, ["a1", "a2"])
    add_group(conn, "其他组", members=["a1"])
    synced = dbmod.sync_subscription_groups(conn, sid, "JPAC直连")
    assert synced == []
    assert group_members(conn, "其他组") == ["a1"]
