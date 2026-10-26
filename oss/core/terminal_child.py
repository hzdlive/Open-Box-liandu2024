"""Probe child: runs inside the probe namespace (never imported by
the panel — it is spawned as `ip netns exec openbox-probe python3
terminal_child.py ...`).

It speaks JSON lines on stdout, one per event, which the
orchestrator consumes:

  {"event": "dns", "server": ..., "ok": bool, "answers": [...],
   "answers6": [...], "ms": int, "error": ...}
  {"event": "connected", "remoteAddress": ..., "localAddress": ...,
   "localPort": int, "ms": int}
  {"event": "response", "status": int|None, "headers": {...}, "ms": int}
  {"event": "error", "stage": "dns"|"connect"|"tls"|"http",
   "error": ..., "ms": int}

After the response event the socket is held open (hold seconds) so
the parent can find the flow in conntrack and /connections; the
parent kills the child when it is done, so the hold is a cap, not a
promise. DNS is resolved explicitly against the lease's servers with
a minimal client: the namespace cannot use the host's
/etc/resolv.conf (it is global, not per-namespace).

This file is ours: the reference ships no child (its
system/lan-probe-child.mjs is referenced but not included), so the
contract above is defined here, to match the events the orchestrator
handles.
"""

import argparse
import ipaddress
import json
import socket
import ssl
import struct
import sys
import time


def _emit(event):
    print(json.dumps(event), flush=True)


def _read_name(msg, off):
    labels = []
    jumped = False
    next_off = off
    while True:
        ln = msg[off]
        if ln == 0:
            off += 1
            break
        if ln & 0xC0 == 0xC0:
            ptr = ((ln & 0x3F) << 8) | msg[off + 1]
            if not jumped:
                next_off = off + 2
            off = ptr
            jumped = True
            continue
        labels.append(msg[off + 1:off + 1 + ln].decode("latin1"))
        off += 1 + ln
    return ".".join(labels), (next_off if jumped else off)


def _dns_query(server, name, qtype, timeout):
    """One UDP DNS query. Returns (answers, error)."""
    tid = 0x1234
    flags = 0x0100
    header = struct.pack(">HHHHHH", tid, flags, 1, 0, 0, 0)
    qname = b""
    for label in name.split("."):
        raw = label.encode()
        qname += bytes([len(raw)]) + raw
    qname += b"\x00"
    packet = header + qname + struct.pack(">HH", qtype, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (server, 53))
        data, _ = sock.recvfrom(4096)
    finally:
        sock.close()
    if len(data) < 12:
        return [], "short response"
    rcode = data[3] & 0x0F
    if rcode != 0:
        return [], f"rcode {rcode}"
    qdcount, ancount = struct.unpack(">HH", data[4:8])
    off = 12
    for _ in range(qdcount):
        _, off = _read_name(data, off)
        off += 4
    answers = []
    for _ in range(ancount):
        _, off = _read_name(data, off)
        rtype, _, _, rdlen = struct.unpack(">HHHI", data[off:off + 10])
        off += 10
        rdata = data[off:off + rdlen]
        off += rdlen
        if rtype == 1 and rdlen == 4:
            answers.append(socket.inet_ntoa(rdata))
        elif rtype == 28 and rdlen == 16:
            answers.append(str(ipaddress.IPv6Address(rdata)))
    return answers, ""


def _resolve(name, servers, resolve6, timeout):
    """Try each server in order; first success wins per family."""
    answers: list[str] = []
    answers6: list[str] = []
    used = ""
    error = ""
    for server in servers:
        try:
            a, err = _dns_query(server, name, 1, timeout)
        except Exception as e:
            err = str(e)
            a = []
        if a:
            answers = a
            used = server
            break
        error = err or error
    if resolve6:
        for server in servers:
            try:
                a6, err6 = _dns_query(server, name, 28, timeout)
            except Exception as e:
                err6 = str(e)
                a6 = []
            if a6:
                answers6 = a6
                used = used or server
                break
            error = err6 or error
    return answers, answers6, used, error


def _read_head(sock, deadline, cap=16384):
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < cap:
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf[:cap]


def _parse_head(head: bytes):
    try:
        text = head.decode("latin1")
    except Exception:
        return None, {}
    lines = text.split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        return None, {}
    parts = lines[0].split(" ", 2)
    try:
        status = int(parts[1])
    except (IndexError, ValueError):
        return None, {}
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        headers[name] = f"{headers[name]}, {value}" \
            if name in headers else value
    return status, headers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--secure", type=int, default=0)
    ap.add_argument("--method", default="GET")
    ap.add_argument("--dns-servers", default="")
    ap.add_argument("--resolve6", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--hold", type=float, default=25.0)
    args = ap.parse_args()
    started = time.monotonic()
    deadline = started + args.timeout
    target = args.target
    is_ip = False
    try:
        ipaddress.ip_address(target)
        is_ip = True
    except ValueError:
        pass
    dial_ip = target
    if not is_ip:
        servers = [s for s in args.dns_servers.split(",") if s]
        answers, answers6, used, error = _resolve(
            target, servers, bool(args.resolve6), 5.0)
        ok = bool(answers or answers6)
        event = {"event": "dns", "server": used, "ok": ok,
                 "answers": answers,
                 "ms": int((time.monotonic() - started) * 1000)}
        if answers6 is not None:
            event["answers6"] = answers6
        if not ok:
            event["error"] = error or "no answer"
        _emit(event)
        if not ok:
            _emit({"event": "error", "stage": "dns",
                   "error": error or "no answer",
                   "ms": int((time.monotonic() - started) * 1000)})
            return 0
        dial_ip = answers[0] if answers else answers6[0]
    try:
        sock = socket.create_connection(
            (dial_ip, args.port),
            timeout=max(0.1, deadline - time.monotonic()))
    except Exception as e:
        _emit({"event": "error", "stage": "connect", "error": str(e),
               "ms": int((time.monotonic() - started) * 1000)})
        return 0
    local_ip, local_port = sock.getsockname()[:2]
    _emit({"event": "connected", "remoteAddress": dial_ip,
           "localAddress": local_ip, "localPort": local_port,
           "ms": int((time.monotonic() - started) * 1000)})
    if args.secure:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(
                sock, server_hostname=None if is_ip else target)
            sock.settimeout(max(0.1, deadline - time.monotonic()))
        except Exception as e:
            _emit({"event": "error", "stage": "tls", "error": str(e),
                   "ms": int((time.monotonic() - started) * 1000)})
            return 0
        if args.method == "TLS":
            _emit({"event": "response", "status": None, "headers": {},
                   "ms": int((time.monotonic() - started) * 1000)})
            time.sleep(args.hold)
            return 0
    if args.method in ("GET", "HEAD"):
        try:
            default_port = 443 if args.secure else 80
            host_hdr = target if args.port == default_port \
                else f"{target}:{args.port}"
            sock.sendall(
                f"{args.method} / HTTP/1.1\r\nHost: {host_hdr}\r\n"
                f"Connection: close\r\n\r\n".encode())
            head = _read_head(sock, deadline)
        except Exception as e:
            _emit({"event": "error", "stage": "http", "error": str(e),
                   "ms": int((time.monotonic() - started) * 1000)})
            return 0
        status, headers = _parse_head(head)
        if status is None:
            _emit({"event": "error", "stage": "http",
                   "error": "no HTTP response",
                   "ms": int((time.monotonic() - started) * 1000)})
            return 0
        _emit({"event": "response", "status": status, "headers": headers,
               "ms": int((time.monotonic() - started) * 1000)})
    else:
        _emit({"event": "response", "status": None, "headers": {},
               "ms": int((time.monotonic() - started) * 1000)})
    time.sleep(args.hold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
