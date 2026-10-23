"""Startup verification for the sing-box kernel (v5 deploy对照).

After a start/restart, read the kernel log for FATAL lines that appeared
*during this start* and report a clear result instead of "see log":

- running, no new FATAL            -> ok
- running, new FATAL present       -> ok with warning (process is up, but
                                      something fatal was logged)
- not running, new FATAL present   -> failed, with the last FATAL line and
                                      a recovery hint (re-apply, or the
                                      direct-only rollback endpoint)
- not running, no new FATAL       -> failed, unknown reason (points at the
                                      log endpoint, does not blame old lines)

Log format notes (observed on the live box, matching v5's stripAnsi):
sing-box wraps the level in ANSI SGR codes (``\\x1b[31mFATAL\\x1b[0m[0000] ...``),
so lines are stripped before matching. A FATAL line is a line whose *level*
is FATAL (line start after stripping), not a line merely containing the word.

"New" lines are determined two ways (v5's two criteria): by byte offset when
the log only appended (the normal case — start() opens the log in append
mode), or by anchoring on the snapshot's last line when the file was
truncated/rotated. If the anchor is gone, the file was replaced, so the
whole current tail postdates the snapshot. An unchanged log anchors cleanly
and yields no new lines, so old FATAL lines are never blamed on a new start.
"""

from __future__ import annotations

import os
import re
import time

ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
FATAL_RE = re.compile(r"^FATAL(\[|\s|$)")
TAIL_BYTES = 256 * 1024
MAX_LINES = 500


def strip_ansi(line: str) -> str:
    """Remove SGR color codes (v5: stripAnsi)."""
    return ANSI_SGR_RE.sub("", line)


def is_fatal_line(line: str) -> bool:
    """True when the line's log level is FATAL (after stripping ANSI)."""
    return FATAL_RE.match(strip_ansi(line).lstrip()) is not None


def _read_tail_bytes(path: str, nbytes: int = TAIL_BYTES) -> bytes:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > nbytes:
                f.seek(size - nbytes)
            return f.read()
    except OSError:
        return b""


def snapshot_log(path: str | None) -> dict | None:
    """Snapshot the log before a start: byte size + last line.

    Returns None when the log is missing/unreadable (verification then
    reports 'no new FATAL' rather than failing).
    """
    if not path:
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    tail = _read_tail_bytes(path)
    lines = tail.decode("utf-8", "replace").splitlines()
    last = lines[-1] if lines else ""
    return {"size": size, "last_line": last}


def new_lines_since(path: str | None, snapshot: dict | None) -> list[str]:
    """Lines appended to the log since the snapshot (raw, ANSI intact)."""
    if not path or not snapshot:
        return []
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    # Criterion 1: pure append — read from the snapshot offset.
    if size > snapshot["size"]:
        try:
            with open(path, "rb") as f:
                f.seek(snapshot["size"])
                data = f.read()
            return data.decode("utf-8", "replace").splitlines()
        except OSError:
            return []
    # Criterion 2: truncated/rotated — anchor on the snapshot's last line.
    # If the anchor is gone, the file was replaced: everything now in it
    # was written after the snapshot, so the whole tail is new.
    tail = _read_tail_bytes(path).decode("utf-8", "replace").splitlines()
    tail = tail[-MAX_LINES:]
    anchor = snapshot.get("last_line", "")
    if anchor:
        for i in range(len(tail) - 1, -1, -1):
            if tail[i] == anchor:
                return tail[i + 1:]
    return tail


def last_fatal_line(lines: list[str], limit: int = 300) -> str | None:
    """Last FATAL line among the given lines (ANSI stripped, truncated).

    Only the last one is returned (v5: newFatalLines takes the last FATAL).
    """
    for line in reversed(lines):
        clean = strip_ansi(line).strip()
        if is_fatal_line(clean):
            return clean[:limit]
    return None


def verify_start(manager, before: dict | None, settle_s: float = 3.0) -> dict:
    """Verify a start/restart against the manager, v5 [0, 3000] polls.

    First poll is immediate; if the kernel is not running, one more poll
    after settle_s. Returns an additive dict for the service response.
    Never raises (a verification failure must not mask the start result).
    """
    try:
        st = manager.status()
        if not st.running and settle_s > 0:
            time.sleep(settle_s)
            st = manager.status()
        new_lines = new_lines_since(manager.log_path, before)
        fatal = last_fatal_line(new_lines)
        pid = st.pid if st.running else None
        if st.running and fatal is None:
            return {"ok": True, "state": "running", "pid": pid,
                    "fatal": None, "message": "内核运行正常"}
        if st.running:
            return {"ok": True, "state": "running_with_warnings", "pid": pid,
                    "fatal": fatal,
                    "message": f"内核已启动，但启动期间日志出现 FATAL 行：{fatal}（进程仍在运行，请留意）"}
        if fatal is not None:
            return {"ok": False, "state": "failed", "pid": None,
                    "fatal": fatal,
                    "message": f"内核启动失败：{fatal}。配置：{manager.config_path}；"
                               "可重新 apply 生成配置，或用 /api/deploy/rollback 恢复直连配置。"}
        return {"ok": False, "state": "failed", "pid": None,
                "fatal": None,
                "message": "内核启动失败，日志中未见 FATAL 行（见 /api/service/log）；"
                           f"配置：{manager.config_path}。"}
    except Exception as e:  # verification must never break the endpoint
        return {"ok": False, "state": "unknown", "pid": None,
                "fatal": None, "message": f"启动验证未完成：{e}"}
