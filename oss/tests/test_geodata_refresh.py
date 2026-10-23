"""Self-test for geodata TTL refresh (core/geodata.py refresh_names)."""

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import geodata as gd  # noqa: E402

NOW = 1_800_000_000


def _setup(files, rows):
    tmp = tempfile.mkdtemp()
    os.environ["OBX_GEODATA"] = tmp
    for name, content, mtime in files:
        p = os.path.join(tmp, f"{name}.srs")
        with open(p, "wb") as f:
            f.write(content)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
    conn = sqlite3.connect(":memory:")
    gd.ensure_state_table(conn)
    for name, url, at in rows:
        conn.execute("INSERT INTO geodata_state VALUES (?, ?, ?)",
                     (name, url, at))
    conn.commit()
    return tmp, conn


def main() -> int:
    calls = []

    def fake_download(url, dest, timeout=60):
        calls.append(url)
        with open(dest + ".part", "wb") as f:
            f.write(b"new-bytes")
        os.replace(dest + ".part", dest)

    def failing_download(url, dest, timeout=60):
        calls.append(url)
        raise OSError("network down")

    orig = gd._download
    try:
        # 1. fresh record + file -> reused, zero downloads, row untouched
        gd._download = fake_download
        _, c = _setup([("geosite-youtube", b"old", NOW - 100)],
                      [("geosite-youtube", gd._urls("geosite-youtube")[0],
                        NOW - 100)])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert r["reused"] == ["geosite-youtube"] and not calls, r
        assert c.execute("SELECT at FROM geodata_state").fetchone()[0] \
            == NOW - 100

        # 2. stale record + file + download ok -> downloaded, row updated
        calls.clear()
        _, c = _setup([("geosite-youtube", b"old", NOW - 100000)],
                      [("geosite-youtube", gd._urls("geosite-youtube")[0],
                        NOW - 100000)])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert r["downloaded"] == ["geosite-youtube"] and len(calls) == 1, r
        row = c.execute("SELECT url, at FROM geodata_state").fetchone()
        assert row[0] == calls[0] and row[1] == NOW, row

        # 3. stale + file + download fails -> kept_old, row + file untouched
        calls.clear()
        gd._download = failing_download
        _, c = _setup([("geosite-youtube", b"old", NOW - 100000)],
                      [("geosite-youtube", gd._urls("geosite-youtube")[0],
                        NOW - 100000)])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert len(r["kept_old"]) == 1 and r["kept_old"][0]["name"] \
            == "geosite-youtube", r
        assert c.execute("SELECT at FROM geodata_state").fetchone()[0] \
            == NOW - 100000
        assert open(os.path.join(os.environ["OBX_GEODATA"],
                                  "geosite-youtube.srs"), "rb").read() == b"old"

        # 4. no file + download fails -> missing (never fatal)
        calls.clear()
        _, c = _setup([], [])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert r["missing"] == ["geosite-youtube"], r

        # 5. no row + recent file -> reused + seeded row (mtime as provenance)
        calls.clear()
        gd._download = fake_download
        _, c = _setup([("geosite-youtube", b"old", NOW - 100)], [])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert r["reused"] == ["geosite-youtube"] and not calls, r
        row = c.execute("SELECT url, at FROM geodata_state").fetchone()
        assert row[0] == gd._urls("geosite-youtube")[0] \
            and row[1] == NOW - 100, row

        # 6. no row + old file -> downloaded (mtime stale)
        calls.clear()
        _, c = _setup([("geosite-youtube", b"old", NOW - 100000)], [])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert r["downloaded"] == ["geosite-youtube"], r

        # 7. url changed (record not in current candidates) + fresh -> download
        calls.clear()
        _, c = _setup([("geosite-youtube", b"old", NOW - 100)],
                      [("geosite-youtube", "https://old.example/x.srs",
                        NOW - 100)])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert r["downloaded"] == ["geosite-youtube"], r

        # 8. prune: unreferenced row removed by default, kept with keep_others
        _, c = _setup([("geosite-youtube", b"old", NOW - 100)],
                      [("geosite-youtube", gd._urls("geosite-youtube")[0],
                        NOW - 100),
                       ("geoip-old", "https://x/y.srs", NOW - 100)])
        r = gd.refresh_names(c, ["geosite-youtube"], now=NOW)
        assert r["pruned"] == ["geoip-old"], r
        assert c.execute("SELECT COUNT(*) FROM geodata_state").fetchone()[0] == 1
        _, c = _setup([("geosite-youtube", b"old", NOW - 100)],
                      [("geosite-youtube", gd._urls("geosite-youtube")[0],
                        NOW - 100),
                       ("geoip-old", "https://x/y.srs", NOW - 100)])
        r = gd.refresh_names(c, ["geosite-youtube"], keep_others=True, now=NOW)
        assert r["pruned"] == [], r
        assert c.execute("SELECT COUNT(*) FROM geodata_state").fetchone()[0] == 2

        # 9. non-downloadable name: present -> local, absent -> missing
        _, c = _setup([("list-custom", b"x", NOW - 100)], [])
        r = gd.refresh_names(c, ["list-custom"], now=NOW)
        assert r["local"] == ["list-custom"] and r["missing"] == [], r
        _, c = _setup([], [])
        r = gd.refresh_names(c, ["list-custom"], now=NOW)
        assert r["missing"] == ["list-custom"], r

        # 10. parallel: several stale files all downloaded, no crash
        calls.clear()
        files = [(f"geosite-t{i}", b"old", NOW - 100000) for i in range(6)]
        rows = [(f"geosite-t{i}", gd._urls(f"geosite-t{i}")[0],
                 NOW - 100000) for i in range(6)]
        _, c = _setup(files, rows)
        r = gd.refresh_names(c, [f"geosite-t{i}" for i in range(6)], now=NOW)
        assert len(r["downloaded"]) == 6, r
    finally:
        gd._download = orig
        os.environ.pop("OBX_GEODATA", None)

    print("OK: geodata refresh — all cases pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
