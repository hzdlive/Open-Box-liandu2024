"""Upgrade preparation and restore (v0.1.344).

Original behavior fixed in v0.1.344: an upgrade downloaded while the kernel
was running could resolve update hosts through cached FakeIP answers, and a
failed or cancelled upgrade could leave the kernel down. The upgrade flow
now shares one preparation before the first network request:

1. Record whether the kernel was running.
2. If running: stop it via the panel service API and wait until it is
   really gone. Service exit is the TUN-exit signal: sing-box does not
   persist its TUN device, and our generated config pins no interface_name,
   so no named-device check is possible -- process exit is the signal.
3. Clean possibly-poisoned FakeIP answers from the local DNS cache
   (systemd-resolved flush, else dnsmasq SIGHUP, else no-op when no local
   cache daemon exists).
4. Only then may the caller download anything. If stop or cleaning fails,
   the kernel is restored first and preparation reports failure -- the
   caller must not enter file replacement.

Restore rules (shared by success, failure, and cancel paths):
- Kernel was running -> start it again (after a panel restart, wait for
  the panel API to come back first).
- Kernel was stopped -> leave it stopped.
- Cancel (TERM) -> restore, then report cancelled.

Scope notes (deliberate, documented):
- This preparation guards the APPLY path (real downloads + file changes).
  The lightweight CHECK path (git ls-remote) is read-only and
  non-destructive, so it does not suspend the kernel: suspending live
  traffic for a read would be disproportionate, and a check that fails on
  poisoned DNS surfaces as a plain check error, not a stuck state.
- Git fetch verifies object hashes itself, so the "wrong manifest SHA"
  case from v0.1.344 maps to git's own integrity failure: fetch fails
  before any merge, and the restore path runs.
- Release-asset packaging (install.sh/update.sh/uninstall.sh + SHA256 in
  the Release) is the original's distribution process and has no
  equivalent here: this panel updates from its own git repo, not release
  assets. Geo snapshots and tutorial lists are likewise untouched by this
  version (Geo is covered by the existing refresh mechanism; tutorials
  belong to the deferred 8-gap item).
- Proxy environment variables, if set by the deployment, are honored
  as-is: this preparation fixes kernel-suspend + DNS-clean, it does not
  rewrite the deployment's network routing policy.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_STATE_FILE = "/tmp/openbox-oss-update-prep.json"


class PanelClient:
    """Minimal panel service API client (localhost, no auth: same as the
    deploy scripts' use of the local API)."""

    def __init__(self, port: str | int):
        self.base = f"http://127.0.0.1:{port}"

    def _req(self, method: str, path: str, timeout: int = 10):
        req = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace") or "{}"
                return True, json.loads(raw)
        except Exception as e:  # noqa: BLE001 - any transport/parse failure
            return False, str(e)

    def get_service(self):
        return self._req("GET", "/api/service")

    def stop_service(self):
        return self._req("POST", "/api/service/stop")

    def start_service(self):
        return self._req("POST", "/api/service/start")


def _is_running(service_data) -> bool:
    return bool((service_data or {}).get("running"))


def clean_dns_cache(run=None, which=None, kill=None):
    """Clean possibly-poisoned FakeIP answers from the local DNS cache.

    Returns (ok, detail). systemd-resolved flush first, else dnsmasq
    SIGHUP (standard cache clear + config re-read), else no-op-ok when no
    local cache daemon exists (then nothing could have been poisoned).
    A failed flush/HUP is a failure, except when the tool reports no
    daemon behind it -- then we fall through to the next method.
    """
    run = run or subprocess.run
    which = which or shutil.which
    kill = kill or os.kill
    if which("resolvectl"):
        try:
            r = run(["resolvectl", "flush-caches"], capture_output=True,
                    text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"resolvectl flush failed: {e}"
        if r.returncode == 0:
            return True, "resolvectl flush-caches"
        err = (r.stderr or "").strip()
        if any(s in err for s in ("not been booted", "Failed to connect",
                                  "No such file", "not running")):
            pass  # no daemon behind the binary; try dnsmasq next
        else:
            return False, f"resolvectl flush failed: {err[:200]}"
    pid = None
    if which("pidof"):
        try:
            r = run(["pidof", "dnsmasq"], capture_output=True, text=True,
                    timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                pid = int(r.stdout.split()[0])
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pid = None
    if pid is not None:
        try:
            kill(pid, signal.SIGHUP)
        except OSError as e:
            return False, f"dnsmasq SIGHUP failed: {e}"
        time.sleep(1)
        try:
            kill(pid, 0)
        except OSError:
            return False, "dnsmasq died after SIGHUP"
        return True, f"dnsmasq SIGHUP (pid {pid})"
    return True, "no local DNS cache daemon found; nothing to clean"


def prepare(client, dns_cleaner=None, stop_timeout: float = 30.0,
            poll: float = 0.5) -> dict:
    """Run the pre-download preparation. Returns {ok, was_running, error,
    detail}. On failure the caller must not download anything; if the
    kernel was already stopped for the attempt it is restored first."""
    ok, st = client.get_service()
    if not ok:
        return {"ok": False, "was_running": False,
                "error": f"service status unreachable: {st}", "detail": ""}
    was_running = _is_running(st)
    stopped = False
    if was_running:
        client.stop_service()
        deadline = time.time() + stop_timeout
        while time.time() < deadline:
            ok2, cur = client.get_service()
            if ok2 and not _is_running(cur):
                stopped = True
                break
            time.sleep(poll)
        if not stopped:
            return {"ok": False, "was_running": True,
                    "error": "kernel did not stop",
                    "detail": "service still reports running after stop"}
    cleaner = dns_cleaner or clean_dns_cache
    cok, cdetail = cleaner()
    if not cok:
        detail = cdetail
        if was_running and stopped:
            r = restore(client, True, wait_panel=False)
            detail += f"; restore after failed clean: {r['detail']}"
        return {"ok": False, "was_running": was_running,
                "error": "DNS cache clean failed", "detail": detail}
    return {"ok": True, "was_running": was_running, "error": "",
            "detail": cdetail}


def restore(client, was_running: bool, wait_panel: bool = False,
            panel_timeout: float = 60.0, start_timeout: float = 30.0,
            poll: float = 0.5) -> dict:
    """Restore the kernel if it was running before the upgrade."""
    if not was_running:
        return {"restored": False,
                "detail": "kernel was stopped before upgrade; left stopped"}
    if wait_panel:
        deadline = time.time() + panel_timeout
        while time.time() < deadline:
            ok, _ = client.get_service()
            if ok:
                break
            time.sleep(poll)
        else:
            return {"restored": False,
                    "detail": "panel API did not come back"}
    client.start_service()
    deadline = time.time() + start_timeout
    while time.time() < deadline:
        ok, cur = client.get_service()
        if ok and _is_running(cur):
            return {"restored": True, "detail": ""}
        time.sleep(poll)
    return {"restored": False,
            "detail": "kernel did not come back after start"}


def write_prep_state(path: str, was_running: bool) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps({"was_running": bool(was_running)}))
    os.replace(tmp, path)


def read_prep_state(path: str):
    """Return was_running, or None when the state file is missing/corrupt
    (fail-safe: an unknown state must not start a kernel on a guess)."""
    try:
        with open(path) as f:
            data = json.load(f)
        return bool(data["was_running"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["prepare", "restore"])
    p.add_argument("--port", default="8080")
    p.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    p.add_argument("--wait-panel", action="store_true")
    args = p.parse_args(argv)
    client = PanelClient(args.port)
    if args.command == "prepare":
        res = prepare(client)
        if res["ok"]:
            write_prep_state(args.state_file, res["was_running"])
            print(f"[upgradeprep] prepared (was_running={res['was_running']}) "
                  f"detail={res['detail']}")
            return 0
        print(f"[upgradeprep] preparation FAILED: {res['error']} "
              f"detail={res['detail']}")
        return 1
    was = read_prep_state(args.state_file)
    if was is None:
        print("[upgradeprep] no prep state; assuming kernel was stopped "
              "(not starting on a guess)")
        return 0
    res = restore(client, was, wait_panel=args.wait_panel)
    print(f"[upgradeprep] restore: {res}")
    return 0 if res["restored"] or not was else 1


if __name__ == "__main__":
    sys.exit(main())
