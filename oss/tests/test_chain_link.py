"""Tests for chain link refinement (panel/db.refine_chain_link).

The chain modal's link parser collapses every non-http scheme to http;
the backend must re-derive protocol/server/port/params from the link
with the subscription parsers, or link-mode creation stores broken
chains (chain 14: an ss:// link stored as http, no cipher method).
"""

import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from panel.db import refine_chain_link  # noqa: E402


def _ss_link():
    userinfo = base64.b64encode(b"2022-blake3-aes-256-gcm:secretpw").decode()
    return f"ss://{userinfo}@sanjose.example.com:22101#SanJose"


def test_ss_link_refined():
    r = refine_chain_link(_ss_link())
    assert r is not None
    assert r["exit_protocol"] == "shadowsocks"
    assert r["server"] == "sanjose.example.com"
    assert r["port"] == 22101
    assert r["params"]["method"] == "2022-blake3-aes-256-gcm"
    assert r["params"]["password"] == "secretpw"
    assert r["params"]["link"] == _ss_link()


def test_vless_link_refined():
    link = ("vless://11111111-2222-3333-4444-555555555555@host.example.com"
            ":443?security=tls&sni=host.example.com#VL")
    r = refine_chain_link(link)
    assert r is not None
    assert r["exit_protocol"] == "vless"
    assert r["server"] == "host.example.com"
    assert r["port"] == 443
    assert r["params"]["uuid"] == "11111111-2222-3333-4444-555555555555"
    assert r["params"]["tls"]["server_name"] == "host.example.com"


def test_http_link_kept_as_is():
    # http/https links are already parsed correctly by the modal;
    # refinement stays out of the way.
    assert refine_chain_link("http://user:pass@h.example.com:8080") is None
    assert refine_chain_link("https://h.example.com:443") is None


def test_unparseable_and_empty():
    assert refine_chain_link("") is None
    assert refine_chain_link("not a link") is None
    assert refine_chain_link("unknown://x.example.com:1234") is None
