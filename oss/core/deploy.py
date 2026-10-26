"""Unified deploy pipeline (v7 #22 POST /deploy 对照，Debian 适配）.

One entry point for a full deploy, replacing the previous scatter of
apply + start + verify calls for the "ship the DB as the live config"
operation:

    preflight (selection reconcile, non-blocking)
      -> rulesets (24h TTL refresh; missing sets are skipped with a
         warning, exactly like apply — see below)
      -> validate (build + sing-box check)
      -> conflict (conflict gate)
      -> start (atomic write + restart/start)
      -> verify (startverify: the kernel really came up)

Single-flight: one module-level lock, held for the whole synchronous
run. A second concurrent deploy is REJECTED with 500 {error} — the
original's semantics (a held lock rejects and express forwards it as
500 {error}), not 409 and not queued. There is no cancel endpoint:
nothing is queued, so there is nothing to cancel.

Status mapping (Ny table, original): ok -> 200, conflict/validate/
cancelled -> 409, rulesets -> 503, start/verify/error -> 500, unknown
stage -> 500. The body is never wrapped: the pipeline's own result
dict is the response body.

Deliberate differences from /api/config/apply and /api/service/start:
- Full path only. Hot/auto modes stay on /api/config/apply; the
  pipeline is the "ship it" operation, not the incremental one.
- Verify failure -> 500 (Ny), NOT 409. /api/service/start keeps its
  409 because deploy scripts and the frontend rely on it.
- Rulesets: DELIBERATE deviation from the original's 503-on-missing.
  Our geodata layer's contract (v6 #14, and build_and_validate's
  "a missing geodata file can never break validation") is
  degrade-and-skip, and a fresh panel's DEFAULT site sets already
  reference 23 sets: a hard fail would make the first deploy 503
  whenever the CDN is unreachable, bricking the very operation the
  pipeline exists to provide. So the stage refreshes, records the
  missing list in the result (visible, not silent), and continues.
  The 503 mapping stays in the table for the stage's contract, but
  this pipeline never emits it today.
- The last outcome is persisted to the "openbox_deploy_state"
  setting (GET /api/openbox/deploy/state reads it, never fails).
  On success the pipeline additionally updates "applied_rev" and
  "deploy_state" so the existing kernel-page stale flag and
  deploy-state poll keep working after a pipeline deploy.
- On success the result carries "dns_upstream_routes" (v8 #33):
  one row per proxy DNS upstream traced through the routing oracle
  (wan/host-supplied rows answer direct without a trace; a failed
  trace is an error row, never a failed deploy). Deliberate
  record-only scope: the original also feeds these rows back into
  the config as dns-proxy detours (pi), but our build already sets
  the detour (所有-自动, or direct outside the region) — rewriting
  it to a traced leaf would pin proxy DNS to one node and drop the
  urltest selection. Detour rewriting is a separate decision.
"""

from __future__ import annotations

import json
import threading
import time

_DEPLOY_LOCK = threading.Lock()
STATE_SETTING = "openbox_deploy_state"


class DeployBusy(RuntimeError):
    """Raised when another deploy already holds the lock."""


def deploy_status(result: dict) -> int:
    """Map a pipeline result to its HTTP status (Ny table)."""
    if result.get("ok") or result.get("stage") == "ok":
        return 200
    return {
        "conflict": 409,
        "validate": 409,
        "cancelled": 409,
        "rulesets": 503,
        "start": 500,
        "verify": 500,
        "error": 500,
    }.get(result.get("stage"), 500)


def _fail(stage: str, error: str, **extra) -> dict:
    d = {"ok": False, "stage": stage, "error": error}
    d.update(extra)
    return d


# ---------------------------------------------------------------- DNS upstreams

_DEFAULT_UPSTREAM_PORTS = {"udp": 53, "tcp": 53, "tls": 853,
                           "https": 443, "quic": 443}


def parse_proxy_upstreams(proxy_dns: str) -> list[dict]:
    """Parse cfg.dns.proxy_dns into [{server, port, protocol, wan}].

    Mirrors _dns_servers' splitting (comma-separated, per-entry label
    stripping) except that "wan" collapses to a single untraceable row:
    the host's own resolver goes direct by definition and cannot be
    traced through the oracle. Identical triples dedupe, config order
    kept. Returns [] when nothing is configured.
    """
    from core.singbox import _strip_upstream_label
    import ipaddress as _ip

    rows: list[dict] = []
    seen: set[tuple] = set()

    def _emit(row: dict) -> None:
        key = (row["server"], row["port"], row["protocol"])
        if key not in seen:
            seen.add(key)
            rows.append(row)

    for entry in (proxy_dns or "").split(","):
        entry = _strip_upstream_label(entry)
        if not entry:
            continue
        if entry.lower() == "wan":
            _emit({"server": "wan", "port": 53, "protocol": "udp",
                   "wan": True})
            continue
        protocol = "udp"
        rest = entry
        if "://" in entry:
            scheme, rest = entry.split("://", 1)
            scheme = scheme.lower()
            if scheme == "dhcp":
                # DHCP-provided resolver: host-supplied, not a literal.
                _emit({"server": entry, "port": 53, "protocol": "dhcp",
                       "wan": True})
                continue
            if scheme not in _DEFAULT_UPSTREAM_PORTS:
                _emit({"server": entry, "port": 53, "protocol": scheme,
                       "wan": False})
                continue
            protocol = scheme
        server, port = rest, _DEFAULT_UPSTREAM_PORTS[protocol]
        if rest.startswith("["):
            # [IPv6] or [IPv6]:port
            import re as _re
            m = _re.match(r"^\[([^\]]+)\](?::(\d+))?$", rest)
            if m:
                server = m.group(1)
                if m.group(2):
                    port = int(m.group(2))
        else:
            try:
                _ip.ip_address(rest)
            except ValueError:
                if rest.count(":") == 1:
                    host, port_s = rest.rsplit(":", 1)
                    if port_s.isdigit():
                        server, port = host, int(port_s)
        _emit({"server": server, "port": port, "protocol": protocol,
               "wan": False})
    return rows


def dns_upstream_routes(cfg, proxies=None, predict_fn=None) -> list[dict]:
    """Trace each proxy DNS upstream through the routing oracle.

    Returns one row per upstream, in config order:
    {server, port, protocol, outbound, reject, owner, chain, ruleIndex,
    assumptions} for traced rows; {server, port, protocol, error} when
    the trace itself fails; and the wan shape (outbound direct,
    wan: True) for host-supplied resolvers. predict_fn, when given,
    replaces the oracle: predict_fn(server, port, network) -> a
    route_oracle.predict-shaped dict (test seam). Never raises for a
    bad row — a failed trace is a row, not a failed deploy.
    """
    rows: list[dict] = []
    for spec in parse_proxy_upstreams(getattr(
            getattr(cfg, "dns", None), "proxy_dns", "") or ""):
        base = {"server": spec["server"], "port": spec["port"],
                "protocol": spec["protocol"]}
        if spec["wan"]:
            rows.append({**base, "outbound": "direct", "reject": False,
                         "owner": None, "chain": [], "ruleIndex": None,
                         "assumptions": [], "wan": True})
            continue
        network = "udp" if spec["protocol"] == "udp" else "tcp"
        try:
            if predict_fn is not None:
                res = predict_fn(spec["server"], spec["port"], network)
            else:
                from core.route_oracle import predict

                res = predict(cfg, spec["server"], port=spec["port"],
                              network=network, proxies=proxies)
        except Exception as e:
            rows.append({**base, "error": str(e)})
            continue
        matched = res.get("matched") or {}
        final = res.get("final_outbound") or ""
        reject = matched.get("action") == "reject" or final == "block"
        rows.append({
            **base,
            "outbound": "" if reject else final,
            "reject": reject,
            "owner": matched.get("owner"),
            "chain": res.get("chain") or [],
            "ruleIndex": matched.get("rule_index"),
            "assumptions": res.get("assumptions") or [],
        })
    return rows


def _upstream_routes(conn, hooks: dict) -> list[dict]:
    """Best-effort upstream table for a deploy result. Never raises:
    a failed table is [] rather than a failed deploy."""
    try:
        from panel import db as dbmod

        # Same table deploy emits: without blocked domains the oracle
        # numbers rules on a cf-less table and ruleIndex drifts from the
        # deployed file (cf moved before the split rules in item 5).
        cfg = dbmod.load_app_config(conn, with_blocked_domains=True)
        if "upstream_proxies" in hooks:
            proxies = hooks["upstream_proxies"]
        else:
            proxies = None
            try:
                from core.clashapi import get_proxies

                ok, data = get_proxies()
                if ok and isinstance(data, dict):
                    proxies = data.get("proxies")
            except Exception:
                proxies = None
        return dns_upstream_routes(
            cfg, proxies=proxies,
            predict_fn=hooks.get("upstream_predict"))
    except Exception:
        return []


def _reconcile_before_build(conn) -> None:
    """Best-effort selection sync before building (mirrors
    apply._sync_selection_before_build: a deploy never resets a live
    selector choice back to members[0]). Never raises."""
    try:
        from core.selectionsync import reconcile
        from panel import db as dbmod

        reconcile(conn, dbmod.load_app_config(conn))
    except Exception:
        pass


def _ruleset_stage(conn, hooks: dict) -> tuple[list[str], dict]:
    """Refresh referenced .srs rule sets (v6 #14 semantics).

    Returns (missing, detail). Per-file failures never raise: a stale
    file that cannot be re-downloaded is kept as-is; only a file
    missing entirely lands in missing. A whole-stage failure falls
    back to ensure() (download missing only), mirroring
    build_and_validate. hooks may override "referenced",
    "refresh_names" and "ensure" (test seams)."""
    from core import geodata as _gd

    names = hooks.get("referenced")
    if names is None:
        from panel import db as dbmod

        names = _gd.referenced_rule_sets(dbmod.load_app_config(conn))
    if not names:
        return [], {"referenced": 0}
    try:
        refresh = hooks.get("refresh_names") or _gd.refresh_names
        res = refresh(conn, names)
        detail = {
            "referenced": len(names),
            "reused": len(res.get("reused", [])),
            "downloaded": len(res.get("downloaded", [])),
            "kept_old": len(res.get("kept_old", [])),
        }
        return res["missing"], detail
    except Exception:
        ensure = hooks.get("ensure") or _gd.ensure
        _ok, missing = ensure(names)
        return missing, {"referenced": len(names), "fallback": "ensure"}


def _run(conn, manager, hooks: dict) -> dict:
    from core.apply import _atomic_write_json, build_and_validate
    from core.conflicts import ConflictError, detect_conflicts
    from core import startverify as _sv

    _reconcile_before_build(conn)

    missing, rulesets = _ruleset_stage(conn, hooks)
    # Degrade-and-skip (apply-consistent): the missing list stays
    # visible in the result; it never blocks the deploy.
    ctx: dict = {"rulesets": rulesets}
    if missing:
        ctx["rulesets_missing"] = missing
        ctx["warning"] = f"规则集缺失，已跳过：{', '.join(missing)}"

    cfg, ok, msg = build_and_validate(conn, manager)
    if not ok:
        from core.badnodes import locate_from_db

        extra: dict = {"validation": msg}
        try:
            bad = locate_from_db(msg, cfg, conn)
        except Exception:
            bad = None
        if bad:
            extra["bad_node"] = bad
        return _fail("validate", f"config validation failed: {msg}",
                     **extra, **ctx)

    detect = hooks.get("detect_conflicts") or detect_conflicts
    conflicts = detect(manager)
    if conflicts:
        return _fail("conflict", "内核冲突，拒绝部署",
                     conflicts=conflicts, **ctx)

    try:
        _atomic_write_json(manager.config_path, cfg)
    except OSError as e:
        return _fail("start", f"写配置失败：{e}", **ctx)

    if not manager.is_installed():
        # Mirrors apply_config: config written, nothing to (re)start.
        return {
            "ok": True, "stage": "ok",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "service": manager.to_dict(),
            "outbounds": len(cfg.get("outbounds", [])),
            "route_rules": len(cfg.get("route", {}).get("rules", [])),
            "validation": msg,
            "note": "sing-box 未安装，仅写入配置",
            "dns_upstream_routes": _upstream_routes(conn, hooks),
            **ctx,
        }

    before = None
    try:
        running = manager.status().running
        before = _sv.snapshot_log(manager.log_path)
        if running:
            manager.restart()
        else:
            manager.start()
    except ConflictError as e:
        return _fail("conflict", str(e), conflicts=e.conflicts, **ctx)
    except Exception as e:
        return _fail("start", str(e), **ctx)

    verify = hooks.get("verify_start") or _sv.verify_start
    ver = verify(manager, before)
    if ver.get("state") == "failed":
        return _fail("verify", ver.get("message", "内核未能跑起来"),
                     verify=ver, **ctx)

    return {
        "ok": True, "stage": "ok",
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "service": manager.to_dict(),
        "outbounds": len(cfg.get("outbounds", [])),
        "route_rules": len(cfg.get("route", {}).get("rules", [])),
        "validation": msg, "verify": ver,
        "dns_upstream_routes": _upstream_routes(conn, hooks),
        **ctx,
    }


def run_deploy(conn, manager, hooks: dict | None = None) -> dict:
    """Run the full pipeline under the single-flight lock.

    Raises DeployBusy when another deploy is running. Persists the
    outcome to the openbox_deploy_state setting (best effort; a
    persistence failure never changes the result)."""
    if not _DEPLOY_LOCK.acquire(blocking=False):
        raise DeployBusy("另一个部署正在进行")
    try:
        result = _run(conn, manager, hooks or {})
        try:
            from panel.db import set_setting

            set_setting(conn, STATE_SETTING,
                        json.dumps(result, ensure_ascii=False))
        except Exception:
            pass
        return result
    finally:
        _DEPLOY_LOCK.release()
