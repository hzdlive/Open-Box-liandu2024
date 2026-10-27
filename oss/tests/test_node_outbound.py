"""Tests for node_to_outbound protocol normalization (singbox.py).

Covers the gaps that made whole protocol families unusable:
http dropped credentials, socks5/https were emitted verbatim although
sing-box has no such outbound types.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import Node  # noqa: E402
from core.singbox import node_to_outbound  # noqa: E402


def test_http_keeps_credentials():
    ob = node_to_outbound(Node(tag="h", protocol="http",
                               server="example.com", server_port=8080,
                               params={"username": "u", "password": "p"}))
    assert ob["type"] == "http"
    assert ob["username"] == "u"
    assert ob["password"] == "p"


def test_socks5_maps_to_socks():
    ob = node_to_outbound(Node(tag="s", protocol="socks5",
                               server="example.com", server_port=1080,
                               params={"username": "u"}))
    assert ob["type"] == "socks"
    assert "version" not in ob  # 5 is the default, omitted like socks
    assert ob["username"] == "u"


def test_https_maps_to_http_with_tls():
    ob = node_to_outbound(Node(tag="t", protocol="https",
                               server="example.com", server_port=443,
                               params={"username": "u"}))
    assert ob["type"] == "http"
    assert ob["tls"] == {"enabled": True}
    assert ob["username"] == "u"


def test_socks_version_preserved():
    ob = node_to_outbound(Node(tag="s4", protocol="socks",
                               server="example.com", server_port=1080,
                               params={"version": "4a"}))
    assert ob["type"] == "socks"
    assert ob["version"] == "4a"
