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
_MAC_DASH_RE = re.compile(r"^([0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}$")


def is_mac(s: str) -> bool:
    s = (s or "").strip()
    return bool(_MAC_RE.match(s) or _MAC_DASH_RE.match(s))


def normalize_mac(s: str) -> str | None:
    """MAC 规范化（对标原版 Tn）：短横线转冒号，小写，六组十六进制校验。

    校验失败返回 None（调用方丢弃该条，不让坏值进 nft 脚本）。
    """
    s = (s or "").strip().lower().replace("-", ":")
    return s if _MAC_RE.match(s) else None


def normalize_cidr(s: str) -> str | None:
    """CIDR 规范化（对标原版 Co）：裸地址补 /32（v4）或 /128（v6），前缀越界拒绝。

    校验失败返回 None（调用方丢弃该条，不让坏值进 nft 脚本）。
    """
    import ipaddress
    s = (s or "").strip()
    if not s:
        return None
    try:
        if "/" in s:
            # 只校验前缀合法性（越界拒绝），不改写主机位，原样保留
            ipaddress.ip_network(s, strict=False)
            return s
        ip = ipaddress.ip_address(s)
        return f"{s}/{32 if ip.version == 4 else 128}"
    except ValueError:
        return None


def parse_port_spec(spec: str) -> list[str] | None:
    """端口串解析（对标原版 parsePortSpec）：单端口或 lo-hi 范围，逗号分隔。

    一条坏项否决整串（返回 None，调用方整条规则不生成），不做部分应用。
    """
    out = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            parts = item.split("-")
            if len(parts) != 2:
                return None
            try:
                lo, hi = int(parts[0]), int(parts[1])
            except ValueError:
                return None
            if not (1 <= lo <= hi <= 65535):
                return None
            out.append(f"{lo}-{hi}")
        else:
            try:
                p = int(item)
            except ValueError:
                return None
            if not (1 <= p <= 65535):
                return None
            out.append(str(p))
    return out or None


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


def ipv6_neigh_table() -> dict[str, str]:
    """Return {ipv6: mac} from IPv6 neighbor evidence, usable states only.

    v0.1.343 terminal IPv6 supplementary rules: /proc/net/arp is IPv4-only,
    so IPv6 neighbors must come from `ip -6 neigh show`. Two filters apply
    at collection, before any rule is built:

    - Entries in FAILED or INCOMPLETE state carry no usable binding and are
      excluded, as are entries without a link-layer address.
    - An address claimed by more than one distinct MAC in the same snapshot
      is ambiguous evidence and is dropped for every claimant: the fix
      generates a supplement only when evidence uniquely confirms the MAC.

    Returns {} when the command is unavailable or fails (callers then emit
    no supplement, never a guess).
    """
    pairs: list[tuple[str, str]] = []
    try:
        r = subprocess.run(["ip", "-6", "neigh", "show"], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    for ln in r.stdout.splitlines():
        m = re.search(r"^(\S+)\s+.*lladdr\s+(([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})",
                      ln)
        if m and "FAILED" not in ln and "INCOMPLETE" not in ln:
            ip = m.group(1)
            if ":" in ip:  # strict: only IPv6 entries belong here
                pairs.append((ip, normalize_mac(m.group(2))))
    claimed: dict[str, set] = {}
    for ip, mac in pairs:
        claimed.setdefault(ip, set()).add(mac)
    out: dict[str, str] = {}
    for ip, mac in pairs:
        if len(claimed[ip]) == 1:
            out[ip] = mac
    return out


def expand_terminal_supplement_v6(mac_idents: list[str],
                                  table: dict[str, str] | None = None
                                  ) -> list[str]:
    """IPv6 supplementary addresses for MAC terminal idents (v0.1.343).

    Original behavior fixed in v0.1.343: a MAC terminal's IPv6 connections
    fell through to the target policy because only its IPv4 rule existed.
    The fix generates IPv6 supplementary rules only when neighbor evidence
    uniquely confirms the MAC, and the supplement is exactly the
    intersection of IPv6 sources with that MAC:

    - Only MAC-derived IPv6 addresses. Literal idents (IP/CIDR, either
      family) are NOT included: literals already enter the main rule
      verbatim, and the supplement must not expand a MAC's addresses into
      other families (no IPv4 of the same MAC in the supplement).
    - No subnet inference: exact neighbor addresses only, never a /64 (or
      any prefix) derived from a single address.
    - Unique confirmation is enforced where evidence is collected (see
      ipv6_neigh_table): usable state only, and an address claimed by
      multiple MACs in one snapshot is dropped. This function additionally
      keeps only IPv6 entries, so even an injected table cannot leak an
      IPv4 address into the supplement.
    - Evidence source is the neighbor table. DHCP leases are not read: no
      DHCP server runs where this panel deploys (VPS), and neighbor
      evidence is the available confirmation.

    Duplicates removed, order kept. Returns [] when nothing confirms.
    """
    if table is None:
        table = ipv6_neigh_table()
    out: list[str] = []
    for ident in mac_idents or []:
        ident = (ident or "").strip()
        if not is_mac(ident):
            continue
        mac = normalize_mac(ident)
        for ip, m in table.items():
            if m == mac and ":" in ip and ip not in out:
                out.append(ip)
    return out
