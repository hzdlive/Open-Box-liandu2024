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


class OutboundError(Exception):
    """Outbound generation failed (e.g. wireguard nodes are endpoints,
    not outbounds). The API answers 400 with prefix
    "生成不出这个节点的出站:" for this."""


def chain_cache_key(chain: dict) -> str:
    """Cache key for a chain probe: tag + front + exit identity.

    The front is part of the key (the exit depends on the path), as
    is the exit server (an exit edit must invalidate the old probe).
    Params are excluded on purpose: a credential change does not
    change the exit IP the probe measured.
    """
    return (f"{chain['name']}\0{chain.get('front') or ''}\0"
            f"{chain.get('exit_protocol')}:"
            f"{chain.get('server')}:{chain.get('server_port')
                                    or chain.get('port')}")


def probe_chain(chain: dict, cfg, timeout: float = 25.0) -> dict:
    """Probe a chain's exit through its front via a scratch sing-box.

    Reuses chain_front resolution (node/sub/group/chain fronts) and
    chain_test's scratch kernel + convergence gate, then maps the
    result onto the node-info shape. Raises OutboundError when the
    exit outbound cannot be built, RuntimeError when the binary is
    missing. A front that cannot be resolved returns ok=False
    (test_chain would fail fast on it anyway).
    """
    import os as _os

    from core import chain_front as _cf
    from core import chain_test as _ct
    from core.models import Chain as _Chain
    from core.singbox import chain_to_outbound as _cto

    if not (_os.path.isfile("/usr/local/bin/sing-box")
            and _os.access("/usr/local/bin/sing-box", _os.X_OK)):
        raise RuntimeError("sing-box binary not installed")
    try:
        _cto(_Chain(
            name=chain["name"],
            exit_protocol=chain.get("exit_protocol", "socks"),
            server=chain.get("server", ""),
            server_port=int(chain.get("server_port") or chain.get("port")
                            or 0),
            params=chain.get("params") or {},
            front=chain.get("front") or "direct"))
    except Exception as e:
        raise OutboundError(str(e)) from e
    front = chain.get("front") or ""
    front_ob, deps, gate_members, gate_group = _cf.resolve_chain_front(
        cfg, front)
    if front and front not in ("direct", "block") and front_ob is None:
        return {"ok": False, "error": f"chain front not found: {front}"}
    try:
        r = _ct.test_chain(
            chain, front_outbound=front_ob, front_deps=deps,
            timeout=int(timeout), gate_members=gate_members,
            gate_group=gate_group)
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or "probe failed"}
    return {"ok": True, "ip": r.get("exit_ip"), "country": r.get("country"),
            "latency_ms": r.get("latency_ms"), "via": "chain",
            "proxy_type": chain.get("exit_protocol")}


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
    try:
        outbound = node_to_outbound(Node(
            tag=node["tag"], protocol=node["protocol"], server=node["server"],
            server_port=node["port"],
            params=node.get("params") if isinstance(node.get("params"), dict)
            else json.loads(node.get("params") or "{}")))
    except Exception as e:
        raise OutboundError(str(e)) from e
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
