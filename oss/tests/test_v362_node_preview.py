"""v0.1.362: WireGuard node preview (node-info probe) via endpoints."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core import nodeinfo as ni


WG = {
    "tag": "wg1", "protocol": "wireguard", "server": "wg.example",
    "port": 51820,
    "params": {
        "private_key": "PRIV", "peer_public_key": "PUB",
        "pre_shared_key": "PSK", "local_address": ["10.0.0.2/32"],
        "mtu": 1400,
    },
}

VLESS = {
    "tag": "vl1", "protocol": "vless", "server": "vl.example",
    "port": 443,
    "params": {"uuid": "11111111-2222-3333-4444-555555555555",
               "tls": {"enabled": True, "server_name": "vl.example"}},
}


def test_wg_probe_config_uses_endpoints():
    cfg = ni._probe_config(WG, 18080)
    assert cfg["route"] == {"final": "probe-out"}
    assert cfg["inbounds"][0]["listen_port"] == 18080
    ep = cfg["endpoints"][0]
    assert ep["type"] == "wireguard"
    assert ep["tag"] == "probe-out"
    assert ep["private_key"] == "PRIV"
    assert ep["peers"][0]["public_key"] == "PUB"
    assert ep["peers"][0]["pre_shared_key"] == "PSK"
    assert ep["mtu"] == 1400
    assert ep["address"] == ["10.0.0.2/32"]
    # No outbound claims the probe tag: the endpoint is the exit.
    assert all(o["tag"] != "probe-out" for o in cfg["outbounds"])


def test_wg_probe_config_accepts_json_params():
    node = dict(WG, params=json.dumps(WG["params"]))
    cfg = ni._probe_config(node, 18081)
    assert cfg["endpoints"][0]["peers"][0]["pre_shared_key"] == "PSK"


def test_non_wg_probe_config_unchanged():
    cfg = ni._probe_config(VLESS, 18082)
    assert "endpoints" not in cfg
    ob = cfg["outbounds"][0]
    assert ob["type"] == "vless" and ob["tag"] == "probe-out"
    assert cfg["outbounds"][1] == {"type": "direct", "tag": "direct"}


def test_outbound_build_failure_maps_to_outbound_error(monkeypatch):
    # _probe_config maps any node_to_outbound failure to OutboundError
    # (the API answers 400 with prefix "生成不出这个节点的出站:").
    import core.singbox as sbmod
    monkeypatch.setattr(sbmod, "node_to_outbound",
                        lambda n: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(ni.OutboundError, match="boom"):
        ni._probe_config(VLESS, 18083)


def test_probe_exit_binary_gate_first():
    # No binary at this path: RuntimeError, not OutboundError, even
    # for a node whose outbound could not be built either.
    with pytest.raises(RuntimeError, match="binary not installed"):
        ni.probe_exit(
            {"tag": "bad", "protocol": "not-a-protocol", "server": "x",
             "port": 1, "params": {}},
            bin_path="/nonexistent/sing-box")
