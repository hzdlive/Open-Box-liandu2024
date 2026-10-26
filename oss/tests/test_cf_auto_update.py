"""Scheduled content-filter refresh (item 6).

Mirrors the DNS filter's daily schedule: cf_auto_update + cf_update_time
(default 04:00) + once-per-day stamp. Refreshes only lists that have a
source -- enabled cf_rulesets with source_url and enabled legacy
content_filters with snapshot_url; manual (no-URL) lists are skipped.
Refresh updates stored lists only; the kernel rule picks them up on the
next apply/deploy (same refresh != apply split as the manual buttons).
"""

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import scheduler as schedmod  # noqa: E402
from panel import db as dbmod  # noqa: E402
from core import cfrefresh as cfrmod  # noqa: E402


def _conn(monkeypatch, auto="1", update_time="00:00", stamp=""):
    conn = sqlite3.connect(":memory:")
    dbmod.init_db(conn)
    dbmod.set_setting(conn, "cf_auto_update", auto)
    dbmod.set_setting(conn, "cf_update_time", update_time)
    dbmod.set_setting(conn, "cf_auto_updated_at", stamp)
    conn.execute(
        "INSERT INTO cf_rulesets (id, name, source_url, enabled)"
        " VALUES ('r-url', 'has-url', 'https://example.com/x.conf', 1)")
    conn.execute(
        "INSERT INTO cf_rulesets (id, name, source_url, enabled)"
        " VALUES ('r-manual', 'manual', '', 1)")
    conn.execute(
        "INSERT INTO cf_rulesets (id, name, source_url, enabled)"
        " VALUES ('r-off', 'disabled', 'https://example.com/y.conf', 0)")
    conn.execute(
        "INSERT INTO content_filters (name, snapshot_url, enabled)"
        " VALUES ('legacy-url', 'https://example.com/hosts', 1)")
    conn.execute(
        "INSERT INTO content_filters (name, snapshot_url, enabled)"
        " VALUES ('legacy-manual', '', 1)")
    conn.commit()
    return conn


def _recorders(monkeypatch):
    calls = {"rulesets": [], "legacy": []}
    monkeypatch.setattr(
        cfrmod, "refresh_ruleset",
        lambda conn, rid, **kw: calls["rulesets"].append(rid) or
        {"status": "unchanged"})
    monkeypatch.setattr(
        dbmod, "refresh_content_filter_from_snapshot",
        lambda conn, fid: calls["legacy"].append(fid) or {"id": fid})
    return calls


def test_off_does_nothing(monkeypatch):
    conn = _conn(monkeypatch, auto="0")
    calls = _recorders(monkeypatch)
    schedmod._maybe_update_content_filter(conn)
    assert calls == {"rulesets": [], "legacy": []}
    assert dbmod.get_setting(conn, "cf_auto_updated_at", "") == ""


def test_on_refreshes_only_sourced_lists(monkeypatch):
    conn = _conn(monkeypatch)
    calls = _recorders(monkeypatch)
    schedmod._maybe_update_content_filter(conn)
    assert calls["rulesets"] == ["r-url"]
    assert len(calls["legacy"]) == 1  # the one legacy row with a URL
    assert dbmod.get_setting(conn, "cf_auto_updated_at", "") == \
        time.strftime("%Y-%m-%d")


def test_second_run_same_day_is_noop(monkeypatch):
    conn = _conn(monkeypatch)
    calls = _recorders(monkeypatch)
    schedmod._maybe_update_content_filter(conn)
    schedmod._maybe_update_content_filter(conn)
    assert len(calls["rulesets"]) == 1
    assert len(calls["legacy"]) == 1


def test_one_failure_does_not_stop_others(monkeypatch):
    conn = _conn(monkeypatch)
    calls = {"rulesets": [], "legacy": []}
    monkeypatch.setattr(
        cfrmod, "refresh_ruleset",
        lambda conn, rid, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        dbmod, "refresh_content_filter_from_snapshot",
        lambda conn, fid: calls["legacy"].append(fid) or {"id": fid})
    schedmod._maybe_update_content_filter(conn)
    assert calls["legacy"]  # legacy run still happened
    assert dbmod.get_setting(conn, "cf_auto_updated_at", "") == \
        time.strftime("%Y-%m-%d")
