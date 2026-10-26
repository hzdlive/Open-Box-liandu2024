"""Batch 3 tests: DNS filter, query log, upstream test/trace, traffic
month/day/drill/usage, latency history, site latency."""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402


def _app():
    return create_app(":memory:")


def _dbconn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


def test_dnsfilter_parse_and_match():
    from core.dnsfilter import parse_list, match_domain
    text = ("# comment\n0.0.0.0 ads.example.com\n"
            "127.0.0.1 tracker.example.org\n||banner.example.net^\n"
            "! adblock comment\n")
    domains = parse_list(text)
    assert domains == {"ads.example.com", "tracker.example.org",
                       "banner.example.net"}, domains
    assert match_domain("sub.ads.example.com", domains) == "ads.example.com"
    assert match_domain("clean.example.com", domains) is None
    print("ok dnsfilter parse+match")


def test_dnsfilter_api():
    app = _app()
    c = app.test_client()
    d = c.get("/api/dns/filter").get_json()
    assert "enabled" in d and "lists" in d and d["compiled_domains"] == 0
    assert len(d["lists"]) >= 1  # builtin defaults
    r = c.put("/api/dns/filter", json={
        "enabled": True,
        "lists": [{"name": "t", "url": "http://127.0.0.1:1/x", "enabled": True}]})
    assert r.status_code == 200
    # preview with empty compiled set -> not blocked
    r = c.get("/api/dns/filter/preview?domain=ads.example.com").get_json()
    assert r["blocked"] is False
    # apply with unreachable URL -> all enabled failed: fail closed, 400,
    # error recorded, not a crash (v7 #24 semantics)
    resp = c.post("/api/dns/filter/apply?update=1")
    assert resp.status_code == 400, resp.get_json()
    r = resp.get_json()
    assert r["total_domains"] == 0
    assert r["lists"][0]["error"]
    print("ok dnsfilter api")


def test_dns_query_log():
    app = _app()
    c = app.test_client()
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("Oct 14 15:30:01 dnsmasq[1]: query[A] ads.example.com from 192.168.1.10\n")
        f.write("Oct 14 15:30:02 dnsmasq[1]: query[AAAA] clean.example.com from 192.168.1.11\n")
        path = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".leases", delete=False) as f:
        f.write("9999999999 aa:bb:cc:dd:ee:ff 192.168.1.10 myphone *\n")
        leases = f.name
    old_log, old_leases = os.environ.get("OBX_DNSMASQ_LOG"), os.environ.get("OBX_DHCP_LEASES")
    os.environ["OBX_DNSMASQ_LOG"] = path
    os.environ["OBX_DHCP_LEASES"] = leases
    try:
        d = c.get("/api/dns/query-log?n=10").get_json()
        assert len(d["queries"]) == 2, d
        q = d["queries"][0]
        assert q["domain"] == "clean.example.com"  # newest first
        assert d["queries"][1]["hostname"] == "myphone"
        r = c.get("/api/dns/filter/records?n=10").get_json()
        assert r["records"] == []  # empty blocklist -> nothing blocked
    finally:
        for k, v in (("OBX_DNSMASQ_LOG", old_log), ("OBX_DHCP_LEASES", old_leases)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.unlink(path)
        os.unlink(leases)
    print("ok dns query log")


def test_dnstest_unit():
    from core.dnstest import _build_query, _parse_answers, _split_upstream, system_upstreams
    q = _build_query("example.com")
    assert len(q) > 12
    assert _split_upstream("8.8.8.8") == ("udp", "8.8.8.8", 53, "")
    assert _split_upstream("tls://1.1.1.1") == ("tls", "1.1.1.1", 853, "")
    s, h, p, path = _split_upstream("https://dns.google/dns-query")
    assert (s, h, p, path) == ("https", "dns.google", 443, "/dns-query")
    assert isinstance(system_upstreams(), list)
    # unsupported scheme -> clean error, no exception
    from core.dnstest import test_upstream
    r = test_upstream("gopher://x", "example.com")
    assert r["ok"] is False and "不支持" in r["error"]
    print("ok dnstest unit")


def test_dns_upstream_api_validation():
    c = _app().test_client()
    r = c.post("/api/dns/upstream-test", json={})
    assert r.status_code == 400
    r = c.post("/api/dns/trace", json={})
    assert r.status_code == 400
    d = c.get("/api/dns/wan").get_json()
    assert "upstreams" in d
    print("ok dns upstream api validation")


def test_traffic_aggregation():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    dbmod.record_traffic(conn, "2026-10-01", "c1", "p1", "h1", 100, 1000)
    dbmod.record_traffic(conn, "2026-10-01", "c2", "p1", "h2", 200, 2000)
    dbmod.record_traffic(conn, "2026-10-02", "c1", "p2", "h1", 50, 500)
    conn.close()
    m = c.get("/api/traffic/month?month=2026-10").get_json()
    # Month view zero-fills all days (1:1 with the original panel);
    # daily_avg divides by days in month, not days with traffic.
    assert len(m["days"]) == 31 and m["total"]["down"] == 3500
    assert m["daily_avg"]["down"] == 3500 // 31
    assert c.get("/api/traffic/month?month=xx").status_code == 400
    d = c.get("/api/traffic/day?day=2026-10-01").get_json()
    assert d["by_proxy"][0]["proxy"] == "p1" and d["by_proxy"][0]["down"] == 3000
    assert len(d["by_client"]) == 2
    dr = c.get("/api/traffic/drill?month=2026-10&dim=client").get_json()
    by_c = {r["client"]: r for r in dr["rows"]}
    assert by_c["c1"]["down"] == 1500 and by_c["c2"]["down"] == 2000
    assert c.get("/api/traffic/drill?dim=bogus").status_code == 400
    u = c.get("/api/traffic/usage").get_json()
    assert u["days"] == 2 and u["rows"] == 3
    print("ok traffic aggregation")


def test_latency_history():
    app = _app()
    c = app.test_client()
    conn = _dbconn(app)
    dbmod.record_latency(conn, "n1", True, 12.5)
    dbmod.record_latency(conn, "n1", False, None)
    conn.close()
    h = c.get("/api/latency/history").get_json()
    assert len(h["n1"]) == 2 and h["n1"][-1]["ok"] is False
    r = c.post("/api/latency/history/samples",
               json={"samples": [{"tag": "n2", "ok": True, "latency_ms": 30}]})
    assert r.get_json()["recorded"] == 1
    # sync with no kernel -> ok False but still returns history
    r = c.post("/api/latency/history/sync").get_json()
    assert "history" in r
    # prune keeps max 50
    conn = _dbconn(app)
    for _ in range(60):
        dbmod.record_latency(conn, "n3", True, 1.0)
    conn.close()
    h = c.get("/api/latency/history").get_json()
    assert len(h["n3"]) == 50
    print("ok latency history")


def test_site_latency():
    app = _app()
    c = app.test_client()
    r = c.post("/api/site-latency", json={"sites": [
        {"name": "g", "url": "https://www.google.com"},
        {"name": "", "url": ""}]})
    assert len(r.get_json()["sites"]) == 1
    d = c.get("/api/site-latency").get_json()
    assert d["sites"][0]["name"] == "g"
    h = c.get("/api/site-latency/history").get_json()
    assert h["checks"] == [] and len(h["sites"]) == 1
    print("ok site latency crud")


def main():
    test_dnsfilter_parse_and_match()
    test_dnsfilter_api()
    test_dns_query_log()
    test_dnstest_unit()
    test_dns_upstream_api_validation()
    test_traffic_aggregation()
    test_latency_history()
    test_site_latency()
    print("ALL BATCH3 TESTS PASSED")


if __name__ == "__main__":
    main()
