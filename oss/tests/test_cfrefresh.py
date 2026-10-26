"""Self-test for content-filter refresh/cooldown/caps (core/cfrefresh.py)."""

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from core import cfrefresh as cfr  # noqa: E402

NOW = 1_800_000_000


def _rules(n, prefix="d"):
    return [{"action": "reject", "type": "domain_suffix",
             "pattern": f"{prefix}{i}.example.com"} for i in range(n)]


def _db():
    c = sqlite3.connect(":memory:")
    dbmod.init_db(c)
    # get_blocked_domains caches by db_path; every :memory: DB shares the
    # same key, so clear it whenever a fresh fixture DB is built.
    dbmod._blocked_domains_cache.clear()
    return c


def _add(c, rid, name, rules, source_url="", enabled=1, dialect="surge"):
    cfr.ensure_columns(c)
    c.execute(
        "INSERT INTO cf_rulesets(id, name, dialect, source_url, text, rules,"
        " enabled, updated_at, domain_count) VALUES (?,?,?,?,?,?,?,?,?)",
        (rid, name, dialect, source_url, "old-text",
         json.dumps(rules), enabled, "2026-01-01T00:00:00",
         len({r["pattern"] for r in rules})))
    c.commit()


def main() -> int:
    orig_fetch = cfr.fetch_text
    orig_single, orig_total = cfr.SINGLE_CAP, cfr.TOTAL_CAP
    cfr.SINGLE_CAP, cfr.TOTAL_CAP = 10, 15
    try:
        # 1. failed fetch -> kept old + cooldown blocks retry, force bypasses
        c = _db()
        _add(c, "r1", "R1", _rules(3), source_url="https://x.test/list")
        calls = []

        def failing(url, timeout=30):
            calls.append(url)
            raise OSError("down")

        cfr.fetch_text = failing
        r = cfr.refresh_ruleset(c, "r1", now=NOW)
        assert r["status"] == "failed" and r["kept_old"], r
        assert len(calls) == 1
        row = c.execute("SELECT text, last_error FROM cf_rulesets"
                        " WHERE id='r1'").fetchone()
        assert row[0] == "old-text" and "down" in row[1], row
        r = cfr.refresh_ruleset(c, "r1", now=NOW + 60)
        assert r["status"] == "cooldown" and r["retry_after"] == 540, r
        assert len(calls) == 1  # no second fetch during cooldown
        r = cfr.refresh_ruleset(c, "r1", force=True, now=NOW + 60)
        assert r["status"] == "failed" and len(calls) == 2, r
        # cooldown expired (600s after the last, forced, attempt) -> fetch again
        r = cfr.refresh_ruleset(c, "r1", now=NOW + 661)
        assert r["status"] == "failed" and len(calls) == 3, r

        # 2. unchanged content -> no updated_at change, error cleared
        c = _db()
        _add(c, "r1", "R1", _rules(3), source_url="https://x.test/list")
        c.execute("UPDATE cf_rulesets SET last_error='boom',"
                  " last_attempt_at=? WHERE id='r1'", (NOW - 700,))
        cfr.fetch_text = lambda url, timeout=30: "old-text"
        r = cfr.refresh_ruleset(c, "r1", now=NOW)
        assert r["status"] == "unchanged", r
        row = c.execute("SELECT updated_at, last_error FROM cf_rulesets"
                        " WHERE id='r1'").fetchone()
        assert row[0] == "2026-01-01T00:00:00" and row[1] == "", row

        # 3. single cap rejection keeps old rules, sets no cooldown
        c = _db()
        _add(c, "r1", "R1", _rules(3), source_url="https://x.test/list")
        big = "[Rule]\n" + "\n".join(
            f"DOMAIN-SUFFIX,big{i}.example.com,REJECT" for i in range(11))
        cfr.fetch_text = lambda url, timeout=30: big
        r = cfr.refresh_ruleset(c, "r1", now=NOW)
        assert r["status"] == "rejected", r
        row = c.execute("SELECT text, last_error FROM cf_rulesets"
                        " WHERE id='r1'").fetchone()
        assert row[0] == "old-text" and row[1] == "", row

        # 4. total cap: existing 12 + new 5 > 15 -> rejected
        c = _db()
        _add(c, "r1", "R1", _rules(12), source_url="https://x.test/list")
        _add(c, "r2", "R2", _rules(3, prefix="e"),
             source_url="https://x.test/list2")
        new = "[Rule]\n" + "\n".join(
            f"DOMAIN-SUFFIX,n{i}.example.com,REJECT" for i in range(5))
        cfr.fetch_text = lambda url, timeout=30: new
        r = cfr.refresh_ruleset(c, "r2", now=NOW)
        assert r["status"] == "rejected", r
        # ...but a 3-domain refresh fits (12 + 3 = 15, not over)
        small = "[Rule]\n" + "\n".join(
            f"DOMAIN-SUFFIX,s{i}.example.com,REJECT" for i in range(3))
        cfr.fetch_text = lambda url, timeout=30: small
        r = cfr.refresh_ruleset(c, "r2", now=NOW)
        assert r["status"] == "updated" and r["domains"] == 3, r

        # 5. no source_url / missing -> errors
        c = _db()
        _add(c, "r1", "R1", _rules(1))
        try:
            cfr.refresh_ruleset(c, "r1", now=NOW)
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "source_url" in str(e)
        try:
            cfr.refresh_ruleset(c, "nope", now=NOW)
            raise AssertionError("expected KeyError")
        except KeyError:
            pass

        # 6. rules_to_domains keeps order + dedup (O(n) rewrite check).
        # NOTE: "*.B.com" normalizes to ".b.com" (lstrip('.') then
        # lstrip('*')); that leading-dot quirk is pre-existing behavior,
        # preserved exactly by the rewrite, not fixed here.
        from core.cf_parser import rules_to_domains
        sample = [{"action": "reject", "type": "domain_suffix",
                   "pattern": "*.B.com"},
                  {"action": "reject", "type": "domain",
                   "pattern": "a.com"},
                  {"action": "reject", "type": "domain_suffix",
                   "pattern": "b.com"},
                  {"action": "allow", "type": "domain_suffix",
                   "pattern": "c.com"}]
        assert rules_to_domains(sample) == [".b.com", "a.com", "b.com"], \
            rules_to_domains(sample)

        # 7. hosts-format refresh: a raw hosts file must parse to block
        # rules even when the stored dialect is quantumultx (the dialect
        # parsers only read [section] content, so without hosts
        # detection a refresh would silently replace working rules
        # with zero rules). Also covers the raised 4 MiB text cap.
        from core import cf_parser as cp
        hosts_text = (
            "# StevenBlack-style sample\n"
            "127.0.0.1 localhost\n"
            "0.0.0.0 ads.example.com\n"
            "0.0.0.0 tracker.example.org # trailing comment\n"
            "0.0.0.0 ADS.EXAMPLE.COM\n"
            "0.0.0.0 0.0.0.0\n"
            "255.255.255.255 broadcasthost\n"
            "::1 localhost\n"
        )
        assert cp.detect_hosts_format(hosts_text)
        assert not cp.detect_hosts_format(
            "[filter_local]\nhost-suffix, a.com, reject\n")
        parsed_hosts = cp.parse_hosts(hosts_text)
        assert rules_to_domains(parsed_hosts["rules"]) == [
            "ads.example.com", "tracker.example.org"], parsed_hosts
        # wrapper: hosts shape wins over the stored dialect
        assert cp.parse_content_filter_text(
            hosts_text, "quantumultx")["rules"] == parsed_hosts["rules"]
        # cap: a 2.2 MB hosts file (current StevenBlack size) parses,
        # anything over 4 MiB is still rejected
        big_hosts = "".join(
            f"0.0.0.0 host{i}.example.com\n" for i in range(90000))
        assert len(big_hosts.encode()) > 2_000_000
        assert len(cp.parse_content_filter_text(
            big_hosts, "quantumultx")["rules"]) == 90000
        try:
            cp.parse_content_filter_text("x" * (cp.MAX_TEXT_BYTES + 1),
                                         "surge")
            raise AssertionError("over-cap text must be rejected")
        except ValueError as e:
            assert "MiB" in str(e), e
        # end-to-end through refresh_ruleset with a mocked fetch
        c2 = _db()
        _add(c2, "rh", "RH", _rules(2), source_url="https://h.test/hosts",
             dialect="quantumultx")
        cfr.fetch_text = lambda url, timeout=30: hosts_text
        r = cfr.refresh_ruleset(c2, "rh", force=True, now=NOW)
        assert r["status"] == "updated" and r["domains"] == 2, r
        row = c2.execute(
            "SELECT rules, text FROM cf_rulesets WHERE id='rh'").fetchone()
        assert len(json.loads(row[0])) == 2
        assert row[1] == hosts_text  # stored complete, not truncated

        # 8. Flask endpoint mapping (404 / 400 / cooldown / 502)
        from panel.app import create_app
        app = create_app(":memory:")
        t = app.test_client()
        assert t.post("/api/openbox/content-filter/nope/refresh",
                      json={}).status_code == 404
        rid = t.post("/api/openbox/content-filter",
                     json={"name": "T", "dialect": "surge",
                           "text": "||a.com^"}).get_json()["id"]
        assert t.post(f"/api/openbox/content-filter/{rid}/refresh",
                      json={}).status_code == 400  # no source_url
    finally:
        cfr.fetch_text = orig_fetch
        cfr.SINGLE_CAP, cfr.TOTAL_CAP = orig_single, orig_total

    print("OK: cfrefresh — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
