"""Kernel conflict detection (v4 service/status + v5 preflight 对照).

The original's two conflict criteria, translated to Debian:

1. **Another kernel process** — the original checks whether the init script
   says the service runs, or the install path appears in some process's
   argv. Here: any ``sing-box``/``openbox-core`` process whose pid is not
   our pidfile pid, and whose ``-c`` config path is not our config path
   (same config + stale pidfile means "our kernel, adopted", not a
   conflict).
2. **A port we need is held by someone else** — the original's preflight
   conflict gate aborts the deploy before anything else. Here: the clash
   API port and every inbound listen port from our config. A holder counts
   only when its bind overlaps ours (wildcard, or the same address).
   When our kernel runs and the holder cannot be identified (fd scan
   denied), the port is assumed ours — a permission-limited scan must not
   block a healthy kernel.

``conflict_auto_stopped`` is the Debian equivalent of the original's
four-way conjunction (not running + conflict + last deploy stage was
"conflict" + autoStopped). We have no deploy-stage machine — our
``deploy_state`` is just the last apply result — so the last two terms map
to one record: the start gate refused a start because of a conflict
(``conflict_stop_at``/``conflict_stop_detail`` in settings, cleared on the
next successful start). The flag is therefore "the kernel is down and the
last thing that kept it down was a conflict refusal", which is the same
user-facing meaning: don't be surprised it's stopped — a conflict stopped
it from starting.

Everything here is pure stdlib /proc parsing (no ``ss`` dependency) and
never raises: a failed scan yields no conflicts, never a crash.
"""

from __future__ import annotations

import ipaddress
import json
import os

KERNEL_NAMES = ("sing-box", "openbox-core")
LISTEN_STATE = "0A"


class ConflictError(RuntimeError):
    """Raised by start() when a conflict refuses the start."""

    def __init__(self, conflicts: list[dict]):
        self.conflicts = conflicts
        super().__init__(conflict_message(conflicts))


# ---------------------------------------------------------------- proc scan

def _read_cmdline(proc_dir: str, pid: str) -> list[str]:
    try:
        with open(os.path.join(proc_dir, pid, "cmdline"), "rb") as f:
            parts = f.read().split(b"\0")
        return [p.decode(errors="replace") for p in parts if p]
    except OSError:
        return []


def _config_path_from_argv(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "-c" or arg == "--config":
            if i + 1 < len(argv):
                return argv[i + 1]
        elif arg.startswith("-c") and len(arg) > 2 and not arg.startswith("--"):
            return arg[2:]
        elif arg.startswith("--config="):
            return arg[len("--config="):]
    return None


def scan_kernel_processes(proc_dir: str = "/proc") -> list[dict]:
    """All sing-box/openbox-core processes visible in /proc."""
    out: list[dict] = []
    try:
        pids = [p for p in os.listdir(proc_dir) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        if int(pid) == os.getpid():
            continue
        argv = _read_cmdline(proc_dir, pid)
        if not argv:
            continue
        name = os.path.basename(argv[0])
        if name not in KERNEL_NAMES:
            continue
        out.append({
            "pid": int(pid),
            "process": name,
            "cmdline": " ".join(argv),
            "config_path": _config_path_from_argv(argv),
        })
    return out


# ---------------------------------------------------------------- port scan

def _parse_proc_ip(hex_ip: str, v6: bool) -> str:
    try:
        raw = bytes.fromhex(hex_ip)
        if v6:
            words = [raw[i:i + 4][::-1] for i in range(0, 16, 4)]
            return ipaddress.IPv6Address(b"".join(words)).compressed
        return ipaddress.IPv4Address(raw[::-1]).compressed
    except (ValueError, IndexError):
        return ""


def _listen_inodes(proc_dir: str, port: int) -> list[tuple[str, str]]:
    """(local_ip, inode) for LISTEN sockets on the given port."""
    found: list[tuple[str, str]] = []
    for name, v6 in (("tcp", False), ("tcp6", True)):
        try:
            with open(os.path.join(proc_dir, "net", name)) as f:
                lines = f.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            local_ip_hex, local_port_hex = fields[1].rsplit(":", 1)
            try:
                local_port = int(local_port_hex, 16)
            except ValueError:
                continue
            if local_port != port or fields[3] != LISTEN_STATE:
                continue
            found.append((_parse_proc_ip(local_ip_hex, v6), fields[9]))
    return found


def _inode_holders(proc_dir: str, inodes: set[str]) -> dict[str, tuple[int, str]]:
    """inode -> (pid, process) for processes holding those sockets."""
    holders: dict[str, tuple[int, str]] = {}
    if not inodes:
        return holders
    try:
        pids = [p for p in os.listdir(proc_dir) if p.isdigit()]
    except OSError:
        return holders
    for pid in pids:
        fd_dir = os.path.join(proc_dir, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        comm = ""
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in inodes:
                if not comm:
                    try:
                        with open(os.path.join(proc_dir, pid, "comm")) as f:
                            comm = f.read().strip()
                    except OSError:
                        comm = "unknown"
                holders[target[8:-1]] = (int(pid), comm or "unknown")
    return holders


def find_port_holders(port: int, proc_dir: str = "/proc") -> list[dict]:
    """Processes (or unknown holders) LISTENing on the port."""
    listeners = _listen_inodes(proc_dir, port)
    if not listeners:
        return []
    holders = _inode_holders(proc_dir, {inode for _, inode in listeners})
    out: list[dict] = []
    for local_ip, inode in listeners:
        pid, process = holders.get(inode, (None, "unknown"))
        out.append({"pid": pid, "process": process, "local_ip": local_ip})
    return out


# ---------------------------------------------------------------- detection

def _split_host_port(value: str) -> tuple[str, int] | None:
    value = value.strip()
    if value.startswith("["):
        # [::1]:9090
        try:
            host, port = value.rsplit("]:", 1)
            return host[1:], int(port)
        except ValueError:
            return None
    if ":" not in value:
        return None
    host, port = value.rsplit(":", 1)
    try:
        return host or "0.0.0.0", int(port)
    except ValueError:
        return None


def _config_listen_ports(config_path: str | None) -> list[tuple[str, int]]:
    """(host, port) pairs our kernel will bind: clash API + inbounds."""
    if not config_path:
        return []
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return []
    ports: list[tuple[str, int]] = []
    clash = (cfg.get("experimental") or {}).get("clash_api") or {}
    if clash.get("external_controller"):
        parsed = _split_host_port(str(clash["external_controller"]))
        if parsed:
            ports.append(parsed)
    for inbound in cfg.get("inbounds") or []:
        listen_port = inbound.get("listen_port")
        if not listen_port:
            continue
        listen = inbound.get("listen") or "0.0.0.0"
        try:
            ports.append((str(listen), int(listen_port)))
        except (TypeError, ValueError):
            continue
    return ports


def _is_wildcard(ip: str) -> bool:
    return ip in ("0.0.0.0", "::")


def _address_overlaps(listen_ip: str, holder_ip: str) -> bool:
    """True when the holder's bind blocks our listen address."""
    if _is_wildcard(holder_ip):
        return True
    try:
        listen = ipaddress.ip_address("127.0.0.1" if listen_ip == "localhost"
                                      else listen_ip)
        holder = ipaddress.ip_address(holder_ip)
    except ValueError:
        return listen_ip == holder_ip
    if listen.version != holder.version:
        return False
    return listen == holder


def _same_path(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return os.path.abspath(a) == os.path.abspath(b)


def detect_conflicts(manager, proc_dir: str = "/proc") -> list[dict]:
    """Conflicts for the manager's kernel. Never raises."""
    try:
        return _detect_conflicts(manager, proc_dir)
    except Exception:
        return []


def _detect_conflicts(manager, proc_dir: str) -> list[dict]:
    try:
        our_pid = manager._read_pid()
    except Exception:
        our_pid = None
    our_config = getattr(manager, "config_path", None)
    conflicts: list[dict] = []
    flagged_pids: set[int] = set()

    for proc in scan_kernel_processes(proc_dir):
        if our_pid is not None and proc["pid"] == our_pid:
            continue
        if _same_path(proc["config_path"], our_config):
            continue  # our kernel with a stale/missing pidfile, not a rival
        conflicts.append({
            "type": "external_process",
            "pid": proc["pid"],
            "process": proc["process"],
            "config_path": proc["config_path"],
            "message": (
                f"检测到另一个内核进程 {proc['process']} (pid {proc['pid']}) 正在运行"
                + (f"，配置 {proc['config_path']}" if proc["config_path"]
                   else "，配置路径未识别")),
        })
        flagged_pids.add(proc["pid"])

    for listen_ip, port in _config_listen_ports(our_config):
        for holder in find_port_holders(port, proc_dir):
            if holder["pid"] is not None and holder["pid"] in flagged_pids:
                continue  # already explained by the process entry
            if our_pid is not None and holder["pid"] is None:
                continue  # unidentified holder while we run: assume ours
            if holder["pid"] == our_pid:
                continue
            if not _address_overlaps(listen_ip, holder["local_ip"]):
                continue
            who = (f"{holder['process']} (pid {holder['pid']})"
                   if holder["pid"] is not None else "未知进程")
            conflicts.append({
                "type": "port_in_use",
                "port": port,
                "listen": listen_ip,
                "holder_pid": holder["pid"],
                "holder_process": holder["process"],
                "message": f"端口 {port} 已被 {who} 占用（本机监听 {listen_ip}）",
            })
            if holder["pid"] is not None:
                flagged_pids.add(holder["pid"])
    return conflicts


def conflict_message(conflicts: list[dict]) -> str:
    """One-line summary (v5 conflictMessage analog)."""
    return "；".join(c["message"] for c in conflicts)


def conflict_auto_stopped(running: bool, conflicts: list[dict],
                          record: str) -> bool:
    """Debian equivalent of the original's four-way conjunction."""
    return (not running) and bool(conflicts) and bool(record)
