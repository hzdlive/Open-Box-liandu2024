"""v0.1.380: an older speedtest run landing later must not overwrite
newer results (the panel form of 'old results overwrite new results
after a network switch': bulk test vs per-sub test, or a pre-switch
run finishing after a fresh one).

Each run stamps its rows with a sequence taken at run start;
save_health applies a row only when its run is at least as new as
the stored row. The counter survives process restarts via MAX seeding.
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
    dbmod._HEALTH_SEQ[0] = None
    return conn


def res(tag, ok, latency):
    return SimpleNamespace(tag=tag, ok=ok, latency_ms=latency, error="",
                          error_kind="", checked_at="2026-01-01")


def row(conn, tag):
    r = conn.execute(
        "SELECT ok, latency_ms, run_seq FROM node_health WHERE tag=?",
        (tag,)).fetchone()
    return r


def test_stale_run_does_not_overwrite():
    conn = fresh_db()
    old_seq = dbmod.next_health_seq(conn)
    dbmod.save_health(conn, [res("A", True, 100)], run_seq=old_seq)
    new_seq = dbmod.next_health_seq(conn)
    dbmod.save_health(conn, [res("A", True, 200)], run_seq=new_seq)
    assert row(conn, "A")[1] == 200
    # The old run lands late: must not clobber the newer row.
    dbmod.save_health(conn, [res("A", True, 100)], run_seq=old_seq)
    assert row(conn, "A") == (1, 200, new_seq)


def test_new_run_always_wins_and_legacy_rows_upgrade():
    conn = fresh_db()
    # Legacy row (pre-migration run_seq 0) is overwritten by any run.
    conn.execute(
        "INSERT INTO node_health(tag, ok, latency_ms, error, error_kind,"
        " checked_at, run_seq) VALUES ('B', 1, 50, '', '', '2026-01-01', 0)")
    conn.commit()
    seq = dbmod.next_health_seq(conn)
    dbmod.save_health(conn, [res("B", False, None)], run_seq=seq)
    assert row(conn, "B")[0] == 0


def test_seq_survives_restart_seed():
    conn = fresh_db()
    conn.execute(
        "INSERT INTO node_health(tag, ok, latency_ms, error, error_kind,"
        " checked_at, run_seq) VALUES ('C', 1, 50, '', '', '2026-01-01', 7)")
    conn.commit()
    # Simulate a fresh process: counter reset, must seed from MAX=7.
    dbmod._HEALTH_SEQ[0] = None
    assert dbmod.next_health_seq(conn) == 8


def test_unstamped_save_keeps_old_behavior():
    conn = fresh_db()
    dbmod.save_health(conn, [res("D", True, 10)])
    dbmod.save_health(conn, [res("D", True, 20)])
    assert row(conn, "D")[1] == 20
