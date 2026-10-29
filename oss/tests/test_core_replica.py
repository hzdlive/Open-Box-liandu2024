"""Core replica slice 1: wire protocol + hello + dispatch errors.

Fixture: fixtures/core-protocol.json (panel-contract/core-protocol.json
from the 2026-10-29 package: 28 malformed-input cases measured against
the real core; inputs are synthetic malformed JSON, no credentials).

The golden corpus (core-golden.json, 212 cases) is NOT a fixture here:
it is 35 MB and a snapshot of a live install. Method parity against it
is measured with oss/core-replica/harness.py, passing the corpus path
explicitly.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "core-replica"))

import main as core_main  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
PROTOCOL = json.loads((FIX / "core-protocol.json").read_text())


def _protocol_cases():
    cases = PROTOCOL.get("cases", [])
    assert len(cases) == 28, len(cases)
    return cases


def test_protocol_cases_exact():
    """Every measured case answers its own exact stdout.

    Error cases compare exactly (all four sentences, in check order).
    Hello success cases compare ok/protocol plus OUR identity fields:
    the fixture's go-native implementation, original buildID and
    bindingSha256 are deliberately NOT reproduced (no impersonation;
    see core-replica/README.md), so those fields are asserted against
    our values instead of the fixture's.
    """
    for case in _protocol_cases():
        got = core_main.handle(case["input"])
        want = json.loads(case["stdout"])
        if not want.get("ok"):
            assert got == want, (case["id"], case["input"][:80], got)
        else:
            assert got["ok"] is True and got["protocol"] == 1, (
                case["id"], got)
            v = got["value"]
            assert v["implementation"] == "oss-python", (case["id"], v)
            assert v["protocol"] == 1, (case["id"], v)
            assert v["buildID"] == core_main.VERSION, (case["id"], v)
            assert v["methods"] == [], (case["id"], v)
            assert "bindingSha256" not in v, (case["id"], v)


def test_hello_returns_our_identity():
    """Handshake: our own implementation/buildID, never the original's
    go-native pin (we do not impersonate; see core-replica/README.md)."""
    got = core_main.handle(json.dumps(
        {"protocol": 1, "method": "hello", "args": []}))
    assert got["ok"] is True and got["protocol"] == 1
    assert got["value"]["implementation"] == "oss-python"
    assert got["value"]["protocol"] == 1
    assert got["value"]["buildID"] == core_main.VERSION


def test_unknown_method_and_licence_methods_are_distinct():
    """Unknown names, unimplemented methods, and the excluded licence
    family must never be conflated."""
    base = {"protocol": 1, "args": []}
    got = core_main.handle(json.dumps({**base, "method": "nope"}))
    assert got == {"protocol": 1, "ok": False,
                   "error": "unsupported native-core method"}
    got = core_main.handle(json.dumps(
        {**base, "method": "normalizeRouting"}))
    assert got == {"protocol": 1, "ok": False,
                   "error": "not implemented yet"}
    for m in ("activationState", "checkActivationCode", "verifyLicense",
              "authorizationState", "featureAccess"):
        got = core_main.handle(json.dumps({**base, "method": m}))
        assert got == {"protocol": 1, "ok": False,
                       "error": core_main.LICENCE_OUT_OF_SCOPE}, m


def test_subprocess_round_trip():
    """The process boundary itself: one JSON in, one JSON out, exit 0
    even for an invalid request."""
    root = Path(__file__).resolve().parent.parent / "core-replica"
    req = json.dumps({"protocol": 1, "method": "hello", "args": []})
    p = subprocess.run([sys.executable, str(root / "main.py")],
                       input=req.encode(), capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr.decode()[:200]
    out = json.loads(p.stdout.decode())
    assert out["ok"] is True and out["value"]["protocol"] == 1
    p = subprocess.run([sys.executable, str(root / "main.py")],
                       input=b"not json", capture_output=True, timeout=30)
    assert p.returncode == 0
    out = json.loads(p.stdout.decode())
    assert out == {"protocol": 1, "ok": False,
                   "error": "invalid native-core request"}
    # Trailing data and protocol mismatch keep exit 0 too.
    p = subprocess.run([sys.executable, str(root / "main.py")],
                       input=b'{"protocol":1,"method":"hello","args":[]} x',
                       capture_output=True, timeout=30)
    assert p.returncode == 0
    out = json.loads(p.stdout.decode())
    assert out == {"protocol": 1, "ok": False,
                   "error": "trailing native-core request data"}
