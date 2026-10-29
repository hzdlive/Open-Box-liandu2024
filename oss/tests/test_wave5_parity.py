"""Wave5 parity (upgrade report items 1+2): our /api/openbox/* error
shapes and status codes against the third-party contract.

Fixtures (provenance: panel-contract/ from Open-Box-liandu2024_0_opjx.zip,
2026-10-29 package; failure bodies measured against a scratch panel):
- fixtures/fail-shapes.json: per-route failure observations.
- fixtures/contract-status.json: route -> completed status list.

Scope: the 28 (method, path) pairs where our routes intersect the
fail-shape routes. Deliberately excluded, with reasons:
- 401/403 everywhere: we have no auth by design (no fake auth).
- DELETE /api/openbox/subscription-shares/:id on a never-existed id:
  fail-shapes says 404, write-shapes re-delete says 200; the distinction
  needs a black-box check on the original panel (mutates original data)
  and is blocked as upgrade-report item 4. Our openbox share delete
  stays unconditional-200 until that check lands.
- POST /api/openbox/deploy: side effect (real deploy). Never invoked.
- POST /api/openbox/dns/flush-cache 503: environment outcome, not a
  contract shape. POST /api/openbox/dns/region-detect: live IP lookup.
- Success-body key sets (e.g. content-filter DELETE returning the full
  summary): a separate parity area, not asserted here.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db as dbmod  # noqa: E402
from panel.app import create_app  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
FAIL_SHAPES = json.loads((FIX / "fail-shapes.json").read_text())
CONTRACT_STATUS = json.loads((FIX / "contract-status.json").read_text())


def _app():
    return create_app(":memory:")


def _dbconn(app):
    return sqlite3.connect(app.config["DB_DSN"], uri=app.config["DB_URI"])


# (method, path, body, expected_status, expected_error_keys)
# Keys are exact: the original never sends the {code, error, message}
# union; each probed failure carries exactly the keys listed.
ERROR_PROBES = [
    ("PATCH", "/api/openbox/content-filter/nope", {}, 404, ["error"]),
    ("POST", "/api/openbox/failover/recheck", {}, 400, ["error"]),
    ("POST", "/api/openbox/penetration", {}, 400, ["message"]),
    ("POST", "/api/openbox/route-test", {}, 400, ["message"]),
    ("POST", "/api/openbox/subscription-shares/", {}, 400, ["error"]),
    ("PATCH", "/api/openbox/subscription-shares/999999", {}, 404, ["error"]),
    ("POST", "/api/openbox/subscription-shares/999999/regenerate", None,
     404, ["error"]),
    ("PUT", "/api/openbox/subscriptions/order", {}, 400, ["error"]),
    ("POST", "/api/openbox/subscriptions/preview", {}, 400, ["error"]),
    ("POST", "/api/openbox/terminal-test", {}, 400, ["message"]),
]


def _call(c, method, path, body):
    if method == "GET":
        return c.get(path)
    if method == "POST":
        return c.post(path, json=body) if body is not None else c.post(path)
    if method == "PUT":
        return c.put(path, json=body)
    if method == "PATCH":
        return c.patch(path, json=body)
    if method == "DELETE":
        return c.delete(path)
    raise AssertionError(method)


def test_error_shapes_match_fail_shapes():
    """Each probed failure returns the original's status and exact keys.

    Collects every mismatch before failing, so one run lists all gaps.
    """
    app = _app()
    c = app.test_client()
    failures = []
    for method, path, body, status, keys in ERROR_PROBES:
        # Terminal-test's container gate is environment-dependent; the
        # shape gate under test is the target-shape 400.
        if path == "/api/openbox/terminal-test":
            with mock.patch("core.terminal_test.is_container",
                            return_value=False):
                r = _call(c, method, path, body)
        else:
            r = _call(c, method, path, body)
        if r.status_code != status:
            failures.append((method, path, "status", r.status_code, status,
                             r.get_data(as_text=True)[:200]))
            continue
        got = sorted(r.get_json().keys())
        if got != sorted(keys):
            failures.append((method, path, "keys", got, keys, ""))
        # The expectation itself must come from the contract, not lore:
        # the expected status must be in the completed status list
        # (minus the auth statuses we deliberately do not implement).
        contract_key = method + " " + path.replace(
            "/nope", "/:id").replace("/999999", "/:id")
        allowed = set(CONTRACT_STATUS.get(contract_key, [])) - {401, 403}
        if status not in allowed:
            failures.append((method, path, "contract", status, allowed, ""))
    assert not failures, failures


def test_success_status_parity():
    """Representative success requests return a status the original lists."""
    app = _app()
    c = app.test_client()
    for path in ("/api/openbox/content-filter",
                 "/api/openbox/deploy/state",
                 "/api/openbox/diagnostics",
                 "/api/openbox/failover/status",
                 "/api/openbox/subscription-shares/",
                 "/api/openbox/terminal-test/capability",
                 "/api/openbox/dns/region-detect"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code,
                                      r.get_data(as_text=True)[:200])
        key = "GET " + path
        allowed = set(CONTRACT_STATUS.get(key, [])) - {401, 403}
        assert 200 in allowed, (key, allowed)


# NOTE: no blanket fixture-vs-contract agreement test. The measured
# fail-shapes are in places MORE complete than the contract lists (e.g.
# GET /api/openbox/activation observes a 500 the contract never recorded),
# which is exactly why wave5 exists. Agreement is asserted per probe
# above, where each expected status was verified to be in its route's
# completed list.


def test_subscription_body_limit_10mb():
    """Upgrade-report item 3: the subscriptions router carries 10mb,
    while other /api/* routes stay at 1mb."""
    app = _app()
    c = app.test_client()
    big = "x" * (1024 * 1024 + 100)
    # Preview with a huge content body: not 413 (10mb), and the preview
    # itself answers 200 with zero parsed nodes for junk content.
    r = c.post("/api/openbox/subscriptions/preview",
               json={"content": big})
    assert r.status_code == 200, (r.status_code,
                                  r.get_data(as_text=True)[:200])
    # Control: the same oversized body on a non-subscription route
    # is still 413 (the handler never runs).
    r = c.post("/api/openbox/route-test", json={"target": big})
    assert r.status_code == 413, r.status_code
