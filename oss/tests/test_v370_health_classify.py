"""v0.1.370: speedtest errors are classified, original error kept.

DNS failure and local resource exhaustion must not be judged as node
faults (direct probes mark them skipped, same precedent as
kernel-unreachable); timeout and ordinary connect failures stay
failed. Kernel delay API failures keep their verdict and only gain
a kind label.
"""
import errno
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oss"))

from core import health  # noqa: E402


def node(tag, protocol, server="203.0.113.7", port=443):
    return SimpleNamespace(tag=tag, protocol=protocol, server=server,
                          server_port=port, params={})


def test_dns_failure_skipped_not_failed(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr(health.socket, "create_connection", boom)
    out = health.check_node(node("n1", "vless"))
    assert out.ok is None and out.error_kind == "dns"
    assert "Name or service not known" in out.error


def test_resource_exhaustion_skipped(monkeypatch):
    def boom(*a, **k):
        raise OSError(errno.EMFILE, "Too many open files")
    monkeypatch.setattr(health.socket, "create_connection", boom)
    out = health.check_node(node("n1", "vless"))
    assert out.ok is None and out.error_kind == "resource"
    assert "Too many open files" in out.error


def test_timeout_stays_failed(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(health.socket, "create_connection", boom)
    out = health.check_node(node("n1", "vless"))
    assert out.ok is False and out.error_kind == "timeout"


def test_refused_stays_failed_as_connect(monkeypatch):
    def boom(*a, **k):
        raise ConnectionRefusedError(111, "Connection refused")
    monkeypatch.setattr(health.socket, "create_connection", boom)
    out = health.check_node(node("n1", "vless"))
    assert out.ok is False and out.error_kind == "connect"


def test_kernel_delay_timeout_classified_verdict_unchanged():
    out = health.check_node(
        node("tuic-1", "tuic"),
        kernel_delay_fn=lambda *a: (False, None, "kernel delay: Timeout"))
    assert out.ok is False and out.error_kind == "timeout"


def test_kernel_unreachable_kind():
    out = health.check_node(
        node("tuic-1", "tuic"),
        kernel_delay_fn=lambda *a: (None, None, "kernel unreachable, skipped"))
    assert out.ok is None and out.error_kind == "kernel"


def test_classify_message_fallbacks():
    assert health.classify_error(message="no such host") == "dns"
    assert health.classify_error(message="Cannot assign requested address") == "resource"
    assert health.classify_error(message="context deadline exceeded") == "connect"
