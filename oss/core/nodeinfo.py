"""Per-node exit info: route a probe through one node via a temporary
sing-box instance and read back IP / country / ASN.

Clean-room reimplementation of the publicly observable behavior:
- exit IP + geo + ASN per node, cached 6h per exit IP (here: per tag),
- manual refresh throttled to 15s,
- entry-country derived from the node's own server address.

Requires the sing-box binary; without it the API reports honestly.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


def probe_exit(node: dict, bin_path: str, timeout: float = 25.0) -> dict:
    """Run one probe through *node* (a node dict as in list_nodes).

    Returns {ok, ip, country, country_code, region, city, isp, asn,
    proxy_type, via}. Raises RuntimeError when the binary is missing.
    """
    from core.singbox import node_to_outbound
    from core.models import Node
    if not (os.path.isfile(bin_path) and os.access(bin_path, os.X_OK)):
        raise RuntimeError("sing-box binary not installed")
    outbound = node_to_outbound(Node(
        tag=node["tag"], protocol=node["protocol"], server=node["server"],
        server_port=node["port"],
        params=node.get("params") if isinstance(node.get("params"), dict)
        else json.loads(node.get("params") or "{}")))
    outbound["tag"] = "probe-out"
    port = _free_port()
    cfg = {
        "log": {"level": "error"},
        "inbounds": [{"type": "mixed", "tag": "probe-in",
                      "listen": "127.0.0.1", "listen_port": port}],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        "route": {"final": "probe-out"},
    }
    proxy_url = f"http://127.0.0.1:{port}"
    result: dict = {"ok": False, "via": "node"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
        cfg_path = f.name
    proc = subprocess.Popen([bin_path, "run", "-c", cfg_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        if not _wait_port(port, timeout=10):
            result["error"] = "probe sing-box did not start"
            return result
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": proxy_url, "https": proxy_url}))
        req = urllib.request.Request(
            "http://ip-api.com/json/?fields=status,country,countryCode,"
            "regionName,city,isp,as,query",
            headers={"User-Agent": "openbox-oss/1.0"})
        t0 = time.monotonic()
        with opener.open(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        ms = (time.monotonic() - t0) * 1000
        if data.get("status") == "success":
            result.update({
                "ok": True, "ip": data.get("query"),
                "country": data.get("country"),
                "country_code": data.get("countryCode"),
                "region": data.get("regionName"), "city": data.get("city"),
                "isp": data.get("isp"), "asn": data.get("as"),
                "proxy_type": node["protocol"],
                "latency_ms": round(ms, 1),
            })
        else:
            result["error"] = "geo lookup failed"
    except Exception as e:
        result["error"] = str(e)[:160]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.unlink(cfg_path)
        except OSError:
            pass
    return result


def entry_country(node: dict, timeout: float = 5.0) -> dict:
    """Country of the node's *entry* (server) IP via a direct lookup."""
    server = node["server"]
    try:
        ip = socket.gethostbyname(server)
    except OSError as e:
        return {"ok": False, "error": str(e)[:120]}
    try:
        req = urllib.request.Request(
            f"http://ip-api.com/json/{ip}?fields=status,country,countryCode",
            headers={"User-Agent": "openbox-oss/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        if data.get("status") == "success":
            return {"ok": True, "ip": ip, "country": data.get("country"),
                    "country_code": data.get("countryCode")}
        return {"ok": False, "error": "lookup failed"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
