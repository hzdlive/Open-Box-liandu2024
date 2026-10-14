"""Panel backend API (Flask). Clean-room reimplementation of the publicly
documented management capabilities; no proprietary code involved."""

from __future__ import annotations

import json
import os
import sqlite3

from flask import Flask, jsonify, request, send_from_directory

from core.routing import preview_route
from core.singbox import build_config
from panel import db as dbmod

VERSION = "0.1.0-oss"
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")


def create_app(db_path: str = ":memory:") -> Flask:
    app = Flask(__name__)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    dbmod.init_db(conn)
    app.config["DB"] = conn

    def db() -> sqlite3.Connection:
        return app.config["DB"]

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": getattr(e, "description", "bad request")}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not found"}), 404

    # ---- subscriptions ----
    @app.post("/api/subscriptions")
    def sub_create():
        d = request.get_json(force=True, silent=True) or {}
        if not d.get("name") or not d.get("content"):
            return jsonify({"error": "name and content are required"}), 400
        try:
            sid, n = dbmod.add_subscription(db(), d["name"], d["content"],
                                            d.get("source", "manual"),
                                            d.get("format", "auto"))
        except Exception as e:
            return jsonify({"error": f"parse failed: {e}"}), 400
        return jsonify({"id": sid, "name": d["name"], "node_count": n}), 201

    @app.get("/api/subscriptions")
    def sub_list():
        return jsonify(dbmod.list_subscriptions(db()))

    @app.delete("/api/subscriptions/<int:sid>")
    def sub_delete(sid: int):
        if not dbmod.delete_subscription(db(), sid):
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    # ---- nodes ----
    @app.get("/api/nodes")
    def node_list():
        return jsonify(dbmod.list_nodes(db()))

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

    # ---- node health ----
    @app.get("/api/health")
    def health_list():
        return jsonify(dbmod.list_health(db()))

    @app.post("/api/health/check")
    def health_check():
        from core.health import check_nodes
        d = request.get_json(force=True, silent=True) or {}
        cfg = dbmod.load_app_config(db())
        results = check_nodes(cfg.nodes, timeout=float(d.get("timeout", 5.0)),
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
        return jsonify(_manager().to_dict())

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
        return jsonify({"log": _manager().log_tail(n)})

    @app.post("/api/config/apply")
    def config_apply():
        from core.apply import apply_config
        try:
            return jsonify(apply_config(db(), _manager()))
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 422

    # ---- transparent proxy artifacts (generate-only) ----
    def _tconfig():
        from core.transparent import TransparentConfig
        d = request.args
        return TransparentConfig(
            tproxy_port=int(d.get("tproxy_port", 7893)),
            dns_port=int(d.get("dns_port", 1053)),
            lan_iface=d.get("lan_iface", "br-lan"),
            enable_ipv6=d.get("ipv6", "1") == "1",
        )

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
    @app.post("/api/failover/elect")
    def failover_elect():
        from core.failover import watch_once
        cfg = dbmod.load_app_config(db())
        health = dbmod.list_health(db())
        d = request.get_json(force=True, silent=True) or {}
        api_base = d.get("api_base", f"http://127.0.0.1:{cfg.clash_api_port}")
        secret = d.get("secret", "")
        return jsonify(watch_once(cfg.groups, health, api_base, secret))

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

    # ---- frontend (SPA, no build step) ----
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        if path.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        full = os.path.join(FRONTEND_DIR, path)
        if path and os.path.isfile(full):
            return send_from_directory(FRONTEND_DIR, path)
        return send_from_directory(FRONTEND_DIR, "index.html")

    return app
