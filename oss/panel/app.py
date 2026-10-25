"""Panel backend API (Flask). Clean-room reimplementation of the publicly
documented management capabilities; no proprietary code involved."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

from flask import Flask, g, jsonify, request, send_from_directory

from core.routing import preview_route
from core.singbox import build_config
from panel import db as dbmod

VERSION = "0.1.0-oss"

# ---- panel-managed dnsmasq drop-in (auto-sync) ----
# The panel keeps /etc/dnsmasq.d/openbox-panel.conf in sync with its own
# state (enabled rewrites + filter blocklist include) so a DNS settings
# edit takes effect without a manual install step. This is deliberately
# NOT the full router snippet: that snippet forwards all DNS to
# sing-box:1053, which does not listen on this host.
PANEL_DNSMASQ_CONF = "/etc/dnsmasq.d/openbox-panel.conf"


def dnsmasq_panel_conf_content(c) -> str:
    """File content for the panel-managed drop-in (pure panel state)."""
    from core import transparent as _tp
    from core import dnsfilter as _df
    from core.service import manager_from_env
    from panel.db import get_setting
    lines = [
        "# Managed by openbox-oss panel (auto-synced on rewrite/filter changes).",
        "# Do not edit by hand: the panel overwrites this file.",
        "# Minimal subset for this host (NOT the full router snippet).",
        "# Rewrites (enabled rows only):",
    ]
    for r in dbmod.list_dns_rewrites(c):
        if not r.get("enabled"):
            continue
        line = _tp.rewrite_dnsmasq_line(r["domain"], r["target"])
        lines.append(line if line is not None else
                     f"# skipped invalid rewrite: {r['domain']} -> {r['target']}")
    if get_setting(c, "dns_filter_enabled", "0") == "1":
        bp = _df.blocklist_path(manager_from_env().workdir)
        if os.path.exists(bp):
            lines.append("# DNS filter blocklist:")
            lines.append(f"conf-file={bp}")
    return "\n".join(lines) + "\n"


def sync_dnsmasq_panel_conf(c, conf_path=None, run=None) -> dict:
    """Regenerate the panel-managed drop-in from current panel state.

    Atomic write; `dnsmasq --test` must pass before any restart; on test
    failure the old file is restored. No restart when the content is
    unchanged or when dnsmasq is not running. Never raises: failures are
    reported so a DB change the caller already committed is not
    misreported as failed. SIGHUP is NOT used: it does not reload
    dnsmasq config files (verified live 2026-10-25), so a restart is
    required for changes to apply.
    """
    import shutil
    import subprocess
    import time
    path = conf_path or PANEL_DNSMASQ_CONF
    if run is None:
        def run(cmd):
            return subprocess.run(cmd, capture_output=True, timeout=30)
    try:
        new = dnsmasq_panel_conf_content(c)
    except Exception as e:
        return {"changed": False, "restarted": False, "error": str(e)}
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read()
    except OSError:
        old = None
    if old == new:
        return {"changed": False, "restarted": False}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, path)
    except OSError as e:
        return {"changed": False, "restarted": False, "error": str(e)}
    dnsmasq = shutil.which("dnsmasq") or "/usr/sbin/dnsmasq"
    try:
        tested = run([dnsmasq, "--test"])
    except (OSError, subprocess.TimeoutExpired) as e:
        tested = None
        test_error = str(e)
    else:
        test_error = "" if tested.returncode == 0 else "dnsmasq --test failed"
    if tested is None or tested.returncode != 0:
        try:
            if old is None:
                os.remove(path)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(old)
        except OSError:
            pass
        return {"changed": False, "restarted": False,
                "error": test_error or "dnsmasq --test could not run"}
    pgrep = shutil.which("pgrep") or "pgrep"
    try:
        running = run([pgrep, "-x", "dnsmasq"]).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        running = False
    if not running:
        return {"changed": True, "restarted": False,
                "note": "dnsmasq not running, file updated only"}
    method, ok = "systemctl", False
    try:
        ok = run(["systemctl", "restart", "dnsmasq"]).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:
        method = "kill+start"
        try:
            run(["pkill", "-x", "dnsmasq"])
            time.sleep(1)
            run([dnsmasq])
            time.sleep(1)
            ok = run([pgrep, "-x", "dnsmasq"]).returncode == 0
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"changed": True, "restarted": False,
                    "method": method, "error": str(e)}
    return {"changed": True, "restarted": ok, "method": method}


COMMON_TIMEZONES = [
    "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Taipei", "Asia/Tokyo",
    "Asia/Seoul", "Asia/Singapore", "Asia/Bangkok", "Asia/Dubai",
    "Asia/Kolkata", "Australia/Sydney", "Europe/London", "Europe/Paris",
    "Europe/Berlin", "Europe/Moscow", "America/New_York", "America/Chicago",
    "America/Denver", "America/Los_Angeles", "America/Anchorage",
    "Pacific/Auckland", "UTC",
]


def _read_timezone() -> dict:
    """Current timezone of the box. OpenWrt: /etc/TZ; else timedatectl/time."""
    import subprocess
    try:
        with open("/etc/TZ", encoding="utf-8") as f:
            return {"timezone": f.read().strip(), "source": "/etc/TZ",
                    "options": COMMON_TIMEZONES}
    except OSError:
        pass
    try:
        p = subprocess.run(["timedatectl", "show", "-p", "Timezone"],
                           capture_output=True, text=True, timeout=5)
        if p.returncode == 0 and "=" in p.stdout:
            return {"timezone": p.stdout.split("=", 1)[1].strip(),
                    "source": "timedatectl", "options": COMMON_TIMEZONES}
    except (OSError, subprocess.TimeoutExpired):
        pass
    import time as _time
    name = _time.tzname[0] if _time.tzname else "UTC"
    return {"timezone": name, "source": "system", "options": COMMON_TIMEZONES,
            "readonly": True}


def _write_timezone(tz: str) -> tuple[bool, str]:
    """Set the box timezone. Only OpenWrt (/etc/TZ + uci) is supported."""
    import subprocess
    if not os.path.isfile("/etc/openwrt_release"):
        return False, "仅支持在 OpenWrt 上修改时区"
    try:
        with open("/etc/TZ", "w", encoding="utf-8") as f:
            f.write(tz + "\n")
    except OSError as e:
        return False, f"写入 /etc/TZ 失败：{e}"
    try:
        subprocess.run(["uci", "set", "system.@system[0].timezone=" + tz],
                       timeout=5, capture_output=True)
        subprocess.run(["uci", "commit", "system"], timeout=5, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return True, "ok"
# oss-zashboard 分支：主 UI 换成基于 zashboard 二开的前端；旧自研 UI 保留在 /legacy/ 作为回退。
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "dashboard", "zashboard-src", "dist")
LEGACY_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")


def create_app(db_path: str = ":memory:") -> Flask:
    import hashlib
    import secrets
    from flask import session
    from werkzeug.security import check_password_hash, generate_password_hash

    app = Flask(__name__)

    # 内置出站组 id 为 0（直连）/-1（拒绝），Flask 的 <int:> 不匹配负数，
    # 注册有符号整型转换器供 /api/groups/<sint:gid> 使用。
    from werkzeug.routing import IntegerConverter

    class SignedIntConverter(IntegerConverter):
        regex = r"-?\d+"

    app.url_map.converters["sint"] = SignedIntConverter

    # Threading: a single sqlite3 connection handle must never be used from
    # two threads at once (the Flask dev server is threaded; concurrent
    # execute() on one handle fails with "bad parameter or other API
    # misuse"). Every request therefore opens its own connection, closed at
    # teardown. The ":memory:" test DB uses a shared-cache URI plus a keeper
    # connection so all requests still see the same database; the URI is
    # unique per app instance so separate create_app(":memory:") calls stay
    # isolated from each other (a fixed URI would leak state between tests).
    if db_path == ":memory:":
        _dsn = ("file:openbox_memdb_%s?mode=memory&cache=shared"
                % uuid.uuid4().hex)
        _keeper = sqlite3.connect(_dsn, uri=True, check_same_thread=False,
                                  timeout=30)
        _keeper.execute("PRAGMA foreign_keys=ON")
        dbmod.init_db(_keeper)
        app.config["MEM_KEEPER"] = _keeper  # keep the shared cache alive
        _uri = True
    else:
        _dsn, _uri = db_path, False
        _boot = sqlite3.connect(_dsn, timeout=30)
        _boot.execute("PRAGMA foreign_keys=ON")
        # WAL 模式：允许多线程并发读 + 单写，避免 scheduler 线程写 failover_state
        # 时阻塞 Web 请求线程导致 "database is locked" 白屏
        try:
            _boot.execute("PRAGMA journal_mode=WAL")
            _boot.execute("PRAGMA busy_timeout=30000")
            _boot.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        dbmod.init_db(_boot)
        _boot.close()

    # DSN of this app's database (tests use it to open their own connection;
    # request handlers must go through db() instead).
    app.config["DB_DSN"] = _dsn
    app.config["DB_URI"] = _uri

    # Session secret: env override, else random per boot (sessions don't
    # survive restart in that case — fine for dev, set the env in prod).
    app.secret_key = os.environ.get("OPENBOX_SECRET_KEY") or secrets.token_hex(32)

    def db() -> sqlite3.Connection:
        if "db_conn" not in g:
            c = sqlite3.connect(_dsn, uri=_uri, timeout=30)
            c.execute("PRAGMA foreign_keys=ON")
            try:
                c.execute("PRAGMA busy_timeout=30000")
            except Exception:
                pass
            g.db_conn = c
        return g.db_conn

    @app.teardown_appcontext
    def _close_db(exc):
        c = g.pop("db_conn", None)
        if c is not None:
            c.close()

    # Bootstrap panel password from env on first boot (no request context
    # here, so use a short-lived connection instead of db()).
    _pw = sqlite3.connect(_dsn, uri=_uri, timeout=30)
    try:
        if not dbmod.get_setting(_pw, "panel_password_hash"):
            _env_pw = os.environ.get("OPENBOX_PANEL_PASSWORD")
            if _env_pw:
                dbmod.set_setting(_pw, "panel_password_hash",
                                  generate_password_hash(_env_pw))
    finally:
        _pw.close()

    def _password_set() -> bool:
        return bool(dbmod.get_setting(db(), "panel_password_hash"))

    def _client_device():
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        h = hashlib.sha256(auth[7:].encode()).hexdigest()
        return dbmod.find_device_by_token_hash(db(), h)

    # Central auth gate for /api/*. Open paths: auth status/login and the
    # pairing confirm (the one-time code is its own credential). When no
    # panel password is set the panel runs in open dev mode.
    _OPEN = {"/api/auth/status", "/api/auth/login", "/api/pair/confirm"}

    @app.before_request
    def _auth_gate():
        if not request.path.startswith("/api/"):
            return None
        if request.path in _OPEN:
            return None
        if not _password_set():
            return None
        if session.get("logged_in"):
            return None
        if request.path.startswith("/api/client/") and _client_device():
            return None
        return jsonify({"error": "login required"}), 401

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": getattr(e, "description", "bad request")}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not found"}), 404

    # ---- auth ----
    @app.get("/api/auth/status")
    def auth_status():
        return jsonify({"has_password": _password_set(),
                        "logged_in": bool(session.get("logged_in"))})

    @app.post("/api/auth/login")
    def auth_login():
        d = request.get_json(force=True, silent=True) or {}
        pw_hash = dbmod.get_setting(db(), "panel_password_hash")
        if not pw_hash:
            return jsonify({"error": "no password set"}), 400
        if not check_password_hash(pw_hash, d.get("password", "")):
            return jsonify({"error": "wrong password"}), 401
        session["logged_in"] = True
        return jsonify({"logged_in": True})

    @app.post("/api/auth/logout")
    def auth_logout():
        session.clear()
        return jsonify({"logged_in": False})

    @app.post("/api/auth/password")
    def auth_password():
        d = request.get_json(force=True, silent=True) or {}
        new = d.get("new", "")
        if len(new) < 4:
            return jsonify({"error": "password too short (min 4)"}), 400
        cur = dbmod.get_setting(db(), "panel_password_hash")
        if cur and not check_password_hash(cur, d.get("old", "")):
            return jsonify({"error": "wrong current password"}), 401
        dbmod.set_setting(db(), "panel_password_hash", generate_password_hash(new))
        return jsonify({"ok": True})

    # ---- pairing ----
    @app.post("/api/pair/code")
    def pair_code():
        token = secrets.token_urlsafe(24)
        dbmod.create_pair_code(db(), token, ttl_s=600)
        return jsonify({"token": token, "expires_in": 600})

    @app.post("/api/pair/confirm")
    def pair_confirm():
        d = request.get_json(force=True, silent=True) or {}
        token = d.get("token", "")
        if not token or not dbmod.consume_pair_code(db(), token):
            return jsonify({"error": "invalid or expired pair code"}), 401
        client_token = secrets.token_urlsafe(32)
        h = hashlib.sha256(client_token.encode()).hexdigest()
        did = dbmod.register_device(db(), d.get("device", ""), h)
        return jsonify({"client_token": client_token, "device_id": did})

    @app.get("/api/pair/devices")
    def pair_devices():
        return jsonify(dbmod.list_devices(db()))

    @app.delete("/api/pair/devices/<int:did>")
    def pair_device_delete(did: int):
        if not dbmod.delete_device(db(), did):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    # ---- subscriptions ----
    @app.post("/api/subscriptions")
    def sub_create():
        import json as _json
        d = request.get_json(force=True, silent=True) or {}
        urls = [str(u).strip() for u in (d.get("urls") or []) if str(u).strip()]
        if not d.get("name") or (not d.get("content") and not urls):
            return jsonify({"error": "name and (content or urls) are required"}), 400
        # URL mode: create empty subscription then refresh from URLs
        if urls and not d.get("content"):
            c = db()
            au = d.get("auto_update") if isinstance(d.get("auto_update"), dict) else {}
            cur = c.execute(
                "INSERT INTO subscriptions(name, source, urls, url, created_at,"
                " auto_update_enabled, auto_update_days, auto_update_hour)"
                " VALUES (?, 'manual', ?, ?, ?, ?, ?, ?)",
                (d["name"], _json.dumps(urls, ensure_ascii=False), urls[0],
                 time.strftime("%Y-%m-%dT%H:%M:%S"),
                 1 if au.get("enabled") else 0,
                 max(1, int(au.get("days", 1) or 1)),
                 min(23, max(0, int(au.get("hour", 4) if au.get("hour") is not None else 4)))))
            sid = cur.lastrowid
            c.commit()
            try:
                r = dbmod.refresh_subscription(c, sid)
            except Exception as e:
                return jsonify({"error": f"fetch failed: {e}"}), 400
            return jsonify({"id": sid, "name": d["name"],
                            "node_count": r["node_count"],
                            "filtered_count": r.get("filtered_count", 0)}), 201
        try:
            sid, n = dbmod.add_subscription(db(), d["name"], d["content"],
                                            d.get("source", "manual"),
                                            d.get("format", "auto"),
                                            url=d.get("url"))
        except Exception as e:
            return jsonify({"error": f"parse failed: {e}"}), 400
        if urls:
            c = db()
            c.execute("UPDATE subscriptions SET urls=?, url=? WHERE id=?",
                      (_json.dumps(urls, ensure_ascii=False), urls[0], sid))
            c.commit()
        return jsonify({"id": sid, "name": d["name"], "node_count": n}), 201

    @app.get("/api/subscriptions")
    def sub_list():
        c = db()
        subs = dbmod.list_subscriptions(c)
        # 折叠卡片的节点圆点：前端模板早已读取 node_dots，但后端从未返回，
        # 故圆点从未画出来。这里按展开态徽标同款阈值（<300 绿、<800 黄、
        # 否则红、无数据灰）从 node_health 生成，测速后 load() 即刷新。
        health = {h["tag"]: h["latency_ms"] for h in dbmod.list_health(c)}
        tags: dict[int, list[str]] = {}
        for tag, sid in c.execute("SELECT tag, sub_id FROM nodes ORDER BY id"):
            tags.setdefault(sid, []).append(tag)
        for s in subs:
            dots = []
            for tag in tags.get(s["id"], []):
                lat = health.get(tag)
                if lat is None:
                    dots.append("")
                elif lat < 300:
                    dots.append("g")
                elif lat < 800:
                    dots.append("y")
                else:
                    dots.append("r")
            s["node_dots"] = dots
        return jsonify(subs)

    @app.get("/api/subscriptions/<int:sid>")
    def sub_detail(sid: int):
        """Full subscription detail for the edit dialog (rename, dns, urls)."""
        subs = [s for s in dbmod.list_subscriptions(db()) if s["id"] == sid]
        if not subs:
            return jsonify({"error": "not found"}), 404
        return jsonify(subs[0])

    @app.get("/api/subscriptions/<int:sid>/nodes")
    def sub_nodes(sid: int):
        return jsonify([n for n in dbmod.list_nodes(db()) if n["sub_id"] == sid])

    @app.post("/api/subscriptions/<int:sid>/reset-rename")
    def sub_reset_rename(sid: int):
        from core import rename as _rn
        c = db()
        if not c.execute("SELECT id FROM subscriptions WHERE id=?", (sid,)).fetchone():
            return jsonify({"error": "not found"}), 404
        c.execute("UPDATE subscriptions SET rename_enabled=0, rename_prefix=1,"
                  " rename_order=?, rename_seq_digits=2, rename_regions=?,"
                  " rename_fallback='其他', rename_features=?, rename_filter=?"
                  " WHERE id=?",
                  (json.dumps(["region", "feature", "seq"]),
                   json.dumps(_rn.DEFAULT_REGIONS, ensure_ascii=False),
                   _rn.DEFAULT_FEATURES, _rn.DEFAULT_FILTER, sid))
        c.commit()
        subs = [s for s in dbmod.list_subscriptions(c) if s["id"] == sid]
        return jsonify({"rename": subs[0]["rename"] if subs else {}})

    @app.post("/api/subscriptions/<int:sid>/reset-names")
    def sub_reset_names(sid: int):
        c = db()
        if not c.execute("SELECT id FROM subscriptions WHERE id=?", (sid,)).fetchone():
            return jsonify({"error": "not found"}), 404
        # clear custom tags; tags revert to rename-generated names on next refresh;
        # for now restore to orig_tag
        c.execute("UPDATE nodes SET custom_tag='' WHERE sub_id=?", (sid,))
        c.execute("UPDATE nodes SET tag=orig_tag WHERE sub_id=? AND orig_tag != ''", (sid,))
        c.commit()
        return jsonify({"ok": True})

    @app.put("/api/subscriptions/<int:sid>")
    def sub_update(sid: int):
        import json as _json
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        row = c.execute("SELECT id FROM subscriptions WHERE id=?", (sid,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        enabled_changed = False
        if "enabled" in d:
            new_enabled = 1 if d["enabled"] else 0
            # 检查是否真的变化了
            cur_enabled = c.execute("SELECT enabled FROM subscriptions WHERE id=?", (sid,)).fetchone()
            if cur_enabled and cur_enabled[0] != new_enabled:
                enabled_changed = True
            c.execute("UPDATE subscriptions SET enabled=? WHERE id=?",
                      (new_enabled, sid))
        if "auto_update" in d and isinstance(d["auto_update"], dict):
            au = d["auto_update"]
            try:
                au_en = 1 if au.get("enabled") else 0
                au_days = max(1, int(au.get("days", 1)))
                au_hour = min(23, max(0, int(au.get("hour", 4))))
            except (TypeError, ValueError):
                return jsonify({"error": "auto_update must be {enabled, days>=1, hour 0-23}"}), 400
            c.execute("UPDATE subscriptions SET auto_update_enabled=?,"
                      " auto_update_days=?, auto_update_hour=? WHERE id=?",
                      (au_en, au_days, au_hour, sid))
        elif "auto_update_hours" in d:
            # legacy: convert per-N-hours to the {enabled, days, hour} model
            try:
                auh = max(0, int(d["auto_update_hours"]))
            except (TypeError, ValueError):
                return jsonify({"error": "auto_update_hours must be an integer >= 0"}), 400
            c.execute("UPDATE subscriptions SET auto_update_hours=?,"
                      " auto_update_enabled=?, auto_update_days=?,"
                      " auto_update_hour=4 WHERE id=?",
                      (auh, 1 if auh > 0 else 0, max(1, round(auh / 24)), sid))
        if "name" in d and str(d["name"]).strip():
            c.execute("UPDATE subscriptions SET name=? WHERE id=?",
                      (str(d["name"]).strip(), sid))
        if "urls" in d and isinstance(d["urls"], list):
            urls = [str(u).strip() for u in d["urls"] if str(u).strip()]
            c.execute("UPDATE subscriptions SET urls=?, url=? WHERE id=?",
                      (_json.dumps(urls, ensure_ascii=False),
                       urls[0] if urls else None, sid))
        if "dns_resolve" in d and d["dns_resolve"] in ("auto", "direct", "proxy"):
            c.execute("UPDATE subscriptions SET dns_resolve=? WHERE id=?",
                      (d["dns_resolve"], sid))
        rn = d.get("rename")
        if isinstance(rn, dict):
            from core import rename as _rn
            if "enabled" in rn:
                c.execute("UPDATE subscriptions SET rename_enabled=? WHERE id=?",
                          (1 if rn["enabled"] else 0, sid))
            if "prefix" in rn:
                c.execute("UPDATE subscriptions SET rename_prefix=? WHERE id=?",
                          (1 if rn["prefix"] else 0, sid))
            if "order" in rn and isinstance(rn["order"], list):
                c.execute("UPDATE subscriptions SET rename_order=? WHERE id=?",
                          (_json.dumps([x for x in rn["order"]
                                        if x in ("region", "feature", "seq")]), sid))
            if "seq_digits" in rn:
                try:
                    c.execute("UPDATE subscriptions SET rename_seq_digits=? WHERE id=?",
                              (max(1, min(4, int(rn["seq_digits"]))), sid))
                except (TypeError, ValueError):
                    pass
            if "regions" in rn and isinstance(rn["regions"], list):
                clean = [{"name": str(r.get("name", ""))[:16],
                          "flag": str(r.get("flag", ""))[:8],
                          "keywords": str(r.get("keywords", ""))[:500]}
                         for r in rn["regions"] if r.get("name")]
                c.execute("UPDATE subscriptions SET rename_regions=? WHERE id=?",
                          (_json.dumps(clean, ensure_ascii=False), sid))
            if "fallback" in rn:
                c.execute("UPDATE subscriptions SET rename_fallback=? WHERE id=?",
                          (str(rn["fallback"])[:16] or "其他", sid))
            for key, col in (("features", "rename_features"), ("filter", "rename_filter")):
                if key in rn:
                    c.execute(f"UPDATE subscriptions SET {col}=? WHERE id=?",
                              (str(rn[key])[:500], sid))
        c.commit()
        dbmod.bump_rev(c)
        updated = next(s for s in dbmod.list_subscriptions(c) if s["id"] == sid)
        # 订阅启停变化时，自动重新生成配置并重载内核（1:1 对标原版）
        apply_result = None
        if enabled_changed:
            try:
                from core.hotapply import hot_apply_config
                cfg = dbmod.load_app_config(c)
                api_base = f"http://127.0.0.1:{cfg.clash_api_port}"
                secret = getattr(cfg, "clash_api_secret", "") or ""
                apply_result = hot_apply_config(c, _manager(), api_base, secret, force="auto")
            except Exception as e:
                # 配置应用失败不阻塞 API 返回，但记录错误
                apply_result = {"error": str(e), "mode": "failed"}
        resp = dict(updated)
        if apply_result is not None:
            resp["_apply"] = {"mode": apply_result.get("mode"), "error": apply_result.get("error")}
        return jsonify(resp)

    @app.post("/api/subscriptions/<int:sid>/preview-rename")
    def sub_preview_rename(sid: int):
        """Preview rename results for current nodes without saving."""
        import json as _json
        from core import rename as _rn
        c = db()
        subs = [s for s in dbmod.list_subscriptions(c) if s["id"] == sid]
        if not subs:
            return jsonify({"error": "not found"}), 404
        s = subs[0]
        d = request.get_json(force=True, silent=True) or {}
        rn = d.get("rename", s["rename"])
        cfg = {
            "enabled": True, "prefix": rn.get("prefix", True),
            "sub_name": d.get("name", s["name"]),
            "order": rn.get("order") or ["region", "feature", "seq"],
            "seq_digits": rn.get("seq_digits", 2) or 2,
            "regions": rn.get("regions") or _rn.DEFAULT_REGIONS,
            "fallback": rn.get("fallback") or "其他",
            "features": rn.get("features", _rn.DEFAULT_FEATURES),
            "filter": rn.get("filter", _rn.DEFAULT_FILTER),
        }
        nodes = dbmod.list_nodes(c)
        origs = [n["orig_tag"] or n["tag"] for n in nodes if n["sub_id"] == sid]
        return jsonify({"items": _rn.rename_nodes(origs, cfg)})

    @app.put("/api/nodes/<int:nid>")
    def node_update(nid: int):
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        row = c.execute("SELECT id, tag FROM nodes WHERE id=?", (nid,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        if "disabled" in d:
            c.execute("UPDATE nodes SET disabled=? WHERE id=?",
                      (1 if d["disabled"] else 0, nid))
        if "custom_tag" in d:
            ct = str(d["custom_tag"] or "").strip()
            if ct:
                # keep tags unique
                exists = c.execute("SELECT id FROM nodes WHERE tag=? AND id != ?",
                                   (ct, nid)).fetchone()
                if exists:
                    return jsonify({"error": "tag already exists"}), 400
                c.execute("UPDATE nodes SET tag=?, custom_tag=? WHERE id=?",
                          (ct, ct, nid))
            else:
                c.execute("UPDATE nodes SET custom_tag='' WHERE id=?", (nid,))
        c.commit()
        dbmod.bump_rev(c)
        return jsonify({"ok": True})

    @app.delete("/api/subscriptions/<int:sid>")
    def sub_delete(sid: int):
        if not dbmod.delete_subscription(db(), sid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.post("/api/subscriptions/<int:sid>/refresh")
    def sub_refresh(sid: int):
        try:
            return jsonify(dbmod.refresh_subscription(db(), sid))
        except KeyError:
            return jsonify({"error": "not found"}), 404
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"refresh failed: {e}"}), 502

    @app.post("/api/openbox/subscriptions/preview")
    def ob_subs_preview():
        """预览订阅：拉取 URL 并解析节点，返回给前端显示（1:1 对标原版）。"""
        from core.subscription import parse_subscription
        from core.clash import parse_clash_yaml, looks_like_clash
        import urllib.request
        d = request.get_json(force=True, silent=True) or {}
        urls = d.get("urls", [])
        if isinstance(urls, str):
            urls = [urls]
        content = d.get("content", "") or ""
        url = d.get("url", "") or ""
        if url:
            urls = [url] + urls

        all_nodes = []
        errors = []
        fetched = []

        # 拉取 URL
        for u in urls:
            u = u.strip()
            if not u:
                continue
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Open-Box/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    text = r.read().decode("utf-8", errors="ignore")
                    fetched.append({"url": u, "length": len(text)})
                    if looks_like_clash(text):
                        nodes = parse_clash_yaml(text)
                    else:
                        nodes = parse_subscription(text)
                    all_nodes.extend(nodes)
            except Exception as e:
                errors.append({"url": u, "error": str(e)})

        # 解析直接粘贴的内容
        if content.strip():
            try:
                if looks_like_clash(content):
                    nodes = parse_clash_yaml(content)
                else:
                    nodes = parse_subscription(content)
                all_nodes.extend(nodes)
            except Exception as e:
                errors.append({"url": "content", "error": str(e)})

        # 去重（按 tag）
        seen = set()
        uniq = []
        for n in all_nodes:
            tag = getattr(n, "tag", "") or f"{n.server}:{n.server_port}"
            if tag not in seen:
                seen.add(tag)
                uniq.append({
                    "tag": tag,
                    "server": getattr(n, "server", ""),
                    "port": getattr(n, "server_port", 0),
                    "protocol": getattr(n, "protocol", ""),
                    "name": getattr(n, "name", tag),
                })

        return jsonify({
            "nodes": uniq,
            "count": len(uniq),
            "fetched": fetched,
            "errors": errors,
            "format": "clash" if any(looks_like_clash(content) for _ in [1]) else "auto",
        })

    @app.put("/api/openbox/subscriptions/order")
    def ob_subs_order():
        d = request.get_json(force=True, silent=True) or {}
        ids = d.get("ids", [])
        c = db()
        for pos, sid in enumerate(ids):
            c.execute("UPDATE subscriptions SET position=? WHERE id=?", (pos, sid))
        c.commit()
        return jsonify({"ok": True})

    @app.post("/api/subscriptions/<int:sid>/speedtest")
    def sub_speedtest(sid: int):
        # 触发该订阅下所有节点的真实测速
        try:
            from core.health import check_nodes
            c = db()
            sub = next((s for s in dbmod.list_subscriptions(c) if s["id"] == sid), None)
            if not sub:
                return jsonify({"error": "not found"}), 404
            cfg = dbmod.load_app_config(c)
            tags = {n["tag"] for n in dbmod.list_nodes(c) if n.get("sub_id") == sid}
            nodes = [n for n in cfg.nodes if n.tag in tags]
            if not nodes:
                return jsonify({"ok": True, "subscription_id": sid, "tested": 0})
            test_url = dbmod.get_setting(
                c, "speedtest_url", "http://www.gstatic.com/generate_204")
            results = check_nodes(nodes, timeout=5.0, max_workers=20,
                                  test_url=test_url)
            dbmod.save_health(c, results)
            ok_count = sum(1 for r in results if r.ok)
            return jsonify({
                "ok": True,
                "subscription_id": sid,
                "tested": len(results),
                "healthy": ok_count,
                "results": [{"tag": r.tag, "ok": r.ok, "latency_ms": r.latency_ms} for r in results],
            })
        except Exception as e:
            return jsonify({"error": f"speedtest failed: {e}"}), 502

    @app.post("/api/subscriptions/<int:sid>/reimport")
    def sub_reimport(sid: int):
        """Manually update nodes from pasted content (for URL-less subs)."""
        d = request.get_json(force=True, silent=True) or {}
        content = (d.get("content") or "").strip()
        if not content:
            return jsonify({"error": "content is required"}), 400
        try:
            return jsonify(dbmod.reimport_subscription(
                db(), sid, content, d.get("format", "auto")))
        except KeyError:
            return jsonify({"error": "not found"}), 404
        except Exception as e:
            return jsonify({"error": f"parse failed: {e}"}), 400

    # ---- subscription shares (public capability links) ----
    @app.get("/api/subscription-shares")
    def subshare_list():
        return jsonify(dbmod.list_sub_shares(db()))

    @app.post("/api/subscription-shares")
    def subshare_create():
        d = request.get_json(force=True, silent=True) or {}
        if not d.get("name"):
            return jsonify({"error": "name required"}), 400
        return jsonify(dbmod.create_sub_share(
            db(), d["name"], d.get("node_filter", ""))), 201

    @app.patch("/api/subscription-shares/<int:sid>")
    def subshare_patch(sid: int):
        d = request.get_json(force=True, silent=True) or {}
        r = dbmod.update_sub_share(db(), sid, d.get("name"),
                                   d.get("node_filter"), d.get("enabled"))
        if r is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(r)

    @app.post("/api/subscription-shares/<int:sid>/regenerate")
    def subshare_regen(sid: int):
        r = dbmod.regenerate_sub_share(db(), sid)
        if r is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(r)

    @app.delete("/api/subscription-shares/<int:sid>")
    def subshare_delete(sid: int):
        if not dbmod.delete_sub_share(db(), sid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.get("/sub/<token>")
    def subshare_public(token: str):
        """Public subscription file. The token is the credential;
        this route is outside /api/* so the auth gate skips it."""
        from core.share import encode_nodes
        share = dbmod.find_sub_share(db(), token)
        if not share or not share.get("enabled", True):
            return jsonify({"error": "not found"}), 404
        filt = {t.strip() for t in (share["node_filter"] or "").split(",") if t.strip()}
        nodes = dbmod.list_nodes(db())
        if filt:
            nodes = [n for n in nodes if n["tag"] in filt]
        items = encode_nodes(nodes)
        lines = [it["link"] for it in items if it.get("link")]
        body = "\n".join(lines) + "\n"
        return app.response_class(body, mimetype="text/plain",
                                  headers={"Content-Disposition":
                                           f"attachment; filename=\"{share['name']}.txt\""})

    # ---- nodes ----
    @app.get("/api/nodes")
    def node_list():
        return jsonify(dbmod.list_nodes(db()))

    @app.post("/api/nodes")
    def node_create():
        """Manually add node(s) from pasted share link(s)."""
        d = request.get_json(force=True, silent=True) or {}
        content = (d.get("content") or "").strip()
        if not content:
            return jsonify({"error": "content is required"}), 400
        try:
            r = dbmod.add_manual_nodes(db(), content, d.get("name", ""))
        except Exception as e:
            return jsonify({"error": f"parse failed: {e}"}), 400
        return jsonify(r), 201

    @app.delete("/api/nodes/<int:nid>")
    def node_delete(nid: int):
        c = db()
        cur = c.execute("DELETE FROM nodes WHERE id=?", (nid,))
        c.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "not found"}), 404
        dbmod.bump_rev(c)
        return jsonify({"ok": True})

    # ---- node exit info (via temp sing-box probe) ----
    def _node_by_tag(c, tag: str) -> dict | None:
        for n in dbmod.list_nodes(c):
            if n["tag"] == tag:
                return n
        return None

    @app.get("/api/node-info/<tag>")
    def node_info(tag: str):
        from core import nodeinfo as _ni
        c = db()
        node = _node_by_tag(c, tag)
        if not node:
            return jsonify({"error": "not found"}), 404
        cached = dbmod.get_node_info_cache(c, tag)
        if cached:
            cached["cached"] = True
            return jsonify(cached)
        return jsonify({"ok": False, "cached": False,
                        "message": "暂无缓存，请刷新"}), 404

    @app.post("/api/node-info/<tag>/exit")
    def node_info_exit(tag: str):
        """Refresh exit info. Throttled to 15s per node (like the original)."""
        import time as _time
        from core import nodeinfo as _ni
        from core.service import manager_from_env
        c = db()
        node = _node_by_tag(c, tag)
        if not node:
            return jsonify({"error": "not found"}), 404
        cached = dbmod.get_node_info_cache(c, tag, max_age_s=2**31)
        if cached and cached.get("_age_s", 1e9) < 15:
            return jsonify({"error": "刷新过于频繁，请 15 秒后再试"}), 429
        try:
            r = _ni.probe_exit(node, manager_from_env().bin_path)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        if r.get("ok"):
            r["_fetched_at"] = _time.strftime("%Y-%m-%dT%H:%M:%S")
            dbmod.set_node_info_cache(c, tag, r)
        return jsonify(r)

    @app.get("/api/node-info/<tag>/entry-country")
    def node_info_entry(tag: str):
        from core import nodeinfo as _ni
        node = _node_by_tag(db(), tag)
        if not node:
            return jsonify({"error": "not found"}), 404
        return jsonify(_ni.entry_country(node))

    # ---- site sets ----
    @app.get("/api/sitesets")
    def siteset_list():
        return jsonify(dbmod.list_site_sets(db()))

    @app.post("/api/sitesets")
    def siteset_create():
        d = request.get_json(force=True, silent=True) or {}
        if not d.get("name"):
            return jsonify({"error": "name is required"}), 400
        try:
            return jsonify(dbmod.create_site_set(db(), d)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except sqlite3.IntegrityError:
            return jsonify({"error": "name already exists"}), 400

    @app.put("/api/sitesets/<int:sid>")
    def siteset_update(sid: int):
        d = request.get_json(force=True, silent=True) or {}
        try:
            row = dbmod.update_site_set(db(), sid, d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(row)

    @app.delete("/api/sitesets/<int:sid>")
    def siteset_delete(sid: int):
        if not dbmod.delete_site_set(db(), sid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.put("/api/sitesets/order")
    def siteset_order():
        d = request.get_json(force=True, silent=True) or {}
        order = d.get("order") or d.get("ids") or []
        c = db()
        for i, sid in enumerate(order):
            try:
                c.execute("UPDATE site_sets SET position=? WHERE id=?", (i, int(sid)))
            except (TypeError, ValueError):
                continue
        c.commit()
        return jsonify({"ok": True})

    # ---- front custom routing (evaluated before all site sets) ----
    @app.get("/api/front-rules")
    def front_rules_list():
        return jsonify(dbmod.list_front_rules(db()))

    @app.post("/api/front-rules")
    def front_rule_create():
        try:
            return jsonify(dbmod.create_front_rule(db(), request.get_json(force=True, silent=True) or {}))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.put("/api/front-rules")
    def front_rules_replace():
        """Bulk replace front rules (zashboard management UI).

        Body: {"rules": [{type, value, note, target}], "enabled": bool?}.
        "rules" omitted -> keep existing rows; "enabled" sets the global
        front_rules_enabled switch. Returns {"rules": [...], "enabled": bool}.
        """
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            if "rules" in d:
                rules = d.get("rules") or []
                if not isinstance(rules, list):
                    return jsonify({"error": "rules must be a list"}), 400
                dbmod.replace_front_rules(c, rules)
            if "enabled" in d:
                dbmod.set_setting(c, "front_rules_enabled",
                                  "1" if d.get("enabled") else "0")
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({
            "rules": dbmod.list_front_rules(c),
            "enabled": dbmod.get_setting(c, "front_rules_enabled", "1") == "1",
        })

    @app.put("/api/front-rules/<int:rid>")
    def front_rule_update(rid: int):
        r = dbmod.update_front_rule(db(), rid, request.get_json(force=True, silent=True) or {})
        if r is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(r)

    @app.delete("/api/front-rules/<int:rid>")
    def front_rule_delete(rid: int):
        if not dbmod.delete_front_rule(db(), rid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    # ---- route preview ----
    @app.post("/api/route/preview")
    def route_preview():
        d = request.get_json(force=True, silent=True) or {}
        target = (d.get("target") or "").strip()
        if not target:
            return jsonify({"error": "target is required"}), 400
        cfg = dbmod.load_app_config(db())
        res = preview_route(cfg.site_sets, target)
        if res["outbound"] is None:
            # Unmatched: report the effective final (the 其他 selector's
            # default), not the shadowed final_outbound setting.
            res["outbound"] = cfg.routing_fallback or cfg.final_outbound
        return jsonify(res)

    @app.post("/api/openbox/penetration")
    def ob_penetration():
        from core import penetration as _pen
        d = request.get_json(force=True, silent=True) or {}
        target = (d.get("target") or d.get("domain") or d.get("query") or "").strip()
        if not target:
            return jsonify({"error": "target is required"}), 400
        cfg = dbmod.load_app_config(db())
        # 新版穿透：前置规则 -> 站点集 -> 兜底
        res = _pen.penetrate(cfg, target)
        res["ok"] = True
        return jsonify(res)

    # ---- generated sing-box config ----
    @app.get("/api/config")
    def config_get():
        from core import geodata as _gd
        cfg = dbmod.load_app_config(db())
        # Preview reflects what apply would actually emit: rule-sets whose
        # .srs is missing are dropped (apply downloads them first).
        names = _gd.referenced_rule_sets(cfg)
        missing = {n for n in names if not _gd.is_available(n)}
        return jsonify(build_config(cfg, missing))

    # ---- settings ----
    @app.get("/api/settings")
    def settings_get():
        c = db()
        return jsonify({k: dbmod.get_setting(c, k, v)
                        for k, v in dbmod.DEFAULT_SETTINGS.items()})

    @app.put("/api/settings")
    def settings_put():
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        allowed = set(dbmod.DEFAULT_SETTINGS)
        for k, v in d.items():
            if k in allowed:
                dbmod.set_setting(c, k, str(v))
        return jsonify({k: dbmod.get_setting(c, k, v)
                        for k, v in dbmod.DEFAULT_SETTINGS.items()})

    # ---- status ----
    @app.get("/api/status")
    def status():
        c = db()
        # 内核版本与运行状态
        kernel_version = ""
        kernel_running = False
        try:
            from core import service as _svc
            km = _svc.manager_from_env()
            v = km.version()
            if v:
                kernel_version = f"sing-box version {v}"
            kernel_running = km.status().running
        except Exception:
            pass
        # Geo 数据统计
        geosite_n = geoip_n = 0
        geodata_time = ""
        try:
            from core import geodata as _gd
            files = _gd.list_local()
            for f_ in files:
                if f_["kind"] == "geosite":
                    geosite_n += 1
                elif f_["kind"] == "geoip":
                    geoip_n += 1
            if files:
                # 用目录的最新修改时间，转为 ISO 8601 UTC
                import os
                from core import geodata as _gd2
                try:
                    d = _gd2.geodata_dir()
                    mtime = os.stat(d).st_mtime
                    import datetime
                    geodata_time = datetime.datetime.fromtimestamp(
                        mtime, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    pass
        except Exception:
            pass
        # 开机自启
        autostart = False
        try:
            autostart = bool(int(dbmod.get_setting(c, "autostart", "0")))
        except Exception:
            pass
        return jsonify({
            "version": VERSION,
            "subscriptions": len(dbmod.list_subscriptions(c)),
            "nodes": len(dbmod.list_nodes(c)),
            "site_sets": len(dbmod.list_site_sets(c)),
            "groups": len(dbmod.list_groups(c)),
            "chains": len(dbmod.list_chains(c)),
            "rule_sets": len(dbmod.list_rule_sets(c)),
            "singbox": "not-installed",
            "kernel_version": kernel_version,
            "kernel_running": kernel_running,
            "geosite_count": geosite_n,
            "geoip_count": geoip_n,
            "geodata_time": geodata_time,
            "autostart": autostart,
        })

    # ---- rule sets ----
    @app.get("/api/rulesets")
    def ruleset_list():
        return jsonify(dbmod.list_rule_sets(db()))

    @app.get("/api/geodata")
    def geodata_list():
        from core import geodata as _gd
        cfg = dbmod.load_app_config(db())
        referenced = _gd.referenced_rule_sets(cfg)
        local = {x["name"]: x for x in _gd.list_local()}
        return jsonify({
            "dir": _gd.geodata_dir(),
            "referenced": referenced,
            "files": _gd.list_local(),
            "missing": [n for n in referenced if n not in local],
            "states": _gd.read_states(db(), referenced),
        })

    @app.post("/api/geodata/ensure")
    def geodata_ensure():
        from core import geodata as _gd
        d = request.get_json(force=True, silent=True) or {}
        cfg = dbmod.load_app_config(db())
        names = d.get("names") or _gd.referenced_rule_sets(cfg)
        ok, missing = _gd.ensure([n for n in names if isinstance(n, str)])
        return jsonify({"downloaded": ok, "missing": missing})

    @app.post("/api/geodata/refresh")
    def geodata_refresh():
        """TTL-aware refresh of referenced .srs files (v6 #14 semantics).

        24h TTL + URL match reuse; stale files re-downloaded (CDN, then
        mirror); a failed re-download keeps the old file (kept_old) and
        only a wholly missing file lands in missing. State rows for
        no-longer-referenced names are pruned unless keep_others is true.
        Files on disk are never deleted.
        """
        from core import geodata as _gd
        d = request.get_json(force=True, silent=True) or {}
        cfg = dbmod.load_app_config(db())
        names = d.get("names") or _gd.referenced_rule_sets(cfg)
        result = _gd.refresh_names(
            db(), [n for n in names if isinstance(n, str)],
            keep_others=bool(d.get("keep_others", False)))
        return jsonify(result)

    @app.get("/api/geodata/detail/<name>")
    def geodata_detail(name: str):
        """返回 geosite/geoip 分类的详细条目（1:1 对标原版详情弹窗）。"""
        from core import geodata as _gd
        # name 格式: geosite-115 或 geoip-cn
        detail = _gd.get_rule_set_detail(name)
        return jsonify(detail)

    @app.post("/api/rulesets")
    def ruleset_create():
        d = request.get_json(force=True, silent=True) or {}
        if not d.get("name"):
            return jsonify({"error": "name is required"}), 400
        try:
            return jsonify(dbmod.create_rule_set(db(), d)), 201
        except sqlite3.IntegrityError:
            return jsonify({"error": "name already exists"}), 400

    @app.get("/api/rulesets/<int:rid>")
    def ruleset_get(rid: int):
        rs = dbmod.get_rule_set(db(), rid)
        if not rs:
            return jsonify({"error": "not found"}), 404
        return jsonify(rs)

    @app.put("/api/rulesets/<int:rid>")
    def ruleset_update(rid: int):
        d = request.get_json(force=True, silent=True) or {}
        rs = dbmod.update_rule_set(db(), rid, d)
        if not rs:
            return jsonify({"error": "not found"}), 404
        return jsonify(rs)

    @app.delete("/api/rulesets/<int:rid>")
    def ruleset_delete(rid: int):
        if not dbmod.delete_rule_set(db(), rid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.post("/api/rulesets/<int:rid>/refresh")
    def ruleset_refresh(rid: int):
        try:
            return jsonify(dbmod.refresh_rule_set(db(), rid))
        except KeyError:
            return jsonify({"error": "not found"}), 404
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"fetch failed: {e}"}), 502

    # ---- chains ----
    @app.get("/api/chains")
    def chain_list():
        return jsonify(dbmod.list_chains(db()))

    @app.post("/api/chains")
    def chain_create():
        d = request.get_json(force=True, silent=True) or {}
        if not d.get("name"):
            return jsonify({"error": "name is required"}), 400
        try:
            return jsonify(dbmod.create_chain(db(), d)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except sqlite3.IntegrityError:
            return jsonify({"error": "name already exists"}), 400

    @app.put("/api/chains/<int:cid>")
    def chain_update(cid: int):
        d = request.get_json(force=True, silent=True) or {}
        try:
            row = dbmod.update_chain(db(), cid, d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(row)

    @app.delete("/api/chains/<int:cid>")
    def chain_delete(cid: int):
        if not dbmod.delete_chain(db(), cid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    def _resolve_chain_front(c, front_tag: str):
        """Resolve front tag to (outbound, deps) for chain speedtest.

        Handles both single nodes and groups (selector/urltest with members).
        Returns (front_ob, front_deps) or (None, None) if direct/not found.
        """
        from core.singbox import node_to_outbound, resolve_group_members
        if not front_tag or front_tag in ("direct", "block"):
            return None, None
        cfg = dbmod.load_app_config(c)
        # Try as node tag first
        for n in cfg.nodes:
            if n.tag == front_tag:
                return node_to_outbound(n), None
        # Try as group
        for g in (cfg.groups or []):
            if g.name == front_tag and g.enabled:
                node_tags = [n.tag for n in cfg.nodes]
                chain_tags = [ch.name for ch in cfg.chains]
                members = resolve_group_members(g, node_tags, chain_tags)
                # Build member outbounds
                deps = []
                for n in cfg.nodes:
                    if n.tag in members:
                        deps.append(node_to_outbound(n))
                # Build group outbound (selector/urltest)
                if g.type == "selector":
                    front_ob = {
                        "type": "selector",
                        "tag": g.name,
                        "outbounds": members or ["direct"],
                        "default": members[0] if members else "direct",
                    }
                else:  # urltest/failover
                    front_ob = {
                        "type": "urltest",
                        "tag": g.name,
                        "outbounds": members or ["direct"],
                        "url": g.test_url or cfg.speedtest_url,
                        "interval": f"{g.interval_s}s",
                    }
                return front_ob, deps
        return None, None

    @app.post("/api/chains/<int:cid>/speedtest")
    def chain_speedtest(cid: int):
        """Real chain proxy speedtest: reports latency, exit IP and country."""
        from core import chain_test as _ct
        c = db()
        chains = dbmod.list_chains(c)
        chain = next((x for x in chains if x["id"] == cid), None)
        if not chain:
            return jsonify({"error": "not found"}), 404
        # Resolve front outbound (node or group)
        front_ob, front_deps = _resolve_chain_front(c, chain.get("front", ""))
        result = _ct.test_chain(chain, front_ob, front_deps)
        return jsonify(result)

    @app.post("/api/chains/speedtest")
    def chain_speedtest_adhoc():
        """Speedtest for unsaved chain config (from modal)."""
        from core import chain_test as _ct
        d = request.get_json(force=True, silent=True) or {}
        if not d.get("server"):
            return jsonify({"error": "server is required"}), 400
        c = db()
        # Resolve front if specified (node or group)
        front_ob, front_deps = _resolve_chain_front(c, d.get("front", ""))
        result = _ct.test_chain(d, front_ob, front_deps)
        return jsonify(result)

    # ---- groups ----
    @app.get("/api/groups")
    def group_list():
        return jsonify(dbmod.list_groups(db()))

    @app.post("/api/groups")
    def group_create():
        d = request.get_json(force=True, silent=True) or {}
        if not d.get("name"):
            return jsonify({"error": "name is required"}), 400
        try:
            return jsonify(dbmod.create_group(db(), d)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except sqlite3.IntegrityError:
            return jsonify({"error": "name already exists"}), 400

    @app.put("/api/groups/<sint:gid>")
    def group_update(gid: int):
        d = request.get_json(force=True, silent=True) or {}
        try:
            row = dbmod.update_group(db(), gid, d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(row)

    @app.delete("/api/groups/<int:gid>")
    def group_delete(gid: int):
        if not dbmod.delete_group(db(), gid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.post("/api/groups/reorder")
    def groups_reorder():
        d = request.get_json(force=True, silent=True) or {}
        ids = d.get("ids") or []
        if not isinstance(ids, list) or not all(isinstance(x, int) for x in ids):
            return jsonify({"error": "ids must be a list of ints"}), 400
        # 1:1 对标原版：ids 包含内置组（0=直连, -1=拒绝），完整顺序存 setting
        dbmod.reorder_groups(db(), ids)
        return jsonify({"ok": True})

    @app.get("/api/groups/<int:gid>/members")
    def group_members(gid: int):
        """Resolved member tags for a group (dynamic expansion included)."""
        from core.singbox import resolve_group_members
        from core.models import Group as _Group
        c = db()
        groups = [g for g in dbmod.list_groups(c) if g["id"] == gid]
        if not groups:
            return jsonify({"error": "not found"}), 404
        g = groups[0]
        node_tags = [n["tag"] for n in dbmod.list_nodes(c)]
        chain_tags = [r[0] for r in c.execute("SELECT name FROM chains ORDER BY id")]
        gm = _Group(name=g["name"], type=g["type"], members=g["members"],
                    dynamic_keywords=g["dynamic_keywords"])
        return jsonify({"group": g["name"],
                        "members": resolve_group_members(gm, node_tags, chain_tags)})

    # ---- node health ----
    @app.get("/api/health")
    def health_list():
        return jsonify(dbmod.list_health(db()))

    @app.post("/api/health/check")
    def health_check():
        from core.health import check_nodes
        d = request.get_json(force=True, silent=True) or {}
        cfg = dbmod.load_app_config(db())
        nodes = cfg.nodes
        if d.get("sub_id"):
            tags = {n["tag"] for n in dbmod.list_nodes(db())
                    if n["sub_id"] == d["sub_id"]}
            nodes = [n for n in nodes if n.tag in tags]
        elif d.get("tag"):
            nodes = [n for n in nodes if n.tag == d["tag"]]
        # UDP nodes (tuic/hysteria2) are measured through the kernel delay
        # API using the configured test URL; TCP nodes keep the direct probe.
        test_url = dbmod.get_setting(
            db(), "speedtest_url", "http://www.gstatic.com/generate_204")
        results = check_nodes(nodes, timeout=float(d.get("timeout", 5.0)),
                              max_workers=int(d.get("max_workers", 20)),
                              test_url=test_url)
        dbmod.save_health(db(), results)
        return jsonify([{"tag": r.tag, "ok": r.ok, "latency_ms": r.latency_ms,
                         "error": r.error, "checked_at": r.checked_at}
                        for r in results])

    # ---- kernel service ----
    def _manager():
        from core.service import manager_from_env
        return manager_from_env()

    def _conflict_record():
        """Last conflict refusal record ('' when none)."""
        try:
            from panel.db import get_setting
            return get_setting(db(), "conflict_stop_at", "")
        except Exception:
            return ""

    def _record_conflict(conflicts):
        try:
            from panel.db import set_setting
            import json as _json, datetime as _dt
            c = db()
            set_setting(c, "conflict_stop_at",
                        _dt.datetime.now().isoformat(timespec="seconds"))
            set_setting(c, "conflict_stop_detail",
                        _json.dumps(conflicts, ensure_ascii=False))
        except Exception:
            pass

    def _clear_conflict_record():
        try:
            from panel.db import set_setting
            c = db()
            set_setting(c, "conflict_stop_at", "")
            set_setting(c, "conflict_stop_detail", "")
        except Exception:
            pass

    @app.get("/api/service")
    def service_status():
        d = _manager().to_dict()
        try:
            from core.conflicts import conflict_auto_stopped
            d["conflict_auto_stopped"] = conflict_auto_stopped(
                d["running"], d["conflicts"], _conflict_record())
        except Exception:
            d["conflict_auto_stopped"] = False
        try:
            c = db()
            from panel.db import get_setting
            rev, applied = get_setting(c, "state_rev", "0"), get_setting(c, "applied_rev", "")
            d["state_rev"] = rev
            d["applied_rev"] = applied or None
            d["config_stale"] = bool(applied) and applied != rev
        except Exception:
            pass
        return jsonify(d)

    @app.post("/api/service/start")
    def service_start():
        from core import startverify as _sv
        from core.conflicts import ConflictError
        m = _manager()
        before = _sv.snapshot_log(m.log_path)
        try:
            m.start()
        except ConflictError as e:
            _record_conflict(e.conflicts)
            return jsonify({"error": str(e), "conflicts": e.conflicts}), 409
        except RuntimeError as e:
            return jsonify({"error": str(e),
                            "verify": _sv.verify_start(m, before, settle_s=0)}), 409
        d = m.to_dict()
        verify = _sv.verify_start(m, before)
        d["verify"] = verify
        # start() 的存活窗口拦不住窗口后死掉的进程：以 verify 为准，
        # 内核最终没跑起来就按失败回（verify 已含精确 FATAL 行）。
        if verify["state"] == "failed":
            return jsonify({"error": verify["message"], "verify": verify}), 409
        _clear_conflict_record()
        return jsonify(d)

    @app.post("/api/service/stop")
    def service_stop():
        m = _manager()
        m.stop()
        return jsonify(m.to_dict())

    @app.post("/api/service/restart")
    def service_restart():
        from core import startverify as _sv
        from core.conflicts import ConflictError
        m = _manager()
        before = _sv.snapshot_log(m.log_path)
        try:
            m.restart()
        except ConflictError as e:
            _record_conflict(e.conflicts)
            return jsonify({"error": str(e), "conflicts": e.conflicts}), 409
        except RuntimeError as e:
            return jsonify({"error": str(e),
                            "verify": _sv.verify_start(m, before, settle_s=0)}), 409
        d = m.to_dict()
        verify = _sv.verify_start(m, before)
        d["verify"] = verify
        if verify["state"] == "failed":
            return jsonify({"error": verify["message"], "verify": verify}), 409
        _clear_conflict_record()
        return jsonify(d)

    @app.get("/api/service/log")
    def service_log():
        n = min(int(request.args.get("n", 200)), 2000)
        source = request.args.get("source", "kernel")
        if source == "panel":
            path = os.environ.get("OBX_PANEL_LOG", "")
            lines: list[str] = []
            if path and os.path.isfile(path):
                try:
                    with open(path, "rb") as f:
                        data = f.read().splitlines()[-n:]
                    lines = [l.decode("utf-8", "replace") for l in data]
                except OSError:
                    pass
            return jsonify({"log": lines, "source": "panel",
                            "note": "" if lines else "面板日志未启用（设置 OBX_PANEL_LOG 环境变量指向日志文件）"})
        return jsonify({"log": _manager().log_tail(n).splitlines(), "source": "kernel"})

    @app.get("/api/diagnostics")
    def diagnostics_export():
        from core.diagnostics import collect
        return jsonify(collect(db(), _manager()))

    @app.post("/api/config/apply")
    def config_apply():
        from core.apply import apply_config, ApplyVerifyError
        from core.hotapply import hot_apply_config
        mode = (request.args.get("mode") or "auto").lower()
        if mode not in ("auto", "hot", "full"):
            return jsonify({"error": "mode must be auto|hot|full"}), 400
        cfg = dbmod.load_app_config(db(), with_blocked_domains=True)
        api_base = f"http://127.0.0.1:{cfg.clash_api_port}"
        secret = getattr(cfg, "clash_api_secret", "") or ""
        try:
            if mode == "full":
                result = apply_config(db(), _manager())
                result["mode"] = "full"
            else:
                result = hot_apply_config(db(), _manager(), api_base, secret,
                                          force=mode)
        except ApplyVerifyError as e:
            # Config was written and the relaunch attempted, but the kernel
            # did not come up: same 409 as /api/service/start, not a 200.
            return jsonify({"error": str(e), "verify": e.verify}), 409
        except RuntimeError as e:
            body = {"error": str(e)}
            bad = getattr(e, "bad", None)
            if bad:
                body["bad_node"] = bad
            return jsonify(body), 422
        # remember which rev is live, so the kernel page can flag stale config
        # + persist last deploy result for the deploy-state poll
        try:
            from panel.db import get_setting, set_setting
            import json as _json
            c = db()
            set_setting(c, "applied_rev", get_setting(c, "state_rev", "0"))
            set_setting(c, "deploy_state", _json.dumps({
                "at": result.get("at"), "mode": result.get("mode"),
                "ok": True, "outbounds": result.get("outbounds"),
                "route_rules": result.get("route_rules"),
                "validation": result.get("validation"),
                "hot_detail": result.get("hot_detail"),
                "hot_fallback": result.get("hot_fallback"),
            }, ensure_ascii=False))
        except Exception:
            pass
        return jsonify(result)

    @app.get("/api/deploy/state")
    def deploy_state():
        import json as _json
        try:
            from panel.db import get_setting
            raw = get_setting(db(), "deploy_state", "")
            return jsonify(_json.loads(raw) if raw else {"ok": False, "message": "尚未部署过"})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)})

    @app.post("/api/deploy/rollback")
    def deploy_rollback():
        """Roll back to a direct-only config and disable autostart."""
        import json as _json, time as _time
        m = _manager()
        direct_cfg = {"log": {"level": "info"},
                      "outbounds": [{"type": "direct", "tag": "direct"}]}
        try:
            tmp = m.config_path + ".rollback"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(direct_cfg, f, ensure_ascii=False, indent=2)
            ok, msg = m.check_config(tmp)
            import os as _os
            _os.replace(tmp, m.config_path)
        except OSError as e:
            return jsonify({"error": str(e)}), 500
        if not ok:
            return jsonify({"error": f"rollback config invalid: {msg}"}), 422
        if m.is_installed():
            try:
                if m.status().running:
                    m.restart()
                else:
                    m.start()
            except RuntimeError as e:
                return jsonify({"error": str(e)}), 409
        # disable autostart (best effort; needs root on the router)
        disabled = []
        for p in ("/etc/init.d/openbox-oss",
                  "/etc/systemd/system/openbox-oss.service"):
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    disabled.append(p)
            except OSError:
                pass
        try:
            from panel.db import set_setting
            set_setting(db(), "deploy_state", _json.dumps({
                "at": _time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "rollback",
                "ok": True, "message": "已回滚到直连配置",
            }, ensure_ascii=False))
            set_setting(db(), "applied_rev", "")
        except Exception:
            pass
        return jsonify({"ok": True, "autostart_disabled": disabled,
                        "service": m.to_dict()})

    @app.post("/api/factory-reset")
    def factory_reset():
        m = _manager()
        try:
            m.stop()
        except Exception:
            pass
        dbmod.factory_reset(db())
        return jsonify({"ok": True, "message": "已恢复出厂：数据已清空，内核已停止"})

    # ---- transparent proxy artifacts (generate-only) ----
    def _tconfig():
        from core.transparent import TransparentConfig
        d = request.args
        c = db()
        cfg = dbmod.load_app_config(c)
        rewrites = [(r.domain, r.target) for r in cfg.dns_rewrites]
        bypass_terms = [t.ident for t in cfg.terminals if t.policy == "bypass"]
        # v0.1.340: proxy terminals ALWAYS enter kernel (skip all bypass)
        proxy_terms = [t.ident for t in cfg.terminals if t.policy == "proxy"]
        # terminal_rules: direct -> bypass kernel; whitelist -> only listed enter
        whitelist_terms = []
        for tr in getattr(cfg, "terminal_rules", []) or []:
            if tr.policy == "direct":
                # direct: never enter kernel (IP or MAC)
                bypass_terms.extend(tr.targets)
            elif tr.policy == "whitelist":
                whitelist_terms.extend(tr.targets)
            elif tr.policy == "proxy":
                # v0.1.340: proxy rule terminals always enter kernel
                proxy_terms.extend(tr.targets)
        site_domains = []
        for s in cfg.site_sets:
            # dnsmasq server=/domain/ matches the domain and its subdomains
            doms = [x for x in list(s.domains) + list(s.domain_suffix) if x]
            if doms:
                site_domains.append((s.action, doms))
        def _strip_scheme(u: str) -> str:
            u = u.strip()
            if "://" in u:
                u = u.split("://", 1)[1]
            return u.split("/")[0].split("#")[0]
        from panel.db import get_setting
        from core.entry_plan import entry_plan as _entry_plan
        direct_bypass = get_setting(c, "direct_bypass_kernel", "1") == "1"
        direct_ipset_domains = []
        direct_ip_cidrs = []
        direct_ip_note = ""
        _expanded_sets: set[str] = set()
        if direct_bypass:
            from core import geodata as _gd
            for s in cfg.site_sets:
                if s.action == "direct":
                    direct_ipset_domains.extend(
                        x for x in list(s.domains) + list(s.domain_suffix) if x)
                    # v0.1.341: direct ip_cidr bypass at ingress
                    direct_ip_cidrs.extend(x for x in list(s.ip_cidr) if x)
                    # geoip rule_sets expand into CIDRs via decompile;
                    # geosite (domains) never yields CIDRs and is skipped
                    # inside expand_geoip.
                    for _rs in (s.rule_sets or []):
                        _got = _gd.expand_geoip(_rs)
                        if _got:
                            _expanded_sets.add(s.name)
                            direct_ip_cidrs.extend(_got)
            # v0.1.341: front_rules ip_cidr with direct target
            for fr in cfg.front_rules or []:
                if not isinstance(fr, dict):
                    continue
                if (fr.get("rtype") or "") == "ip_cidr":
                    target = (fr.get("target") or "").strip().lower()
                    if target in ("direct", "直连"):
                        val = (fr.get("domain") or "").strip()
                        if val:
                            direct_ip_cidrs.append(val)
            # front geoip rules to direct expand like site sets
            # (route generator names them geoip-<val>); geosite rows
            # are domains and never yield CIDRs.
            from core.transparent import front_geoip_direct_cidrs as _fg
            direct_ip_cidrs.extend(_fg(cfg.front_rules, _gd.expand_geoip))
            # front domain/geosite rules to direct join the DNS bypass
            # set (same ipset mechanism as direct site sets); keywords
            # cannot be expressed as dnsmasq ipset lines and are skipped.
            from core.transparent import front_dns_direct_domains as _fd
            direct_ipset_domains.extend(
                _fd(cfg.front_rules, _gd.expand_geosite))
            direct_ipset_domains = sorted(set(direct_ipset_domains))
            direct_ip_cidrs = sorted(set(direct_ip_cidrs))
        # v6 #15 fallback wording (summary, ";"-joined): why some direct
        # site sets yield no ip_cidr. Domain-only sets are handled by the
        # DNS ipset by design; geoip rule_sets now expand (decompile),
        # only geosite domain lists still cannot; logical/negation composition does not exist in
        # our flat site-set model, so that wording never applies here.
        direct_ip_note = ""
        if direct_bypass:
            from core.transparent import classify_direct_ip_gaps as _gaps
            _causes = _gaps(cfg.site_sets, _expanded_sets)
            _parts = [f"{k} {v} 个" for k, v in _causes.items() if v]
            if _parts:
                direct_ip_note = "直连站点集无 ip_cidr：" + ";".join(_parts)
        # Entry bypass mode (1:1 对标原版)：自动选择 blacklist/whitelist
        _ep = _entry_plan(
            enabled=direct_bypass,
            fakeip_enabled=get_setting(c, "dns_fakeip", "0") == "1",
            final_outbound=get_setting(c, "final_outbound", "所有-自动"),
        )
        return TransparentConfig(
            entry_mode=_ep.mode,
            direct_answer_enabled=_ep.direct_answer,
            tproxy_port=int(d.get("tproxy_port", 7893)),
            dns_port=int(d.get("dns_port", 1053)),
            lan_iface=d.get("lan_iface", "br-lan"),
            enable_ipv6=d.get("ipv6", "1") == "1",
            quic_block=cfg.quic_block,
            terminal_bypass=bypass_terms,
            terminal_whitelist=whitelist_terms,
            terminal_proxy=proxy_terms,
            dns_rewrites=rewrites,
            dns_direct_ip=_strip_scheme(cfg.dns.direct_dns),
            dns_proxy_ip=_strip_scheme(cfg.dns.proxy_dns),
            site_domains=site_domains,
            dns_filter_conf=_dns_filter_conf_path(c),
            direct_ipset_domains=direct_ipset_domains,
            direct_ip_cidrs=direct_ip_cidrs,
            direct_ip_note=direct_ip_note,
            # 端口黑白名单分开存（原版语义：两个字段不合并）：
            # 前端存 port_list_mode + bypass_ports_white，旧键 bypass_ports_mode 兼容。
            bypass_ports=_port_list_for_mode(c),
            bypass_ports_mode=_port_list_mode(c),
            mss_clamp=int(get_setting(c, "mss_clamp", "0") or 0),
        )

    def _port_list_mode(c) -> str:
        from panel.db import get_setting
        mode = get_setting(c, "port_list_mode", "") or get_setting(c, "bypass_ports_mode", "black")
        return "white" if mode == "white" else "black"

    def _port_list_for_mode(c) -> str:
        from panel.db import get_setting
        if _port_list_mode(c) == "white":
            return get_setting(c, "bypass_ports_white", "")
        return get_setting(c, "bypass_ports", "")

    def _dns_filter_conf_path(c) -> str:
        from panel.db import get_setting
        from core import dnsfilter as _df
        from core.service import manager_from_env
        if get_setting(c, "dns_filter_enabled", "0") != "1":
            return ""
        return _df.blocklist_path(manager_from_env().workdir)


    @app.get("/api/transparent/nft")
    def transparent_nft():
        from core.transparent import nft_script
        return jsonify({"script": nft_script(_tconfig())})

    @app.get("/api/transparent/iprules")
    def transparent_iprules():
        from core.transparent import ip_rules
        return jsonify({"script": ip_rules(_tconfig())})

    @app.get("/api/transparent/dnsmasq")
    def transparent_dnsmasq():
        from core.transparent import dnsmasq_snippet
        return jsonify({"script": dnsmasq_snippet(_tconfig())})

    # ---- failover ----
    def _failover_ctx():
        cfg = dbmod.load_app_config(db())
        api_base = f"http://127.0.0.1:{cfg.clash_api_port}"
        secret = getattr(cfg, "clash_api_secret", "") or ""
        return cfg, api_base, secret

    def _failover_record(c, actions):
        for a in actions:
            if a.get("action") in ("switch", "failed") and a.get("target"):
                prev = dbmod.get_failover_state(c, a["group"])
                switched = (not prev) or (prev["current_tag"] != a["target"])
                dbmod.set_failover_state(c, a["group"], a["target"],
                                         switched and a["action"] == "switch")

    @app.post("/api/failover/elect")
    def failover_elect():
        from core.failover import watch_once
        cfg, api_base, secret = _failover_ctx()
        health = dbmod.list_health(db())
        d = request.get_json(force=True, silent=True) or {}
        api_base = d.get("api_base", api_base)
        secret = d.get("secret", secret)
        actions = watch_once(cfg.groups, health, api_base, secret)
        _failover_record(db(), actions)
        return jsonify(actions)

    @app.get("/api/failover/status")
    def failover_status():
        cfg = dbmod.load_app_config(db())
        health = {h["tag"]: h["ok"] for h in dbmod.list_health(db())}
        out = []
        for g in cfg.groups:
            if g.type != "failover":
                continue
            members = list(g.members)
            st = dbmod.get_failover_state(db(), g.name)
            current = (st["current_tag"] if st and st["current_tag"] else
                       (members[0] if members else None))
            out.append({
                "group": g.name,
                "primary": members[0] if members else None,
                "members": [{"tag": m, "health": health.get(m)} for m in members],
                "current": current,
                "updated_at": st["updated_at"] if st else None,
                "last_switch_at": st["last_switch_at"] if st else None,
            })
        return jsonify(out)

    @app.post("/api/failover/refresh")
    def failover_refresh():
        """Reload mapping and re-run election for all failover groups."""
        from core.failover import watch_once
        cfg, api_base, secret = _failover_ctx()
        actions = watch_once(cfg.groups, dbmod.list_health(db()), api_base, secret)
        _failover_record(db(), actions)
        return jsonify(actions)

    @app.post("/api/failover/recheck")
    def failover_recheck():
        """Force re-probe of one group's members, then re-elect."""
        from core.failover import watch_once
        from core.health import check_nodes
        d = request.get_json(force=True, silent=True) or {}
        name = d.get("group", "")
        cfg, api_base, secret = _failover_ctx()
        groups = [g for g in cfg.groups if g.type == "failover" and g.name == name]
        if not groups:
            return jsonify({"error": "failover group not found"}), 404
        members = set(groups[0].members)
        nodes = [n for n in cfg.nodes if n.tag in members]
        if nodes:
            results = check_nodes(nodes, timeout=float(d.get("timeout", 5.0)))
            dbmod.save_health(db(), results)
        actions = watch_once(groups, dbmod.list_health(db()), api_base, secret)
        _failover_record(db(), actions)
        return jsonify(actions)

    # ---- subscription sharing ----
    @app.post("/api/share")
    def share_links():
        from core.share import encode_nodes
        d = request.get_json(force=True, silent=True) or {}
        tags = d.get("node_tags") or []
        nodes = [n for n in dbmod.list_nodes(db()) if n["tag"] in tags]
        return jsonify(encode_nodes(nodes))

    @app.get("/api/share/qr")
    def share_qr():
        import io
        import qrcode
        text = request.args.get("text", "")
        if not text:
            return jsonify({"error": "text required"}), 400
        img = qrcode.make(text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return app.response_class(buf.getvalue(), mimetype="image/png")

    # ---- content filtering (0.1.328) ----
    # 新版：Surge/QuantumultX 规则集管理器（1:1 对标原版）
    # 原版路径：/api/openbox/content-filter（单数）
    @app.get("/api/openbox/content-filter")
    def cf_ruleset_list():
        return jsonify(dbmod.list_cf_rulesets(db()))

    @app.post("/api/openbox/content-filter")
    def cf_ruleset_create():
        """Create ruleset from text/URL.
        
        Body: {name, dialect, text?, source_url?}
        """
        from core.cf_parser import parse_ruleset
        import hashlib, time, json
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        dialect = (data.get("dialect") or "surge").strip()
        text = data.get("text") or ""
        source_url = (data.get("source_url") or "").strip()
        
        if not name:
            return jsonify({"error": "name required"}), 400
        if dialect not in ("surge", "quantumultx"):
            return jsonify({"error": "dialect must be surge or quantumultx"}), 400
        
        # 从 URL 拉取
        if source_url and not text:
            import urllib.request
            try:
                req = urllib.request.Request(source_url, headers={"User-Agent": "OpenBox/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    text = r.read().decode('utf-8', errors='ignore')
            except Exception as e:
                return jsonify({"error": f"fetch failed: {e}"}), 400
        
        if not text:
            return jsonify({"error": "text or source_url required"}), 400
        
        try:
            parsed = parse_ruleset(text, dialect)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        
        from core.cfrefresh import check_caps, domain_count_of_rules
        _nd = domain_count_of_rules(parsed["rules"])
        _ok, _msg = check_caps(db(), _nd)
        if not _ok:
            return jsonify({"error": _msg}), 400
        rid = hashlib.sha256(f"cf-{name}-{time.time()}".encode()).hexdigest()[:16]
        conn = db()
        conn.execute("""INSERT INTO cf_rulesets
            (id, name, dialect, source_url, text, rules, hostnames, arguments, scripts,
             enabled, updated_at, skipped_scripts, skipped_unsupported, skipped_routing, skipped_unrepresentable, domain_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
            (rid, name, dialect, source_url, text[:524288],
             json.dumps(parsed["rules"], ensure_ascii=False),
             json.dumps(parsed["hostnames"], ensure_ascii=False),
             json.dumps(parsed["arguments"], ensure_ascii=False),
             json.dumps(parsed["scripts"], ensure_ascii=False),
             time.strftime("%Y-%m-%dT%H:%M:%S"),
             parsed["skipped_scripts"], parsed["skipped_unsupported"],
             parsed["skipped_routing"], parsed["skipped_unrepresentable"], _nd))
        conn.commit()
        return jsonify({"id": rid, "parsed": parsed})

    @app.get("/api/openbox/content-filter/<rid>")
    def cf_ruleset_get(rid: str):
        r = dbmod.get_cf_ruleset(db(), rid)
        if not r:
            return jsonify({"error": "not found"}), 404
        return jsonify(r)

    @app.delete("/api/openbox/content-filter/<rid>")
    def cf_ruleset_delete(rid: str):
        conn = db()
        conn.execute("DELETE FROM cf_rulesets WHERE id = ?", (rid,))
        conn.commit()
        return jsonify({"deleted": True})

    @app.patch("/api/openbox/content-filter/<rid>")
    def cf_ruleset_patch(rid: str):
        data = request.get_json() or {}
        conn = db()
        if "enabled" in data and data["enabled"]:
            # Enabling emits this ruleset's domains into the config: the
            # caps apply here just as at create/refresh.
            from core.cfrefresh import (check_caps, domain_count_of_rules,
                                        ensure_columns)
            ensure_columns(conn)
            row = conn.execute("SELECT rules, domain_count FROM cf_rulesets"
                               " WHERE id = ?", (rid,)).fetchone()
            if row is not None:
                nd = row[1] if row[1] is not None else domain_count_of_rules(
                    json.loads(row[0] or "[]"))
                ok, msg = check_caps(conn, nd)
                if not ok:
                    return jsonify({"error": msg}), 400
            conn.execute("UPDATE cf_rulesets SET enabled = ? WHERE id = ?",
                        (1, rid))
        elif "enabled" in data:
            conn.execute("UPDATE cf_rulesets SET enabled = ? WHERE id = ?",
                        (0, rid))
        if "name" in data:
            conn.execute("UPDATE cf_rulesets SET name = ? WHERE id = ?",
                        (data["name"], rid))
        conn.commit()
        return jsonify({"updated": True})

    @app.post("/api/openbox/content-filter/<rid>/refresh")
    def cf_ruleset_refresh(rid: str):
        """Re-fetch a URL ruleset's source (v6 #18 semantics).

        Cooldown: a failed attempt blocks retry for 600s unless force=true.
        Old rules are always kept on failure; cap rejections keep them too.
        """
        from core.cfrefresh import refresh_ruleset
        data = request.get_json(force=True, silent=True) or {}
        try:
            result = refresh_ruleset(db(), rid,
                                     force=bool(data.get("force", False)))
        except KeyError:
            return jsonify({"error": "not found"}), 404
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if result["status"] == "failed":
            return jsonify(result), 502
        if result["status"] == "rejected":
            return jsonify(result), 400
        return jsonify(result)

    @app.post("/api/openbox/content-filter/preset-defaults")
    def cf_preset_defaults():
        """预置默认规则集（仅补缺失的，不动已有条目）。"""
        from panel.cf_defaults import preset_default_rulesets
        return jsonify(preset_default_rulesets(db()))

    @app.post("/api/openbox/content-filter/restore-defaults")
    def cf_restore_defaults():
        """恢复默认：重建 3 条默认规则集，用户自加的规则集保留。"""
        from panel.cf_defaults import restore_defaults
        return jsonify(restore_defaults(db()))

    # 旧版接口（兼容保留）
    @app.get("/api/content-filters")
    def content_filter_list():
        return jsonify(dbmod.list_content_filters(db()))

    @app.get("/api/content-filters/<int:fid>")
    def content_filter_get(fid: int):
        r = dbmod.get_content_filter(db(), fid)
        if not r:
            return jsonify({"error": "not found"}), 404
        return jsonify(r)

    @app.put("/api/content-filters/<int:fid>")
    def content_filter_update(fid: int):
        d = request.get_json(force=True, silent=True) or {}
        r = dbmod.update_content_filter(db(), fid, d.get("enabled"), d.get("domains"), d.get("snapshot_url"))
        if not r:
            return jsonify({"error": "not found"}), 404
        return jsonify(r)

    @app.post("/api/content-filters/<int:fid>/refresh")
    def content_filter_refresh(fid: int):
        """从快照 URL 拉取域名并更新。"""
        try:
            r = dbmod.refresh_content_filter_from_snapshot(db(), fid)
            if not r:
                return jsonify({"error": "not found or no snapshot url"}), 404
            # 重新生成 sing-box 配置使新规则生效
            from core import singbox as _sb
            from core import models as _models
            # 触发配置重新生成（经由 apply 接口逻辑）
            return jsonify({"ok": True, "filter": r, "domains": len(r.get("domains", []))})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- backup / restore ----
    @app.get("/api/backup")
    def backup_export():
        from core.backup import backup_to_json, BACKUP_GROUPS, REQUIRED_GROUPS
        # 选择性导出：?groups=routing,groups,dns,panel,subscriptions,chain,share,apps
        # 不传则导出全部；必选分组总是包含
        groups_param = request.args.get("groups", "").strip()
        if groups_param:
            groups = [g.strip() for g in groups_param.split(",") if g.strip() in BACKUP_GROUPS]
        else:
            groups = None
        return app.response_class(
            backup_to_json(db(), groups), mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=openbox-oss-backup.json"})

    @app.get("/api/backup/groups")
    def backup_groups():
        """返回可用的备份分组及其描述。"""
        from core.backup import BACKUP_GROUPS, REQUIRED_GROUPS
        descs = {
            "routing": "目标分流（站点集）与前置规则",
            "groups": "出站节点分组",
            "dns": "DNS 设置",
            "panel": "面板设置",
            "subscriptions": "订阅与节点",
            "chain": "链式代理",
            "share": "订阅分享",
            "apps": "终端分流",
        }
        return jsonify({
            "groups": [{"id": g, "required": g in REQUIRED_GROUPS,
                        "description": descs.get(g, g),
                        "tables": BACKUP_GROUPS[g]} for g in sorted(BACKUP_GROUPS.keys())],
        })

    @app.post("/api/backup")
    def backup_import():
        from core.backup import backup_from_json
        try:
            if request.is_json:
                result = backup_from_json(db(), json.dumps(request.get_json()))
            else:
                result = backup_from_json(db(), request.get_data(as_text=True))
        except (ValueError, json.JSONDecodeError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(result)

    # ---- client API (Bearer client_token; see docs/client-api.md) ----
    def _client_cfg():
        return dbmod.load_app_config(db())

    @app.get("/api/client/status")
    def client_status():
        from core.service import manager_from_env
        m = manager_from_env()
        st = m.status()
        return jsonify({
            "running": st.running,
            "version": st.version,
            "uptime_s": round(st.uptime_s, 1) if st.uptime_s is not None else None,
            "mode": dbmod.get_setting(db(), "client_mode", "rule"),
            "rev": dbmod.get_rev(db()),
        })

    @app.get("/api/client/nodes")
    def client_nodes():
        health = {h["tag"]: h for h in dbmod.list_health(db())}
        out = []
        for n in dbmod.list_nodes(db()):
            h = health.get(n["tag"], {})
            out.append({**n, "latency_ms": h.get("latency_ms"),
                        "ok": h.get("ok")})
        return jsonify(out)

    @app.get("/api/client/groups")
    def client_groups():
        cfg = _client_cfg()
        from core.singbox import resolve_group_members
        node_tags = [n.tag for n in cfg.nodes]
        chain_tags = [c.name for c in cfg.chains]
        return jsonify([{
            "name": g.name, "type": g.type,
            "members": resolve_group_members(g, node_tags, chain_tags),
        } for g in cfg.groups])

    @app.post("/api/client/groups/<name>/select")
    def client_group_select(name: str):
        from core.failover import switch_selector
        d = request.get_json(force=True, silent=True) or {}
        tag = d.get("tag", "")
        if not tag:
            return jsonify({"error": "tag required"}), 400
        cfg = _client_cfg()
        ok, msg = switch_selector(f"http://127.0.0.1:{cfg.clash_api_port}", "", name, tag)
        if not ok:
            return jsonify({"error": msg}), 502
        return jsonify({"ok": True, "group": name, "tag": tag})

    @app.get("/api/client/config")
    def client_config():
        from core.client_config import build_client_config
        cfg = _client_cfg()
        mode = request.args.get("mode") or dbmod.get_setting(db(), "client_mode", "rule")
        ruleset = request.args.get("ruleset", "follow")
        try:
            out = build_client_config(cfg, mode=mode, ruleset=ruleset)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        c = db()
        out["openbox"] = {
            "router": {
                "name": dbmod.get_setting(c, "router_name", "OpenBox"),
                "icon": dbmod.get_setting(c, "router_icon", "router"),
                "region": dbmod.get_setting(c, "router_region", "cn"),
            },
            "region_rules": [r for r in dbmod.list_region_rules(c) if r["enabled"]],
        }
        return jsonify(out)

    # ---- region routing (client apps) ----
    @app.get("/api/region-rules")
    def region_rules_list():
        return jsonify(dbmod.list_region_rules(db()))

    @app.post("/api/region-rules")
    def region_rule_create():
        try:
            return jsonify(dbmod.create_region_rule(db(), request.get_json(force=True, silent=True) or {}))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.put("/api/region-rules/<int:rid>")
    def region_rule_update(rid: int):
        r = dbmod.update_region_rule(db(), rid, request.get_json(force=True, silent=True) or {})
        if r is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(r)

    @app.delete("/api/region-rules/<int:rid>")
    def region_rule_delete(rid: int):
        if not dbmod.delete_region_rule(db(), rid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.get("/api/client/mode")
    def client_mode_get():
        return jsonify({"mode": dbmod.get_setting(db(), "client_mode", "rule")})

    @app.post("/api/client/mode")
    def client_mode_set():
        from core.client_config import VALID_MODES
        d = request.get_json(force=True, silent=True) or {}
        mode = d.get("mode", "")
        if mode not in VALID_MODES:
            return jsonify({"error": f"mode must be one of {VALID_MODES}"}), 400
        dbmod.set_setting(db(), "client_mode", mode)
        return jsonify({"mode": mode})

    @app.post("/api/client/subscriptions/sync")
    def client_sync():
        d = request.get_json(force=True, silent=True) or {}
        direction = d.get("direction", "pull")
        if direction == "push":
            content = d.get("content", "")
            if not content:
                return jsonify({"error": "content required"}), 400
            _sid, n = dbmod.add_subscription(
                db(), d.get("name", "client-push"),
                content, source="client-push",
                format=d.get("format", "auto"))
            return jsonify({"added": n, "rev": dbmod.get_rev(db())})
        # pull
        rev = dbmod.get_rev(db())
        if d.get("client_rev") == rev:
            return jsonify({"rev": rev, "nodes": []})
        return jsonify({"rev": rev, "nodes": dbmod.list_nodes(db())})

    @app.get("/api/client/wifi-policy")
    def client_wifi_policy_get():
        return jsonify(json.loads(dbmod.get_setting(
            db(), "wifi_policy",
            '{"enabled": false, "pause_ssids": [], "action": "pause"}')))

    @app.put("/api/client/wifi-policy")
    def client_wifi_policy_put():
        d = request.get_json(force=True, silent=True) or {}
        policy = {"enabled": bool(d.get("enabled")),
                  "pause_ssids": [str(s) for s in d.get("pause_ssids", [])],
                  "action": d.get("action", "pause")}
        if policy["action"] not in ("pause", "direct"):
            return jsonify({"error": "action must be pause|direct"}), 400
        dbmod.set_setting(db(), "wifi_policy", json.dumps(policy))
        return jsonify(policy)

    # ---- DNS management ----
    @app.get("/api/dns")
    def dns_get():
        c = db()
        return jsonify({
            "mode": dbmod.get_setting(c, "dns_mode", "dnsmasq"),
            "region": dbmod.get_setting(c, "dns_region", "auto"),
            "region_detected": dbmod.get_setting(c, "dns_region_detected", ""),
            "direct_dns": dbmod.get_setting(c, "dns_direct", dbmod.DEFAULT_SETTINGS["dns_direct"]),
            "proxy_dns": dbmod.get_setting(c, "dns_proxy", dbmod.DEFAULT_SETTINGS["dns_proxy"]),
            "fakeip": dbmod.get_setting(c, "dns_fakeip", "0") == "1",
            "split": dbmod.get_setting(c, "dns_split", "1") == "1",
            "upstream_latency": dbmod._safe_json_loads(
                dbmod.get_setting(c, "dns_upstream_latency", "{}")),
            "rewrites": dbmod.list_dns_rewrites(c),
        })

    @app.put("/api/dns")
    def dns_put():
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        if "mode" in d:
            mode = d["mode"]
            # 1:1 original: "hijack" is the firewall-hijack mode
            if mode == "hijack":
                mode = "firewall"
            if mode not in ("dnsmasq", "firewall", "off"):
                return jsonify({"error": "mode must be dnsmasq|firewall|hijack|off"}), 400
            dbmod.set_setting(c, "dns_mode", mode)
        if "region" in d:
            if d["region"] not in ("auto", "cn", "outside"):
                return jsonify({"error": "region must be auto|cn|outside"}), 400
            dbmod.set_setting(c, "dns_region", d["region"])
        for k in ("direct_dns", "proxy_dns"):
            skey = "dns_direct" if k == "direct_dns" else "dns_proxy"
            if k in d and str(d[k]).strip():
                val = str(d[k]).strip()
                # 验收 #16：在中国大陆，代理 DNS 不得使用上游 DNS
                if k == "proxy_dns" and "上游 DNS" in val:
                    region = d.get("region") or dbmod.get_setting(c, "dns_region", "auto")
                    # auto 时按检测值判断；未检测过默认为 cn（保守）
                    if region == "auto":
                        region = dbmod.get_setting(c, "dns_region_detected", "cn") or "cn"
                    if region == "cn":
                        return jsonify({"error": "在中国大陆，代理 DNS 不能使用「上游 DNS」：大陆的 DNS 对境外域名有污染，走代理的域名必须经代理 DNS（如 TCP 1.1.1.1）查询，否则会被污染结果误导。"}), 400
                dbmod.set_setting(c, skey, val)
        if "fakeip" in d:
            dbmod.set_setting(c, "dns_fakeip", "1" if d["fakeip"] else "0")
        if "split" in d:
            dbmod.set_setting(c, "dns_split", "1" if d["split"] else "0")
        c.commit()
        return dns_get()

    @app.post("/api/dns/detect-region")
    def dns_detect_region():
        # Auto-detect mainland vs outside from the exit IP's country.
        import urllib.request as _url
        country = ""
        try:
            with _url.urlopen("https://ip-api.com/json/?fields=countryCode",
                              timeout=8) as r:
                country = (json.loads(r.read().decode()) or {}).get("countryCode", "")
        except Exception as e:
            return jsonify({"error": f"detection failed: {e}"}), 502
        region = "cn" if country.upper() == "CN" else "outside"
        dbmod.set_setting(db(), "dns_region_detected", region)
        return jsonify({"country": country.upper(), "region": region})

    @app.post("/api/dns/rewrite")
    def dns_rewrite_add():
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            row = dbmod.add_dns_rewrite(c, d.get("domain", ""), d.get("target", ""))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        row["dnsmasq_sync"] = sync_dnsmasq_panel_conf(c)
        return jsonify(row), 201

    @app.delete("/api/dns/rewrite/<int:rid>")
    def dns_rewrite_del(rid: int):
        c = db()
        if not dbmod.delete_dns_rewrite(c, rid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True,
                        "dnsmasq_sync": sync_dnsmasq_panel_conf(c)})

    @app.put("/api/dns/rewrite/<int:rid>")
    def dns_rewrite_put(rid: int):
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        if "domain" in d or "target" in d:
            # Edit domain/target
            try:
                row = dbmod.update_dns_rewrite(
                    c, rid, d.get("domain", ""), d.get("target", ""))
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            if not row:
                return jsonify({"error": "not found"}), 404
            row["dnsmasq_sync"] = sync_dnsmasq_panel_conf(c)
            return jsonify(row)
        if "enabled" not in d:
            return jsonify({"error": "enabled is required"}), 400
        if not dbmod.set_dns_rewrite_enabled(c, rid, bool(d["enabled"])):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True, "enabled": bool(d["enabled"]),
                        "dnsmasq_sync": sync_dnsmasq_panel_conf(c)})

    @app.post("/api/dns/rewrite/reset")
    def dns_rewrite_reset():
        c = db()
        count = dbmod.reset_dns_rewrites(c)
        return jsonify({"ok": True, "count": count,
                        "dnsmasq_sync": sync_dnsmasq_panel_conf(c)})

    def _df_workdir() -> str:
        from core.service import manager_from_env
        return manager_from_env().workdir

    def _trace_proxy_route(c, domain: str) -> bool:
        """Best-effort: would *domain* go through the proxy? Used to pick
        the trace upstream. Pure rule matching, no network."""
        from core.routing import preview_route
        from panel.db import get_setting
        try:
            cfg = dbmod.load_app_config(c)
            r = preview_route(cfg.site_sets, domain)
            action = r.get("action") or ""
            if action == "proxy":
                return True
            if action == "direct":
                return False
            return get_setting(c, "final_outbound", "auto") not in ("direct",)
        except Exception:
            return False

    # ---- DNS filter (ad/malware blocklists) ----
    def _dns_filter_lists(c):
        import json as _json
        from panel.db import get_setting
        try:
            lists = _json.loads(get_setting(c, "dns_filter_lists", "[]"))
        except ValueError:
            lists = []
        if not lists:
            from core.dnsfilter import BUILTIN_LISTS
            lists = [dict(x) for x in BUILTIN_LISTS]
        return lists

    @app.get("/api/dns/filter")
    def dns_filter_get():
        from panel.db import get_setting
        from core import dnsfilter as _df
        c = db()
        m = _df.load_compiled(_df_workdir())
        return jsonify({
            "enabled": get_setting(c, "dns_filter_enabled", "0") == "1",
            "lists": _dns_filter_lists(c),
            "compiled_domains": len(m),
            "applied_at": get_setting(c, "dns_filter_applied_at", ""),
            "auto_update": get_setting(c, "dns_filter_auto_update", "0") == "1",
            "update_time": get_setting(c, "dns_filter_update_time", "04:00"),
            "blocklist_path": _df.blocklist_path(_df_workdir()),
        })

    @app.put("/api/dns/filter")
    def dns_filter_put():
        import json as _json
        from panel.db import set_setting
        d = request.get_json(force=True, silent=True) or {}
        lists = d.get("lists", [])
        clean = [{"name": str(x.get("name", ""))[:80],
                  "url": str(x.get("url", ""))[:500],
                  "enabled": bool(x.get("enabled", True))}
                 for x in lists if x.get("name") and x.get("url")]
        c = db()
        set_setting(c, "dns_filter_enabled",
                    "1" if d.get("enabled") else "0")
        set_setting(c, "dns_filter_lists", _json.dumps(clean, ensure_ascii=False))
        if "auto_update" in d:
            set_setting(c, "dns_filter_auto_update",
                        "1" if d.get("auto_update") else "0")
        ut = str(d.get("update_time", "")).strip()
        if ut:
            import re as _re
            if _re.match(r"^\d{1,2}:\d{2}$", ut):
                set_setting(c, "dns_filter_update_time", ut)
        c.commit()
        return jsonify({"ok": True, "lists": clean,
                        "dnsmasq_sync": sync_dnsmasq_panel_conf(c)})

    @app.post("/api/dns/filter/apply")
    def dns_filter_apply():
        import json as _json
        from panel.db import get_setting, set_setting
        from core import dnsfilter as _df
        c = db()
        update_only = request.args.get("update") == "1"
        lists = _dns_filter_lists(c)
        result = _df.apply_lists(_df_workdir(), lists)
        if not update_only:
            set_setting(c, "dns_filter_enabled", "1")
        set_setting(c, "dns_filter_applied_at", result["applied_at"])
        set_setting(c, "dns_filter_lists", _json.dumps(
            [{**l, "domains": s.get("domains", 0),
              "updated_at": s.get("updated_at", ""),
              "error": s.get("error", "")}
             for l, s in zip(lists, result["lists"])], ensure_ascii=False))
        result["dnsmasq_sync"] = sync_dnsmasq_panel_conf(c)
        return jsonify(result)

    @app.get("/api/dns/filter/preview")
    def dns_filter_preview():
        from core import dnsfilter as _df
        domain = request.args.get("domain", "").strip()
        if not domain:
            return jsonify({"error": "domain required"}), 400
        hit = _df.match_domain(domain, _df.load_compiled(_df_workdir()))
        return jsonify({"domain": domain, "blocked": hit is not None,
                        "matched": hit})

    @app.get("/api/dns/filter/records")
    def dns_filter_records():
        from core import dnsfilter as _df
        from core import dnslog as _dl
        n = min(int(request.args.get("n", 200)), 2000)
        log_path = os.environ.get("OBX_DNSMASQ_LOG", "/var/log/dnsmasq.log")
        queries, note = _dl.parse_dnsmasq_log(log_path, n * 2)
        blocked = [q for q in _dl.enrich(
            queries, _df.load_compiled(_df_workdir())) if q["blocked"]]
        return jsonify({"records": blocked[:n], "note": note})

    # ---- DNS query log ----
    @app.get("/api/dns/query-log")
    def dns_query_log():
        from core import dnslog as _dl
        from core import dnsfilter as _df
        n = min(int(request.args.get("n", 200)), 2000)
        log_path = os.environ.get("OBX_DNSMASQ_LOG", "/var/log/dnsmasq.log")
        queries, note = _dl.parse_dnsmasq_log(log_path, n)
        return jsonify({"queries": _dl.enrich(
            queries, _df.load_compiled(_df_workdir())), "note": note,
            "log_path": log_path})

    # ---- DNS upstream test / WAN DNS / trace ----
    @app.post("/api/dns/upstream-test")
    def dns_upstream_test():
        from core import dnstest as _dt
        from panel.db import get_setting, set_setting
        import json as _json
        d = request.get_json(force=True, silent=True) or {}
        upstream = (d.get("upstream") or "").strip()
        if not upstream:
            return jsonify({"error": "upstream required"}), 400
        result = _dt.test_upstream(
            upstream, d.get("domain") or "www.google.com",
            timeout=float(d.get("timeout", 5.0)))
        # persist latency for primary/backup ordering in generated config
        c = db()
        try:
            lat = _json.loads(get_setting(c, "dns_upstream_latency", "{}") or "{}")
        except ValueError:
            lat = {}
        if result.get("ok") and result.get("latency_ms") is not None:
            lat[upstream] = result["latency_ms"]
        elif upstream in lat:
            del lat[upstream]
        set_setting(c, "dns_upstream_latency", _json.dumps(lat))
        c.commit()
        return jsonify(result)

    @app.post("/api/openbox/terminal-test")
    def ob_terminal_test():
        d = request.get_json(force=True, silent=True) or {}
        target = (d.get("target") or "").strip()
        if not target:
            return jsonify({"error": "target is required"}), 400
        # 基础连通性测试：尝试解析并连接
        import socket
        result = {"target": target, "ok": False}
        try:
            # 尝试 DNS 解析
            ip = socket.gethostbyname(target.split(":")[0])
            result["resolved_ip"] = ip
            result["ok"] = True
        except Exception as e:
            result["error"] = str(e)
        return jsonify(result)

    @app.get("/api/openbox/terminal-test/capability")
    def ob_terminal_capability():
        """探测终端分流能力（REA 26.3：先探测能力，绝不静默降级）。"""
        import shutil
        import subprocess
        missing = []
        # nftables 可用性
        has_nft = shutil.which("nft") is not None
        if not has_nft:
            missing.append("nftables")
        # 检查是否有 LAN 网卡（非 lo）
        has_lan = False
        try:
            out = subprocess.run(["ip", "-o", "link", "show"],
                               capture_output=True, text=True, timeout=5)
            for line in out.stdout.splitlines():
                if ": lo:" not in line and "state UP" in line:
                    has_lan = True
                    break
        except Exception:
            missing.append("ip-command")
        # ARP 可用性（MAC -> IP 解析）
        has_arp = shutil.which("arp") is not None or shutil.which("ip") is not None
        if not has_arp:
            missing.append("arp")
        ok = has_nft and has_lan and not missing
        return jsonify({
            "ok": ok,
            "lan": has_lan,
            "nftables": has_nft,
            "arp": has_arp,
            "missing": missing,
        })

    @app.post("/api/openbox/dns/flush-cache")
    def ob_dns_flush():
        """Clear DNS caches on both ends (1:1).

        - dnsmasq (LAN): SIGHUP clears its cache immediately. Safe.
        - kernel (sing-box): in-memory DNS cache has no flush API in
          stock or tcp23-patched sing-box; it is rebuilt on the next
          config apply/restart. We do NOT restart the shared kernel
          automatically; the response reports this honestly.
        """
        import subprocess
        dnsmasq_ok = False
        dnsmasq_note = ""
        try:
            r = subprocess.run(["pkill", "-HUP", "dnsmasq"],
                               timeout=5, capture_output=True)
            # pkill returns 0 if at least one process matched
            dnsmasq_ok = (r.returncode == 0)
            if not dnsmasq_ok:
                dnsmasq_note = "dnsmasq 未运行"
        except Exception as e:
            dnsmasq_note = str(e)[:100]
        return jsonify({
            "dnsmasq": dnsmasq_ok,
            "dnsmasq_note": dnsmasq_note,
            # Kernel DNS cache: no runtime flush API; cleared on next
            # config apply / service restart.
            "kernel": False,
            "kernel_note": "sing-box 无运行时清缓存接口，缓存将在下次配置应用/重启时重建",
            "resolved": False,
        })

    @app.get("/api/openbox/dns/region-detect")
    def ob_dns_region_get():
        c = db()
        region = dbmod.get_setting(c, "dns_region", "auto")
        detected = dbmod.get_setting(c, "dns_region_detected", "")
        # REA 26.4: 全新安装/升级/恢复默认值时自动检测
        # region=auto 且未检测过 -> 触发异步检测
        if region == "auto" and not detected:
            import threading
            def _auto_detect():
                try:
                    import json as _json
                    import urllib.request as _req
                    req = _req.Request(
                        "http://ip-api.com/json/?fields=status,countryCode,query",
                        headers={"User-Agent": "openbox-oss/1.0"})
                    with _req.urlopen(req, timeout=10) as r:
                        data = _json.loads(r.read().decode())
                    cc = (data.get("countryCode") or "").upper()
                    detected_region = "cn" if cc == "CN" else "outside"
                    c2 = db()
                    dbmod.set_setting(c2, "dns_region_detected", detected_region)
                    c2.commit()
                except Exception:
                    pass
            threading.Thread(target=_auto_detect, daemon=True).start()
            return jsonify({"region": region, "pending": True})
        return jsonify({"region": detected if region == "auto" else region, "pending": False})

    @app.get("/api/openbox/entry-plan")
    def ob_entry_plan():
        """Get entry bypass plan (mode + reason).
        
        1:1 对标原版：自动模式选择（blacklist/whitelist），规则页显示模式及原因。
        """
        from core.entry_plan import entry_plan, plan_to_dict
        from panel.db import get_setting
        conn = db()
        enabled = get_setting(conn, "direct_bypass_kernel", "1") == "1"
        fakeip = get_setting(conn, "dns_fakeip", "0") == "1"
        final = get_setting(conn, "final_outbound", "所有-自动")
        # TODO: 从站点集提取 direct/proxy CIDRs（Phase C）
        plan = entry_plan(
            enabled=enabled,
            fakeip_enabled=fakeip,
            final_outbound=final,
        )
        return jsonify(plan_to_dict(plan))

    @app.get("/api/openbox/proxy-settings")
    def ob_proxy_settings_get():
        """代理页策略设置（排序/分组/卡宽/显示顺序），服务端持久化。"""
        from panel.db import get_setting
        import json as _json
        conn = db()
        try:
            order = _json.loads(get_setting(conn, "proxy_display_order", "[]") or "[]")
            if not isinstance(order, list):
                order = []
        except ValueError:
            order = []
        return jsonify({
            "sort": get_setting(conn, "proxy_sort", "latencyasc"),
            "group_by_provider": get_setting(conn, "proxy_group_by_provider", "1") == "1",
            "card_min_width": int(get_setting(conn, "proxy_card_min_width", "155") or 155),
            "display_order": order,
        })

    @app.put("/api/openbox/proxy-settings")
    def ob_proxy_settings_put():
        """部分更新代理页策略设置。"""
        from panel.db import get_setting, set_setting
        import json as _json
        d = request.get_json(force=True, silent=True) or {}
        conn = db()
        if "sort" in d and d["sort"] in ("defaultsort", "nameasc", "namedesc",
                                         "latencyasc", "latencydesc"):
            set_setting(conn, "proxy_sort", d["sort"])
        if "group_by_provider" in d:
            set_setting(conn, "proxy_group_by_provider",
                        "1" if d["group_by_provider"] else "0")
        if "card_min_width" in d:
            try:
                w = max(80, min(400, int(d["card_min_width"])))
            except (TypeError, ValueError):
                w = 155
            set_setting(conn, "proxy_card_min_width", str(w))
        if "display_order" in d and isinstance(d["display_order"], list):
            names = [str(x) for x in d["display_order"] if isinstance(x, str)][:64]
            set_setting(conn, "proxy_display_order",
                        _json.dumps(names, ensure_ascii=False))
        conn.commit()
        return ob_proxy_settings_get()

    @app.post("/api/openbox/dns/region-detect")
    def ob_dns_region_post():
        """Detect region by exit IP geolocation (1:1).

        Queries ip-api.com for country code; maps CN -> "cn",
        otherwise -> "outside". Falls back to "cn" on failure.
        """
        import json as _json
        import urllib.request as _req
        region = "cn"
        ip = ""
        country = ""
        try:
            req = _req.Request(
                "http://ip-api.com/json/?fields=status,country,countryCode,query",
                headers={"User-Agent": "openbox-oss/1.0"})
            with _req.urlopen(req, timeout=10) as r:
                data = _json.loads(r.read().decode())
            if data.get("status") == "success":
                ip = data.get("query", "")
                country = data.get("country", "")
                cc = (data.get("countryCode") or "").upper()
                region = "cn" if cc == "CN" else "outside"
        except Exception:
            pass
        return jsonify({"region": region, "ip": ip, "country": country})

    # ---- subscription shares (1:1 对标原版) ----
    @app.get("/api/openbox/subscription-shares/")
    def ob_subshares_list():
        c = db()
        rows = c.execute("SELECT id, name, host, protocol, token, subscription_ids, enabled, created_at FROM ob_subscription_shares ORDER BY id").fetchall()
        import json as _json
        return jsonify({"shares": [{
            "id": r[0], "name": r[1], "host": r[2], "protocol": r[3], "token": r[4],
            "subscriptionIds": _json.loads(r[5] or "[]"), "enabled": bool(r[6]), "created_at": r[7],
        } for r in rows]})

    @app.post("/api/openbox/subscription-shares/")
    def ob_subshares_create():
        import json as _json, secrets, time
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        token = d.get("token") or secrets.token_urlsafe(16)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        cur = c.execute(
            "INSERT INTO ob_subscription_shares(name, host, protocol, token, subscription_ids, enabled, created_at) VALUES (?,?,?,?,?,?,?)",
            (d.get("name", ""), d.get("host", ""), d.get("protocol", "clash"), token,
             _json.dumps(d.get("subscriptionIds", [])), 1, now))
        c.commit()
        return jsonify({"share": {"id": cur.lastrowid, "token": token}}), 201

    @app.delete("/api/openbox/subscription-shares/<int:sid>")
    def ob_subshares_del(sid):
        c = db()
        c.execute("DELETE FROM ob_subscription_shares WHERE id=?", (sid,))
        c.commit()
        return jsonify({"ok": True})

    @app.patch("/api/openbox/subscription-shares/<int:sid>")
    def ob_subshares_patch(sid):
        import json as _json, secrets
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        fields, vals = [], []
        for k, col in (("name", "name"), ("host", "host"), ("protocol", "protocol"), ("enabled", "enabled")):
            if k in d:
                v = d[k]
                if k == "enabled":
                    v = 1 if v else 0
                fields.append(f"{col}=?")
                vals.append(v)
        if "subscriptionIds" in d:
            fields.append("subscription_ids=?")
            vals.append(_json.dumps(d["subscriptionIds"]))
        if d.get("regenerate"):
            fields.append("token=?")
            vals.append(secrets.token_urlsafe(16))
        if fields:
            vals.append(sid)
            c.execute(f"UPDATE ob_subscription_shares SET {', '.join(fields)} WHERE id=?", vals)
            c.commit()
        row = c.execute("SELECT token FROM ob_subscription_shares WHERE id=?", (sid,)).fetchone()
        return jsonify({"share": {"id": sid, "token": row[0] if row else ""}})

    @app.post("/api/openbox/subscription-shares/<int:sid>/regenerate")
    def ob_subshares_regen(sid):
        import secrets
        c = db()
        token = secrets.token_urlsafe(16)
        c.execute("UPDATE ob_subscription_shares SET token=? WHERE id=?", (token, sid))
        c.commit()
        return jsonify({"share": {"id": sid, "token": token}})

    # ---- failover status (1:1 对标原版) ----
    def _fsm_reason_text(reason: str) -> str:
        """Failover 原因码 → 中文（REA §24.5 i18n 表）。"""
        return {
            "initial": "初始选择",
            "lane-failed": "通道故障，已切换",
            "all-failed": "全部通道故障",
            "primary-restored": "主通道恢复",
            "healthy": "运行正常",
        }.get(reason, reason)

    @app.get("/api/openbox/failover/status")
    def ob_failover_status():
        from core import failover_sm as _fsm
        import json as _json
        c = db()
        groups = dbmod.list_groups(c)
        result = []
        for g in groups:
            if g.get("type") != "failover":
                continue
            # 加载或初始化状态机
            state_json = c.execute(
                "SELECT state_json FROM failover_state WHERE group_name=?",
                (g["name"],)).fetchone()
            if state_json and state_json[0] and state_json[0] != '{}':
                try:
                    st = _fsm.FailoverState.from_dict(_json.loads(state_json[0]))
                except Exception:
                    st = None
            else:
                st = None
            if st is None:
                # 初始化
                lanes_cfg = g.get("lanes") or []
                st = _fsm.failover_init(g["name"], lanes_cfg, {
                    "probe_interval_s": g.get("interval_s", 300),
                    "tolerance_ms": g.get("tolerance_ms", 100),
                    "probe_timeout_ms": 5000,
                    "fail_threshold": 2,
                    "restore_primary": True,
                    "restore_hold_ms": 60000,
                })
                c.execute(
                    "INSERT INTO failover_state(group_name, current_tag, updated_at, state_json)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(group_name) DO UPDATE SET state_json=excluded.state_json",
                    (g["name"], st.current_id, _fsm._now_iso(),
                     _json.dumps(st.to_dict(), ensure_ascii=False)))
                c.commit()
            # 构建前端展示的 lanes
            lanes_out = []
            for lane in st.lanes:
                lanes_out.append({
                    "id": lane["id"],
                    "name": lane["name"],
                    "tag": lane["tag"],
                    "members": lane["members"],
                    "mode": lane["mode"],
                    "health": lane["health"],
                    "ok": lane["ok"],
                    "failStreak": lane["fail_streak"],
                    "reason": lane["reason"],
                    "upSince": lane["up_since"],
                    "isCurrent": lane["id"] == st.current_lane_id,
                })
            # 最近切换日志
            last_log = st.logs[-1] if st.logs else None
            result.append({
                "id": g["id"],
                "name": g["name"],
                "current": st.current_id,
                "currentLaneId": st.current_lane_id,
                "reason": st.last_reason,
                "reasonText": _fsm_reason_text(st.last_reason),
                "lastSwitch": st.last_switch,
                "lastSwitchText": (
                    f"{last_log['from']} → {last_log['to']} ({_fsm_reason_text(last_log['reason'])})"
                    if last_log else "—"
                ),
                "nextRoundAt": st.next_round_at,
                "lanes": lanes_out,
                "logs": st.logs[-10:],
            })
        return jsonify({"groups": result})

    @app.post("/api/openbox/failover/recheck")
    def ob_failover_recheck():
        from core import failover_sm as _fsm
        import json as _json
        d = request.get_json(force=True, silent=True) or {}
        gid = d.get("groupId") or d.get("id")
        c = db()
        groups = dbmod.list_groups(c)
        target = None
        for g in groups:
            if g.get("type") == "failover" and (str(g["id"]) == str(gid) or g["name"] == gid):
                target = g
                break
        if not target:
            return jsonify({"ok": False, "error": "failover group not found"}), 404
        # 加载状态
        row = c.execute(
            "SELECT state_json FROM failover_state WHERE group_name=?",
            (target["name"],)).fetchone()
        st = None
        if row and row[0] and row[0] != '{}':
            try:
                st = _fsm.FailoverState.from_dict(_json.loads(row[0]))
            except Exception:
                st = None
        if st is None:
            lanes_cfg = target.get("lanes") or []
            st = _fsm.failover_init(target["name"], lanes_cfg)
        # 运行一轮探测
        cfg = dbmod.load_app_config(c)
        api_base = f"http://127.0.0.1:{cfg.clash_api_port}"
        secret = getattr(cfg, "clash_api_secret", "") or ""
        try:
            result = _fsm.run_round(st, api_base, secret)
            # 持久化状态
            c.execute(
                "INSERT INTO failover_state(group_name, current_tag, updated_at, last_switch_at, state_json)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(group_name) DO UPDATE SET current_tag=excluded.current_tag,"
                " updated_at=excluded.updated_at, last_switch_at=excluded.last_switch_at,"
                " state_json=excluded.state_json",
                (target["name"], st.current_id, _fsm._now_iso(),
                 st.last_switch, _json.dumps(st.to_dict(), ensure_ascii=False)))
            c.commit()
            # 应用切换（如果需要）
            if result.get("switched"):
                _fsm.apply_switch(api_base, secret, target["name"], result["currentTag"])
            return jsonify({
                "ok": True,
                "groupId": gid,
                "groupName": target["name"],
                "switched": result.get("switched", False),
                "current": result.get("currentTag"),
                "reason": result.get("reason"),
                "reasonText": _fsm_reason_text(result.get("reason", "")),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    @app.get("/api/dns/wan")
    def dns_wan():
        from core import dnstest as _dt
        return jsonify({"upstreams": _dt.system_upstreams()})

    @app.post("/api/dns/trace")
    def dns_trace():
        from core import dnstest as _dt
        from panel.db import get_setting
        d = request.get_json(force=True, silent=True) or {}
        domain = (d.get("domain") or "").strip()
        if not domain:
            return jsonify({"error": "domain required"}), 400
        c = db()
        direct = get_setting(c, "dns_direct", "223.5.5.5")
        proxy = get_setting(c, "dns_proxy", "tcp://1.1.1.1")
        route = d.get("route") or ("proxy" if _trace_proxy_route(c, domain) else "direct")
        return jsonify(_dt.trace(domain, direct, proxy, route,
                                 timeout=float(d.get("timeout", 5.0))))

    # ---- live connections (via kernel clash API) ----
    @app.get("/api/connections")
    def connections_list():
        from core import clashapi
        ok, conns = clashapi.list_connections()
        if not ok:
            return jsonify({"error": "kernel clash API unreachable", "connections": []}), 502
        out = []
        for cn in conns:
            m = cn.get("metadata", {}) or {}
            out.append({
                "id": str(cn.get("id", "")),
                "start": cn.get("start", ""),
                "upload": cn.get("upload", 0), "download": cn.get("download", 0),
                "chains": cn.get("chains", []),
                "rule": cn.get("rule", ""), "rule_payload": cn.get("rulePayload", ""),
                "src": f"{m.get('sourceIP', '')}:{m.get('sourcePort', '')}",
                "dst": m.get("host", "") or m.get("destinationIP", ""),
                "dport": m.get("destinationPort", ""),
                "network": m.get("network", ""), "type": m.get("type", ""),
            })
        return jsonify({"connections": out})

    @app.delete("/api/connections/<cid>")
    def connection_close(cid: str):
        from core import clashapi
        ok, data = clashapi.close_connection(cid)
        if not ok:
            return jsonify({"error": "close failed", "detail": data}), 502
        return jsonify({"ok": True})

    @app.get("/api/traffic/now")
    def traffic_now():
        from core import clashapi
        ok, conns = clashapi.list_connections()
        up = down = 0
        if ok:
            for cn in conns:
                up += int(cn.get("upload", 0)); down += int(cn.get("download", 0))
        return jsonify({"up": up, "download": down, "connections": len(conns) if ok else 0,
                        "kernel": ok})

    @app.get("/api/traffic/daily")
    def traffic_daily():
        days = min(max(int(request.args.get("days", 7)), 1), 90)
        return jsonify({"rows": dbmod.traffic_summary(db(), days)})

    @app.get("/api/traffic/usage")
    def traffic_usage():
        return jsonify(dbmod.traffic_usage(db()))

    @app.get("/api/traffic/month")
    def traffic_month():
        import time as _time
        month = request.args.get("month") or _time.strftime("%Y-%m")
        if not __import__("re").match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month must be YYYY-MM"}), 400
        return jsonify(dbmod.traffic_month(db(), month))

    @app.get("/api/traffic/day")
    def traffic_day():
        import time as _time, re as _re
        day = request.args.get("day") or _time.strftime("%Y-%m-%d")
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            return jsonify({"error": "day must be YYYY-MM-DD"}), 400
        return jsonify(dbmod.traffic_day(db(), day))

    @app.get("/api/traffic/drill")
    def traffic_drill():
        import time as _time, re as _re
        month = request.args.get("month") or _time.strftime("%Y-%m")
        dim = request.args.get("dim", "proxy")
        if not _re.match(r"^\d{4}-\d{2}$", month):
            return jsonify({"error": "month must be YYYY-MM"}), 400
        if dim not in ("proxy", "host", "client"):
            return jsonify({"error": "dim must be proxy|host|client"}), 400
        return jsonify({"month": month, "dim": dim,
                        "rows": dbmod.traffic_drill(db(), month, dim)})

    # ---- latency history (shared across browsers) ----
    @app.get("/api/latency/history")
    def latency_history():
        return jsonify(dbmod.get_latency_history(db()))

    @app.post("/api/latency/history/samples")
    def latency_samples():
        d = request.get_json(force=True, silent=True) or {}
        samples = d.get("samples", [])
        c = db()
        n = 0
        for s in samples:
            tag = str(s.get("tag", ""))
            if not tag:
                continue
            dbmod.record_latency(c, tag, bool(s.get("ok", True)),
                                 s.get("latency_ms"))
            n += 1
        return jsonify({"recorded": n})

    @app.post("/api/latency/history/sync")
    def latency_history_sync():
        """Pull per-proxy delay history from the kernel clash API."""
        from core import clashapi
        ok, data = clashapi.get_proxies()
        c = db()
        n = 0
        if ok and isinstance(data, dict):
            for tag, p in (data.get("proxies") or {}).items():
                hist = (p or {}).get("history") or []
                if not hist:
                    continue
                last = hist[-1]
                try:
                    dbmod.record_latency(c, tag, True, float(last.get("delay")))
                    n += 1
                except (TypeError, ValueError):
                    pass
        return jsonify({"ok": ok, "synced": n,
                        "history": dbmod.get_latency_history(c)})

    # ---- site latency ----
    @app.get("/api/site-latency")
    def site_latency_get():
        return jsonify({"sites": dbmod.list_site_latency_sites(db())})

    @app.post("/api/site-latency")
    def site_latency_set():
        d = request.get_json(force=True, silent=True) or {}
        sites = d.get("sites", [])
        clean = [{"name": str(s.get("name", ""))[:60],
                  "url": str(s.get("url", ""))[:500]}
                 for s in sites if s.get("url")]
        return jsonify({"sites": dbmod.set_site_latency_sites(db(), clean)})

    @app.post("/api/site-latency/check")
    def site_latency_check():
        from core import sitelatency as _sl
        cfg = dbmod.load_app_config(db())
        m = _manager()
        proxy = None
        if m.status().running:
            proxy = "http://127.0.0.1:2080"  # kernel loopback mixed inbound
        c = db()
        out = []
        for s in dbmod.list_site_latency_sites(c):
            r = _sl.check_site(s["url"], proxy)
            dbmod.record_site_check(c, s["id"], r["ok"], r["latency_ms"])
            out.append({"id": s["id"], "name": s["name"], "url": s["url"], **r})
        return jsonify(out)

    @app.get("/api/site-latency/history")
    def site_latency_history():
        days = min(max(int(request.args.get("days", 7)), 1), 90)
        return jsonify({"checks": dbmod.site_latency_history(db(), days),
                        "sites": dbmod.list_site_latency_sites(db())})

    # ---- domain penetration: full chain site set -> group -> node ----
    @app.post("/api/route/penetrate")
    def route_penetrate():
        from core import clashapi
        from core.routing import preview_route
        d = request.get_json(force=True, silent=True) or {}
        target = str(d.get("target", "")).strip()
        if not target:
            return jsonify({"error": "target is required"}), 400
        c = db()
        cfg = dbmod.load_app_config(c)
        pv = preview_route(cfg.site_sets, target)
        chain = [{"level": "site_set", "name": pv["site_set"], "action": pv["action"],
                  "flip": pv.get("flip")}]
        node_detail = None
        kernel = False
        if pv["outbound"]:
            ob = pv["outbound"]
            chain.append({"level": "outbound", "name": ob})
            # resolve selector -> current node via clash API
            ok, proxies = clashapi.get_proxies()
            kernel = ok
            if ok:
                entry = (proxies.get("proxies", {}) or {}).get(ob, {})
                now = entry.get("now")
                if now:
                    chain.append({"level": "node", "name": now})
                    nodes = {n.tag: n for n in cfg.nodes}
                    if now in nodes:
                        n = nodes[now]
                        node_detail = {"tag": n.tag, "protocol": n.protocol,
                                       "server": n.server, "port": n.server_port}
        return jsonify({"target": target, "chain": chain, "node": node_detail,
                        "kernel": kernel})

    @app.post("/api/route/test")
    def route_test():
        """Actually fetch a URL through the local mixed inbound and report
        what happened (status, time, matched rule)."""
        from core.routing import preview_route
        import urllib.request as _url
        d = request.get_json(force=True, silent=True) or {}
        url = str(d.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            return jsonify({"error": "url must start with http:// or https://"}), 400
        c = db()
        cfg = dbmod.load_app_config(c)
        host = url.split("://", 1)[1].split("/", 1)[0].split("@")[-1].split(":")[0]
        pv = preview_route(cfg.site_sets, host)
        t0 = time.time()
        try:
            proxy = _url.ProxyHandler({"http": "http://127.0.0.1:2080",
                                       "https": "http://127.0.0.1:2080"})
            opener = _url.build_opener(proxy)
            req = _url.Request(url, headers={"User-Agent": "openbox-oss/route-test"})
            with opener.open(req, timeout=15) as r:
                status, final = r.status, r.geturl()
        except Exception as e:
            return jsonify({"url": url, "preview": pv, "error": str(e),
                            "elapsed_ms": int((time.time() - t0) * 1000)}), 502
        return jsonify({"url": url, "preview": pv, "status": status,
                        "final_url": final,
                        "elapsed_ms": int((time.time() - t0) * 1000)})

    # ---- terminal policies ----
    @app.get("/api/terminals")
    def terminals_list():
        return jsonify({"terminals": dbmod.list_terminals(db())})

    @app.post("/api/terminals")
    def terminal_upsert():
        d = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(dbmod.upsert_terminal(
                db(), d.get("ident", ""), d.get("name", ""), d.get("policy", "proxy"))), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.delete("/api/terminals/<int:tid>")
    def terminal_del(tid: int):
        if not dbmod.delete_terminal(db(), tid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    # ---- terminal rules (1:1 对标原版) ----
    @app.get("/api/terminal-rules")
    def terminal_rules_list():
        return jsonify(dbmod.list_terminal_rules(db()))

    @app.post("/api/terminal-rules")
    def terminal_rule_create():
        d = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(dbmod.create_terminal_rule(db(), d))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.put("/api/terminal-rules/<int:rid>")
    def terminal_rule_update(rid: int):
        d = request.get_json(force=True, silent=True) or {}
        try:
            row = dbmod.update_terminal_rule(db(), rid, d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(row)

    @app.delete("/api/terminal-rules/<int:rid>")
    def terminal_rule_del(rid: int):
        if not dbmod.delete_terminal_rule(db(), rid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.get("/api/terminal-test/capability")
    def terminal_test_capability():
        from core import terminalprobe as _tp
        return jsonify(_tp.capability())

    @app.post("/api/terminal-test")
    def terminal_test():
        from core import terminalprobe as _tp
        d = request.get_json(force=True, silent=True) or {}
        target = (d.get("target") or "").strip()
        if not target:
            return jsonify({"error": "target required"}), 400
        return jsonify(_tp.probe(target, timeout=float(d.get("timeout", 3.0))))

    @app.get("/api/terminal-candidates")
    def terminal_candidates():
        return jsonify({"candidates": dbmod.terminal_candidates(db())})

    @app.get("/api/arp")
    def arp_table():
        from core import arp as _arp
        table = _arp.arp_table()
        return jsonify({"entries": [
            {"ip": ip, "mac": mac} for ip, mac in sorted(table.items())]})

    # ---- shared network (LAN proxy inbound) ----
    @app.get("/api/share-network")
    def share_network_get():
        from panel.db import get_setting
        c = db()
        return jsonify({
            "enabled": get_setting(c, "share_lan_enabled", "0") == "1",
            "port": int(get_setting(c, "share_lan_port", "8088") or 8088),
        })

    @app.put("/api/share-network")
    def share_network_put():
        from panel.db import set_setting
        d = request.get_json(force=True, silent=True) or {}
        port = int(d.get("port", 8088))
        if not 1024 <= port <= 65535:
            return jsonify({"error": "port must be 1024-65535"}), 400
        c = db()
        set_setting(c, "share_lan_enabled", "1" if d.get("enabled") else "0")
        set_setting(c, "share_lan_port", str(port))
        return jsonify({"ok": True, "enabled": bool(d.get("enabled")), "port": port})

    @app.get("/api/share-network/port-check")
    def share_network_port_check():
        import socket as _socket
        port = int(request.args.get("port", 8088))
        conflicts = []
        s = _socket.socket()
        try:
            s.bind(("0.0.0.0", port))
        except OSError as e:
            conflicts.append(f"本机端口 {port} 已被占用：{e}")
        finally:
            s.close()
        for reserved, name in ((53, "DNS"), (80, "HTTP"), (443, "HTTPS"),
                               (8080, "面板"), (9090, "clash API")):
            if port == reserved:
                conflicts.append(f"端口 {port} 与{ name}服务冲突")
        return jsonify({"port": port, "ok": not conflicts, "conflicts": conflicts})

    # ---- share servers (1:1 original: LAN shadowsocks inbounds) ----
    @app.get("/api/share-servers")
    def share_servers_list():
        return jsonify(dbmod.list_share_servers(db()))

    @app.post("/api/share-servers")
    def share_server_create():
        d = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(dbmod.create_share_server(db(), d)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.put("/api/share-servers/<int:sid>")
    def share_server_update(sid: int):
        d = request.get_json(force=True, silent=True) or {}
        try:
            row = dbmod.update_share_server(db(), sid, d)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(row)

    @app.delete("/api/share-servers/<int:sid>")
    def share_server_delete(sid: int):
        if not dbmod.delete_share_server(db(), sid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    # ---- system timezone ----
    @app.get("/api/system/timezone")
    def system_timezone_get():
        return jsonify(_read_timezone())

    @app.put("/api/system/timezone")
    def system_timezone_put():
        d = request.get_json(force=True, silent=True) or {}
        tz = (d.get("timezone") or "").strip()
        if not tz or "/" not in tz and tz != "UTC":
            return jsonify({"error": "timezone 无效（如 Asia/Shanghai）"}), 400
        ok, msg = _write_timezone(tz)
        if not ok:
            return jsonify({"error": msg}), 409
        return jsonify({"ok": True, "timezone": tz})

    # ---- hot-switch a site set between direct and proxy (no restart) ----
    @app.post("/api/sitesets/<int:sid>/flip")
    def siteset_flip(sid: int):
        from core import clashapi
        d = request.get_json(force=True, silent=True) or {}
        to = d.get("to", "")
        if to not in ("direct", "proxy"):
            return jsonify({"error": "to must be direct|proxy"}), 400
        c = db()
        rows = [s for s in dbmod.list_site_sets(c) if s["id"] == sid]
        if not rows:
            return jsonify({"error": "not found"}), 404
        if rows[0]["action"] == "reject":
            return jsonify({"error": "reject site sets cannot be flipped"}), 400
        tag = f"flip-{sid}"
        # try the live switch first; persist regardless so apply() picks it up
        target = "direct" if to == "direct" else rows[0]["group"]
        ok, detail = clashapi.switch_selector(tag, target)
        dbmod.set_site_set_flip(c, sid, to)
        # Regenerate config so obflip/QUIC rules match the new flip state
        # (takes effect on next kernel restart; hot selector handles immediate traffic)
        try:
            from core.singbox import build_config
            cfg = dbmod.load_app_config(db())
            new_cfg = build_config(cfg, set())
            import os, json
            workdir = os.environ.get("OPENBOX_WORKDIR", "/root/.openbox-zashboard")
            with open(os.path.join(workdir, "config.json"), "w") as f:
                json.dump(new_cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return jsonify({"ok": True, "hot": ok, "detail": detail})

    @app.post("/api/sitesets/<int:sid>/select")
    def siteset_select(sid: int):
        """Policy-card selection (1:1 with the original): pick any group
        for a site set from its card. Hot-switches the flip-<id> selector
        immediately, then persists the choice into the site set itself
        (group/action) and clears the binary flip override, so the next
        config regeneration keeps the same selection as its default.
        The frontend already calls this endpoint; it previously 404'd
        (only /flip existed), so card clicks silently did nothing."""
        from core import clashapi
        d = request.get_json(force=True, silent=True) or {}
        outbound = (d.get("outbound") or "").strip()
        c = db()
        rows = [s for s in dbmod.list_site_sets(c) if s["id"] == sid]
        if not rows:
            return jsonify({"error": "not found"}), 404
        allowed = {"direct", "block"}
        # 只认内核 tag：内置组在 list_groups 里是显示名（可改名），排除
        allowed |= {g["name"] for g in dbmod.list_groups(c)
                    if g.get("enabled", True) and not g.get("builtin")}
        if outbound not in allowed:
            return jsonify({"error": f"unknown outbound: {outbound}"}), 400
        tag = f"flip-{sid}"
        # Live switch first; persist regardless so apply() picks it up.
        ok, detail = clashapi.switch_selector(tag, outbound)
        if outbound == "direct":
            dbmod.update_site_set(c, sid, {"action": "direct"})
        elif outbound == "block":
            dbmod.update_site_set(c, sid, {"action": "reject"})
        else:
            dbmod.update_site_set(c, sid, {"action": "proxy", "group": outbound})
        dbmod.set_site_set_flip(c, sid, "")
        try:
            from core.singbox import build_config
            cfg = dbmod.load_app_config(db())
            new_cfg = build_config(cfg, set())
            import os, json
            workdir = os.environ.get("OPENBOX_WORKDIR", "/root/.openbox-zashboard")
            with open(os.path.join(workdir, "config.json"), "w") as f:
                json.dump(new_cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        row = [s for s in dbmod.list_site_sets(c) if s["id"] == sid][0]
        return jsonify({"ok": True, "hot": ok, "detail": detail, "site_set": row})

    @app.post("/api/openbox/final-select")
    def ob_final_select():
        """Fallback policy card (其他) selection: pick the final outbound
        from the card. Hot-switches the 其他 selector immediately, then
        persists the choice into both final settings (routing_fallback
        drives route.final; final_outbound is read by entry-plan display)
        and regenerates config so the selector default keeps it."""
        from core import clashapi
        d = request.get_json(force=True, silent=True) or {}
        outbound = (d.get("outbound") or "").strip()
        c = db()
        allowed = {"direct", "block"}
        allowed |= {g["name"] for g in dbmod.list_groups(c)
                    if g.get("enabled", True) and not g.get("builtin")}
        if outbound not in allowed:
            return jsonify({"error": f"unknown outbound: {outbound}"}), 400
        ok, detail = clashapi.switch_selector("其他", outbound)
        dbmod.set_setting(c, "routing_fallback", outbound)
        dbmod.set_setting(c, "final_outbound", outbound)
        try:
            from core.singbox import build_config
            cfg = dbmod.load_app_config(db())
            new_cfg = build_config(cfg, set())
            import os, json
            workdir = os.environ.get("OPENBOX_WORKDIR", "/root/.openbox-zashboard")
            with open(os.path.join(workdir, "config.json"), "w") as f:
                json.dump(new_cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return jsonify({"ok": True, "hot": ok, "detail": detail, "final": outbound})

    @app.post("/api/openbox/selection-sync")
    def ob_selection_sync():
        """Reconcile kernel selector choices back to group defaults.

        Native proxy-UI switches go straight to the kernel's Clash API, so
        the panel profile never sees them. This endpoint reads the kernel's
        current `now` per selector group and persists changed values as the
        group's default (only selector groups, only members, only changes).
        Called debounced from the dashboard after a native switch, and
        automatically before every apply (so apply never resets a live
        choice). Never fails the caller: an unreachable kernel yields
        ok=False instead of an error status.
        """
        from core.selectionsync import reconcile
        c = db()
        cfg = dbmod.load_app_config(c)
        return jsonify(reconcile(c, cfg))

    # ---- component upgrade ----
    @app.get("/api/upgrade/status")
    def upgrade_status():
        from core.service import manager_from_env
        import glob as _glob
        m = manager_from_env()
        geos = sorted(_glob.glob(os.path.expanduser("~/.openbox-oss/geoip*.dat")) +
                      _glob.glob(os.path.expanduser("~/.openbox-oss/geosite*.dat")))
        return jsonify({
            "panel": VERSION,
            "singbox": m.version(),
            "singbox_running": m.status().running if hasattr(m.status(), "running") else False,
            "geo_files": [os.path.basename(g) for g in geos],
        })

    @app.get("/api/upgrade/check")
    def upgrade_check():
        import urllib.request as _url
        try:
            req = _url.Request("https://api.github.com/repos/SagerNet/sing-box/releases/latest",
                               headers={"User-Agent": "openbox-oss", "Accept": "application/vnd.github+json"})
            with _url.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            return jsonify({"latest": data.get("tag_name", ""), "name": data.get("name", ""),
                            "published_at": data.get("published_at", "")})
        except Exception as e:
            return jsonify({"error": f"check failed: {e}"}), 502

    @app.post("/api/upgrade/run")
    def upgrade_run():
        import subprocess as _sp
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "scripts", "upgrade.sh")
        logf = "/tmp/openbox-oss-upgrade.log"
        if not os.path.isfile(script):
            return jsonify({"error": "upgrade script not found"}), 404
        with open(logf, "ab") as lf:
            _sp.Popen(["bash", script], stdout=lf, stderr=_sp.STDOUT,
                      start_new_session=True)
        return jsonify({"ok": True, "log": logf})

    @app.get("/api/upgrade/log")
    def upgrade_log():
        try:
            with open("/tmp/openbox-oss-upgrade.log", "rb") as f:
                f.seek(max(0, os.path.getsize("/tmp/openbox-oss-upgrade.log") - 20000))
                return jsonify({"log": f.read().decode("utf-8", "replace")})
        except FileNotFoundError:
            return jsonify({"log": ""})

    # ---- panel self-update (update_auto / update_hour / update_channel /
    #        update_check_channel / update_days settings) ----
    @app.get("/api/panel/update/status")
    def panel_update_status():
        from core import selfupdate as _su
        c = db()
        res = _su.last_result(c)
        return jsonify({
            "update_auto": dbmod.get_setting(c, "update_auto", "0"),
            "update_hour": dbmod.get_setting(c, "update_hour", "4"),
            "update_channel": dbmod.get_setting(c, "update_channel", "auto"),
            "update_check_channel": dbmod.get_setting(c, "update_check_channel", "mirror"),
            "update_days": dbmod.get_setting(c, "update_days", "1"),
            "update_last_check": dbmod.get_setting(c, "update_last_check", ""),
            "last_result": res,
            "local_commit": _su.local_head(),
            "panel_version": VERSION,
            # 进行中的更新（对标原版 update/status：running 只认 pid 存活）
            "run": _su.read_status(),
        })

    @app.post("/api/panel/update/check")
    def panel_update_check():
        from core import selfupdate as _su
        c = db()
        result = _su.check_for_update(c)
        return jsonify(result)

    @app.post("/api/panel/update/apply")
    def panel_update_apply():
        from core import selfupdate as _su
        c = db()
        # 已有一次更新在进行中时拒绝重入（对标原版 run 的 409）
        if _su.read_status()["running"]:
            return jsonify({"error": "update already in progress"}), 409
        res = _su.last_result(c)
        if not res.get("available"):
            return jsonify({"error": "no update available (run a check first)"}), 409
        ref = res.get("ref") or f"refs/heads/{_su.current_branch()}"
        logf = _su.apply_update_async(ref)
        return jsonify({"ok": True, "ref": ref, "log": logf})

    @app.post("/api/panel/update/cancel")
    def panel_update_cancel():
        from core import selfupdate as _su
        return jsonify(_su.cancel_update())

    @app.get("/api/panel/update/notes")
    def panel_update_notes():
        from core import selfupdate as _su
        c = db()
        return jsonify({"commits": _su.recent_commits(20),
                        "pending": _su.last_result(c)})

    @app.get("/api/panel/update/log")
    def panel_update_log():
        try:
            with open("/tmp/openbox-oss-selfupdate.log", "rb") as f:
                f.seek(max(0, os.path.getsize("/tmp/openbox-oss-selfupdate.log") - 20000))
                return jsonify({"log": f.read().decode("utf-8", "replace")})
        except FileNotFoundError:
            return jsonify({"log": ""})

    # ---- openbox dashboard config (for the zashboard-based UI auto-connect) ----
    @app.get("/api/openbox/clash-config")
    def openbox_clash_config():
        cfg = dbmod.load_app_config(db())
        return jsonify({"port": cfg.clash_api_port,
                        "secret": cfg.clash_api_secret,
                        "listen": cfg.clash_api_listen})

    @app.get("/api/openbox/clash-proxies")
    def openbox_clash_proxies():
        """代理页用：经后端转发 clash API 的 /proxies，附带延迟与存活信息。"""
        import urllib.request
        cfg = dbmod.load_app_config(db())
        port = cfg.clash_api_port or 9090
        secret = cfg.clash_api_secret or ""
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/proxies")
            if secret:
                req.add_header("Authorization", f"Bearer {secret}")
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
        except Exception as e:
            return jsonify({"error": f"clash api failed: {e}"}), 502
        # 取延迟信息
        delays = {}
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/proxies")
            if secret:
                req.add_header("Authorization", f"Bearer {secret}")
            # 用 /proxies 的 history 或单独查延迟
        except Exception:
            pass
        return jsonify({"proxies": data.get("proxies", {})})

    @app.get("/api/openbox/clash-connections")
    def openbox_clash_connections():
        """连接页用：经后端转发 clash API 的 /connections 原始格式（绕过浏览器 WebSocket 问题）。"""
        import urllib.request
        cfg = dbmod.load_app_config(db())
        port = cfg.clash_api_port or 9090
        secret = cfg.clash_api_secret or ""
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/connections")
            if secret:
                req.add_header("Authorization", f"Bearer {secret}")
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": f"clash api failed: {e}", "connections": []}), 502

    @app.get("/api/openbox/clash-logs")
    def openbox_clash_logs():
        """日志页用：读取 sing-box 日志文件（轮询，绕过浏览器 WebSocket 问题）。"""
        import os, re
        level = request.args.get("level", "info")
        try:
            log_path = os.path.join(os.environ.get("OPENBOX_WORKDIR", "/root/.openbox-zashboard"), "sing-box.log")
            if not os.path.isfile(log_path):
                return jsonify({"logs": []})
            with open(log_path, 'r', errors='ignore') as f:
                lines = f.readlines()[-100:]
            out = []
            # 去除 ANSI 颜色码
            ansi = re.compile(r'\x1b\[[0-9;]*m')
            for line in lines:
                line = ansi.sub('', line).strip()
                if not line:
                    continue
                # 解析级别：WARN/ERROR/INFO/DEBUG/TRACE
                ltype = "info"
                for lv in ["ERROR", "WARN", "INFO", "DEBUG", "TRACE"]:
                    if lv in line[:20]:
                        ltype = lv.lower()
                        break
                # 按 level 过滤
                if level != "debug" and ltype in ("debug", "trace"):
                    continue
                out.append({"type": ltype, "payload": line[-300:]})
            return jsonify({"logs": out[-50:]})
        except Exception as e:
            return jsonify({"error": str(e), "logs": []}), 502

    @app.post("/api/openbox/clash-select")
    def openbox_clash_select():
        """代理页用：切换指定分组的当前节点。"""
        import urllib.request
        d = request.get_json(force=True) or {}
        group, name = d.get("group"), d.get("name")
        if not group or not name:
            return jsonify({"error": "group and name required"}), 400
        cfg = dbmod.load_app_config(db())
        port = cfg.clash_api_port or 9090
        secret = cfg.clash_api_secret or ""
        try:
            payload = json.dumps({"name": name}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/proxies/{urllib.parse.quote(group)}",
                data=payload, method="PUT",
                headers={"Content-Type": "application/json"})
            if secret:
                req.add_header("Authorization", f"Bearer {secret}")
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
        except Exception as e:
            return jsonify({"error": f"select failed: {e}"}), 502
        return jsonify({"ok": True})

    # ---- legacy frontend (pre-zashboard UI, kept as fallback) ----
    @app.get("/legacy", defaults={"path": ""})
    @app.get("/legacy/<path:path>")
    def legacy_frontend(path: str):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        full = os.path.join(LEGACY_FRONTEND_DIR, path)
        if path and os.path.isfile(full):
            return send_from_directory(LEGACY_FRONTEND_DIR, path)
        return send_from_directory(LEGACY_FRONTEND_DIR, "index.html")

    # ---- frontend (Vue build output) ----
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        full = os.path.join(FRONTEND_DIR, path)
        if path and os.path.isfile(full):
            resp = send_from_directory(FRONTEND_DIR, path)
            # JS/CSS 带 content hash，可长期缓存；index.html 永不缓存
            if path.endswith(('.js', '.css')):
                resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            return resp
        resp = send_from_directory(FRONTEND_DIR, "index.html")
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp

    # background jobs: subscription auto-update, DNS filter auto-update
    if db_path != ":memory:":
        from core.scheduler import start_scheduler
        start_scheduler(_dsn, _uri)

    return app
