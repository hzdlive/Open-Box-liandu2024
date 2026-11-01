"""v0.1.343 terminal IPv6 supplementary rules.

Original behavior fixed: a MAC terminal's IPv6 connections fell through to
the target policy because only its IPv4 rule existed. The supplement is
generated only when neighbor evidence uniquely confirms the MAC, and it is
exactly the intersection of IPv6 sources with that MAC: no IPv4 of the same
MAC, no subnet inference, conflicted addresses dropped at collection.
"""

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core import arp  # noqa: E402
from core.models import AppConfig, TerminalPolicy, TerminalRule  # noqa: E402
from core.singbox import build_route_rules  # noqa: E402

MAC_A = "aa:bb:cc:dd:ee:01"
MAC_B = "aa:bb:cc:dd:ee:02"
V4_A = "192.168.1.10"
V6_FIXED = "2001:db8::10"
V6_TEMP = "2001:db8::11"
V6_B = "2001:db8::20"
V6_SHARED = "2001:db8::99"


def _rules_with_source(rules, outbound):
    return [r for r in rules
            if r.get("outbound") == outbound and "source_ip_cidr" in r]


def test_supplement_fixed_and_temporary_v6_no_v4():
    table = {V4_A: MAC_A, V6_FIXED: MAC_A, V6_TEMP: MAC_A}
    assert arp.expand_terminal_supplement_v6([MAC_A], table) == [
        V6_FIXED, V6_TEMP]


def test_supplement_v4_only_mac_is_empty():
    assert arp.expand_terminal_supplement_v6([MAC_A], {V4_A: MAC_A}) == []


def test_supplement_unknown_mac_is_empty():
    assert arp.expand_terminal_supplement_v6(
        [MAC_A], {V6_B: MAC_B}) == []


def test_supplement_ignores_literal_idents():
    table = {V6_FIXED: MAC_A}
    assert arp.expand_terminal_supplement_v6(
        [MAC_A, V6_B, V4_A, "2001:db8::/64"], table) == [V6_FIXED]


def test_supplement_dedups_and_keeps_order():
    table = {V6_FIXED: MAC_A, V6_TEMP: MAC_A}
    assert arp.expand_terminal_supplement_v6(
        [MAC_A, MAC_A], table) == [V6_FIXED, V6_TEMP]


def test_ipv6_neigh_table_filters_states_and_conflicts(monkeypatch):
    out = (
        f"{V6_FIXED} dev br-lan lladdr {MAC_A} REACHABLE\n"
        f"{V6_TEMP} dev br-lan lladdr {MAC_A} STALE\n"
        f"{V6_B} dev br-lan lladdr {MAC_B} FAILED\n"
        f"{V6_SHARED} dev br-lan lladdr {MAC_A} REACHABLE\n"
        f"{V6_SHARED} dev br-lan lladdr {MAC_B} REACHABLE\n"
        f"{V4_A} dev br-lan lladdr {MAC_A} REACHABLE\n"
    )
    monkeypatch.setattr(
        arp.subprocess, "run",
        lambda *a, **k: mock.Mock(stdout=out))
    table = arp.ipv6_neigh_table()
    assert table == {V6_FIXED: MAC_A, V6_TEMP: MAC_A}
    # FAILED excluded, shared address dropped for both claimants,
    # IPv4 line (from a combined listing) excluded.


def test_direct_terminal_gets_main_plus_supplement(monkeypatch):
    monkeypatch.setattr(arp, "arp_table", lambda: {V4_A: MAC_A})
    monkeypatch.setattr(
        arp, "ipv6_neigh_table",
        lambda: {V6_FIXED: MAC_A, V6_TEMP: MAC_A})
    c = AppConfig()
    c.terminals = [TerminalPolicy(ident=MAC_A, policy="direct")]
    rules, _, _ = build_route_rules(c)
    direct = _rules_with_source(rules, "direct")
    assert [V4_A] in [r["source_ip_cidr"] for r in direct]
    assert [V6_FIXED, V6_TEMP] in [r["source_ip_cidr"] for r in direct]


def test_direct_terminal_v6_only_gets_supplement_alone(monkeypatch):
    monkeypatch.setattr(arp, "arp_table", lambda: {})
    monkeypatch.setattr(arp, "ipv6_neigh_table", lambda: {V6_FIXED: MAC_A})
    c = AppConfig()
    c.terminals = [TerminalPolicy(ident=MAC_A, policy="direct")]
    rules, _, _ = build_route_rules(c)
    direct = _rules_with_source(rules, "direct")
    assert [r["source_ip_cidr"] for r in direct] == [[V6_FIXED]]


def test_no_supplement_when_no_v6(monkeypatch):
    monkeypatch.setattr(arp, "arp_table", lambda: {V4_A: MAC_A})
    monkeypatch.setattr(arp, "ipv6_neigh_table", lambda: {})
    c = AppConfig()
    c.terminals = [TerminalPolicy(ident=MAC_A, policy="direct")]
    rules, _, _ = build_route_rules(c)
    direct = _rules_with_source(rules, "direct")
    assert [r["source_ip_cidr"] for r in direct] == [[V4_A]]


def test_proxy_mac_rule_gets_supplement(monkeypatch):
    monkeypatch.setattr(arp, "arp_table", lambda: {V4_A: MAC_A})
    monkeypatch.setattr(arp, "ipv6_neigh_table", lambda: {V6_FIXED: MAC_A})
    c = AppConfig()
    c.terminal_rules = [TerminalRule(match_by="mac", targets=[MAC_A],
                                     policy="proxy", outbound="ALIHK")]
    rules, _, _ = build_route_rules(c)
    ali = _rules_with_source(rules, "ALIHK")
    assert [V4_A] in [r["source_ip_cidr"] for r in ali]
    assert [V6_FIXED] in [r["source_ip_cidr"] for r in ali]


def test_proxy_ip_rule_gets_no_supplement(monkeypatch):
    monkeypatch.setattr(arp, "arp_table", lambda: {V4_A: MAC_A})
    monkeypatch.setattr(arp, "ipv6_neigh_table", lambda: {V6_FIXED: MAC_A})
    c = AppConfig()
    c.terminal_rules = [TerminalRule(match_by="ip", targets=[V4_A],
                                     policy="proxy", outbound="ALIHK")]
    rules, _, _ = build_route_rules(c)
    ali = _rules_with_source(rules, "ALIHK")
    assert [r["source_ip_cidr"] for r in ali] == [["192.168.1.10/32"]]
