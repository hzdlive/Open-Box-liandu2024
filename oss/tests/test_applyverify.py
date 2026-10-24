"""Self-test for apply-path start verification (apply_config/hot_apply).

Simulates the 2026-10-23 gap: apply returned 200 while the kernel died
right after (dangling detour FATAL at startup). After this change the
relaunch is verified like /api/service/start: death -> ApplyVerifyError
(endpoint maps it to 409 with the verify dict), health -> 200 + verify.
The hot path (no relaunch) gets no verify key at all.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import service as svcmod  # noqa: E402
from core.apply import apply_config, ApplyVerifyError  # noqa: E402
from core.hotapply import hot_apply_config  # noqa: E402
from core import hotapply as hotmod  # noqa: E402
from core import apply as applymod  # noqa: E402


class FakeManager:
    """KernelManager stand-in: restart()/start() flip running + log."""

    def __init__(self, tmpdir, die=False):
        self.config_path = os.path.join(tmpdir, "config.json")
        self.log_path = os.path.join(tmpdir, "sing-box.log")
        self.workdir = tmpdir
        self._running = True
        self._die = die
        Path(self.log_path).write_text("INFO start old\n")

    def is_installed(self):
        return True

    def status(self):
        return svcmod.ServiceStatus(installed=True, running=self._running,
                                    pid=1234 if self._running else None)

    def to_dict(self):
        return {"installed": True, "running": self._running,
                "pid": 1234 if self._running else None}

    def check_config(self, path=None):
        return True, "ok"

    def restart(self):
        if self._die == "fatal_only":
            # 2026-10-24 live case: FATAL logged but the process lingers
            # ~1s past the grace window before exiting.
            with open(self.log_path, "a") as f:
                f.write("FATAL[0000] start service: dependency[X] not found"
                        " for outbound[Y]\n")
            return self.status()
        if self._die:
            with open(self.log_path, "a") as f:
                f.write("FATAL[0000] start service: dependency[X] not found"
                        " for outbound[Y]\n")
            self._running = False
        return self.status()

    def start(self):
        return self.restart()


def _patch_build(monkey_ok=True):
    """Stub the build side so tests only exercise relaunch+verify."""
    orig_build = applymod.build_and_validate
    orig_sync = applymod._sync_selection_before_build
    orig_write = applymod._atomic_write_json
    applymod.build_and_validate = lambda conn, m: (
        {"outbounds": [], "route": {"rules": []}}, True, "ok")
    applymod._sync_selection_before_build = lambda conn: None
    applymod._atomic_write_json = lambda path, obj: None
    # hotapply imported the names at module level; patch there too.
    hotmod.build_and_validate = applymod.build_and_validate
    hotmod._sync_selection_before_build = applymod._sync_selection_before_build
    hotmod._atomic_write_json = applymod._atomic_write_json
    return orig_build, orig_sync, orig_write


def _restore(patch):
    ob, osy, ow = patch
    applymod.build_and_validate = ob
    applymod._sync_selection_before_build = osy
    applymod._atomic_write_json = ow


def main() -> int:
    # verify_start only sleeps when the first poll shows not-running;
    # neutralize that sleep so the death case stays fast.
    orig_sleep = time.sleep
    time.sleep = lambda s: None
    patch = _patch_build()
    try:
        with tempfile.TemporaryDirectory() as d:
            # 1. full apply, kernel dies on restart -> ApplyVerifyError.
            m = FakeManager(d, die=True)
            try:
                apply_config(None, m)
                raise AssertionError("expected ApplyVerifyError")
            except ApplyVerifyError as e:
                assert e.verify["state"] == "failed", e.verify
                assert "dependency[X]" in e.verify["fatal"], e.verify

            # 2. full apply, kernel healthy -> 200-shape with verify.
            m = FakeManager(d, die=False)
            r = apply_config(None, m)
            assert r["applied"] and r["verify"]["state"] == "running", r

            # 2b. kernel logs FATAL but is briefly still alive -> still
            # ApplyVerifyError (the 2026-10-24 lingering-process case).
            m = FakeManager(d, die="fatal_only")
            try:
                apply_config(None, m)
                raise AssertionError("expected ApplyVerifyError")
            except ApplyVerifyError as e:
                assert e.verify["state"] == "failed", e.verify
                assert "尚存" in e.verify["message"], e.verify
            orig_push = hotmod.native_push_outbounds
            hotmod.native_push_outbounds = lambda a, s, o: (True, "pushed")
            try:
                m = FakeManager(d, die=True)  # would die if relaunched
                r = hot_apply_config(None, m, "http://127.0.0.1:9090", "",
                                     force="hot")
                assert r["mode"] == "hot" and "verify" not in r, r
            finally:
                hotmod.native_push_outbounds = orig_push

            # 4. hot falls back to full + kernel dies -> ApplyVerifyError.
            hotmod.native_push_outbounds = lambda a, s, o: (False, "no api")
            try:
                m = FakeManager(d, die=True)
                try:
                    hot_apply_config(None, m, "http://127.0.0.1:9090", "",
                                     force="hot")
                    raise AssertionError("expected ApplyVerifyError")
                except ApplyVerifyError as e:
                    assert e.verify["state"] == "failed", e.verify
            finally:
                hotmod.native_push_outbounds = orig_push

        # 5. endpoint mapping: 409 with verify on death, 200 on health.
        from panel.app import create_app
        orig_mfe = svcmod.manager_from_env
        try:
            with tempfile.TemporaryDirectory() as d:
                svcmod.manager_from_env = lambda: FakeManager(d, die=True)
                app = create_app(":memory:")
                t = app.test_client()
                resp = t.post("/api/config/apply?mode=full")
                assert resp.status_code == 409, (resp.status_code,
                                                 resp.get_json())
                body = resp.get_json()
                assert body["verify"]["state"] == "failed", body
                assert "dependency[X]" in body["verify"]["fatal"], body

                svcmod.manager_from_env = lambda: FakeManager(d, die=False)
                app = create_app(":memory:")
                t = app.test_client()
                resp = t.post("/api/config/apply?mode=full")
                assert resp.status_code == 200, (resp.status_code,
                                                 resp.get_json())
                assert resp.get_json()["verify"]["state"] == "running", \
                    resp.get_json()
        finally:
            svcmod.manager_from_env = orig_mfe
    finally:
        time.sleep = orig_sleep
        _restore(patch)

    print("OK: applyverify — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
