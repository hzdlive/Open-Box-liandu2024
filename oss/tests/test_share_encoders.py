"""Share-encoder round-trip tests (socks + ss plugin).

encode_node output must parse back to the same node: protocol, server,
port and params subset. This closes the socks gap left by the 43/43
golden (parse-only) and the ss plugin loss on export.
"""
import sys

sys.path.insert(0, "oss")

from core.share import encode_node
from core.subscription import parse_subscription


def _roundtrip(node: dict) -> dict:
    link = encode_node(node)
    parsed = parse_subscription(link)
    assert len(parsed) == 1, (link, parsed)
    n = parsed[0]
    assert n.protocol == node["protocol"], (link, n.protocol)
    assert n.server == node["server"] and n.server_port == node["port"], link
    assert n.tag == node["tag"], (link, n.tag)
    return n


def test_socks_roundtrip():
    cases = [
        {"tag": "s5", "protocol": "socks", "server": "example.com", "port": 1080,
         "params": {"username": "user", "password": "p@ss", "version": "5"}},
        {"tag": "s5-anon", "protocol": "socks", "server": "example.com", "port": 1080,
         "params": {"version": "5"}},
        {"tag": "s4a", "protocol": "socks", "server": "example.com", "port": 1080,
         "params": {"version": "4a"}},
        {"tag": "s4", "protocol": "socks", "server": "example.com", "port": 1080,
         "params": {"version": "4"}},
        {"tag": "s5-user-only", "protocol": "socks", "server": "example.com",
         "port": 1080, "params": {"username": "only", "version": "5"}},
    ]
    for node in cases:
        n = _roundtrip(node)
        assert n.params.get("version") == node["params"]["version"], node
        assert n.params.get("username") == node["params"].get("username"), node
        assert n.params.get("password") == node["params"].get("password"), node


def test_ss_plugin_roundtrip():
    node = {"tag": "ss-obfs", "protocol": "shadowsocks", "server": "example.com",
            "port": 8388, "params": {"method": "aes-256-gcm", "password": "pw",
                                     "plugin": "obfs-local",
                                     "plugin_opts": "obfs=http;obfs-host=b.example.com"}}
    n = _roundtrip(node)
    assert n.params["plugin"] == "obfs-local", n.params
    assert n.params["plugin_opts"] == "obfs=http;obfs-host=b.example.com", n.params
    # No plugin -> no query string, plain form unchanged.
    plain = {"tag": "ss", "protocol": "shadowsocks", "server": "example.com",
             "port": 8388, "params": {"method": "aes-256-gcm", "password": "pw"}}
    link = encode_node(plain)
    assert "?" not in link, link
    _roundtrip(plain)


if __name__ == "__main__":
    test_socks_roundtrip()
    test_ss_plugin_roundtrip()
    print("OK: share encoders (socks + ss plugin) — all cases pass")
