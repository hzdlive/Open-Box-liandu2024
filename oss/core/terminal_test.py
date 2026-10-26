"""Terminal test orchestrator: "what happens to a packet that starts
on the LAN?"

Puts a virtual client on the LAN (a namespace with a veth pair, a
DHCP lease and the router's address as its gateway) and asks that
client to reach a target. The verdict is read out of conntrack, `ip
route get`, /connections and the bypass nft set — four pieces of
evidence, classified by terminal_probe.classify_entry. The DNS log
half is deliberately separate from the verdict; on this panel the
kernel-DNS log tap is not wired, so the report says
{seen: false, reason: "no-log"} rather than inventing log evidence.

Serialised, not parallel: there is one probe namespace and one veth
pair, so run_serialised puts every test behind one lock. A failed
test must not poison the next one — the lock always releases.

Adaptations from the reference (v8 #35, OpenWrt):

- No sidecar file on this panel, so there is no firstLayer/dnsForward
  plan: the DNS half is the child's own resolution plus dnsEvidence
  from conntrack, not a dnsmasq forward plan.
- The child resolves both families (no profile ipv6 gate on this
  panel) and dials the first A answer, else the first AAAA.
- The report's error shape is {message} for the routes (the
  diagnostics routes' contract), while a capability failure or a
  setup failure is a 200 report field (capable: false / setupError),
  not an HTTP error — the test ran, it just could not run here.
"""

import threading
import time

from core.route_test import detect_challenge, normalize_method
from core.terminal_probe import (
    CHAIN_SETTLE_S,
    CONNECTIONS_DELAYS_S,
    CONNTRACK_DELAYS_S,
    TERMINAL_CHILD_TIMEOUT_S,
    TERMINAL_HOLD_S,
    TERMINAL_PROBE_TIMEOUT_S,
    bypass_set_has,
    classify_entry,
    dns_evidence,
    ensure_probe_netns,
    find_flow,
    parse_addr_show,
    probe_capability,
    read_conntrack,
    route_get,
    run_probe_child,
    tun_settings,
)

CONTAINER_PROBE_REFUSAL = "Docker 版请使用独立终端测试旁路由"
BAD_TARGET_MESSAGE = "target must be a domain or IP"

_SERIAL_LOCK = threading.Lock()


def run_serialised(fn):
    """One test at a time; the lock always releases, even on error."""
    with _SERIAL_LOCK:
        return fn()


def is_container():
    """Docker detection for the container gate: /.dockerenv, or
    docker in this process's cgroup."""
    import os

    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/self/cgroup") as f:
            return "docker" in f.read()
    except Exception:
        return False


def _probe_port(port, literal: bool) -> int:
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 0
    if port and 1 <= port <= 65535:
        return port
    return 80 if literal else 443


def _exit_url(method, target, port, secure):
    host = f"[{target}]" if ":" in target else target
    if method in ("TCP", "TLS"):
        return f"{method.lower()}://{host}:{port}"
    default_port = 443 if secure else 80
    return (f"{'https' if secure else 'http'}://{host}"
            f"{'' if port == default_port else f':{port}'}/")


def format_kernel_connection(conn):
    """One /connections entry as the report carries it (chains are
    already leaf-first from sing-box; no reversal)."""
    if not conn:
        return {"seen": False}
    md = conn.get("metadata") or {}
    out = {"seen": True, "chains": conn.get("chains") or [],
           "rule": conn.get("rule") or "",
           "rulePayload": conn.get("rulePayload") or "",
           "destinationIP": md.get("destinationIP") or "",
           "sourcePort": md.get("sourcePort")}
    if conn.get("id") is not None:
        out["id"] = conn.get("id")
    if conn.get("start") is not None:
        out["start"] = conn.get("start")
    return out


def terminal_test(body: dict, *, deployed=None, run=None, exists=None,
                  connections_fn=None, spawn=None, uid=None):
    """Run one terminal test. Returns the report dict (always 200 at
    the route: capable/setup failures are report fields)."""
    from core.clashapi import list_connections
    from core.terminal_probe import _default_exists, _default_run

    run = run or _default_run
    exists = exists or _default_exists
    if connections_fn is None:
        def connections_fn():
            ok, conns = list_connections()
            if not ok:
                raise RuntimeError("读取 /connections 失败")
            return conns

    # The route gates invalid input; direct callers must too — the
    # parse raises before any capability check or namespace work.
    from core.route_oracle import parse_target

    raw = str(body.get("target") or "").strip().lower()
    parsed = parse_target(raw)
    target = parsed.value
    literal = parsed.kind == "ip"
    method = normalize_method(body.get("method"))
    started_at = time.monotonic()
    report: dict = {"target": target, "mode": "lan"}

    # -- 1. capability ----------------------------------------------
    capability = probe_capability(run, exists, uid)
    if not capability["ok"]:
        return {**report, "capable": False,
                "missing": capability["missing"]}
    report["capable"] = True

    # -- 2. deployed config (best effort; absent still coherent) ----
    tun = tun_settings(deployed)

    # -- 3. namespace + lease ----------------------------------------
    try:
        lease = ensure_probe_netns(run, exists,
                                   capability.get("dhcp_client"))
    except Exception as e:
        return {**report, "setupError": str(e)}
    report["source"] = {
        "kind": "virtual", "name": lease.get("hostname"),
        "ip": lease.get("ip"), "mac": lease.get("mac"),
        "via": "dhcp", "dns": lease.get("dns"),
        "gateway": lease.get("gateway"),
        "override": lease.get("override"),
        "lanDevice": lease.get("lanDevice"),
        "reused": bool(lease.get("reused")),
        "dhcpMs": lease.get("dhcpMs"),
    }

    # -- 4. exit skeleton --------------------------------------------
    typed_port = body.get("port")
    if typed_port is None:
        typed_port = parsed.port
    target_port = _probe_port(typed_port, literal)
    secure = method == "TLS" or (method != "TCP" and target_port != 80)
    report["exit"] = {"url": _exit_url(method, target, target_port,
                                       secure),
                      "port": target_port, "method": method}
    observed = {"ip": target if literal else "",
                "source": lease.get("ip")}

    # -- 5. evidence ---------------------------------------------------
    lock = threading.Lock()
    state = {"evidence_done": False, "responded": False,
             "handle": None, "finished": False,
             "evidence_thread": None, "late_thread": None,
             "late_options": None}

    def gather(options, late=False):
        local_port = options.get("localPort")
        flows = None
        flow = None
        for delay in ([0] if late else CONNTRACK_DELAYS_S):
            if delay:
                time.sleep(delay)
            flows = read_conntrack(run)
            flow = find_flow(flows, proto="tcp", src=observed["source"],
                             sport=local_port, dst=observed["ip"],
                             dport=target_port) if observed["ip"] else None
            if flow or flows is None:
                break
        addresses = []
        for family in ("-4", "-6"):
            code, out, _ = run(["ip", family, "-o", "addr"], timeout=5)
            if code == 0:
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 4 and parts[2] == "inet":
                        addresses.append(
                            {"iface": parts[1],
                             "address": parts[3].split("/")[0]})
        local_addresses = [a["address"] for a in addresses]
        route = route_get(run, dst=observed["ip"],
                          from_ip=observed["source"],
                          iif=lease.get("lanDevice"),
                          mark=flow["mark"] if flow else 0) \
            if observed["ip"] else None
        device_addresses = [a["address"] for a in addresses
                            if route and a["iface"] == route.get("dev")]
        kernel_connection = {"seen": False}
        kernel_error = ""
        try:
            for delay in ([0] if late else CONNECTIONS_DELAYS_S):
                if delay:
                    time.sleep(delay)
                conns = connections_fn()
                hit = next(
                    (c for c in (conns or [])
                     if isinstance(c, dict)
                     and isinstance(c.get("metadata"), dict)
                     and c["metadata"].get("sourceIP")
                     == observed["source"]
                     and (local_port is None or str(
                         c["metadata"].get("sourcePort"))
                         == str(local_port))
                     and (not observed["ip"]
                          or c["metadata"].get("destinationIP")
                          == observed["ip"]
                          or str(c["metadata"].get("host") or "")
                          .lower() == target)
                     and str(c["metadata"].get("destinationPort"))
                     == str(target_port)),
                    None)
                if hit is not None:
                    kernel_connection = format_kernel_connection(hit)
                    break
            if (not late and kernel_connection.get("seen")
                    and kernel_connection.get("id") is not None):
                time.sleep(CHAIN_SETTLE_S)
                conns = connections_fn()
                again = next(
                    (c for c in (conns or [])
                     if isinstance(c, dict)
                     and c.get("id") == kernel_connection.get("id")),
                    None)
                if (again and isinstance(again.get("chains"), list)
                        and len(again["chains"])
                        > len(kernel_connection.get("chains") or [])):
                    kernel_connection = format_kernel_connection(again)
        except Exception as e:
            kernel_error = str(e)
        bypass = bypass_set_has(run, observed["ip"]) \
            if observed["ip"] else {"set": None, "hit": False}
        entry = classify_entry(
            flow=flow, local_addresses=local_addresses,
            tun_device=tun["device"], tun_mark=tun["inputMark"],
            route=route, kernel_conn=kernel_connection.get("seen"),
            device_addresses=device_addresses)
        entry["evidence"]["set"] = bypass["set"]
        entry["evidence"]["setHit"] = bypass["hit"]
        if flows is None:
            entry["evidence"]["conntrackError"] = "unreadable"
        if kernel_error:
            entry["evidence"]["kernelError"] = kernel_error
        entry["evidence"]["autoRedirect"] = tun["autoRedirect"]
        entry["evidence"]["tunDevice"] = tun["device"]
        report["entry"] = entry
        report["kernel"] = kernel_connection
        if entry.get("kind") == "bypass":
            report["exit"]["forward"] = {
                "device": entry.get("device"),
                "gateway": entry.get("gateway"),
                "masquerade": entry.get("masquerade"),
                "address": device_addresses[0] if device_addresses else "",
            }
        if not literal and flows and (lease.get("dns") or [None])[0]:
            report["dnsEvidence"] = dns_evidence(
                flows, src=lease.get("ip"),
                server=lease["dns"][0])

    def settle():
        with lock:
            if (not state["evidence_done"] or not state["responded"]
                    or state["handle"] is None or state["finished"]):
                return
            state["finished"] = True
        if report["exit"].get("ok") and not (
                report.get("kernel") or {}).get("seen"):
            # Exit succeeded but the kernel never showed the flow:
            # one more read before the socket goes away.
            def _late():
                try:
                    gather(state["late_options"], late=True)
                except Exception:
                    pass
                finally:
                    try:
                        state["handle"].close()
                    except Exception:
                        pass

            t = threading.Thread(target=_late, daemon=True)
            state["late_thread"] = t
            t.start()
        else:
            try:
                state["handle"].close()
            except Exception:
                pass

    def start_evidence(options, handle):
        with lock:
            state["handle"] = handle
            if state["evidence_thread"] is not None:
                return
            state["late_options"] = options

        def _run():
            try:
                gather(options)
            except Exception as e:
                report["entry"] = {"kind": "unknown",
                                   "reason": "evidence-failed",
                                   "error": str(e), "evidence": {}}
            finally:
                with lock:
                    state["evidence_done"] = True
                settle()

        t = threading.Thread(target=_run, daemon=True)
        state["evidence_thread"] = t
        t.start()

    # -- 6. DNS log tap: not wired on this panel ----------------------
    # The verdict deliberately does not depend on it; a verdict that
    # disagreed with the log would be a finding, and inventing log
    # evidence would hide it.
    if not literal:
        report["kernelDns"] = {"seen": False, "reason": "no-log"}

    # -- 7. the child --------------------------------------------------
    def on_event(event, handle):
        kind = event.get("event")
        if kind == "dns":
            dns = {"server": event.get("server"), "ok": bool(event.get("ok")),
                   "answers": event.get("answers") or [],
                   "ms": event.get("ms")}
            if event.get("error"):
                dns["error"] = event["error"]
            if event.get("answers6") is not None:
                dns["answers6"] = event["answers6"]
                if event.get("error6"):
                    dns["error6"] = event["error6"]
            report["dns"] = dns
            observed["ip"] = (event.get("answers") or [None])[0] \
                or (event.get("answers6") or [None])[0] or ""
            return
        if kind == "connected":
            observed["ip"] = event.get("remoteAddress") or observed["ip"]
            observed["source"] = event.get("localAddress") \
                or lease.get("ip")
            report["exit"]["connectTo"] = observed["ip"]
            report["exit"]["localPort"] = event.get("localPort")
            report["exit"]["connectMs"] = event.get("ms")
            start_evidence({"localPort": event.get("localPort")}, handle)
            return
        if kind == "response":
            report["exit"]["ok"] = True
            report["exit"]["status"] = event.get("status")
            report["exit"]["ms"] = event.get("ms")
            headers = event.get("headers")
            if isinstance(headers, dict) and headers:
                report["exit"]["headers"] = headers
                challenge = detect_challenge(event.get("status"), headers)
                if challenge:
                    report["exit"]["challenge"] = challenge
            with lock:
                state["responded"] = True
            settle()
            return
        if kind == "error":
            report["exit"]["ok"] = False
            report["exit"]["error"] = (
                f"dns: {event.get('error')}"
                if event.get("stage") == "dns" else event.get("error"))
            if event.get("ms") is not None:
                report["exit"]["ms"] = event.get("ms")
            with lock:
                state["responded"] = True
            if event.get("stage") != "dns":
                start_evidence({"localPort": report["exit"].get("localPort")},
                               handle)
            else:
                try:
                    handle.close()
                except Exception:
                    pass
            settle()

    child = run_probe_child(
        spawn=spawn,
        opts={"target": target, "port": target_port, "secure": secure,
              "method": method, "dns_servers": lease.get("dns") or [],
              "resolve6": True,
              "timeout_s": TERMINAL_PROBE_TIMEOUT_S,
              "hold_s": TERMINAL_HOLD_S},
        timeout_s=TERMINAL_CHILD_TIMEOUT_S,
        on_event=on_event)

    # -- 8. tail --------------------------------------------------------
    if state["evidence_thread"] is not None:
        state["evidence_thread"].join(timeout=30)
    if state["late_thread"] is not None:
        state["late_thread"].join(timeout=30)
    if literal:
        report["dns"] = {"skipped": True}
    elif "dns" not in report:
        report["dns"] = {"server": (lease.get("dns") or [""])[0],
                         "ok": False, "answers": [], "ms": 0,
                         "error": child.get("error") or "no answer"}
    if "entry" not in report:
        reason = "not-connected" if (
            report["exit"].get("error") or "").startswith("dns:") \
            else "no-connection"
        report["entry"] = {"kind": "unknown", "reason": reason,
                           "evidence": {}}
    if child.get("error"):
        report["exit"]["error"] = report["exit"].get("error") \
            or child["error"]
    if report["exit"].get("ok") is None:
        report["exit"]["ok"] = False
        report["exit"]["error"] = report["exit"].get("error") \
            or "no response"
    if child.get("stderr"):
        report["probeStderr"] = child["stderr"][:500]
    report["timing"] = {"totalMs": int(
        (time.monotonic() - started_at) * 1000)}
    return report
