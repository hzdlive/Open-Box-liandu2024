"""Wave6 items 1+2 (2026-11-01): content-filter DELETE projection.

DELETE /api/openbox/content-filter/<id> returns the deleted object's
metadata with exactly the contract keys (hostnames, sets, sha256,
size, version). Mapping notes (documented in the handler): version is
updated_at (no separate version column exists), sets is the ruleset's
own set name, sha256/size are computed from the stored text.
Deleting a missing id stays 200 (the contract status list for this
DELETE has no 404).
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.app import create_app  # noqa: E402

TEXT = "[Rule]\nDOMAIN-SUFFIX,example.com,REJECT\n"


def _client():
    return create_app(":memory:").test_client()


def test_cf_delete_returns_projection_then_missing_stays_200():
    c = _client()
    r = c.post("/api/openbox/content-filter",
               json={"name": "del-test", "dialect": "surge", "text": TEXT})
    assert r.status_code == 200, r.get_json()
    rid = r.get_json()["id"]
    r = c.delete(f"/api/openbox/content-filter/{rid}")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"hostnames", "sets", "sha256", "size",
                         "version"}
    assert body["sets"] == ["del-test"]
    assert body["sha256"] == hashlib.sha256(
        TEXT.encode("utf-8")).hexdigest()
    assert body["size"] == len(TEXT.encode("utf-8"))
    assert body["version"]  # updated_at timestamp
    # Row is gone; deleting again stays 200 with the old shape.
    r = c.delete(f"/api/openbox/content-filter/{rid}")
    assert r.status_code == 200
    assert r.get_json() == {"deleted": True}
    # Unknown id from the start: same 200 shape.
    r = c.delete("/api/openbox/content-filter/0123456789abcdef")
    assert r.status_code == 200
    assert r.get_json() == {"deleted": True}
