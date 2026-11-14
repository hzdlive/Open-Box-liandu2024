"""Config alignment with the closed-source original (2026-11-08).

Evidence: golden corpus (core v0.1.337, 225 cases) + black-box captures
against the original core binary (v0.1.331, /opt/openbox-orig) + live
original config inspection. Each test names the evidence it pins.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core import dnsfilter as dfmod  # noqa: E402
from core import route_oracle as orc  # noqa: E402
from core.models import AppConfig, Group, Node, SiteSet  # noqa: E402
from core.singbox import build_config, build_outbounds, build_route_rules  # noqa: E402


def _node(tag):
    return Node(tag=tag, protocol="vless", server="example.com",
                server_port=443, params={"uuid": "x"})


def _cfg(nodes=("n1", "n2"), groups=(), sites=(), blocked=()):
    c = AppConfig()
    c.nodes = [_node(t) for t in nodes]
    c.groups = list(groups)
    c.site_sets = list(sites)
    c.blocked_domains = list(blocked)
    return c


def _shards(c):
    """Pretend the apply flow wrote the DNS-filter rule-sets."""
    c._dns_filter_rulesets = [
        {"tag": "dns-filter-anti-ad-block", "path": "/tmp/df/block.json"},
        {"tag": "dns-filter-anti-ad-allow", "path": "/tmp/df/allow.json"},
    ]
    return c


def test_failover_selector_interrupts_existing_connections():
    # 原版 failover selector 带 interrupt_exist_connections=true（金语料
    # 88/88 个 failover 组）；此前我方没有。
    g = Group(name="FO", type="failover", members=["n1", "n2"], lanes=[
        {"name": "主用", "members": ["n1"]},
        {"name": "备用", "members": ["n2"]},
    ])
    obs = build_outbounds(_cfg(groups=[g]))
    fo = next(o for o in obs if o.get("tag") == "FO")
    assert fo["type"] == "selector"
    assert fo["outbounds"] == ["n1", "n2"]
    assert fo["default"] == "n1"
    assert fo["interrupt_exist_connections"] is True


def test_dns_strategy_and_reverse_mapping():
    # 原版 dns 38/38：strategy=ipv4_only、reverse_mapping=true、
    # fakeip 只有 inet4 段（34/34）。
    c = _cfg()
    c.dns.enable_fakeip = True
    cfg = build_config(c)
    dns = cfg["dns"]
    assert dns["strategy"] == "ipv4_only"
    assert dns["reverse_mapping"] is True
    fakeip = next(s for s in dns["servers"] if s["tag"] == "dns-fakeip")
    assert fakeip["inet4_range"] == "198.19.0.0/16"
    assert "inet6_range" not in fakeip


def test_inbounds_panel_in_and_dns_in():
    # 原版入站（金语料 38/38）：tun-in、panel-in（mixed 127.0.0.1:7891）、
    # dns-in（direct 0.0.0.0:7853）；此前我方是 mixed-in:2080，无 dns-in。
    cfg = build_config(_cfg())
    inb = {i["tag"]: i for i in cfg["inbounds"]}
    assert inb["panel-in"]["type"] == "mixed"
    assert inb["panel-in"]["listen"] == "127.0.0.1"
    assert inb["panel-in"]["listen_port"] == 7891
    assert inb["dns-in"]["type"] == "direct"
    assert inb["dns-in"]["listen"] == "0.0.0.0"
    assert inb["dns-in"]["listen_port"] == 7853
    assert "mixed-in" not in inb


def test_route_rule_order_hijack_dns_twice():
    # 原版开头：[0] logical bypass → [1] sniff → [2] hijack-dns
    # （protocol=dns）→ [3] hijack-dns（inbound=dns-in）；此前只有一条。
    # 重排在 build_config 里做（build_route_rules 只产原始规则表）。
    rules = build_config(_cfg())["route"]["rules"]
    assert rules[1] == {"action": "sniff"}
    assert rules[2] == {"protocol": "dns", "action": "hijack-dns"}
    assert rules[3] == {"inbound": ["dns-in"], "action": "hijack-dns"}


def test_loadbalance_emits_real_loadbalance_outbound():
    # 真负载均衡（2026-11-14，用户已批）：loadbalance 组发内核原生
    # loadbalance 出站（v0.1.384+，轮询），不再归一化为 selector。
    # interval 取组的 interval_s（面板默认 120s），url 取全局测速地址。
    g = Group(name="LB", type="loadbalance", members=["n1", "n2"],
              interval_s=120)
    obs = build_outbounds(_cfg(groups=[g]))
    lb = next(o for o in obs if o.get("tag") == "LB")
    assert lb["type"] == "loadbalance"
    assert lb["outbounds"] == ["n1", "n2"]
    assert lb["interval"] == "120s"
    assert lb["url"] == "http://www.gstatic.com/generate_204"
    assert "default" not in lb


def test_siteset_reject_and_quic_use_action_reject():
    # 原版拒绝用 action=reject（金语料 1260 条），不用 outbound=block；
    # 此前站点集 reject 与 QUIC 拦截都走 outbound=block。
    s = SiteSet(name="rej", group="所有-自动", action="reject",
                domain_suffix=["blocked.example.com"])
    p = SiteSet(name="px", group="所有-自动", action="proxy",
                domain_suffix=["proxy.example.com"])
    rules, _, _ = build_route_rules(_cfg(sites=[s, p]))
    rej = [r for r in rules
           if r.get("domain_suffix") == ["blocked.example.com"]]
    assert len(rej) == 1
    assert rej[0].get("action") == "reject"
    assert "outbound" not in rej[0]
    quic = [r for r in rules if r.get("network") == "udp"
            and r.get("port") == 443]
    assert quic, "proxy site set must emit a QUIC reject rule"
    assert all(r.get("action") == "reject" for r in quic)
    assert all("outbound" not in r for r in quic)


def test_content_filter_dns_rules_and_declarations():
    # 原版形状：NOERROR（压 HTTPS/SVCB）打头，之后每分片一条 NXDOMAIN
    # 逻辑规则（命中拦截名单且不在放行名单）；规则集在 route.rule_set
    # 声明；路由层没有任何规则指向 block 出站。
    c = _shards(_cfg(blocked=["ads.example.com", "trk.example.org"]))
    cfg = build_config(c)
    dns_rules = cfg["dns"]["rules"]
    assert dns_rules[0] == {"action": "predefined",
                            "query_type": ["HTTPS", "SVCB"],
                            "rcode": "NOERROR"}
    nx = dns_rules[1]
    assert nx["action"] == "predefined" and nx["rcode"] == "NXDOMAIN"
    assert nx["mode"] == "and" and nx["type"] == "logical"
    assert nx["rules"] == [
        {"rule_set": ["dns-filter-anti-ad-block"]},
        {"invert": True, "rule_set": ["dns-filter-anti-ad-allow"]},
    ]
    decls = {r["tag"]: r for r in cfg["route"]["rule_set"]}
    assert decls["dns-filter-anti-ad-block"]["type"] == "local"
    assert decls["dns-filter-anti-ad-block"]["format"] == "source"
    assert decls["dns-filter-anti-ad-allow"]["type"] == "local"
    assert not any(r.get("outbound") == "block"
                   for r in cfg["route"]["rules"])


def test_content_filter_fallback_route_rule_without_rulesets():
    # 未传入规则集声明时（预览/干跑/旧调用方）回退到旧的路由层规则，
    # 拦截不断。
    rules, _, _ = build_route_rules(_cfg(blocked=["a.example.com"]))
    cf = [r for r in rules if r.get("outbound") == "block"]
    assert len(cf) == 1
    assert cf[0]["domain_suffix"] == ["a.example.com"]


def test_dnsfilter_write_kernel_rulesets(tmp_path, monkeypatch):
    monkeypatch.setattr(dfmod, "KERNEL_SHARD_SIZE", 2)
    entries = dfmod.write_kernel_rulesets(
        str(tmp_path), ["b.example.com", "a.example.com", "c.example.com",
                        "d.example.com", "e.example.com"])
    assert [e["tag"] for e in entries] == [
        "dns-filter-anti-ad-block", "dns-filter-anti-ad-block-2",
        "dns-filter-anti-ad-block-3", "dns-filter-anti-ad-allow"]
    for e in entries:
        data = json.loads(Path(e["path"]).read_text())
        assert data["version"] == 3
        assert data["rules"][0]["domain_suffix"]
    allow = json.loads(Path(entries[-1]["path"]).read_text())
    assert allow["rules"][0]["domain_suffix"] == [dfmod.ALLOW_SENTINEL]
    first = json.loads(Path(entries[0]["path"]).read_text())
    assert first["rules"][0]["domain_suffix"] == ["a.example.com",
                                                  "b.example.com"]
    # 第二次写内容不变：文件 mtime 不动。
    mtimes = {e["path"]: Path(e["path"]).stat().st_mtime for e in entries}
    dfmod.write_kernel_rulesets(str(tmp_path), ["e.example.com",
                                                "d.example.com",
                                                "c.example.com",
                                                "b.example.com",
                                                "a.example.com"])
    assert {e["path"]: Path(e["path"]).stat().st_mtime
            for e in entries} == mtimes


def test_oracle_dns_block(monkeypatch):
    # 预言机：DNS 层命中 NXDOMAIN 时直接报内容过滤拦截，不再走路由；
    # 未命中名单的域名照常走站点集。
    monkeypatch.setattr(orc, "_resolve_domain", lambda *a: [])
    c = _shards(_cfg(
        sites=[SiteSet(name="g", group="所有-自动", action="proxy",
                       domain_suffix=["example.com"])],
        blocked=["ads.example.com"]))
    r = orc.predict(c, "www.ads.example.com")
    assert r["matched"]["source"] == "content"
    assert r["matched"]["target"] == "block"
    assert r["matched"]["dns_rule_index"] == 1
    assert r["final_outbound"] == "reject"
    r = orc.predict(c, "www.example.com")
    assert r["matched"]["source"] == "siteset"


def test_dns_rules_carry_no_ip_matchers():
    # sing-box 1.14：DNS 规则表含 query_type 规则时，IP 型匹配
    # （geoip 规则集、ip_cidr、port）直接 FATAL；原版 2726 条 DNS
    # 规则里 geoip/ip_cidr 均为 0。geoip 前置规则不发 DNS 伴生规则；
    # 站点集的 DNS 规则只抄域名型匹配。
    c = _cfg(sites=[SiteSet(name="mix", group="所有-自动", action="proxy",
                            domain_suffix=["example.com"],
                            ip_cidr=["10.0.0.0/8"],
                            rule_sets=["geoip-cn", "geosite-google"])])
    c.front_rules = [
        {"rtype": "geoip", "domain": "google", "target": "direct",
         "enabled": True},
        {"rtype": "geosite", "domain": "google", "target": "direct",
         "enabled": True},
    ]
    _, dns_rules, _ = build_route_rules(c)
    assert not any("ip_cidr" in r for r in dns_rules)
    assert not any("port" in r for r in dns_rules)
    assert not any(str(t).startswith("geoip-")
                   for r in dns_rules for t in (r.get("rule_set") or []))
    # geosite 伴生规则还在，geoip 的不在。
    assert any(r.get("rule_set") == ["geosite-google"] for r in dns_rules)
    assert not any(r.get("rule_set") == ["geoip-google"] for r in dns_rules)
    # 站点集的 DNS 规则保留 domain_suffix，丢掉 ip_cidr 与 geoip-cn。
    mix = [r for r in dns_rules if r.get("domain_suffix") == ["example.com"]]
    assert mix and "ip_cidr" not in mix[0]
    assert mix[0].get("rule_set") == ["geosite-google"]


def test_tls_block_drops_unknown_utls_fingerprint():
    # 订阅/导入带进来的哈希串指纹原样发出会让整份配置校验失败；
    # 未知值丢 utls 段（等同旧配置里该节点无 utls），合法名照发。
    from core.singbox import _tls_block
    h = "5343bfcb1c5db62de169584dd7ae238dc9a8f2659283f1ee99b06d744c644806"
    out = _tls_block({"tls": {"server_name": "x.example", "insecure": True,
                              "fingerprint": h}})
    assert "utls" not in out
    assert out["server_name"] == "x.example" and out["insecure"] is True
    out = _tls_block({"tls": {"fingerprint": "chrome"}})
    assert out["utls"] == {"enabled": True, "fingerprint": "chrome"}
    out = _tls_block({"tls": {"utls": {"fingerprint": h}}})
    assert "utls" not in out
    out = _tls_block({"tls": {"utls": {"fingerprint": "firefox"}}})
    assert out["utls"]["fingerprint"] == "firefox"


def test_anytls_idle_durations_get_seconds_unit():
    # 订阅链接里时长是裸数字（=30），sing-box 只要 Go 时长串；
    # 裸数字按秒补 s，已带单位的原样。
    from core.singbox import _duration_str, node_to_outbound
    assert _duration_str(30) == "30s"
    assert _duration_str("30") == "30s"
    assert _duration_str("30s") == "30s"
    assert _duration_str("1m30s") == "1m30s"
    n = Node(tag="a", protocol="anytls", server="example.com",
             server_port=443,
             params={"password": "p",
                     "idle_session_check_interval": "30",
                     "idle_session_timeout": 45,
                     "min_idle_session": 2})
    ob = node_to_outbound(n)
    assert ob["idle_session_check_interval"] == "30s"
    assert ob["idle_session_timeout"] == "45s"
    assert ob["min_idle_session"] == 2
