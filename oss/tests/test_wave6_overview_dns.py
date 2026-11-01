"""Wave6 item 3 (2026-11-01): overview DNS section backend.

GET /api/dns/filter/overview aggregates the dnsmasq query log:
last-24h query count + top blocked domains, plus the filter state.
Average resolution time is deliberately absent (dnsmasq logs carry
no durations). A log without parseable timestamps falls back to
window "all"; a missing log reports collected=False.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import create_app  # noqa: E402


def _fmt(ts: float) -> str:
    return time.strftime("%b %e %H:%M:%S", time.localtime(ts))


def _line(ts: float, domain: str) -> str:
    return (f"{_fmt(ts)} dnsmasq[123]: query[A] {domain} "
            f"from 192.168.1.10")


def _setup_env(tmp: str):
    log_path = os.path.join(tmp, "dnsmasq.log")
    now = time.time()
    lines = [
        _line(now - 60, "bad.example"),
        _line(now - 120, "bad.example"),
        _line(now - 180, "ok.example"),
        _line(now - 25 * 3600, "bad.example"),  # outside 24h
    ]
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(tmp, "dnsmasq-blocklist.conf"),
              "w", encoding="utf-8") as f:
        f.write("address=/bad.example/#\n")
    old_log = os.environ.get("OBX_DNSMASQ_LOG")
    old_wd = os.environ.get("OPENBOX_WORKDIR")
    os.environ["OBX_DNSMASQ_LOG"] = log_path
    os.environ["OPENBOX_WORKDIR"] = tmp
    return old_log, old_wd


def _restore_env(old_log, old_wd):
    if old_log is None:
        os.environ.pop("OBX_DNSMASQ_LOG", None)
    else:
        os.environ["OBX_DNSMASQ_LOG"] = old_log
    if old_wd is None:
        os.environ.pop("OPENBOX_WORKDIR", None)
    else:
        os.environ["OPENBOX_WORKDIR"] = old_wd


def test_dns_filter_overview_24h_and_top_blocked():
    tmp = tempfile.mkdtemp()
    old_log, old_wd = _setup_env(tmp)
    try:
        c = create_app(":memory:").test_client()
        r = c.get("/api/dns/filter/overview")
        assert r.status_code == 200
        body = r.get_json()
        assert body["window"] == "24h"
        assert body["queries"] == 3  # the 25h-old query is excluded
        assert body["blocked"] == 2
        assert body["top_blocked"] == [
            {"domain": "bad.example", "count": 2}]
        assert body["collected"] is True
        assert body["enabled"] is False
        assert body["compiled_domains"] == 1
        assert "avg" not in body  # no duration source; not faked
    finally:
        _restore_env(old_log, old_wd)


def test_dns_filter_overview_missing_log():
    tmp = tempfile.mkdtemp()
    old_log = os.environ.get("OBX_DNSMASQ_LOG")
    old_wd = os.environ.get("OPENBOX_WORKDIR")
    os.environ["OBX_DNSMASQ_LOG"] = os.path.join(tmp, "nope.log")
    os.environ["OPENBOX_WORKDIR"] = tmp
    try:
        c = create_app(":memory:").test_client()
        body = c.get("/api/dns/filter/overview").get_json()
        assert body["collected"] is False
        assert body["queries"] == 0
        assert body["top_blocked"] == []
        assert body["note"]
    finally:
        _restore_env(old_log, old_wd)
