"""HTTP surface alignment with the original (Express) panel.

Verified live against the original panel (2026) without login:
- unmatched /api/* -> finalhandler 404 page (text/html, `Cannot <METHOD>
  <path>` with no query, nosniff + default-src 'none' headers);
- SPA fallback excludes only the case-sensitive literal `/api/`, so
  /API/* and /Api/* get the shell;
- X-Powered-By: Express on every response;
- static cache rules: hashed JS/CSS immutable, shell/manifest never
  stored, everything else public, max-age=0.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import FRONTEND_DIR, create_app  # noqa: E402

FINAL_404 = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    "<meta charset=\"utf-8\">\n<title>Error</title>\n</head>\n"
    "<body>\n<pre>Cannot %s %s</pre>\n</body>\n</html>\n"
)


def _client():
    return create_app(":memory:").test_client()


def test_api_fallthrough_finalhandler_page():
    c = _client()
    r = c.get("/api/nope")
    assert r.status_code == 404
    assert r.data.decode() == FINAL_404 % ("GET", "/api/nope")
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Content-Security-Policy"] == "default-src 'none'"
    assert r.headers["X-Powered-By"] == "Express"


def test_api_fallthrough_ignores_query_and_uses_method():
    c = _client()
    r = c.get("/api/HEALTH?x=1&y=2")
    assert r.status_code == 404
    assert "Cannot GET /api/HEALTH</pre>" in r.data.decode()
    assert "?x=1" not in r.data.decode()
    r = c.post("/api/nope", json={})
    assert r.status_code == 404
    assert "Cannot POST /api/nope</pre>" in r.data.decode()


def test_api_fallthrough_escapes_path():
    c = _client()
    r = c.get("/api/%3Cscript%3E")
    assert r.status_code == 404
    assert "<script>" not in r.data.decode()
    assert "&lt;script&gt;" in r.data.decode()


def test_spa_fallback_case_sensitive():
    c = _client()
    for p in ("/API/HEALTH", "/Api/HEALTH", "/some-page"):
        r = c.get(p)
        assert r.status_code == 200, p
        assert b'<div id="app">' in r.data
    # Real API routes are not shadowed by the fallthrough.
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/status").status_code == 200


def test_powered_by_on_api_response():
    c = _client()
    r = c.get("/api/status")
    assert r.headers["X-Powered-By"] == "Express"


def test_static_cache_rules():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store, no-cache, must-revalidate"
    r = c.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "public, max-age=0"
    dist = Path(FRONTEND_DIR)
    js = sorted((dist / "assets").glob("*.js")) if (dist / "assets").exists() else []
    if js:
        r = c.get(f"/assets/{js[0].name}")
        assert r.status_code == 200
        assert r.headers["Cache-Control"] == \
            "public, max-age=31536000, immutable"
