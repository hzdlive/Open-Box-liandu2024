"""Chain proxy speedtest - real measurement via temporary sing-box.

Reports exit IP and country (1:1 with original panel behavior).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.request
import os


def test_chain(chain: dict, front_outbound: dict | None = None,
               timeout: int = 15) -> dict:
    """Test a chain proxy by routing through it.

    chain: {"name": ..., "exit_protocol": "socks"|"http",
            "server": ..., "server_port": ..., "params": {...},
            "front": "tag of front node/group"}
    front_outbound: the sing-box outbound dict for the front (if any)

    Returns: {"ok": bool, "latency_ms": int|None,
              "exit_ip": str|None, "country": str|None,
              "error": str|None}
    """
    # Build a minimal sing-box config with the chain
    chain_ob = {
        "type": chain.get("exit_protocol", "socks"),
        "tag": "chain-test",
        "server": chain.get("server", ""),
        "server_port": int(chain.get("server_port", 0)),
    }
    params = chain.get("params", {}) or {}
    if params.get("username"):
        chain_ob["username"] = params["username"]
    if params.get("password"):
        chain_ob["password"] = params["password"]

    # If there's a front, the chain dials through it
    outbounds = [chain_ob, {"type": "direct", "tag": "direct"}]
    if front_outbound:
        # Add front outbound and set chain to detour through it
        front_ob = dict(front_outbound)
        front_ob["tag"] = "front"
        outbounds.insert(0, front_ob)
        chain_ob["detour"] = "front"

    # Test port (avoid conflicts)
    test_port = 18901
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

        # Start sing-box
        proc = subprocess.Popen(
            ["/usr/local/bin/sing-box", "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)  # let it start

        if proc.poll() is not None:
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": "sing-box failed to start"}

        # Test via the SOCKS proxy: fetch IP info
        start = time.time()
        # Use curl via socks proxy for reliability
        r = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout),
             "-x", f"socks5h://127.0.0.1:{test_port}",
             "http://ip-api.com/json/?fields=status,country,query"],
            capture_output=True, timeout=timeout + 5)
        latency_ms = int((time.time() - start) * 1000)

        if r.returncode != 0:
            return {"ok": False, "latency_ms": None,
                    "exit_ip": None, "country": None,
                    "error": f"proxy request failed: {r.stderr.decode()[:200]}"}

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
