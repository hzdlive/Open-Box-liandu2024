"""Tests for route-test by measurement (v8 #34 对照）.

All network is stubbed: the probe, the resolver and the /connections
fetch are injected, so the suite never opens a socket.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import route_test as rt  # noqa: E402


DEPLOYED = {
    "dns": {
        "rules": [
            {"domain_suffix": ["example.org"], "server": "dns-direct"},
            {"rule_set": ["geosite-youtube"], "server": "dns-proxy"},
        ],
        "servers": [
            {"tag": "dns-direct", "address": "223.5.5.5"},
            {"tag": "dns-proxy", "address": "tcp://1.1.1.1",
             "detour": "所有-自动"},
        ],
        "final": "dns-direct",
    },
    "route": {
        "rules": [
            {"rule_set": ["geosite-youtube"],
             "outbound": "JPAC转甲骨文新加坡"},
            {"domain_suffix": ["example.org"], "outbound": "direct"},
        ],
        "final": "其他",
    },
    "outbounds": [
        {"tag": "JPAC转甲骨文新加坡", "type": "vless"},
        {"tag": "所有-自动", "type": "urltest"},
        {"tag": "其他", "type": "selector"},
    ],
    "inbounds": [{"type": "mixed", "tag": "mixed-in",
                  "listen": "127.0.0.1", "listen_port": 2080}],
}

GEOSITE = lambda tag: ([], ["youtube.com"]) if tag == "geosite-youtube" else ([], [])  # noqa: E731


def _probe_ok(calls):
    def probe(target, **kw):
        calls.append((target, kw))
        return ({"ok": True, "status": 200,
                 "headers": {"content-type": "text/html"}, "ms": 12},
                lambda: calls.append(("closed",)))
    return probe


def _conns(entries):
    def fetch():
        return list(entries)
    return fetch


def _base(**kw):
    d = {"deployed": DEPLOYED, "mixed_host": "127.0.0.1",
         "mixed_port": 2080, "mixed_tag": "mixed-in", "proxies": {},
         "flip_map": {}, "geosite_split": GEOSITE}
    d.update(kw)
    return d


def test_bad_target_and_method_are_400_before_config():
    status, body = rt.run_route_test({"target": "-oops"}, **_base())
    assert status == 400 and body["message"] == "target must be a domain or IP"
    status, body = rt.run_route_test({"target": ""}, **_base())
    assert status == 400
    status, body = rt.run_route_test(
        {"target": "a.test", "method": "POST"}, **_base())
    assert status == 400
    assert body["message"] == "method must be GET, HEAD, TCP or TLS"


def test_no_deployed_config_is_503():
    status, body = rt.run_route_test({"target": "a.test"},
                                     **_base(deployed=None))
    assert status == 503
    assert body["message"] == "还没有生成过配置（内核没启动过）"


def test_literal_skips_dns_and_defaults_to_port_80():
    calls = []
    status, body = rt.run_route_test(
        {"target": "1.1.1.1"}, **_base(probe_fn=_probe_ok(calls),
                                        connections_fn=_conns([])))
    assert status == 200
    assert body["dns"] == {"skipped": True}
    assert "resolve" not in body
    assert body["exit"]["url"] == "http://1.1.1.1/"
    assert calls[0][1]["port"] == 80
    assert calls[0][1]["secure"] is False
    assert calls[0][1]["connect_to"] == ""
    assert body["exit"]["ok"] is True


def test_domain_resolve_connect_to_and_dns_half():
    calls = []
    conns = _conns([{
        "metadata": {"host": "", "destinationIP": "1.2.3.4",
                     "destinationPort": 443, "type": "mixed/mixed-in"},
        "start": "2026-10-26T13:00:00+08:00",
        "chains": ["JPAC转甲骨文新加坡"],
        "rule": "rule_set=geosite-youtube => route(JPAC转甲骨文新加坡)",
        "rulePayload": ""}])
    status, body = rt.run_route_test(
        {"target": "  WWW.Youtube.COM  "},
        **_base(probe_fn=_probe_ok(calls), connections_fn=conns,
                resolve_fn=lambda t: (["1.2.3.4"], [], 5),
                proxies={"所有-自动": {"now": "JPAC转甲骨文新加坡"}}))
    assert status == 200
    assert body["target"] == "www.youtube.com"
    assert body["resolve"]["answers"] == ["1.2.3.4"]
    assert body["exit"]["connectTo"] == "1.2.3.4"
    assert calls[0][1]["connect_to"] == "1.2.3.4"
    assert calls[0][1]["port"] == 443
    assert calls[0][1]["secure"] is True
    # DNS half comes from the deployed config, not a rebuilt model.
    assert body["dns"]["ruleIndex"] == 1
    assert body["dns"]["server"]["tag"] == "dns-proxy"
    assert body["dns"]["viaProxy"] is True
    assert body["dns"]["runtimeChain"] == ["所有-自动", "JPAC转甲骨文新加坡"]
    assert body["dns"]["runtimeLeaf"] == "JPAC转甲骨文新加坡"
    # The kernel's own rule text attributes the owner; chains stay
    # leaf-first (no Mihomo-style reversal).
    assert body["exit"]["chains"] == ["JPAC转甲骨文新加坡"]
    assert body["exit"]["owner"] == {"kind": "node",
                                     "name": "JPAC转甲骨文新加坡"}


def test_probe_failure_still_200_with_exit_ok_false():
    def probe(target, **kw):
        return ({"ok": False, "status": None, "ms": 3,
                 "error": "inbound: refused"}, lambda: None)

    status, body = rt.run_route_test(
        {"target": "1.1.1.1"}, **_base(probe_fn=probe,
                                        connections_fn=_conns([])))
    assert status == 200
    assert body["exit"]["ok"] is False
    assert body["exit"]["error"] == "inbound: refused"
    assert body["exit"]["debug"]["connections"] == 0


def test_exit6_for_ipv6_answer():
    seen = []

    def probe(target, **kw):
        seen.append(kw["connect_to"])
        return ({"ok": True, "status": None, "ms": 1}, lambda: None)

    status, body = rt.run_route_test(
        {"target": "dual.test"},
        **_base(probe_fn=probe, connections_fn=_conns([]),
                resolve_fn=lambda t: (["1.2.3.4"], ["2001:db8::1"], 5)))
    assert status == 200
    assert "exit" in body and "exit6" in body
    assert seen == ["1.2.3.4", "2001:db8::1"]


def test_exit6_does_not_match_lingering_v4_flow():
    # Regression: the exit6 poll must not report a v4 flow left over
    # from the exit probe. The v6 flow appears only on the third
    # fetch; a name-based matcher would take the v4 flow at once.
    v4_flow = {"metadata": {"host": "", "destinationIP": "1.2.3.4",
                            "destinationPort": 443,
                            "type": "mixed/mixed-in"},
               "start": "2026-10-26T13:00:00+08:00",
               "chains": ["node-a"], "rule": "final", "rulePayload": ""}
    v6_flow = {"metadata": {"host": "", "destinationIP": "2001:db8::1",
                            "destinationPort": 443,
                            "type": "mixed/mixed-in"},
               "start": "2026-10-26T13:00:01+08:00",
               "chains": ["node-b"], "rule": "final", "rulePayload": ""}
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return [v4_flow] if calls["n"] < 3 else [v4_flow, v6_flow]

    def probe(target, **kw):
        return ({"ok": True, "status": None, "ms": 1}, lambda: None)

    status, body = rt.run_route_test(
        {"target": "dual.test"},
        **_base(probe_fn=probe, connections_fn=fetch,
                resolve_fn=lambda t: (["1.2.3.4"], ["2001:db8::1"], 5)))
    assert status == 200
    assert body["exit"]["destinationIP"] == "1.2.3.4"
    assert body["exit6"]["destinationIP"] == "2001:db8::1"
    assert body["exit6"]["chains"] == ["node-b"]


def _domain_flow(flow_id, host, dest_ip):
    return {"id": flow_id,
            "metadata": {"host": host, "destinationIP": dest_ip,
                         "destinationPort": 443,
                         "type": "mixed/mixed-in"},
            "start": "2026-10-26T13:00:00+08:00",
            "chains": ["JPAC转甲骨文新加坡"],
            "rule": "rule_set=geosite-youtube => route(JPAC转甲骨文新加坡)",
            "rulePayload": ""}


def test_domain_routed_flow_matches_by_host():
    # Regression: a domain-routed flow has destinationIP "" and only
    # the host names the target. Resolution succeeded, so match_ips
    # is set — the flow must still match, via the host fallback.
    flow = _domain_flow("new-id", "www.youtube.com", "")
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return [] if calls["n"] == 1 else [flow]

    status, body = rt.run_route_test(
        {"target": "www.youtube.com"},
        **_base(probe_fn=_probe_ok([]), connections_fn=fetch,
                resolve_fn=lambda t: (["1.2.3.4"], [], 5)))
    assert status == 200
    assert body["exit"]["chains"] == ["JPAC转甲骨文新加坡"]
    assert body["exit"]["destinationIP"] == ""
    assert body["exit"]["owner"] == {"kind": "node",
                                     "name": "JPAC转甲骨文新加坡"}


def test_host_fallback_ignores_baseline_flow():
    # The host fallback must not claim a flow that was already listed
    # before this probe started (the lingering-flow case, now with
    # domain routing instead of a v4 address).
    lingering = _domain_flow("old-id", "www.youtube.com", "")
    status, body = rt.run_route_test(
        {"target": "www.youtube.com"},
        **_base(probe_fn=_probe_ok([]),
                connections_fn=_conns([lingering]),
                resolve_fn=lambda t: (["1.2.3.4"], [], 5)))
    assert status == 200
    assert "chains" not in body["exit"]
    assert body["exit"]["debug"]["connections"] == 1


def test_host_fallback_rejects_wrong_address():
    # A flow whose destinationIP is present but outside match_ips is
    # a miss even when its host equals the target: the fallback only
    # applies to the empty-address shape.
    flow = _domain_flow("new-id", "www.youtube.com", "9.9.9.9")
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return [] if calls["n"] == 1 else [flow]

    status, body = rt.run_route_test(
        {"target": "www.youtube.com"},
        **_base(probe_fn=_probe_ok([]), connections_fn=fetch,
                resolve_fn=lambda t: (["1.2.3.4"], [], 5)))
    assert status == 200
    assert "chains" not in body["exit"]


def test_rule_text_parsing_and_final():
    conds, out = rt.parse_rule_text(
        "rule_set=[geosite-gfw geoip-google] => route(flip-11)")
    assert conds["rule_set"] == ["geosite-gfw", "geoip-google"]
    assert out == "flip-11"
    assert rt.parse_rule_text("final") == ({"final": True}, None)
    owner = rt.attribute_owner("final", DEPLOYED, {})
    assert owner == {"kind": "final", "name": "其他"}
    owner = rt.attribute_owner(
        "rule_set=geosite-youtube => route(JPAC转甲骨文新加坡)",
        DEPLOYED, {"flip-9": "国外"})
    assert owner == {"kind": "node", "name": "JPAC转甲骨文新加坡"}
    # A flip outbound attributes to its site set via the flip map.
    deployed = {**DEPLOYED, "route": {"rules": [
        {"rule_set": ["geosite-youtube"], "outbound": "flip-9"}],
        "final": "其他"}}
    owner = rt.attribute_owner(
        "rule_set=geosite-youtube => route(flip-9)", deployed,
        {"flip-9": "国外"})
    assert owner == {"kind": "siteset", "name": "国外"}


def test_endpoint_400_before_config_and_503_without_deployed(
        monkeypatch, tmp_path):
    import sqlite3
    import tempfile

    from panel import app as appmod
    from panel import db as dbmod

    dbfile = tempfile.mktemp(suffix=".db")
    c = sqlite3.connect(dbfile)
    dbmod.init_db(c)
    c.close()
    client = appmod.create_app(dbfile).test_client()
    r = client.post("/api/openbox/route-test", json={"target": "-oops"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "target must be a domain or IP"
    # No deployed config in this workdir -> 503, not a reason to build.
    monkeypatch.setenv("OPENBOX_WORKDIR", str(tmp_path))
    r = client.post("/api/openbox/route-test", json={"target": "a.test"})
    assert r.status_code == 503
    assert r.get_json()["message"] == "还没有生成过配置（内核没启动过）"


def test_normalize_method():
    assert rt.normalize_method(None) == "GET"
    assert rt.normalize_method("tls") == "TLS"
    assert rt.normalize_method(" head ") == "HEAD"
    try:
        rt.normalize_method("POST")
    except ValueError as e:
        assert str(e) == "method must be GET, HEAD, TCP or TLS"
    else:
        raise AssertionError("expected ValueError")
