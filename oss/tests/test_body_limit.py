"""Per-route body limits (original effective behavior).

- Default 1mb for real /api/* routes; 32mb for the backup import
  (POST /api/backup).
- Unmatched paths are never 413'd: the original's parsers live on
  routers, so a 2MB POST to an unmatched path answers 404, not 413
  (verified live against the original panel).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import create_app  # noqa: E402

MB = 1024 * 1024


def _client():
    return create_app(":memory:").test_client()


def test_unmatched_path_never_413():
    c = _client()
    r = c.post("/api/nope", data=b"x" * (2 * MB),
               content_type="application/json")
    assert r.status_code == 404
    r = c.post("/api/nope", data=b"x" * (40 * MB),
               content_type="application/json")
    assert r.status_code == 404


def test_real_route_over_1mb_is_413():
    # The 1mb default is proven on a NON-subscription route: the
    # subscriptions routers moved to 10mb (upgrade-report item 3), so
    # /api/subscriptions no longer 413s at 1mb (see the 10mb test below).
    c = _client()
    r = c.post("/api/openbox/route-test", data=b"x" * (MB + 1),
               content_type="application/json")
    assert r.status_code == 413
    assert r.get_json()["error"] == "request entity too large"


def test_subscription_routes_10mb():
    # Upgrade-report item 3: both subscriptions routers (the
    # /api/openbox/subscriptions router and the /api/subscriptions
    # alias) carry 10mb.
    c = _client()
    r = c.post("/api/subscriptions", data=b"x" * (10 * MB + 1),
               content_type="application/json")
    assert r.status_code == 413
    assert r.get_json()["error"] == "request entity too large"
    # Exactly at the limit passes the gate (the gate is `cl > limit`).
    # Raw bytes keep the body at exactly 10mb; a 10mb *name* inside a
    # JSON object would exceed it by the object's own framing.
    r = c.post("/api/subscriptions", data=b"x" * (10 * MB),
               content_type="application/json")
    assert r.status_code != 413


def test_real_route_at_1mb_passes_gate():
    c = _client()
    r = c.post("/api/subscriptions", data=b"x" * MB,
               content_type="application/json")
    assert r.status_code != 413


def test_put_route_limited_too():
    c = _client()
    r = c.put("/api/settings", data=b"x" * (MB + 1),
              content_type="application/json")
    assert r.status_code == 413


def test_backup_import_allows_32mb():
    c = _client()
    r = c.post("/api/backup", data=b"x" * (2 * MB),
               content_type="application/json")
    assert r.status_code != 413
    r = c.post("/api/backup", data=b"x" * (32 * MB + 1),
               content_type="application/json")
    assert r.status_code == 413


def test_get_without_body_unaffected():
    c = _client()
    assert c.get("/api/status").status_code == 200
