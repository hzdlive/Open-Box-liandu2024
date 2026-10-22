"""sing-box kernel lifecycle management.

Clean-room reimplementation of the publicly documented behavior:
install / start / stop / restart / status / log tail for the sing-box
kernel process. Uses only the public sing-box CLI surface
(`version`, `check -c`, `run -c`). No proprietary code involved.
"""

from __future__ import annotations

import json
import os
import platform as _platform
import signal
import subprocess
import time
from dataclasses import dataclass, field

PANEL_VERSION = "0.1.0-oss"


@dataclass
class ServiceStatus:
    installed: bool
    running: bool
    pid: int | None = None
    version: str | None = None
    uptime_s: float | None = None
    config_path: str | None = None


@dataclass
class KernelManager:
    """Manages one sing-box kernel process via a pidfile."""

    bin_path: str
    workdir: str
    config_path: str | None = None
    log_path: str | None = None
    start_timeout: float = 10.0

    def __post_init__(self) -> None:
        os.makedirs(self.workdir, exist_ok=True)
        if self.config_path is None:
            self.config_path = os.path.join(self.workdir, "config.json")
        if self.log_path is None:
            self.log_path = os.path.join(self.workdir, "sing-box.log")

    @property
    def pidfile(self) -> str:
        return os.path.join(self.workdir, "sing-box.pid")

    # -- discovery -----------------------------------------------------
    def is_installed(self) -> bool:
        return os.path.isfile(self.bin_path) and os.access(self.bin_path, os.X_OK)

    def version(self) -> str | None:
        if not self.is_installed():
            return None
        try:
            out = subprocess.run(
                [self.bin_path, "version"], capture_output=True, text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode != 0:
            return None
        # e.g. "sing-box version 1.14.1-openbox-tcp23 ..."
        for line in out.stdout.splitlines():
            if "version" in line:
                parts = line.strip().split()
                try:
                    return parts[parts.index("version") + 1]
                except (ValueError, IndexError):
                    return line.strip()
        return out.stdout.strip().splitlines()[0] if out.stdout.strip() else None

    def check_config(self, path: str | None = None) -> tuple[bool, str]:
        """Validate a config file with `sing-box check -c`. Returns (ok, message)."""
        if not self.is_installed():
            return False, "sing-box not installed"
        target = path or self.config_path
        try:
            out = subprocess.run(
                [self.bin_path, "check", "-c", target],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        msg = (out.stdout + out.stderr).strip() or "ok"
        return out.returncode == 0, msg

    # -- process control -----------------------------------------------
    def _read_pid(self) -> int | None:
        try:
            with open(self.pidfile) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            # EPERM 算活着（对标原版：pid 存活判定里 EPERM 视为在跑）：
            # 进程属于其他用户、信号发不出去，但进程确实存在。
            return pid
        except OSError:
            return None
        return pid

    def _scan_pid(self) -> tuple[int | None, float | None]:
        """Fallback: find a sing-box process started outside the panel
        (manual run, init script, old CLI). Returns (pid, uptime_s)."""
        me = os.getpid()
        procdir = "/proc"
        try:
            pids = [p for p in os.listdir(procdir) if p.isdigit()]
        except OSError:
            return None, None
        for p in pids:
            ipid = int(p)
            if ipid == me:
                continue
            try:
                with open(f"{procdir}/{p}/cmdline", "rb") as f:
                    parts = f.read().split(b"\0")
            except OSError:
                continue
            if not parts or not parts[0]:
                continue
            exe = parts[0].decode(errors="replace")
            base = os.path.basename(exe)
            if base == "sing-box" or exe == self.bin_path or base == "openbox-core":
                try:
                    uptime = time.time() - os.path.getmtime(f"{procdir}/{p}")
                except OSError:
                    uptime = None
                return ipid, uptime
        return None, None

    def _resolve_pid(self) -> tuple[int | None, float | None, bool]:
        """(pid, uptime_s, external). Prefers our pidfile, falls back to a
        system-wide scan for sing-box started outside the panel."""
        pid = self._read_pid()
        if pid is not None:
            try:
                uptime_s = time.time() - os.path.getmtime(self.pidfile)
            except OSError:
                uptime_s = None
            return pid, uptime_s, False
        pid, uptime_s = self._scan_pid()
        return pid, uptime_s, pid is not None

    def status(self) -> ServiceStatus:
        pid, uptime_s, _external = self._resolve_pid()
        st = ServiceStatus(
            installed=self.is_installed(),
            running=pid is not None,
            pid=pid,
            version=self.version() if self.is_installed() else None,
            config_path=self.config_path,
        )
        st.uptime_s = uptime_s
        return st

    def start(self) -> ServiceStatus:
        """Start the kernel. Raises RuntimeError on failure."""
        if self._read_pid() is not None:
            return self.status()
        if not self.is_installed():
            raise RuntimeError("sing-box not installed")
        if not os.path.isfile(self.config_path or ""):
            raise RuntimeError(f"config not found: {self.config_path}")
        logf = open(self.log_path, "a")
        try:
            proc = subprocess.Popen(
                [self.bin_path, "run", "-c", self.config_path],
                stdout=logf, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
        finally:
            logf.close()
        with open(self.pidfile, "w") as f:
            f.write(str(proc.pid))
        deadline = time.time() + self.start_timeout
        while time.time() < deadline:
            if self._read_pid() is None:
                raise RuntimeError("sing-box exited during startup; see log")
            time.sleep(0.2)
            # process survived the grace window -> consider started
            if time.time() - os.path.getmtime(self.pidfile) > 0.5:
                break
        return self.status()

    def stop(self, timeout: float = 10.0) -> ServiceStatus:
        pid, _uptime, _external = self._resolve_pid()
        if pid is None:
            self._clear_pidfile()
            return self.status()
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._clear_pidfile()
            return self.status()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError):
                break
            time.sleep(0.2)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self._clear_pidfile()
        return self.status()

    def restart(self) -> ServiceStatus:
        self.stop()
        time.sleep(0.5)
        return self.start()

    def _clear_pidfile(self) -> None:
        try:
            os.remove(self.pidfile)
        except OSError:
            pass

    def log_tail(self, n: int = 200) -> str:
        try:
            with open(self.log_path, "rb") as f:
                data = f.read().splitlines()[-n:]
            return b"\n".join(data).decode("utf-8", "replace")
        except OSError:
            return ""

    def to_dict(self) -> dict:
        st = self.status()
        return {
            "installed": st.installed,
            "running": st.running,
            "pid": st.pid,
            "version": st.version,
            "uptime_s": round(st.uptime_s, 1) if st.uptime_s is not None else None,
            "config_path": st.config_path,
            "bin_path": self.bin_path,
            "platform": detect_platform(),
            "arch": _platform.machine(),
            "os_version": os_pretty_name(),
            "autostart": detect_autostart(),
            "panel_version": PANEL_VERSION,
        }


def detect_platform() -> str:
    """openwrt | systemd | other — best effort, never raises."""
    try:
        if os.path.isfile("/etc/openwrt_release"):
            return "openwrt"
        if os.path.isdir("/run/systemd/system"):
            return "systemd"
    except OSError:
        pass
    return "other"


def os_pretty_name() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return f"{_platform.system()} {_platform.release()}".strip()


def detect_autostart() -> str:
    """enabled | disabled | unknown — checks our own init artifacts only."""
    try:
        if os.path.isfile("/etc/init.d/openbox-oss"):
            return "enabled"
        for p in ("/etc/systemd/system/openbox-oss.service",
                  os.path.expanduser("~/.config/systemd/user/openbox-oss.service")):
            if os.path.isfile(p):
                return "enabled"
    except OSError:
        pass
    return "unknown"


def default_workdir() -> str:
    return os.path.join(os.path.expanduser("~"), ".openbox-oss")


def manager_from_env(bin_path: str | None = None,
                     workdir: str | None = None) -> KernelManager:
    """Build a manager from env overrides (OPENBOX_SINGBOX_BIN / OPENBOX_WORKDIR)."""
    return KernelManager(
        bin_path=bin_path or os.environ.get("OPENBOX_SINGBOX_BIN", "/usr/local/bin/sing-box"),
        workdir=workdir or os.environ.get("OPENBOX_WORKDIR", default_workdir()),
    )
