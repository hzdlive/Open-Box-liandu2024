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


def test_chain(chain: dict, front_outbound: dict | None = None,
               front_deps: list[dict] | None = None,
               timeout: int = 15) -> dict:
    """Test a chain proxy by routing through it.

    chain: {"name": ..., "exit_protocol": "socks"|"http"|"shadowsocks"|"vmess"|"vless"|"trojan"|"tuic"|"hysteria2"|"anytls",
            "server": ..., "server_port": ..., "params": {...},
            "front": "tag of front node/group"}
    front_outbound: the sing-box outbound dict for the front (if any)
    front_deps: additional outbounds the front depends on (e.g. group members)

    Returns: {"ok": bool, "latency_ms": int|None,
              "exit_ip": str|None, "country": str|None,
              "error": str|None}

    timeout is the total budget for the probe phase. The probe is
    retried within that budget: a temp urltest front starts with no
    delay history, so the first attempt can hit a dead member before
    the urltest has learned which member is alive; retrying (with a
    short pause for the test round to settle) turns that cold-start
    false negative into a real measurement instead of reporting a
    working chain as down. latency_ms is the successful attempt's
    duration, not the sum of attempts.
    """
    # Build a minimal sing-box config with the chain
    # 复用 chain_to_outbound 以支持全协议（ss/vmess/vless/trojan/tuic/hy2/anytls）
    from .singbox import chain_to_outbound
    from .models import Chain
    _chain = Chain(
        name="chain-test",
        exit_protocol=chain.get("exit_protocol", "socks"),
        server=chain.get("server", ""),
        server_port=int(chain.get("server_port", 0)),
        params=chain.get("params", {}) or {},
        front=chain.get("front", "direct"),
    )
    chain_ob = chain_to_outbound(_chain)

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

    config = {
        "log": {"level": "error"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {"final": "chain-test"},
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

        # Probe via the SOCKS proxy: fetch IP info, retrying within
        # the budget (see the docstring: urltest cold start). -sS
        # keeps the progress meter silent but preserves curl's error
        # text: with plain -s every failure surfaced as a bare
        # "proxy request failed:" and the cause was unknowable.
        deadline = time.time() + timeout
        data = None
        latency_ms = None
        last_error = "proxy request failed: "
        attempts = 0
        while attempts < 4 and time.time() < deadline:
            attempts += 1
            start = time.time()
            r = subprocess.run(
                ["curl", "-sS", "--max-time", "5",
                 "-x", f"socks5h://127.0.0.1:{test_port}",
                 "http://ip-api.com/json/?fields=status,country,query"],
                capture_output=True, timeout=10)
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout.decode())
                    latency_ms = int((time.time() - start) * 1000)
                except Exception:
                    return {"ok": False, "latency_ms":
                            int((time.time() - start) * 1000),
                            "exit_ip": None, "country": None,
                            "error": "invalid response"}
                break
            last_error = ("proxy request failed: "
                          f"{r.stderr.decode().strip()[:200]}")
            if time.time() + 1 < deadline:
                time.sleep(1)  # let the urltest round settle
        if data is None:
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": last_error}

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
