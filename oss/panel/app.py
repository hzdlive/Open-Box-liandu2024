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
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")


def create_app(db_path: str = ":memory:") -> Flask:
    import hashlib
    import secrets
    from flask import session
    from werkzeug.security import check_password_hash, generate_password_hash

    app = Flask(__name__)

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
            cur = c.execute(
                "INSERT INTO subscriptions(name, source, urls, url, created_at)"
                " VALUES (?, 'manual', ?, ?, ?)",
                (d["name"], _json.dumps(urls, ensure_ascii=False), urls[0],
                 time.strftime("%Y-%m-%dT%H:%M:%S")))
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
        return jsonify(dbmod.list_subscriptions(db()))

    @app.put("/api/subscriptions/<int:sid>")
    def sub_update(sid: int):
        import json as _json
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        row = c.execute("SELECT id FROM subscriptions WHERE id=?", (sid,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        if "enabled" in d:
            c.execute("UPDATE subscriptions SET enabled=? WHERE id=?",
                      (1 if d["enabled"] else 0, sid))
        if "auto_update_hours" in d:
            try:
                auh = max(0, int(d["auto_update_hours"]))
            except (TypeError, ValueError):
                return jsonify({"error": "auto_update_hours must be an integer >= 0"}), 400
            c.execute("UPDATE subscriptions SET auto_update_hours=? WHERE id=?", (auh, sid))
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
        return jsonify(updated)

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
                                   d.get("node_filter"))
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
        if not share:
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
            r = dbmod.add_manual_nodes(db(), content)
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
            res["outbound"] = cfg.final_outbound
        return jsonify(res)

    # ---- generated sing-box config ----
    @app.get("/api/config")
    def config_get():
        cfg = dbmod.load_app_config(db())
        return jsonify(build_config(cfg))

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
        return jsonify({
            "version": VERSION,
            "subscriptions": len(dbmod.list_subscriptions(c)),
            "nodes": len(dbmod.list_nodes(c)),
            "site_sets": len(dbmod.list_site_sets(c)),
            "groups": len(dbmod.list_groups(c)),
            "chains": len(dbmod.list_chains(c)),
            "rule_sets": len(dbmod.list_rule_sets(c)),
            "singbox": "not-installed",
        })

    # ---- rule sets ----
    @app.get("/api/rulesets")
    def ruleset_list():
        return jsonify(dbmod.list_rule_sets(db()))

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

    @app.put("/api/groups/<int:gid>")
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
        results = check_nodes(nodes, timeout=float(d.get("timeout", 5.0)),
                              max_workers=int(d.get("max_workers", 20)))
        dbmod.save_health(db(), results)
        return jsonify([{"tag": r.tag, "ok": r.ok, "latency_ms": r.latency_ms,
                         "error": r.error, "checked_at": r.checked_at}
                        for r in results])

    # ---- kernel service ----
    def _manager():
        from core.service import manager_from_env
        return manager_from_env()

    @app.get("/api/service")
    def service_status():
        d = _manager().to_dict()
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
        m = _manager()
        try:
            m.start()
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        return jsonify(m.to_dict())

    @app.post("/api/service/stop")
    def service_stop():
        m = _manager()
        m.stop()
        return jsonify(m.to_dict())

    @app.post("/api/service/restart")
    def service_restart():
        m = _manager()
        try:
            m.restart()
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        return jsonify(m.to_dict())

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
        from core.apply import apply_config
        from core.hotapply import hot_apply_config
        mode = (request.args.get("mode") or "auto").lower()
        if mode not in ("auto", "hot", "full"):
            return jsonify({"error": "mode must be auto|hot|full"}), 400
        cfg = dbmod.load_app_config(db())
        api_base = f"http://127.0.0.1:{cfg.clash_api_port}"
        secret = getattr(cfg, "clash_api_secret", "") or ""
        try:
            if mode == "full":
                result = apply_config(db(), _manager())
                result["mode"] = "full"
            else:
                result = hot_apply_config(db(), _manager(), api_base, secret,
                                          force=mode)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 422
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
        direct_bypass = get_setting(c, "direct_bypass_kernel", "0") == "1"
        direct_ipset_domains = []
        if direct_bypass:
            for s in cfg.site_sets:
                if s.action == "direct":
                    direct_ipset_domains.extend(
                        x for x in list(s.domains) + list(s.domain_suffix) if x)
            direct_ipset_domains = sorted(set(direct_ipset_domains))
        return TransparentConfig(
            tproxy_port=int(d.get("tproxy_port", 7893)),
            dns_port=int(d.get("dns_port", 1053)),
            lan_iface=d.get("lan_iface", "br-lan"),
            enable_ipv6=d.get("ipv6", "1") == "1",
            quic_block=cfg.quic_block,
            terminal_bypass=bypass_terms,
            dns_rewrites=rewrites,
            dns_direct_ip=_strip_scheme(cfg.dns.direct_dns),
            dns_proxy_ip=_strip_scheme(cfg.dns.proxy_dns),
            site_domains=site_domains,
            dns_filter_conf=_dns_filter_conf_path(c),
            direct_ipset_domains=direct_ipset_domains,
            bypass_ports=get_setting(c, "bypass_ports", ""),
            bypass_ports_mode=get_setting(c, "bypass_ports_mode", "black"),
        )

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

    # ---- backup / restore ----
    @app.get("/api/backup")
    def backup_export():
        from core.backup import backup_to_json
        return app.response_class(
            backup_to_json(db()), mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=openbox-oss-backup.json"})

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
            "upstream_latency": dbmod._safe_json_loads(
                dbmod.get_setting(c, "dns_upstream_latency", "{}")),
            "rewrites": dbmod.list_dns_rewrites(c),
        })

    @app.put("/api/dns")
    def dns_put():
        d = request.get_json(force=True, silent=True) or {}
        c = db()
        if "mode" in d:
            if d["mode"] not in ("dnsmasq", "firewall", "off"):
                return jsonify({"error": "mode must be dnsmasq|firewall|off"}), 400
            dbmod.set_setting(c, "dns_mode", d["mode"])
        if "region" in d:
            if d["region"] not in ("auto", "cn", "outside"):
                return jsonify({"error": "region must be auto|cn|outside"}), 400
            dbmod.set_setting(c, "dns_region", d["region"])
        for k in ("direct_dns", "proxy_dns"):
            skey = "dns_direct" if k == "direct_dns" else "dns_proxy"
            if k in d and str(d[k]).strip():
                dbmod.set_setting(c, skey, str(d[k]).strip())
        if "fakeip" in d:
            dbmod.set_setting(c, "dns_fakeip", "1" if d["fakeip"] else "0")
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
        try:
            return jsonify(dbmod.add_dns_rewrite(db(), d.get("domain", ""), d.get("target", ""))), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.delete("/api/dns/rewrite/<int:rid>")
    def dns_rewrite_del(rid: int):
        if not dbmod.delete_dns_rewrite(db(), rid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

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
        return jsonify({"ok": True, "lists": clean})

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
        return jsonify(dbmod.terminal_candidates(db()))

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
        return jsonify({"ok": True, "hot": ok, "detail": detail})

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

    # ---- frontend (Vue build output) ----
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        full = os.path.join(FRONTEND_DIR, path)
        if path and os.path.isfile(full):
            return send_from_directory(FRONTEND_DIR, path)
        return send_from_directory(FRONTEND_DIR, "index.html")

    # background jobs: subscription auto-update, DNS filter auto-update
    if db_path != ":memory:":
        from core.scheduler import start_scheduler
        start_scheduler(_dsn, _uri)

    return app
