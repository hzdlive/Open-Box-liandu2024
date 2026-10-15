"""Panel self-update: check the oss repo for newer commits and apply them.

Honors the update_* settings (mirrored from the original panel's
updates.openbox profile section):
- update_auto:         "1" = check on schedule AND apply automatically
- update_hour:         hour of day (0-23) at which the scheduled check runs
- update_channel:      auto|stable|beta -> which ref to track
- update_check_channel: mirror|official -> where to check
- update_days:         minimum interval between checks, in days

State kept in settings:
- update_last_check:  ISO timestamp of the last check
- update_last_result: JSON {available, local, remote, remote_msg,
                      checked_at, channel, check_channel} or {error, ...}

The check compares the local HEAD with the remote ref via `git ls-remote`,
so it works on git-based deployments (the VPS updates with git pull).
Applying = fast-forward only `git pull` + panel restart, run detached so the
HTTP response that triggered it is not blocked. update_auto defaults to "0",
so nothing happens unless the user explicitly enables it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

REPO_URL_OFFICIAL = "https://github.com/hzdlive/Open-Box-liandu2024.git"
REPO_URL_MIRROR = "https://ghfast.top/https://github.com/hzdlive/Open-Box-liandu2024.git"

TS_FMT = "%Y-%m-%dT%H:%M:%S"


def repo_dir() -> str:
    """Repo root: env override, else derived from this file's location."""
    env = os.environ.get("OBX_REPO_DIR")
    if env and os.path.isdir(env):
        return env
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_git(args: list[str], cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def local_head(repo: str | None = None) -> str | None:
    repo = repo or repo_dir()
    try:
        r = _run_git(["rev-parse", "HEAD"], cwd=repo)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def _remote_url(check_channel: str) -> str:
    return REPO_URL_MIRROR if check_channel == "mirror" else REPO_URL_OFFICIAL


def _pick_ref(channel: str, url: str) -> tuple[str, str | None]:
    """Return (refspec-pattern, error). Resolves stable/beta to the newest tag."""
    if channel in ("stable", "beta"):
        try:
            r = _run_git(["ls-remote", url, "refs/tags/*"], cwd=repo_dir(), timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            return "", f"tag list failed: {e}"
        if r.returncode != 0:
            return "", (r.stderr.strip() or "tag list failed")[:200]
        tags = []
        for line in r.stdout.splitlines():
            sha, _, ref = line.partition("\t")
            name = ref.rsplit("/", 1)[-1]
            if name.endswith("^{}"):
                continue
            tags.append((name, sha.strip()))
        if tags:
            # newest tag by version-ish sort; beta takes the newest of any tag,
            # stable skips tags that look like pre-releases
            def _key(t):
                n = t[0].lstrip("vV")
                parts = []
                for p in n.replace("-", ".").split("."):
                    parts.append(int(p) if p.isdigit() else 0)
                return parts
            cands = [t for t in tags
                     if channel == "beta" or not any(
                         k in t[0].lower() for k in ("beta", "alpha", "rc", "pre"))]
            if cands:
                name, sha = max(cands, key=_key)
                return f"refs/tags/{name}", None
    return "refs/heads/oss", None


def check_remote(channel: str, check_channel: str) -> dict:
    """Query the remote ref. Returns {sha, ref} or {error}."""
    url = _remote_url(check_channel)
    pattern, err = _pick_ref(channel, url)
    if err:
        return {"error": err}
    try:
        r = _run_git(["ls-remote", url, pattern], cwd=repo_dir(), timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": f"ls-remote failed: {e}"}
    if r.returncode != 0:
        return {"error": (r.stderr.strip() or "ls-remote failed")[:200]}
    sha = ""
    for line in r.stdout.splitlines():
        s, _, _ref = line.partition("\t")
        if s.strip():
            sha = s.strip()
            break
    if not sha:
        return {"error": f"no such ref on remote: {pattern}"}
    msg = ""
    try:
        r2 = _run_git(["ls-remote", "--symref", url, "HEAD"], cwd=repo_dir(), timeout=30)
        _ = r2
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"sha": sha, "ref": pattern, "message": msg}


def due_for_check(conn, now: float | None = None) -> bool:
    """True when a scheduled update check should run now.

    Gating: at least update_days since the last check, current hour >=
    update_hour, and not already checked today.
    """
    from panel.db import get_setting
    now = now if now is not None else time.time()
    try:
        days = max(1, int(get_setting(conn, "update_days", "1") or 1))
    except ValueError:
        days = 1
    try:
        hour = min(23, max(0, int(get_setting(conn, "update_hour", "4") or 4)))
    except ValueError:
        hour = 4
    last = get_setting(conn, "update_last_check", "")
    last_ts = 0.0
    if last:
        try:
            last_ts = time.mktime(time.strptime(last, TS_FMT))
        except ValueError:
            last_ts = 0.0
    if last_ts and now - last_ts < days * 86400:
        return False
    lt = time.localtime(now)
    if lt.tm_hour < hour:
        return False
    if last_ts:
        ll = time.localtime(last_ts)
        if (ll.tm_year, ll.tm_yday) == (lt.tm_year, lt.tm_yday):
            return False
    return True


def check_for_update(conn) -> dict:
    """Run one update check, persist last_check/last_result, return the result."""
    from panel.db import get_setting, set_setting
    channel = get_setting(conn, "update_channel", "auto") or "auto"
    check_channel = get_setting(conn, "update_check_channel", "mirror") or "mirror"
    now_s = time.strftime(TS_FMT, time.localtime())
    local = local_head()
    remote = check_remote(channel, check_channel)
    if "error" in remote:
        result = {"available": False, "local": local, "remote": None,
                  "checked_at": now_s, "channel": channel,
                  "check_channel": check_channel, "error": remote["error"]}
    else:
        result = {"available": bool(local and remote["sha"] and
                                    remote["sha"] != local),
                  "local": local, "remote": remote["sha"], "ref": remote["ref"],
                  "checked_at": now_s, "channel": channel,
                  "check_channel": check_channel}
    set_setting(conn, "update_last_check", now_s)
    set_setting(conn, "update_last_result", json.dumps(result, ensure_ascii=False))
    return result


def apply_update_async(ref: str = "refs/heads/oss") -> str:
    """Spawn the detached self-update applier. Returns the log path."""
    repo = repo_dir()
    script = os.path.join(repo, "oss", "scripts", "selfupdate-apply.sh")
    logf = "/tmp/openbox-oss-selfupdate.log"
    port = os.environ.get("PORT", "8080")
    subprocess.Popen(
        ["bash", script, repo, sys.executable, port, ref],
        stdout=open(logf, "ab"), stderr=subprocess.STDOUT,
        start_new_session=True)
    return logf


def last_result(conn) -> dict:
    from panel.db import get_setting
    raw = get_setting(conn, "update_last_result", "")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}
