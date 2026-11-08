"""Core binary client: run oss-core (Go) for config generation.

The panel uses the Go core when a binary is available (``OBX_CORE_BIN``
or ``oss-core`` on PATH); otherwise it uses the in-process Python
generator. When the binary IS in use, any failure (binary missing,
handshake mismatch, nonzero exit, bad JSON) raises CoreError and the
operation fails loudly -- there is no silent fallback to Python.

The profile document (AppConfig -> JSON) is built by
:mod:`core.profile`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

from core.profile import app_config_to_profile

# Contract (oss/core-go/CONTRACT.md): the core reports this sing-box
# version and these methods. A mismatch means the installed binary
# does not match this panel, and using it would silently generate
# configs for the wrong kernel.
EXPECTED_SINGBOX = "1.14.1"
REQUIRED_METHODS = {"config", "configDetailed", "emitGroups"}

# Generous: the core is a local static binary, normally <1s.
RUN_TIMEOUT_S = 30.0
VERSION_TIMEOUT_S = 10.0


class CoreError(Exception):
    """The core binary failed (missing, handshake mismatch, bad output)."""


def find_core_bin() -> str | None:
    """Configured core binary path, or None when no binary is set up.

    ``OBX_CORE_BIN`` wins; otherwise ``oss-core`` on PATH (the router
    install puts it in /usr/local/bin).
    """
    env = os.environ.get("OBX_CORE_BIN", "").strip()
    if env:
        return env
    return shutil.which("oss-core")


def handshake(bin_path: str, timeout: float = VERSION_TIMEOUT_S) -> dict:
    """Run `oss-core version` and validate the handshake.

    Returns the parsed handshake dict. Raises CoreError on any
    mismatch (wrong name, missing methods, wrong sing-box version).
    """
    try:
        r = subprocess.run([bin_path, "version"], capture_output=True,
                           text=True, timeout=timeout)
    except FileNotFoundError:
        raise CoreError(f"core binary not found: {bin_path}")
    except subprocess.TimeoutExpired:
        raise CoreError(f"core binary version check timed out: {bin_path}")
    if r.returncode != 0:
        raise CoreError(
            f"core binary version check failed (exit {r.returncode}): "
            f"{r.stderr.strip()[:300]}")
    try:
        hs = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise CoreError(
            f"core binary version output is not JSON: {r.stdout[:200]!r}")
    if hs.get("name") != "oss-core":
        raise CoreError(f"core binary name mismatch: {hs.get('name')!r}")
    methods = set(hs.get("methods") or [])
    missing = REQUIRED_METHODS - methods
    if missing:
        raise CoreError(
            f"core binary missing methods: {sorted(missing)}")
    if hs.get("singbox") != EXPECTED_SINGBOX:
        raise CoreError(
            f"core binary sing-box version mismatch: {hs.get('singbox')!r} "
            f"(expected {EXPECTED_SINGBOX!r})")
    return hs


def _run(bin_path: str, command: str, profile: dict, workdir: str,
         skip: set[str] | None = None,
         timeout: float = RUN_TIMEOUT_S) -> dict:
    """Run one core command over a profile document. Returns parsed stdout."""
    fd, tmp = tempfile.mkstemp(prefix="oss-core-profile-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(profile, f, ensure_ascii=False,
                      default=lambda v: sorted(v) if isinstance(v, set) else str(v))
        os.chmod(tmp, 0o600)
        cmd = [bin_path, command, "--profile", tmp]
        if command in ("config", "configDetailed"):
            cmd += ["--workdir", workdir]
        if skip:
            cmd += ["--skip-rule-sets", ",".join(sorted(skip))]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout)
        except FileNotFoundError:
            raise CoreError(f"core binary not found: {bin_path}")
        except subprocess.TimeoutExpired:
            raise CoreError(f"core binary {command} timed out after {timeout}s")
        if r.returncode != 0:
            raise CoreError(
                f"core binary {command} failed (exit {r.returncode}): "
                f"{r.stderr.strip()[:500]}")
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            raise CoreError(
                f"core binary {command} output is not JSON: "
                f"{r.stdout[:200]!r}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def build_config_via_core(app_cfg, workdir: str,
                          skip: set[str] | None = None,
                          bin_path: str | None = None) -> dict:
    """Full sing-box config via the core binary (writes dns-filter files).

    Handshake first; any failure raises CoreError (no Python fallback).
    """
    bin_path = bin_path or find_core_bin()
    if not bin_path:
        raise CoreError("no core binary configured (OBX_CORE_BIN or oss-core on PATH)")
    handshake(bin_path)
    profile = app_config_to_profile(app_cfg, workdir)
    return _run(bin_path, "config", profile, workdir, skip)


def config_detailed_via_core(app_cfg, workdir: str,
                             skip: set[str] | None = None,
                             bin_path: str | None = None) -> dict:
    """configDetailed via the core binary (preview: writes no files)."""
    bin_path = bin_path or find_core_bin()
    if not bin_path:
        raise CoreError("no core binary configured (OBX_CORE_BIN or oss-core on PATH)")
    handshake(bin_path)
    profile = app_config_to_profile(app_cfg, workdir)
    return _run(bin_path, "configDetailed", profile, workdir, skip)


def emit_groups_via_core(app_cfg, workdir: str,
                         bin_path: str | None = None) -> dict:
    """emitGroups via the core binary."""
    bin_path = bin_path or find_core_bin()
    if not bin_path:
        raise CoreError("no core binary configured (OBX_CORE_BIN or oss-core on PATH)")
    handshake(bin_path)
    profile = app_config_to_profile(app_cfg, workdir)
    return _run(bin_path, "emitGroups", profile, workdir)


def build_config_auto(app_cfg, workdir: str,
                      skip: set[str] | None = None) -> dict:
    """Deploy-path config: core binary when available, else Python.

    The core path writes the dns-filter files (same as apply.py's
    Python path does today); a core failure raises CoreError.
    """
    bin_path = find_core_bin()
    if bin_path is None:
        from core.singbox import build_config
        return build_config(app_cfg, skip)
    return build_config_via_core(app_cfg, workdir, skip, bin_path)


def preview_config_auto(app_cfg, workdir: str,
                        skip: set[str] | None = None) -> dict:
    """Preview-path config: core binary when available, else Python.

    Uses configDetailed (no dns-filter file writes), returns the
    config field.
    """
    bin_path = find_core_bin()
    if bin_path is None:
        from core.singbox import build_config
        return build_config(app_cfg, skip)
    return config_detailed_via_core(app_cfg, workdir, skip, bin_path)["config"]
