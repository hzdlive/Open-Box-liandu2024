"""Terminal probe: the network namespace a terminal test dials from.

"Terminal test" answers the question the panel cannot answer by
reading configuration: *if a device on the LAN opened this site right
now, which path would the packet take?* The only honest way to answer
is to be that device — so this module builds one: a network namespace,
a veth pair with one end inside it, a DHCP lease from the LAN, and a
child process that dials from inside the namespace.

The verdict comes from four pieces of evidence (see classify_entry),
deliberately kept separate from the DNS log half: a verdict that
disagreed with the log is a finding, and merging them would hide it.

Adaptations from the reference (v8 #35, OpenWrt) to our Debian panel:

- The LAN is the router's LAN bridge: ubus, else an interface
  literally named br-lan with an IPv4 address. Docker bridges
  (docker0, br-*) are NOT a LAN — joining them would put the probe
  on a container network the panel does not serve.
- The DHCP check accepts any DHCP client (udhcpc, dhcpcd, dhclient),
  not only BusyBox's udhcpc: the check's purpose is "can we get a
  lease", and Debian boxes have dhcpcd/dhclient instead. The client
  found is reported so the lease step uses the right CLI.
- tun_settings: our build stamps no fwmark (no auto_redirect_input
  _mark in our tun inbound), so the input mark defaults to None,
  NOT the reference's 8227 — a mark can never prove "tun" for us,
  and borrowing their panel's mark would misclassify.
- The bypass nft set is looked up in the reference's sing-box table;
  our entry nft is generated but not applied, so on this panel the
  lookup fails and the answer is honestly {set: None, hit: False}.
- The probe child is ours (terminal_child.py, Python): the reference
  ships no child (system/lan-probe-child.mjs is referenced but not
  included), so the child contract here is defined by the events the
  orchestrator consumes (dns/connected/response/error).

Commands run through an injectable runner so the suite never touches
a real namespace: run(argv, timeout) -> (code, stdout, stderr).
"""

import os
import subprocess
import sys
import threading
import time

PROBE_NETNS = "openbox-probe"
PROBE_VETH_HOST = "obprobe0"
PROBE_VETH_NS = "obprobe1"
PROBE_MAC = "02:4f:42:00:00:01"
PROBE_HOSTNAME = "openbox-probe"
PROBE_DHCP_SCRIPT = "/tmp/openbox-probe-dhcp.sh"
NETNS_IDLE_S = 600
SINGBOX_NFT_TABLE = "sing-box"
CONNTRACK_PATH = "/proc/net/nf_conntrack"

TERMINAL_PROBE_TIMEOUT_S = 10.0
TERMINAL_HOLD_S = 25.0
TERMINAL_CHILD_TIMEOUT_S = 30.0
CONNECTIONS_DELAYS_S = (0, 0.15, 0.25, 0.35, 0.45)
CONNTRACK_DELAYS_S = (0, 0.15, 0.3, 0.6)
CHAIN_SETTLE_S = 0.25
EVIDENCE_TIMEOUT_S = 5.0

UDHCPC_SCRIPT = """#!/bin/sh
# udhcpc hook: report the lease in one LEASE line.
echo "LEASE ip=$ip mask=$subnet router=$router dns=$dns"
"""


def _default_run(argv, timeout):
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)


def _default_exists(path):
    return os.path.exists(path)


# ---------------------------------------------------------------- parses

def parse_addr_show(stdout: str):
    """`ip -o addr show dev X` -> {device, address} or None."""
    for line in (stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "inet":
            addr = parts[3].split("/")[0]
            return {"device": parts[1], "address": addr}
    return None


def parse_conntrack(text: str) -> list:
    """Parse /proc/net/nf_conntrack into flow dicts.

    Each flow: {l3, proto, state, orig: {src, dst, sport, dport},
    reply: {...}, flags, mark, line}. Only the first two tuples
    (original, reply) are kept; the state is the bare uppercase word
    before the first tuple.
    """
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        l3, proto = parts[0], parts[2]
        tuples: list[dict] = []
        current = None
        state = ""
        mark = None
        flags: list[str] = []
        for token in parts[3:]:
            if "=" in token:
                key, value = token.split("=", 1)
                if key == "src":
                    current = {"src": value}
                    tuples.append(current)
                    continue
                if current is not None and key in (
                        "dst", "type", "code", "id"):
                    current[key] = value
                    continue
                if current is not None and key in ("sport", "dport"):
                    try:
                        current[key] = int(value)
                    except ValueError:
                        pass
                    continue
                if key == "mark":
                    try:
                        mark = int(value)
                    except ValueError:
                        pass
                    continue
                continue
            if token.startswith("[") and token.endswith("]"):
                flags.append(token[1:-1])
                continue
            if not tuples and token.isupper():
                state = token
        if len(tuples) < 2:
            continue
        out.append({"l3": l3, "proto": proto, "state": state,
                    "orig": tuples[0], "reply": tuples[1],
                    "flags": flags, "mark": mark, "line": line})
    return out


def parse_lease_udhcpc(stdout: str):
    """The LEASE line the udhcpc hook prints, or None."""
    import ipaddress
    import re

    m = re.search(r"LEASE ip=(\S+) mask=(\S*) router=(.*?) dns=(.*)$",
                  stdout or "", re.M)
    if not m:
        return None
    try:
        ipaddress.ip_address(m.group(1))
    except ValueError:
        return None
    dns = []
    for value in m.group(4).strip().split():
        try:
            ipaddress.ip_address(value)
            dns.append(value)
        except ValueError:
            continue
    routers = m.group(3).strip().split()
    return {"ip": m.group(1),
            "mask": int(m.group(2)) if m.group(2).isdigit() else 24,
            "gateway": routers[0] if routers else "",
            "dns": dns}


def parse_lease_dhcpcd(stdout: str):
    """`dhcpcd -U <iface>` variables into the same lease shape."""
    import ipaddress

    vals = {}
    for line in (stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            vals[key.strip()] = value.strip().strip("'")
    ip = vals.get("ip_address", "")
    if not ip:
        return None
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    mask = vals.get("subnet_mask", "")
    try:
        prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen \
            if mask else 24
    except ValueError:
        prefix = 24
    dns = []
    for value in vals.get("domain_name_servers", "").split():
        try:
            ipaddress.ip_address(value)
            dns.append(value)
        except ValueError:
            continue
    routers = vals.get("routers", "").split()
    return {"ip": ip, "mask": prefix,
            "gateway": routers[0] if routers else "", "dns": dns}


def parse_route_get(stdout: str):
    """First line of `ip route get` -> {line, dev, via, table}."""
    line = ""
    for entry in (stdout or "").splitlines():
        if entry.strip():
            line = entry.strip()
            break
    if not line:
        return None
    import re

    def _field(name):
        m = re.search(rf"\b{name}\s+(\S+)", line)
        return m.group(1) if m else ""

    return {"line": line, "dev": _field("dev"), "via": _field("via"),
            "table": _field("table")}


# ---------------------------------------------------------------- capability

def read_lan_interface(run=_default_run):
    """The LAN bridge, via ubus first, else br-lan. None is not an
    error yet — probe_capability turns it into a missing entry."""
    code, out, _ = run(["ubus", "call", "network.interface.lan",
                        "status"], timeout=5)
    if code == 0:
        import json

        try:
            status = json.loads(out)
            dev = (status.get("device") or "")
            addr = ""
            for entry in status.get("ipv4-address") or []:
                addr = entry.get("address") or addr
            if dev and addr:
                return {"device": dev, "address": addr}
        except Exception:
            pass
    code, out, _ = run(["ip", "-4", "-o", "addr", "show", "dev",
                        "br-lan"], timeout=5)
    if code == 0:
        parsed = parse_addr_show(out)
        if parsed:
            return parsed
    return None


def find_dhcp_client(exists=_default_exists, run=_default_run):
    """Any DHCP client binary: udhcpc first, then the Debian ones.
    Returns the client name or None."""
    for path in ("/sbin/udhcpc", "/usr/sbin/udhcpc", "/bin/udhcpc"):
        if exists(path):
            return "udhcpc"
    for name in ("dhcpcd", "dhclient"):
        code, _, _ = run(["which", name], timeout=5)
        if code == 0:
            return name
    return None


def probe_capability(run=_default_run, exists=_default_exists, uid=None):
    """Six hard requirements; the answer is the list of what is
    missing so the caller can say why instead of just refusing:
    root, ip netns, veth, a LAN bridge, conntrack, a DHCP client."""
    if uid is None:
        uid = os.getuid() if hasattr(os, "getuid") else 0
    missing: list[str] = []
    if uid != 0:
        missing.append("root")
    code, _, _ = run(["ip", "netns", "list"], timeout=5)
    if code != 0:
        missing.append("netns")
    veth = exists("/sys/module/veth")
    if not veth:
        code, _, _ = run(["modprobe", "veth"], timeout=5)
        veth = code == 0
    if not veth:
        missing.append("veth")
    lan = read_lan_interface(run)
    if lan is None:
        missing.append("lan")
    elif not exists(f"/sys/class/net/{lan['device']}/bridge"):
        missing.append("bridge")
    if not exists(CONNTRACK_PATH):
        missing.append("conntrack")
    dhcp_client = find_dhcp_client(exists, run)
    if dhcp_client is None:
        missing.append("dhcp")
    return {"ok": not missing, "missing": missing, "lan": lan,
            "dhcp_client": dhcp_client}


# ---------------------------------------------------------------- lifecycle

class _ProbeState:
    def __init__(self):
        self.lease = None
        self.lease_at = 0.0
        self.timer = None
        self.lock = threading.Lock()


STATE = _ProbeState()


def teardown_probe_netns(run=_default_run, exists=_default_exists):
    """Best-effort, out of order on purpose: the namespace may not
    exist, the veth may already be gone with it."""
    with STATE.lock:
        if STATE.timer is not None:
            STATE.timer.cancel()
            STATE.timer = None
        STATE.lease = None
    run(["ip", "netns", "del", PROBE_NETNS], timeout=10)
    run(["ip", "link", "del", PROBE_VETH_HOST], timeout=5)
    try:
        if exists(PROBE_DHCP_SCRIPT):
            os.unlink(PROBE_DHCP_SCRIPT)
    except Exception:
        pass


def _schedule_teardown(run):
    with STATE.lock:
        if STATE.timer is not None:
            STATE.timer.cancel()
        timer = threading.Timer(NETNS_IDLE_S,
                                lambda: teardown_probe_netns(run))
        timer.daemon = True
        timer.start()
        STATE.timer = timer


def ensure_probe_netns(run=_default_run, exists=_default_exists,
                       dhcp_client=None):
    """Create (or reuse, <10min old) the probe namespace + veth pair
    and get a DHCP lease. Raises on failure; the caller reports it as
    setupError, not as a verdict."""
    with STATE.lock:
        if (STATE.lease is not None
                and time.monotonic() - STATE.lease_at < NETNS_IDLE_S):
            _schedule_teardown(run)
            return {**STATE.lease, "reused": True}
    lan = read_lan_interface(run)
    if lan is None:
        raise RuntimeError("no LAN interface")
    if dhcp_client is None:
        dhcp_client = find_dhcp_client(exists, run)
    if dhcp_client is None:
        raise RuntimeError("no DHCP client")
    code, out, _ = run(["ip", "netns", "list"], timeout=5)
    has_ns = code == 0 and any(
        line.strip().split()[0] == PROBE_NETNS
        for line in out.splitlines() if line.strip())
    if not has_ns:
        for argv in (
                ["ip", "netns", "add", PROBE_NETNS],
                ["ip", "link", "add", PROBE_VETH_HOST, "type", "veth",
                 "peer", "name", PROBE_VETH_NS],
                ["ip", "link", "set", PROBE_VETH_NS, "netns", PROBE_NETNS],
                ["ip", "link", "set", PROBE_VETH_HOST, "master",
                 lan["device"]],
                ["ip", "link", "set", PROBE_VETH_HOST, "up"],
                ["ip", "netns", "exec", PROBE_NETNS, "ip", "link", "set",
                 PROBE_VETH_NS, "address", PROBE_MAC],
                ["ip", "netns", "exec", PROBE_NETNS, "ip", "link", "set",
                 PROBE_VETH_NS, "up"],
                ["ip", "netns", "exec", PROBE_NETNS, "ip", "link", "set",
                 "lo", "up"]):
            code, _, err = run(argv, timeout=10)
            if code != 0:
                raise RuntimeError(
                    f"netns setup failed at {' '.join(argv)}: {err}")
    dhcp_started = time.monotonic()
    if dhcp_client == "udhcpc":
        with open(PROBE_DHCP_SCRIPT, "w") as f:
            f.write(UDHCPC_SCRIPT)
        os.chmod(PROBE_DHCP_SCRIPT, 0o755)
        code, out, err = run(
            ["ip", "netns", "exec", PROBE_NETNS, "udhcpc", "-i",
             PROBE_VETH_NS, "-s", PROBE_DHCP_SCRIPT, "-n", "-q"],
            timeout=30)
        lease = parse_lease_udhcpc(out) if code == 0 else None
        if lease is None:
            raise RuntimeError(f"DHCP failed: {err or out}")
    else:
        code, _, err = run(
            ["ip", "netns", "exec", PROBE_NETNS, dhcp_client, "-1",
             PROBE_VETH_NS], timeout=30)
        if code != 0:
            raise RuntimeError(f"DHCP failed: {err}")
        code, out, _ = run(
            ["ip", "netns", "exec", PROBE_NETNS, dhcp_client, "-U",
             PROBE_VETH_NS], timeout=10)
        lease = parse_lease_dhcpcd(out) if code == 0 else None
        if lease is None:
            raise RuntimeError("DHCP lease unreadable")
    lease = {**lease, "hostname": PROBE_HOSTNAME, "mac": PROBE_MAC,
             "lanDevice": PROBE_VETH_NS, "reused": False,
             "override": None,
             "dhcpMs": int((time.monotonic() - dhcp_started) * 1000)}
    with STATE.lock:
        STATE.lease = lease
        STATE.lease_at = time.monotonic()
    _schedule_teardown(run)
    return lease


# ---------------------------------------------------------------- evidence

def read_conntrack(run=_default_run):
    try:
        with open(CONNTRACK_PATH) as f:
            return parse_conntrack(f.read())
    except Exception:
        return None


def find_flow(flows, *, proto, src, sport, dst, dport):
    """Match on the original tuple (what the probe sent); the reply
    tuple is the answer, not the question. Last match wins: a retried
    connect leaves several entries and the newest is the one that
    succeeded."""
    found = None
    for flow in flows or []:
        if flow.get("proto") != proto:
            continue
        orig = flow.get("orig") or {}
        if orig.get("src") != src or orig.get("dst") != dst:
            continue
        if dport is not None and orig.get("dport") != dport:
            continue
        if sport is not None and orig.get("sport") != sport:
            continue
        found = flow
    return found


def dns_evidence(flows, *, src, server):
    """What the kernel's own resolver did with the name: a reply
    whose source is not the server means something on the router
    hijacked the query."""
    queries = [f for f in (flows or [])
               if f.get("proto") == "udp"
               and (f.get("orig") or {}).get("src") == src
               and (f.get("orig") or {}).get("dst") == server
               and (f.get("orig") or {}).get("dport") == 53]
    hijacked = [f for f in queries
                if (f.get("reply") or {}).get("src") != server]
    sample = hijacked[0] if hijacked else (queries[-1] if queries else None)
    return {"flows": len(queries), "hijacked": bool(hijacked),
            "answeredBy": hijacked[0]["reply"]["src"] if hijacked
            else (server if queries else ""),
            "line": sample["line"] if sample else ""}


def route_get(run=_default_run, *, dst, from_ip, iif, mark):
    """`ip route get` is a lookup, not a probe: it answers from the
    routing table without sending anything. The mark is passed only
    when conntrack reported one, because a marked flow can take a
    policy route the unmarked one does not."""
    args = ["ip", "route", "get", dst, "from", from_ip, "iif", iif]
    if mark:
        args += ["mark", f"0x{int(mark):x}"]
    code, out, _ = run(args, timeout=5)
    return parse_route_get(out) if code == 0 else None


def bypass_set_has(run, address):
    """Is this address in the deploy's entry-bypass set? When the set
    does not exist the answer is {set: None, hit: False} — "no bypass
    set", not "not bypassed"."""
    import ipaddress

    try:
        version = ipaddress.ip_address(address).version
    except ValueError:
        return {"set": None, "hit": False}
    name = ("inet6_route_exclude_address_set" if version == 6
            else "inet4_route_exclude_address_set")
    code, _, _ = run(["nft", "list", "set", "inet", SINGBOX_NFT_TABLE,
                      name], timeout=5)
    if code != 0:
        return {"set": None, "hit": False}
    code, _, _ = run(["nft", "get", "element", "inet", SINGBOX_NFT_TABLE,
                      name, "{", address, "}"], timeout=5)
    return {"set": name, "hit": code == 0}


def tun_settings(deployed):
    """The TUN inbound's settings, from the deployed config.

    device defaults to tun0 and auto_redirect to False, as in the
    reference — but the input mark defaults to None, not 8227: our
    build stamps no fwmark, so borrowing the reference panel's mark
    would misclassify any flow that happens to carry it.
    """
    tun = {}
    for inbound in (deployed or {}).get("inbounds") or []:
        if isinstance(inbound, dict) and inbound.get("type") == "tun":
            tun = inbound
            break
    mark = tun.get("auto_redirect_input_mark")
    return {"device": tun.get("interface_name") or "tun0",
            "autoRedirect": bool(tun.get("auto_redirect")),
            "inputMark": int(mark) if mark is not None else None,
            "outputMark": tun.get("auto_redirect_output_mark")}


def classify_entry(*, flow, local_addresses=None, tun_device="tun0",
                   tun_mark=None, route=None, kernel_conn=False,
                   device_addresses=None):
    """Six tests, in this order, and the order is the answer:
    no-conntrack, redirect (reply rewritten to a local address), tun
    (the TUN's mark), connection-table, dnat-elsewhere, route-tun —
    anything left is a bypass out of a physical interface."""
    local_addresses = local_addresses or []
    device_addresses = device_addresses or []
    evidence = {"conntrack": flow["line"] if flow else "",
                "mark": flow["mark"] if flow else None,
                "route": route["line"] if route else "",
                "kernelConn": kernel_conn}
    if flow is None:
        return {"kind": "unknown", "reason": "no-conntrack",
                "evidence": evidence}
    orig, reply = flow.get("orig") or {}, flow.get("reply") or {}
    rewritten = (reply.get("src") != orig.get("dst")
                 or reply.get("sport") != orig.get("dport"))
    redirected = rewritten and reply.get("src") in local_addresses
    marked = tun_mark is not None and flow.get("mark") == tun_mark
    if redirected:
        return {"kind": "kernel", "via": "redirect",
                "redirectPort": reply.get("sport"), "evidence": evidence}
    if marked:
        return {"kind": "kernel", "via": "tun", "evidence": evidence}
    if kernel_conn:
        return {"kind": "kernel", "via": "connection-table",
                "evidence": evidence}
    if rewritten:
        return {"kind": "unknown", "reason": "dnat-elsewhere",
                "rewrittenTo": f"{reply.get('src')}:{reply.get('sport')}",
                "evidence": evidence}
    if route is None:
        return {"kind": "unknown", "reason": "no-route",
                "evidence": evidence}
    if route.get("dev") == tun_device:
        return {"kind": "unknown", "reason": "route-tun",
                "evidence": evidence}
    masquerade = reply.get("dst") in device_addresses
    return {"kind": "bypass", "via": "forward", "device": route.get("dev"),
            "gateway": route.get("via"), "masquerade": masquerade,
            "evidence": evidence}


def dnsmasq_forward_for(text: str, target: str):
    """What dnsmasq would do with this name: scan server=/domain/
    upstream lines; the first matching suffix wins (the panel's file
    never has overlapping entries, so first == longest)."""
    import re

    name = (target or "").lower().rstrip(".")
    for raw in (text or "").splitlines():
        m = re.match(r"^server=/([^/]+)/(\S+)", raw.strip())
        if not m:
            continue
        suffix = m.group(1).lower().lstrip(".")
        if name == suffix or name.endswith(f".{suffix}"):
            return {"forward": "kernel", "suffix": suffix, "to": m.group(2)}
    return None


# ---------------------------------------------------------------- child

def run_probe_child(*, spawn=None, opts: dict, timeout_s: float,
                    on_event):
    """Run the probe child inside the namespace and stream its JSON
    events to on_event(event, handle). Returns {error, stderr}.

    The stdout reader runs in a thread so a child that holds its
    socket (25 s) cannot block the timeout: after timeout_s the
    child is terminated and the error is "child timeout". spawn, when
    given, replaces the real spawner (tests): it receives the argv
    and must return an object with .stdout_lines() (an iterator of
    lines) and .terminate().
    """
    import json

    child_path = os.path.join(os.path.dirname(__file__),
                              "terminal_child.py")
    argv = ["ip", "netns", "exec", PROBE_NETNS, sys.executable,
            child_path,
            "--target", opts["target"], "--port", str(opts["port"]),
            "--secure", "1" if opts.get("secure") else "0",
            "--method", opts.get("method", "GET"),
            "--dns-servers", ",".join(opts.get("dns_servers") or []),
            "--resolve6", "1" if opts.get("resolve6") else "0",
            "--timeout", str(opts.get("timeout_s", TERMINAL_PROBE_TIMEOUT_S)),
            "--hold", str(opts.get("hold_s", TERMINAL_HOLD_S))]
    if spawn is not None:
        proc = spawn(argv)
        handle = proc
        stderr_of = lambda: ""
    else:
        import subprocess as _sp

        proc = _sp.Popen(argv, stdout=_sp.PIPE, stderr=_sp.PIPE,
                         text=True, bufsize=1)

        class _Handle:
            def close(self):
                try:
                    proc.terminate()
                except Exception:
                    pass

        handle = _Handle()

        def _lines():
            try:
                for line in proc.stdout:
                    yield line
            except Exception:
                return

        proc.stdout_lines = _lines

        def stderr_of():
            try:
                proc.wait(timeout=5)
                return proc.stderr.read() or ""
            except Exception:
                return ""

    error = {"value": ""}

    def _reader():
        try:
            for line in proc.stdout_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and "event" in event:
                    on_event(event, handle)
        except Exception as e:
            error["value"] = str(e)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    reader.join(timeout=timeout_s)
    if reader.is_alive():
        try:
            proc.terminate()
        except Exception:
            pass
        reader.join(timeout=5)
        error["value"] = error["value"] or "child timeout"
    return {"error": error["value"], "stderr": stderr_of()}
