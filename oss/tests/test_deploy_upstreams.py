"""Tests for the deploy pipeline's dns_upstream_routes table (v8 #33).

The table records, per proxy DNS upstream, the outbound the routing
oracle picks for it. Record-only: the pipeline never rewrites detours
from these rows (see core/deploy.py).
"""

import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import deploy as deploy_mod  # noqa: E402
from core.models import AppConfig, DnsConfig  # noqa: E402
from panel import db as dbmod  # noqa: E402


def _cfg(proxy_dns):
    c = AppConfig()
    c.dns = DnsConfig(proxy_dns=proxy_dns)
    return c


def test_parse_proxy_upstreams():
    rows = deploy_mod.parse_proxy_upstreams(
        "tcp://1.1.1.1, 1.0.0.1, tls://8.8.8.8:8853, "
        "https://dns.google, tcp://1.1.1.1, 上游 DNS 1.2.3.4")
    assert rows == [
        {"server": "1.1.1.1", "port": 53, "protocol": "tcp", "wan": False},
        {"server": "1.0.0.1", "port": 53, "protocol": "udp", "wan": False},
        {"server": "8.8.8.8", "port": 8853, "protocol": "tls", "wan": False},
        {"server": "dns.google", "port": 443, "protocol": "https",
         "wan": False},
        # tcp://1.1.1.1 deduped; label stripped, bare -> udp/53
        {"server": "1.2.3.4", "port": 53, "protocol": "udp", "wan": False},
    ]
    assert deploy_mod.parse_proxy_upstreams("wan") == [
        {"server": "wan", "port": 53, "protocol": "udp", "wan": True}]
    assert deploy_mod.parse_proxy_upstreams("") == []
    assert deploy_mod.parse_proxy_upstreams("dhcp://") == [
        {"server": "dhcp://", "port": 53, "protocol": "dhcp", "wan": True}]


def _stub_predict(calls):
    def predict(server, port, network):
        calls.append((server, port, network))
        return {
            "matched": {"action": "", "owner": {"kind": "siteset",
                                               "name": "国外"},
                        "rule_index": 40},
            "final_outbound": "node-a",
            "chain": ["flip-11", "所有-自动", "node-a"],
            "assumptions": [],
        }
    return predict


def test_dns_upstream_routes_shapes():
    calls = []
    rows = deploy_mod.dns_upstream_routes(
        _cfg("tcp://1.1.1.1, wan"), proxies={},
        predict_fn=_stub_predict(calls))
    assert calls == [("1.1.1.1", 53, "tcp")]
    assert rows[0]["outbound"] == "node-a"
    assert rows[0]["reject"] is False
    assert rows[0]["owner"] == {"kind": "siteset", "name": "国外"}
    assert rows[0]["chain"] == ["flip-11", "所有-自动", "node-a"]
    assert rows[0]["ruleIndex"] == 40
    assert rows[1]["wan"] is True and rows[1]["outbound"] == "direct"
    assert rows[1]["ruleIndex"] is None


def test_dns_upstream_routes_reject_and_error():
    def predict(server, port, network):
        if server == "9.9.9.9":
            return {"matched": {"action": "reject", "owner": None,
                                "rule_index": 3},
                    "final_outbound": "reject", "chain": ["reject"],
                    "assumptions": []}
        raise ValueError("boom")

    rows = deploy_mod.dns_upstream_routes(
        _cfg("udp://9.9.9.9, tcp://bad host"), proxies={},
        predict_fn=predict)
    assert rows[0]["reject"] is True and rows[0]["outbound"] == ""
    assert rows[1]["error"] == "boom"


def _pipeline_harness():
    import importlib.util
    path = os.path.join(os.path.dirname(__file__),
                        "test_deploy_pipeline.py")
    spec = importlib.util.spec_from_file_location("test_deploy_pipeline",
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FakeManager, mod._fresh_db, mod._conn


def test_pipeline_includes_rows_and_survives_trace_failure():
    FakeManager, _fresh_db, _conn = _pipeline_harness()

    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager()
    result = deploy_mod.run_deploy(
        conn, m,
        hooks={"verify_start": lambda manager, before: {"state": "running"},
               "upstream_proxies": {},
               "upstream_predict": _stub_predict([])})
    assert result["ok"] is True
    rows = result["dns_upstream_routes"]
    assert rows and rows[0]["outbound"] == "node-a"

    # A predict function that always raises still yields error rows,
    # never a failed deploy.
    conn2 = _conn(_fresh_db())
    m2 = FakeManager()

    def _boom(server, port, network):
        raise RuntimeError("oracle down")

    result2 = deploy_mod.run_deploy(
        conn2, m2,
        hooks={"verify_start": lambda manager, before: {"state": "running"},
               "upstream_proxies": {},
               "upstream_predict": _boom})
    assert result2["ok"] is True
    assert result2["dns_upstream_routes"][0]["error"] == "oracle down"
