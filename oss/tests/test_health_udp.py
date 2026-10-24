"""Regression: tuic/hysteria2 nodes showed no latency in the subscription
edit modal because the panel probe skipped every UDP-only protocol.

2026-10-24: /api/health stored tuic/hysteria2 as ok=None/latency=None
("udp-only protocol, skipped"), so the modal's latency column could
never show a number for them -- even for nodes the kernel measures
fine (BWG tuic/hy2: kernel delay 1337/206ms). Fix: tuic/hysteria2 are
measured through the kernel's clash delay API; wireguard (no kernel
outbound) stays skipped; a kernel that cannot be reached stays skipped
instead of marking working nodes failed.
"""
import socket
import sys
import threading
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core import health  # noqa: E402


def node(tag, protocol, server="127.0.0.1", port=1):
    return SimpleNamespace(tag=tag, protocol=protocol, server=server,
                          server_port=port, params={})


def test_tuic_uses_kernel_delay(monkeypatch):
    seen = {}

    def fake_delay(tag, timeout_s, test_url):
        seen["args"] = (tag, timeout_s, test_url)
        return True, 206.0, ""

    out = health.check_nodes([node("hysteria2-22105", "hysteria2")],
                             kernel_delay_fn=fake_delay)
    assert out[0].ok is True and out[0].latency_ms == 206.0
    assert seen["args"][0] == "hysteria2-22105"


def test_kernel_delay_timeout_maps_to_failed(monkeypatch):
    monkeypatch.setattr(
        health.clashapi, "clash_get",
        lambda path, timeout: (False, {"error": "context deadline exceeded",
                                       "message": "Timeout"}))
    ok, latency, err = health.kernel_delay("tuic-22100", 5.0,
                                           health.DEFAULT_TEST_URL)
    assert ok is False and latency is None and "Timeout" in err


def test_kernel_delay_success_maps(monkeypatch):
    monkeypatch.setattr(
        health.clashapi, "clash_get",
        lambda path, timeout: (True, {"delay": 1337}))
    ok, latency, err = health.kernel_delay("tuic-22100 #2", 5.0,
                                           health.DEFAULT_TEST_URL)
    assert ok is True and latency == 1337.0 and err == ""


def test_kernel_unreachable_stays_skipped(monkeypatch):
    monkeypatch.setattr(
        health.clashapi, "clash_get",
        lambda path, timeout: (False, {"error": "[Errno 111] Connection refused"}))
    ok, latency, err = health.kernel_delay("tuic-22100", 5.0,
                                           health.DEFAULT_TEST_URL)
    assert ok is None and latency is None and "skipped" in err


def test_wireguard_still_skipped():
    out = health.check_nodes(
        [node("wg-1", "wireguard")],
        kernel_delay_fn=lambda *a: (_ for _ in ()).throw(AssertionError("must not be called")))
    assert out[0].ok is None and out[0].latency_ms is None


def test_tcp_path_unchanged_via_loopback():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    t = threading.Thread(target=lambda: srv.accept(), daemon=True)
    t.start()
    try:
        out = health.check_nodes(
            [node("vless-1", "vless", "127.0.0.1", port)])
        assert out[0].ok is True and out[0].latency_ms is not None
    finally:
        srv.close()
