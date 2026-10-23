"""Self-test for chain front validation (core/chainvalidate.py) and for the
disabled-chain build exclusion (load_app_config + build_outbounds)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from core.chainvalidate import validate_front  # noqa: E402


def _db():
    c = sqlite3.connect(":memory:")
    dbmod.init_db(c)
    c.execute("INSERT INTO subscriptions(id, name, enabled, created_at)"
              " VALUES (1, 'S1', 1, '2026-01-01T00:00:00')")
    c.execute("INSERT INTO subscriptions(id, name, enabled, created_at)"
              " VALUES (2, 'S2', 0, '2026-01-01T00:00:00')")
    c.execute("INSERT INTO nodes(sub_id, tag, protocol, server, port,"
              " params, disabled) VALUES (1, 'n1', 'vless', '1.1.1.1', 443,"
              " '{}', 0)")
    c.execute("INSERT INTO nodes(sub_id, tag, protocol, server, port,"
              " params, disabled) VALUES (1, 'n-off', 'vless', '1.1.1.2', 443,"
              " '{}', 1)")
    c.execute("INSERT INTO groups(name, type, enabled) VALUES ('G1', 'urltest', 1)")
    c.execute("INSERT INTO groups(name, type, enabled) VALUES ('G-off', 'urltest', 0)")
    c.commit()
    return c


def _expect_error(c, name, front, needle, **kw):
    try:
        validate_front(c, name, front, **kw)
    except ValueError as e:
        assert needle in str(e), (needle, str(e))
        return
    raise AssertionError(f"expected ValueError ({needle}) for {name}/{front}")


def main() -> int:
    c = _db()
    # valid fronts
    for front in ("direct", "block", "n1", "G1", "sub-1"):
        validate_front(c, "C-new", front)
    # unknown / disabled
    _expect_error(c, "C-new", "ghost", "不存在")
    _expect_error(c, "C-new", "n-off", "已停用")
    _expect_error(c, "C-new", "G-off", "已停用")
    _expect_error(c, "C-new", "sub-2", "已停用")
    _expect_error(c, "C-new", "sub-99", "不存在")
    _expect_error(c, "C-new", "", "不能为空")
    _expect_error(c, "C-new", "sub-x", "不存在")
    # self-reference
    _expect_error(c, "C-self", "C-self", "不能是自身")
    # chain -> chain ok, then cycles via create/update path
    dbmod.create_chain(c, {"name": "A", "exit_protocol": "socks",
                           "server": "127.0.0.1", "port": 1080, "front": "G1"})
    dbmod.create_chain(c, {"name": "B", "exit_protocol": "socks",
                           "server": "127.0.0.1", "port": 1081, "front": "A"})
    # B -> A -> G1 is a diamond-free chain, valid; now A -> B would cycle
    try:
        dbmod.update_chain(c, 1, {"front": "B"})
        raise AssertionError("expected cycle rejection on A -> B")
    except ValueError as e:
        assert "成环" in str(e) and "A → B → A" in str(e), str(e)
    # 3-cycle: C -> B, then B -> C would close A? No: B -> C, C -> B = 2-cycle
    dbmod.create_chain(c, {"name": "C", "exit_protocol": "socks",
                           "server": "127.0.0.1", "port": 1082, "front": "B"})
    try:
        dbmod.update_chain(c, 2, {"front": "C"})
        raise AssertionError("expected cycle rejection on B -> C")
    except ValueError as e:
        assert "成环" in str(e), str(e)
    # disabled chain as front -> rejected
    dbmod.create_chain(c, {"name": "D", "exit_protocol": "socks",
                           "server": "127.0.0.1", "port": 1083, "front": "G1"})
    dbmod.update_chain(c, 4, {"enabled": 0})
    _expect_error(c, "E-new", "D", "已停用")
    # disabling a chain with a legacy bad front does not fail the toggle
    c.execute("INSERT INTO chains(name, exit_protocol, server, port, params,"
              " front, enabled) VALUES ('LEG', 'socks', '127.0.0.1', 1084,"
              " '{}', 'ghost', 1)")
    c.commit()
    leg_id = c.execute("SELECT id FROM chains WHERE name='LEG'").fetchone()[0]
    dbmod.update_chain(c, leg_id, {"enabled": 0})  # must not raise
    # ...but re-enabling it validates the front
    try:
        dbmod.update_chain(c, leg_id, {"enabled": 1})
        raise AssertionError("expected rejection on re-enable with bad front")
    except ValueError as e:
        assert "不存在" in str(e), str(e)
    # rename: old name no longer counts as an existing front target
    dbmod.update_chain(c, 1, {"name": "A2"})
    _expect_error(c, "F-new", "A", "不存在")
    validate_front(c, "F-new", "A2")  # renamed target resolves
    # disabled chains are excluded from the built config
    cfg = dbmod.load_app_config(c)
    names = [ch.name for ch in cfg.chains]
    assert "D" not in names and "LEG" not in names, names
    assert "A2" in names and "B" in names and "C" in names, names
    from core.singbox import build_outbounds
    tags = [o["tag"] for o in build_outbounds(cfg)]
    assert "D" not in tags and "LEG" not in tags, tags
    assert "A2" in tags, tags

    print("OK: chainvalidate — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
