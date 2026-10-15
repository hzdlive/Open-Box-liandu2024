"""ARP / neighbor table reading: resolve MAC <-> IP for terminal policies.

Terminal idents may be an IP, a CIDR, or a MAC address. IP/CIDR idents are
used verbatim; MAC idents are resolved to their current LAN IP via the ARP
table when a config is built (sing-box route rules are L3-only), while the
nftables bypass path can match MACs directly (ether saddr).
"""

from __future__ import annotations

import os
import re
import subprocess

_MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


def is_mac(s: str) -> bool:
    return bool(_MAC_RE.match((s or "").strip()))


def normalize_mac(s: str) -> str:
    return (s or "").strip().lower()


def arp_table() -> dict[str, str]:
    """Return {ip: mac} from the kernel ARP table. Empty on failure."""
    out: dict[str, str] = {}
    # /proc/net/arp: IP address, HW type, Flags, HW address, Mask, Device
    try:
        with open("/proc/net/arp", encoding="utf-8") as f:
            lines = f.read().splitlines()[1:]
        for ln in lines:
            parts = ln.split()
            if len(parts) >= 6 and is_mac(parts[3]) and parts[2] != "0x0":
                out[parts[0]] = normalize_mac(parts[3])
        if out:
            return out
    except OSError:
        pass
    # fallback: ip neigh show
    try:
        r = subprocess.run(["ip", "neigh", "show"], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return out
    for ln in r.stdout.splitlines():
        m = re.search(r"^(\S+)\s+.*lladdr\s+(([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})",
                      ln)
        if m and "FAILED" not in ln and "INCOMPLETE" not in ln:
            out[m.group(1)] = normalize_mac(m.group(2))
    return out


def mac_to_ips(mac: str, table: dict[str, str] | None = None) -> list[str]:
    """Current IPs using this MAC (usually 0 or 1)."""
    mac = normalize_mac(mac)
    table = table if table is not None else arp_table()
    return [ip for ip, m in table.items() if m == mac]


def split_mac_ip(idents: list[str]) -> tuple[list[str], list[str]]:
    """Split idents into (macs, ip_or_cidr)."""
    macs, ips = [], []
    for i in idents:
        (macs if is_mac(i) else ips).append(i.strip())
    return macs, ips


def expand_terminal_idents(idents: list[str],
                           table: dict[str, str] | None = None) -> list[str]:
    """Expand idents to IP/CIDR strings for L3 consumers (sing-box routes).

    MAC idents resolve to their current ARP IP; unresolvable MACs are
    dropped (caller should warn). Duplicates removed, order kept.
    """
    if table is None:
        table = arp_table()
    out: list[str] = []
    for ident in idents:
        ident = ident.strip()
        if is_mac(ident):
            out.extend(mac_to_ips(ident, table))
        elif ident:
            out.append(ident)
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq
