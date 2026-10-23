"""Self-test for kernel conflict detection (core/conflicts.py)."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import conflicts as cf  # noqa: E402


class FakeManager:
    def __init__(self, pid, config_path):
        self._pid = pid
        self.config_path = config_path

    def _read_pid(self):
        return self._pid


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _proc_pid(proc: str, pid: int, cmdline: bytes, comm: str = "",
              fds: dict | None = None) -> None:
    d = os.path.join(proc, str(pid))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "cmdline"), "wb") as f:
        f.write(cmdline)
    if comm:
        _write(os.path.join(d, "comm"), comm + "\n")
    if fds:
        fd_dir = os.path.join(d, "fd")
        os.makedirs(fd_dir, exist_ok=True)
        for fd, target in fds.items():
            os.symlink(target, os.path.join(fd_dir, str(fd)))


TCP_LINE = ("   0: 0100007F:2382 00000000:0000 0A 00000000:00000000 "
            "00:00000000 00000000  0        0 12345 1 0000000000000000 "
            "100 0 0 10 0\n")
TCP_TIMEWAIT = ("   1: 0100007F:2382 00000000:0000 06 00000000:00000000 "
                "00:00000000 00000000  0        0 55555 1 0000000000000000 "
                "100 0 0 10 0\n")
TCP_OTHER_ADDR = ("   2: 0200007F:2382 00000000:0000 0A 00000000:00000000 "
                   "00:00000000 00000000  0        0 99999 1 0000000000000000 "
                   "100 0 0 10 0\n")


def main() -> int:
    # IP parsing
    assert cf._parse_proc_ip("0100007F", False) == "127.0.0.1"
    assert cf._parse_proc_ip("00000000", False) == "0.0.0.0"
    assert cf._parse_proc_ip("00000000000000000000000001000000", True) == "::1"
    assert cf._parse_proc_ip("00000000000000000000000000000000", True) == "::"
    # host:port parsing
    assert cf._split_host_port("127.0.0.1:9090") == ("127.0.0.1", 9090)
    assert cf._split_host_port("[::1]:9090") == ("::1", 9090)
    assert cf._split_host_port("9090") is None
    # overlap rules
    assert cf._address_overlaps("127.0.0.1", "0.0.0.0")
    assert cf._address_overlaps("127.0.0.1", "127.0.0.1")
    assert not cf._address_overlaps("127.0.0.1", "127.0.0.2")
    # IPv6 wildcard binds dual-stack on Linux, so it blocks IPv4 too;
    # a v6 loopback address does not.
    assert cf._address_overlaps("127.0.0.1", "::")
    assert not cf._address_overlaps("127.0.0.1", "::1")
    assert cf._address_overlaps("::1", "::")

    with tempfile.TemporaryDirectory() as td:
        proc = os.path.join(td, "proc")
        _write(os.path.join(proc, "net", "tcp"),
               "sl local_address rem_address st\n"
               + TCP_LINE + TCP_TIMEWAIT + TCP_OTHER_ADDR)
        _write(os.path.join(proc, "net", "tcp6"), "sl local_address\n")
        cfg_path = os.path.join(td, "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"experimental": {"clash_api": {"external_controller": "127.0.0.1:9090"}},
                       "inbounds": [{"type": "mixed", "listen": "0.0.0.0", "listen_port": 7080}]},
                      f)
        _proc_pid(proc, 1000, b"python\0server.py\0", "python",
                  {3: "socket:[12345]"})
        _proc_pid(proc, 2000, b"other\0", "other", {7: "socket:[99999]"})
        _proc_pid(proc, 3000, b"sing-box\0run\0-c\0/cfg/a.json\0", "sing-box")
        _proc_pid(proc, 3001, b"python\0app.py\0", "python")
        _proc_pid(proc, 3002, b"/usr/local/bin/sing-box\0run\0-c\0/other.json\0",
                  "sing-box")
        _proc_pid(proc, 3003, b"sing-box\0run\0-c\0" + cfg_path.encode() + b"\0",
                  "sing-box")

        # port holders: TIME_WAIT ignored, both LISTEN addrs reported
        holders = cf.find_port_holders(9090, proc)
        assert sorted(h["pid"] for h in holders) == [1000, 2000], holders
        assert holders[0]["local_ip"] == "127.0.0.1"
        assert holders[1]["local_ip"] == "127.0.0.2"
        assert cf.find_port_holders(19090, proc) == []

        # kernel process scan: python skipped, sing-box found
        procs = cf.scan_kernel_processes(proc)
        assert sorted(p["pid"] for p in procs) == [3000, 3002, 3003], procs
        assert cf._config_path_from_argv(["sing-box", "run", "-c", "/x.json"]) == "/x.json"
        assert cf._config_path_from_argv(["sing-box", "run", "-c/x.json"]) == "/x.json"

        # our kernel running (pid 3000): only the rival config flagged as a
        # process; 127.0.0.1:9090 holder is a port conflict; 127.0.0.2 is not
        # (different loopback); same-config pid 3003 is not a conflict.
        m = FakeManager(3000, cfg_path)
        confs = cf.detect_conflicts(m, proc)
        types = sorted(c["type"] for c in confs)
        assert types == ["external_process", "port_in_use"], confs
        ext = [c for c in confs if c["type"] == "external_process"][0]
        assert ext["pid"] == 3002 and ext["config_path"] == "/other.json"
        port = [c for c in confs if c["type"] == "port_in_use"][0]
        assert port["port"] == 9090 and port["holder_pid"] == 1000
        # message join
        msg = cf.conflict_message(confs)
        assert "3002" in msg and "9090" in msg

        # our kernel stopped: pidfile is gone, so 3000 (different config)
        # counts as a rival too; 3003 (same config) still does not.
        m = FakeManager(None, cfg_path)
        confs = cf.detect_conflicts(m, proc)
        assert sorted(c["type"] for c in confs) == [
            "external_process", "external_process", "port_in_use"], confs
        assert 3003 not in [c.get("pid") for c in confs]

        # clean box: no rival procs, no holders -> no conflicts
        proc2 = os.path.join(td, "proc2")
        _write(os.path.join(proc2, "net", "tcp"), "sl local_address\n")
        _write(os.path.join(proc2, "net", "tcp6"), "sl local_address\n")
        _proc_pid(proc2, 3000, b"sing-box\0run\0-c\0" + cfg_path.encode() + b"\0",
                  "sing-box")
        m = FakeManager(3000, cfg_path)
        assert cf.detect_conflicts(m, proc2) == []

    # conflict_auto_stopped: four-way conjunction (Debian mapping)
    assert cf.conflict_auto_stopped(False, [{"type": "port_in_use"}], "2026-10-23T00:00:00")
    assert not cf.conflict_auto_stopped(True, [{"type": "port_in_use"}], "rec")
    assert not cf.conflict_auto_stopped(False, [], "rec")
    assert not cf.conflict_auto_stopped(False, [{"type": "port_in_use"}], "")

    print("OK: conflicts — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
