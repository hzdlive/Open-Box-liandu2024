"""Self-test for startup verification (core/startverify.py)."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import startverify as sv  # noqa: E402


class FakeStatus:
    def __init__(self, running, pid=None):
        self.running = running
        self.pid = pid


class FakeManager:
    def __init__(self, log_path, states):
        self.log_path = log_path
        self.config_path = "/tmp/fake-config.json"
        self._states = list(states)

    def status(self):
        running, pid = self._states.pop(0) if len(self._states) > 1 else self._states[0]
        return FakeStatus(running, pid)


def main() -> int:
    # strip ANSI + FATAL level matching
    assert sv.strip_ansi("\x1b[31mFATAL\x1b[0m[0000] boom") == "FATAL[0000] boom"
    assert sv.is_fatal_line("\x1b[31mFATAL\x1b[0m[0000] boom")
    assert sv.is_fatal_line("FATAL listen error")
    assert not sv.is_fatal_line("\x1b[31mERROR\x1b[0m[0000] something failed")
    assert not sv.is_fatal_line("note: this mentions FATAL in the middle")
    assert not sv.is_fatal_line("")

    # last FATAL wins
    lines = ["INFO start", "\x1b[31mFATAL\x1b[0m[0000] first fatal",
             "INFO middle", "FATAL second fatal"]
    assert sv.last_fatal_line(lines) == "FATAL second fatal"
    assert sv.last_fatal_line(["INFO only"]) is None

    with tempfile.TemporaryDirectory() as td:
        log = os.path.join(td, "sing-box.log")
        with open(log, "w") as f:
            f.write("INFO old boot\n\x1b[31mFATAL\x1b[0m[0000] old bind error\n")
        before = sv.snapshot_log(log)
        assert before is not None
        # append-only: only new lines are attributed
        with open(log, "a") as f:
            f.write("INFO new boot\nFATAL new bind error\n")
        new = sv.new_lines_since(log, before)
        assert new == ["INFO new boot", "FATAL new bind error"], new
        assert sv.last_fatal_line(new) == "FATAL new bind error"
        # old FATAL is NOT blamed on the new start
        assert "old bind error" not in " ".join(new)

        # truncated/rotated: anchor on the snapshot's last line
        before2 = sv.snapshot_log(log)
        with open(log, "w") as f:
            f.write("INFO rotated boot\nFATAL rotated fatal\n")
        new2 = sv.new_lines_since(log, before2)
        assert new2 == ["INFO rotated boot", "FATAL rotated fatal"], new2

        # missing log: never raises, yields nothing
        assert sv.snapshot_log(os.path.join(td, "nope.log")) is None
        assert sv.new_lines_since(os.path.join(td, "nope.log"), before) == []

        # verify decisions, each on a fresh log (settle_s=0 for speed)
        def fresh_log(content: str) -> tuple[str, dict]:
            p = os.path.join(td, f"v-{fresh_log.n}.log")
            fresh_log.n += 1
            with open(p, "w") as f:
                f.write(content)
            return p, sv.snapshot_log(p)
        fresh_log.n = 0

        p, b = fresh_log("INFO boot\n")
        with open(p, "a") as f:
            f.write("INFO up\n")
        m = FakeManager(p, [(True, 123)])
        r = sv.verify_start(m, b, settle_s=0)
        assert r["ok"] and r["state"] == "running", r

        p, b = fresh_log("INFO boot\n")
        with open(p, "a") as f:
            f.write("FATAL bind error\n")
        m = FakeManager(p, [(False, None)])
        r = sv.verify_start(m, b, settle_s=0)
        assert not r["ok"] and r["state"] == "failed" and r["fatal"] == "FATAL bind error", r

        p, b = fresh_log("INFO boot\n")
        with open(p, "a") as f:
            f.write("INFO quiet boot\n")
        m = FakeManager(p, [(False, None)])
        r = sv.verify_start(m, b, settle_s=0)
        assert not r["ok"] and r["fatal"] is None and "未见 FATAL" in r["message"], r

        p, b = fresh_log("INFO boot\n")
        with open(p, "a") as f:
            f.write("FATAL odd line\n")
        m = FakeManager(p, [(True, 456)])
        r = sv.verify_start(m, b, settle_s=0)
        assert r["ok"] and r["state"] == "running_with_warnings", r

    print("OK: startverify — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
