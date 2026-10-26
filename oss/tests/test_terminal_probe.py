"""Tests for the terminal probe table (v8 #35 对照）.

No real namespace, no real commands: the runner and the file checks
are injected.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import terminal_probe as tp  # noqa: E402

CT_LINE = ("ipv4 2 tcp 6 431999 ESTABLISHED src=192.168.1.50 "
           "dst=1.2.3.4 sport=40000 dport=443 src=1.2.3.4 "
           "dst=192.168.1.50 sport=443 dport=40000 [ASSURED] mark=0 "
           "use=1")


def test_parse_conntrack():
    flows = tp.parse_conntrack(CT_LINE + "\n")
    assert len(flows) == 1
    f = flows[0]
    assert f["proto"] == "tcp" and f["state"] == "ESTABLISHED"
    assert f["orig"] == {"src": "192.168.1.50", "dst": "1.2.3.4",
                         "sport": 40000, "dport": 443}
    assert f["reply"]["src"] == "1.2.3.4"
    assert f["mark"] == 0


def test_parse_leases():
    lease = tp.parse_lease_udhcpc(
        "LEASE ip=192.168.1.50 mask=24 router=192.168.1.1 "
        "dns=192.168.1.1 8.8.8.8\n")
    assert lease == {"ip": "192.168.1.50", "mask": 24,
                     "gateway": "192.168.1.1",
                     "dns": ["192.168.1.1", "8.8.8.8"]}
    assert tp.parse_lease_udhcpc("nothing here") is None
    lease = tp.parse_lease_dhcpcd(
        "ip_address=192.168.1.50\nsubnet_mask=255.255.255.0\n"
        "routers=192.168.1.1\ndomain_name_servers='192.168.1.1'\n")
    assert lease["ip"] == "192.168.1.50" and lease["mask"] == 24
    assert lease["gateway"] == "192.168.1.1"
    assert lease["dns"] == ["192.168.1.1"]


def test_parse_route_get():
    r = tp.parse_route_get("1.2.3.4 via 192.168.1.1 dev eth0 src "
                           "192.168.1.50 uid 0\n")
    assert r["dev"] == "eth0" and r["via"] == "192.168.1.1"
    assert tp.parse_route_get("") is None


def _fake_env(*, lan=True, bridge=True, conntrack=True, dhcp="dhcpcd",
              uid=0, netns_ok=True, veth_ok=True):
    def run(argv, timeout):
        if argv[:2] == ["ip", "netns"]:
            return (0, "", "") if netns_ok else (1, "", "no netns")
        if argv[0] == "ubus":
            return 1, "", ""
        if argv == ["ip", "-4", "-o", "addr", "show", "dev", "br-lan"]:
            return (0, "2: br-lan inet 192.168.1.1/24 brd x scope "
                       "global br-lan\n", "") if lan else (1, "", "")
        if argv[0] == "modprobe":
            return (0, "", "") if veth_ok else (1, "", "")
        if argv[0] == "which":
            return (0, f"/usr/sbin/{argv[1]}\n", "") \
                if dhcp == argv[1] else (1, "", "")
        return 1, "", ""
    paths = {"/sys/module/veth": veth_ok,
             "/proc/net/nf_conntrack": conntrack}
    if lan and bridge:
        paths["/sys/class/net/br-lan/bridge"] = True

    def exists(path):
        return paths.get(path, False)
    return run, exists


def test_capability_all_and_each_missing():
    run, exists = _fake_env()
    cap = tp.probe_capability(run, exists, uid=0)
    assert cap["ok"] is True and cap["missing"] == []
    assert cap["lan"] == {"device": "br-lan", "address": "192.168.1.1"}
    assert cap["dhcp_client"] == "dhcpcd"
    run, exists = _fake_env(uid=1000)
    assert "root" in tp.probe_capability(run, exists, uid=1000)["missing"]
    run, exists = _fake_env(netns_ok=False)
    assert "netns" in tp.probe_capability(run, exists)["missing"]
    run, exists = _fake_env(veth_ok=False)
    assert "veth" in tp.probe_capability(run, exists)["missing"]
    run, exists = _fake_env(lan=False)
    missing = tp.probe_capability(run, exists)["missing"]
    assert missing == ["lan"]
    run, exists = _fake_env(bridge=False)
    assert "bridge" in tp.probe_capability(run, exists)["missing"]
    run, exists = _fake_env(conntrack=False)
    assert "conntrack" in tp.probe_capability(run, exists)["missing"]
    run, exists = _fake_env(dhcp=None)
    assert "dhcp" in tp.probe_capability(run, exists)["missing"]


def test_classify_verdicts():
    base = {"local_addresses": ["192.168.1.1"], "tun_device": "tun0",
            "tun_mark": None, "route": None, "kernel_conn": False,
            "device_addresses": []}
    assert tp.classify_entry(flow=None, **base)["reason"] == "no-conntrack"
    flow = {"orig": {"src": "192.168.1.50", "dst": "1.2.3.4",
                     "sport": 40000, "dport": 443},
            "reply": {"src": "192.168.1.1", "dst": "192.168.1.50",
                      "sport": 8080, "dport": 40000},
            "mark": None, "line": "x"}
    r = tp.classify_entry(flow=flow, **base)
    assert (r["kind"], r["via"], r["redirectPort"]) == (
        "kernel", "redirect", 8080)
    flow2 = {"orig": {"src": "192.168.1.50", "dst": "1.2.3.4",
                      "sport": 40000, "dport": 443},
             "reply": {"src": "1.2.3.4", "dst": "192.168.1.50",
                       "sport": 443, "dport": 40000},
             "mark": 8227, "line": "x"}
    r = tp.classify_entry(flow=flow2, tun_mark=8227, **{
        k: v for k, v in base.items() if k != "tun_mark"})
    assert (r["kind"], r["via"]) == ("kernel", "tun")
    r = tp.classify_entry(flow=flow2, kernel_conn=True, **{
        k: v for k, v in base.items() if k != "kernel_conn"})
    assert (r["kind"], r["via"]) == ("kernel", "connection-table")
    flow3 = {"orig": {"src": "192.168.1.50", "dst": "1.2.3.4",
                      "sport": 40000, "dport": 443},
             "reply": {"src": "9.9.9.9", "dst": "192.168.1.50",
                       "sport": 443, "dport": 40000},
             "mark": None, "line": "x"}
    r = tp.classify_entry(flow=flow3, **base)
    assert (r["kind"], r["reason"]) == ("unknown", "dnat-elsewhere")
    r = tp.classify_entry(flow=flow2, **base)
    assert (r["kind"], r["reason"]) == ("unknown", "no-route")
    noroute = {k: v for k, v in base.items() if k != "route"}
    r = tp.classify_entry(flow=flow2, route={"dev": "tun0", "via": "",
                                              "line": ""}, **noroute)
    assert (r["kind"], r["reason"]) == ("unknown", "route-tun")
    r = tp.classify_entry(flow=flow2, route={"dev": "eth0",
                                              "via": "192.168.1.1",
                                              "line": ""}, **noroute)
    assert (r["kind"], r["via"]) == ("bypass", "forward")


def test_dns_evidence_and_forward():
    flows = tp.parse_conntrack(
        "ipv4 2 udp 17 30 src=192.168.1.50 dst=192.168.1.1 sport=50000 "
        "dport=53 src=192.168.1.1 dst=192.168.1.50 sport=53 "
        "dport=50000 [ASSURED]\n")
    ev = tp.dns_evidence(flows, src="192.168.1.50",
                         server="192.168.1.1")
    assert ev["flows"] == 1 and ev["hijacked"] is False
    assert ev["answeredBy"] == "192.168.1.1"
    fwd = tp.dnsmasq_forward_for(
        "server=/google.com/1.1.1.1\nserver=/example.org/8.8.8.8\n",
        "www.google.com")
    assert fwd == {"forward": "kernel", "suffix": "google.com",
                   "to": "1.1.1.1"}
    assert tp.dnsmasq_forward_for("server=/google.com/1.1.1.1\n",
                                  "other.com") is None


def test_tun_settings_defaults():
    s = tp.tun_settings(None)
    assert s["device"] == "tun0" and s["autoRedirect"] is False
    # Our build stamps no fwmark: the default is None, not 8227.
    assert s["inputMark"] is None
    s = tp.tun_settings({"inbounds": [
        {"type": "tun", "interface_name": "tun9",
         "auto_redirect": True, "auto_redirect_input_mark": 1234}]})
    assert s["device"] == "tun9" and s["inputMark"] == 1234
    assert s["autoRedirect"] is True


def test_bypass_set_has():
    def run(argv, timeout):
        if argv[:2] == ["nft", "list"]:
            return 1, "", "no such set"
        return 1, "", ""
    assert tp.bypass_set_has(run, "1.2.3.4") == {"set": None,
                                                 "hit": False}

    def run2(argv, timeout):
        return 0, "set contents", ""
    assert tp.bypass_set_has(run2, "1.2.3.4") == {
        "set": "inet4_route_exclude_address_set", "hit": True}
