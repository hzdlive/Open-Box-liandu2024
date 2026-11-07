"""v0.1.387: loadbalance groups default to a 120s check interval.

- New loadbalance group without interval_s -> 120 (was 300).
- Other types without interval_s stay 300.
- An explicit interval_s is preserved for every type.
- Existing groups keep their stored interval when updated without
  an interval_s key (saved custom settings are never rewritten).
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from panel import db as dbmod  # noqa: E402


def fresh_db():
    conn = sqlite3.connect(":memory:")
    dbmod.init_db(conn)
    return conn


def test_lb_default_120():
    conn = fresh_db()
    g = dbmod.create_group(conn, {"name": "LB1", "type": "loadbalance"})
    assert g["interval_s"] == 120, g


def test_other_types_default_300():
    conn = fresh_db()
    for t in ("urltest", "selector", "smart", "failover"):
        d = {"name": f"G-{t}", "type": t}
        if t == "failover":
            d["lanes"] = [
                {"name": "main", "mode": "auto", "members": []},
                {"name": "bak", "mode": "auto", "members": []},
            ]
        g = dbmod.create_group(conn, d)
        assert g["interval_s"] == 300, (t, g)


def test_explicit_interval_preserved():
    conn = fresh_db()
    g = dbmod.create_group(conn, {"name": "LB60", "type": "loadbalance",
                                  "interval_s": 60})
    assert g["interval_s"] == 60, g
    g = dbmod.create_group(conn, {"name": "U600", "type": "urltest",
                                  "interval_s": 600})
    assert g["interval_s"] == 600, g


def test_update_keeps_stored_interval():
    conn = fresh_db()
    g = dbmod.create_group(conn, {"name": "LB1", "type": "loadbalance"})
    assert g["interval_s"] == 120
    # Rename only: no interval_s key -> stored value untouched.
    g2 = dbmod.update_group(conn, g["id"], {"name": "LB1-renamed"})
    assert g2["interval_s"] == 120, g2
    # Explicit update still works.
    g3 = dbmod.update_group(conn, g["id"], {"interval_s": 180})
    assert g3["interval_s"] == 180, g3


if __name__ == "__main__":
    test_lb_default_120()
    test_other_types_default_300()
    test_explicit_interval_preserved()
    test_update_keeps_stored_interval()
    print("test_v387_lb_interval: 4 passed")
