"""Terminal connectivity probe: ping + TCP connect to a LAN target.

Clean-room reimplementation of the publicly observable behavior:
- capability check (what the box can do: ping binary? raw TCP?),
- probe a target IP/hostname: ICMP latency + a few common TCP ports.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time


def capability() -> dict:
    """What LAN probing can this box do?"""
    return {
        "ping": shutil.which("ping") is not None,
        "tcp": True,  # plain sockets, always available
        "arp": shutil.which("arp") is not None or shutil.which("ip") is not None,
    }


def _ping(host: str, timeout: float = 3.0) -> dict:
    if not shutil.which("ping"):
        return {"ok": False, "error": "ping not available"}
    try:
        p = subprocess.run(["ping", "-c", "2", "-W", str(int(timeout)), host],
                           capture_output=True, text=True, timeout=timeout + 2)
        out = p.stdout
        ms = None
        for line in out.splitlines():
            if "avg" in line or "min/avg" in line:
                # e.g. "rtt min/avg/max/mdev = 0.5/0.6/0.7/0.1 ms"
                try:
                    ms = float(line.split("=")[1].split("/")[1].strip())
                except (IndexError, ValueError):
                    pass
        return {"ok": p.returncode == 0, "latency_ms": ms,
                "detail": out.strip().splitlines()[-1] if out.strip() else ""}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)[:120]}


def _tcp_probe(host: str, ports: list[int], timeout: float = 2.0) -> dict:
    open_ports = []
    for port in ports:
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            open_ports.append(port)
        except OSError:
            pass
    return {"open_ports": open_ports, "tested": ports}


def probe(target: str, timeout: float = 3.0) -> dict:
    """Probe a terminal target. Returns ping + TCP results."""
    target = target.strip()
    if not target:
        return {"ok": False, "error": "target required"}
    t0 = time.monotonic()
    ping_r = _ping(target, timeout)
    tcp_r = _tcp_probe(target, [22, 80, 443, 8080], timeout)
    ms = (time.monotonic() - t0) * 1000
    return {"ok": ping_r.get("ok") or bool(tcp_r["open_ports"]),
            "target": target,
            "ping": ping_r, "tcp": tcp_r,
            "elapsed_ms": round(ms, 1)}
