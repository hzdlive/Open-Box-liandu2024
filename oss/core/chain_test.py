"""Chain proxy speedtest - real measurement via temporary sing-box.

Reports exit IP and country (1:1 with original panel behavior).
"""

from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import time
import urllib.request
import os


def _free_port() -> int:
    """Find a free TCP port for the test SOCKS inbound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout_s: float = 3.0) -> bool:
    """True once something accepts TCP on the local test port (i.e.
    the temp sing-box is actually listening), instead of assuming a
    fixed sleep is enough for it to start."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port),
                                          timeout=0.2):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _fetch_clash_proxies(clash_port: int) -> dict:
    """GET /proxies from a sing-box Clash API (no secret)."""
    with urllib.request.urlopen(
            f"http://127.0.0.1:{clash_port}/proxies",
            timeout=2) as r:
        return json.load(r).get("proxies", {})


def _wait_for_front_ready(clash_port: int, member_tags: list,
                          budget_s: float = 20.0, fetch=None,
                          sleep=None) -> str:
    """Wait until a temp urltest front has measured at least one live
    member. Returns "ready", "no-live-member" (the API answered but
    no member ever got a delay within budget), or "api-unavailable"
    (the API never answered at all: the gate is inconclusive, so the
    caller should probe anyway rather than fail on a gate fault).

    This is the correct fix for the urltest cold start: a temp
    urltest starts with no delay history, so probing immediately can
    pin the connection to a dead member even when the group has live
    members. Retrying after failure cannot rescue such an attempt —
    the connection is already pinned — so the probe must wait for
    convergence first. A member counts as live only with a delay > 0
    (failed tests record no usable delay).
    """
    fetch = fetch or (lambda: _fetch_clash_proxies(clash_port))
    sleep = sleep or time.sleep
    deadline = time.time() + budget_s
    api_ok = False
    while time.time() < deadline:
        try:
            proxies = fetch()
            api_ok = True
        except Exception:
            sleep(1)
            continue
        for tag in member_tags:
            history = (proxies.get(tag) or {}).get("history") or []
            if history and (history[-1] or {}).get("delay"):
                return "ready"
        sleep(1)
    return "no-live-member" if api_ok else "api-unavailable"


def test_chain(chain: dict, front_outbound: dict | None = None,
               front_deps: list[dict] | None = None,
               timeout: int = 15,
               gate_members: list | None = None) -> dict:
    """Test a chain proxy by routing through it.

    chain: {"name": ..., "exit_protocol": "socks"|"http"|"shadowsocks"|"vmess"|"vless"|"trojan"|"tuic"|"hysteria2"|"anytls",
            "server": ..., "server_port": ..., "params": {...},
            "front": "tag of front node/group"}
    front_outbound: the sing-box outbound dict for the front (if any)
    front_deps: additional outbounds the front depends on (e.g. group members)

    Returns: {"ok": bool, "latency_ms": int|None,
              "exit_ip": str|None, "country": str|None,
              "error": str|None}

    timeout is the curl budget for the single probe. When gate_members
    is given (urltest/sub groups, or a failover front's primary auto
    lane), the probe additionally waits (up to 20s) for a live member
    to be measured first: a temp urltest starts with no delay
    history, so probing immediately can pin the connection to a dead
    member even when the group has live members, and no retry can
    rescue an already-pinned attempt. Callers that do not pass
    gate_members get the legacy rule (gate on a urltest front's
    members). A front that cannot be resolved at all fails fast with
    a clear message instead of probing through a dangling detour
    (sing-box check does not catch those, rc=0).
    """
    # Build a minimal sing-box config with the chain
    # 复用 chain_to_outbound 以支持全协议（ss/vmess/vless/trojan/tuic/hy2/anytls）
    from .singbox import chain_to_outbound
    from .models import Chain
    _chain = Chain(
        name="chain-test",
        exit_protocol=chain.get("exit_protocol", "socks"),
        server=chain.get("server", ""),
        # Saved chains (db.list_chains) carry "port"; the unsaved
        # modal form carries "server_port". Reading only the latter
        # built every saved-chain probe with port 0 — the actual
        # cause of the reported "proxy request failed:" on the chain
        # page (the probe dialled port 0, not the chain's port).
        server_port=int(chain.get("server_port") or chain.get("port")
                        or 0),
        params=chain.get("params", {}) or {},
        front=chain.get("front", "direct"),
    )
    chain_ob = chain_to_outbound(_chain)

    # Fail fast on a front that cannot be resolved: chain_to_outbound
    # already stamped detour=<front tag>, and sing-box check does NOT
    # catch a dangling detour (rc=0), so without this the probe would
    # fail later with a generic SOCKS error that names no cause.
    # (direct needs no resolution; block cannot be probed at all.)
    _front_tag = chain.get("front", "direct")
    if front_outbound is None:
        if _front_tag == "block":
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": "front is block"}
        if _front_tag not in ("direct", "", None):
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": f"front not found: {_front_tag}"}

    # If there's a front, the chain dials through it
    outbounds = [chain_ob, {"type": "direct", "tag": "direct"}]
    if front_outbound:
        # Add front outbound and its dependencies, set chain to detour
        front_ob = dict(front_outbound)
        orig_tag = front_ob.get("tag", "front")
        front_ob["tag"] = "front"
        # Insert dependencies first (so tags resolve)
        for dep in (front_deps or []):
            d = dict(dep)
            # Avoid tag collision with our "front"
            if d.get("tag") == "front":
                d["tag"] = f"dep-{d['tag']}"
            outbounds.insert(0, d)
        outbounds.insert(0, front_ob)
        chain_ob["detour"] = "front"
        # If front references member tags (selector/urltest), ensure they're present
        # (front_deps should already include them)

    # Test port: dynamically allocated to avoid concurrent conflicts
    test_port = _free_port()
    inbounds = [{
        "type": "socks",
        "tag": "test-in",
        "listen": "127.0.0.1",
        "listen_port": test_port,
    }]

    # The probe waits for convergence only when the front needs it:
    # gate_members (urltest/sub groups, or a failover front's primary
    # auto lane) from the resolver, or legacy fallback: a urltest
    # front's own member list. A front that resolved to nothing but
    # "direct" (empty group) routes direct and needs no gate.
    if gate_members is None:
        gate_members = list(front_outbound.get("outbounds") or []) \
            if front_outbound and \
            front_outbound.get("type") == "urltest" else []
    gate_members = [m for m in (gate_members or []) if m != "direct"]
    clash_port = _free_port() if gate_members else None

    config = {
        "log": {"level": "error"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {"final": "chain-test"},
    }
    if gate_members:
        config["experimental"] = {
            "clash_api": {
                "external_controller": f"127.0.0.1:{clash_port}",
            },
        }

    # Write temp config and run sing-box
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     delete=False) as f:
        json.dump(config, f)
        cfg_path = f.name

    proc = None
    try:
        # Validate config first
        r = subprocess.run(
            ["/usr/local/bin/sing-box", "check", "-c", cfg_path],
            capture_output=True, timeout=10)
        if r.returncode != 0:
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": f"config invalid: {r.stderr.decode()[:200]}"}

        # Start sing-box and wait until its SOCKS port actually
        # accepts connections (a fixed sleep is not a readiness
        # signal: on a slow start the first probe would fail even
        # though the chain is fine).
        proc = subprocess.Popen(
            ["/usr/local/bin/sing-box", "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.poll() is not None or not _wait_for_port(test_port):
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": ("sing-box failed to start" if proc.poll()
                               is not None else
                               "sing-box test proxy did not start in time")}

        # Wait for convergence before probing: without a measured
        # live member the probe can pin to a dead member and fail a
        # working chain. A front with no live member at all is itself
        # the diagnosis, reported directly. (Gate inconclusive ->
        # probe anyway; see the gate docstring.)
        if gate_members:
            gate = _wait_for_front_ready(clash_port, gate_members)
            if gate == "no-live-member":
                return {"ok": False, "latency_ms": None,
                        "exit_ip": None, "country": None,
                        "error": "front urltest has no live member"}

        # Probe via the SOCKS proxy: fetch IP info. -sS keeps the
        # progress meter silent but preserves curl's error text:
        # with plain -s every failure surfaced as a bare
        # "proxy request failed:" and the cause was unknowable.
        start = time.time()
        r = subprocess.run(
            ["curl", "-sS", "--max-time", str(timeout),
             "-x", f"socks5h://127.0.0.1:{test_port}",
             "http://ip-api.com/json/?fields=status,country,query"],
            capture_output=True, timeout=timeout + 5)
        latency_ms = int((time.time() - start) * 1000)

        if r.returncode != 0:
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": ("proxy request failed: "
                              f"{r.stderr.decode().strip()[:200]}")}

        try:
            data = json.loads(r.stdout.decode())
        except Exception:
            return {"ok": False, "latency_ms": latency_ms,
                    "exit_ip": None, "country": None,
                    "error": "invalid response"}

        if data.get("status") != "success":
            return {"ok": False, "latency_ms": latency_ms,
                    "exit_ip": None, "country": None,
                    "error": data.get("message", "lookup failed")}

        return {
            "ok": True,
            "latency_ms": latency_ms,
            "exit_ip": data.get("query"),
            "country": data.get("country"),
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "latency_ms": None,
                "exit_ip": None, "country": None,
                "error": str(e)[:200]}
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        try:
            os.unlink(cfg_path)
        except Exception:
            pass
