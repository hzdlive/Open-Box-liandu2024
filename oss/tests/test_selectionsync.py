"""Self-test for selection sync (core/selectionsync.py)."""

import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Group  # noqa: E402
from core import selectionsync as ss  # noqa: E402


def _cfg(groups):
    cfg = types.SimpleNamespace(
        groups=groups, nodes=[types.SimpleNamespace(tag="n1"),
                              types.SimpleNamespace(tag="n2")],
        chains=[], clash_api_port=9090)
    return cfg


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE groups(name TEXT UNIQUE, default_outbound TEXT)")
    return c


def main() -> int:
    # selector group, now is a member, changed -> updated + persisted
    c = _conn()
    c.execute("INSERT INTO groups VALUES ('所有-手动', '')")
    g = Group(name="所有-手动", type="selector", members=["n1", "n2"],
              default_outbound="")
    r = ss.reconcile(c, _cfg([g]),
                     proxies={"proxies": {"所有-手动": {"now": "n2"}}})
    assert r["ok"] and r["updated"] == [{"group": "所有-手动", "from": "", "to": "n2"}], r
    assert c.execute("SELECT default_outbound FROM groups").fetchone()[0] == "n2"

    # unchanged now -> no write
    g2 = Group(name="所有-手动", type="selector", members=["n1", "n2"],
               default_outbound="n2")
    r = ss.reconcile(c, _cfg([g2]),
                     proxies={"proxies": {"所有-手动": {"now": "n2"}}})
    assert r["ok"] and r["updated"] == [], r

    # urltest / failover / disabled groups are skipped (now is computed, not chosen)
    c2 = _conn()
    groups = [Group(name="所有-自动", type="urltest", members=["n1", "n2"]),
              Group(name="故转", type="failover", members=["n1", "n2"]),
              Group(name="关着", type="selector", members=["n1", "n2"],
                    enabled=False)]
    r = ss.reconcile(c2, _cfg(groups),
                     proxies={"proxies": {"所有-自动": {"now": "n2"},
                                          "故转": {"now": "n2"},
                                          "关着": {"now": "n2"}}})
    # out of scope, not candidates: no updates and no skipped entries
    assert r["ok"] and r["updated"] == [] and r["skipped"] == [], r

    # now not a member -> skipped, never stored (no guessing)
    c3 = _conn()
    c3.execute("INSERT INTO groups VALUES ('所有-手动', '')")
    g3 = Group(name="所有-手动", type="selector", members=["n1"],
               default_outbound="")
    r = ss.reconcile(c3, _cfg([g3]),
                     proxies={"proxies": {"所有-手动": {"now": "ghost"}}})
    assert r["ok"] and r["updated"] == [] and \
        r["skipped"] == [{"group": "所有-手动", "reason": "not-member"}], r
    assert c3.execute("SELECT default_outbound FROM groups").fetchone()[0] == ""

    # entry without now -> skipped
    r = ss.reconcile(c3, _cfg([g3]),
                     proxies={"proxies": {"所有-手动": {"all": ["n1"]}}})
    assert r["skipped"] == [{"group": "所有-手动", "reason": "no-now"}], r

    # unreachable kernel -> ok False, never raises
    orig = ss.get_proxies
    ss.get_proxies = lambda port=None: (False, {})
    try:
        r = ss.reconcile(c3, _cfg([g3]))
        assert r["ok"] is False and r["error"], r
    finally:
        ss.get_proxies = orig

    print("OK: selectionsync — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
