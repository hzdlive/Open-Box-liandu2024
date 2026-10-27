"""One-click diagnostics support bundle: GET /api/openbox/diagnostics.

Shape mirrors the publicly observable response of the original panel's
diagnostics endpoint. The top-level keys and their types were verified
against the third-party contract's live-captured response shapes
(``panel-contract/response-shapes.json``, captured against a live panel):
``format, generatedAt, dnsPort53, kernel{config, configMeta, flip,
nftTables, processes, status}, lastDeploy, logs, settings (11-field
whitelist), system, versions``.

Collection rules (same source):
- Probes run in parallel. A probe failure is rendered as TEXT for string
  fields (an empty list for array fields, a neutral default for other
  types); only an assembly failure answers 500 ``{"message": ...}``.
- Desensitization order: secrets (passwords / uuids / tokens / keys,
  longest first) are replaced BEFORE hostnames, so a secret that
  contains a hostname cannot survive host scrubbing.
- Panel-side deploy state (``lastDeploy``) and kernel-side config meta
  (``kernel.configMeta``) are different sources and are never mixed:
  the former comes from the ``openbox_deploy_state`` setting, the latter
  from the live ``config.json`` plus deploy metadata.

Honest divergences (values the contract does not establish, because its
capture truncated them or left them empty):
- ``format`` is rendered as ``"json"``: the bundle is a JSON document.
  The original's exact value was not verifiable without a live
  original-panel login; treat this as an inference, not a measurement.
- ``dnsPort53`` items are ``"addr:port"`` strings parsed from ``ss``;
  the capture's array was empty, so the item shape is inferred.
- ``system.disk`` / ``memAvailable`` / ``memTotal`` are human-readable
  strings rendered from ``df`` / ``/proc/meminfo``; the capture only
  fixes their types.
- ``versions.builtAt`` / ``versions.node`` are empty strings: this panel
  tracks no build timestamp and runs on Python, not Node.
- ``kernel.flip`` / parts of ``kernel.configMeta`` / ``settings`` map
  our closest equivalents (site-set flip overrides, entry-bypass mode,
  deploy metadata); where we track nothing, the field is an honest
  empty (``""``, ``[]``) rather than an invented value.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform as _platform
import re
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from core.service import PANEL_VERSION

_SECRET_KEYS = {"password", "uuid", "token", "secret", "private_key",
                "presharedkey", "psk", "key"}


def _setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    except sqlite3.Error:
        return default


def _table_rows(conn: sqlite3.Connection, sql: str) -> list:
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.Error:
        return []


def _run(cmd: list[str], timeout: int = 10) -> str:
    """Run a probe command; return stdout, or failure rendered as text."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip()
            return f"command failed ({r.returncode}): {err}" if err \
                else f"command failed ({r.returncode})"
        return r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"command failed: {e}"


def _tail(path: str | None, n: int = 120) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            step, data = 8192, b""
            while len(data.splitlines()) <= n and size > 0:
                step = min(step, size)
                size -= step
                f.seek(size)
                data = f.read() + data
        return [l.decode("utf-8", "replace") for l in data.splitlines()[-n:]]
    except OSError:
        return []


def _human_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


def _meminfo() -> dict:
    info: dict = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition(":")
                k = k.strip()
                if k in ("MemTotal", "MemAvailable"):
                    info[k] = int(v.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    return info


def _uptime_seconds() -> int:
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            for line in f:
                if line.startswith("btime "):
                    return max(0, int(time.time()) - int(line.split()[1]))
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _board() -> str:
    for path in ("/sys/devices/virtual/dmi/id/product_name",
                 "/proc/device-tree/model"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                v = f.read().strip().strip("\x00")
                if v:
                    return v
        except OSError:
            pass
    return ""


def _dns_port53() -> list[str]:
    out = _run(["ss", "-tln"])
    if out.startswith("command failed"):
        return []
    found = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "LISTEN":
            addr = parts[4]
            if addr.endswith(":53"):
                found.add(addr)
    return sorted(found)


def _split_upstream(value: str) -> tuple[str, str, int]:
    """(host, protocol, port) for a dns_direct/dns_proxy setting value."""
    value = (value or "").strip()
    if "://" in value:
        u = urlparse(value)
        proto = u.scheme or "udp"
        port = u.port or {"udp": 53, "tcp": 53, "tls": 853,
                          "https": 443, "quic": 443}.get(proto, 53)
        return u.hostname or "", proto, port
    return value, "udp", 53


def _collect_secrets_and_hosts(conn, config: dict) -> tuple[list[str], set[str]]:
    secrets: set[str] = set()
    for table in ("nodes", "chains"):
        for (params,) in _table_rows(
                conn, f"SELECT params FROM {table}"):
            try:
                p = json.loads(params) if isinstance(params, str) else params
            except (ValueError, TypeError):
                continue
            if isinstance(p, dict):
                for k, v in p.items():
                    if k in _SECRET_KEYS and isinstance(v, str) and len(v) >= 4:
                        secrets.add(v)
    hosts: set[str] = set()
    for (srv,) in _table_rows(conn, "SELECT server FROM nodes"):
        if srv:
            hosts.add(srv)
    for (srv,) in _table_rows(conn, "SELECT server FROM chains"):
        if srv:
            hosts.add(srv)
    for (url,) in _table_rows(
            conn, "SELECT url FROM subscriptions WHERE url IS NOT NULL"):
        if not url:
            continue
        secrets.add(url)  # full URL may embed a token
        try:
            h = urlparse(url).hostname
            if h:
                hosts.add(h)
        except ValueError:
            pass
    for ob in config.get("outbounds", []) if isinstance(config, dict) else []:
        srv = ob.get("server") if isinstance(ob, dict) else None
        if srv:
            hosts.add(srv)
    ordered = sorted(secrets, key=len, reverse=True)
    return ordered, hosts


def _scrub(text: str, secrets: list[str], hosts: set[str]) -> str:
    """Secrets first (raw and JSON-escaped forms), then hostnames."""
    for s in secrets:
        if not s:
            continue
        text = text.replace(s, "[redacted]")
        esc = json.dumps(s)[1:-1]
        if esc != s:
            text = text.replace(esc, "[redacted]")
    for h in sorted(hosts, key=len, reverse=True):
        if h:
            text = text.replace(h, "[host]")
    return text


def _scrub_secrets_only(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if not s:
            continue
        text = text.replace(s, "[redacted]")
        esc = json.dumps(s)[1:-1]
        if esc != s:
            text = text.replace(esc, "[redacted]")
    return text


def _parse_epoch_ms(local_str: str) -> int:
    """Our deploy state's ``at`` is a local-time string; convert to ms."""
    try:
        dt = datetime.datetime.strptime(local_str, "%Y-%m-%d %H:%M:%S")
        return int(dt.astimezone().timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _last_deploy(conn) -> dict:
    raw = _setting(conn, "openbox_deploy_state", "")
    st: dict = {}
    if raw:
        try:
            st = json.loads(raw)
        except ValueError:
            st = {}
    if not isinstance(st, dict):
        st = {}
    bad: list = []
    for c in st.get("conflicts", []) or []:
        bad.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
    if st.get("ok"):
        message = st.get("validation", "") or ""
    else:
        message = st.get("error", "") or ""
    return {
        "at": _parse_epoch_ms(st.get("at", "")),
        "badTags": bad,
        "message": message,
        "stage": st.get("stage", "") or "",
    }


def _failover_list(conn) -> list:
    try:
        from panel import db as dbmod
        cfg = dbmod.load_app_config(conn)
        out = []
        for g in cfg.groups:
            if g.type != "failover":
                continue
            st = dbmod.get_failover_state(conn, g.name)
            out.append({
                "group": g.name,
                "current": (st.get("current_tag") if st else None),
            })
        return out
    except Exception:
        return []


def _config_meta(conn, config: dict, config_path: str,
                 config_bytes: bytes) -> dict:
    dns_filter_lists = []
    try:
        for item in json.loads(_setting(conn, "dns_filter_lists", "[]")):
            if isinstance(item, dict) and item.get("enabled"):
                dns_filter_lists.append(item.get("name", ""))
    except ValueError:
        pass
    dns_mode = _setting(conn, "dns_mode", "dnsmasq")
    tun_in = None
    if isinstance(config, dict):
        for ib in config.get("inbounds", []) or []:
            if isinstance(ib, dict) and ib.get("type") == "tun":
                tun_in = ib
                break
    mtime = ""
    try:
        mtime = datetime.datetime.fromtimestamp(
            os.path.getmtime(config_path),
            tz=datetime.timezone.utc).isoformat()
    except OSError:
        pass
    rewrite_rows = _table_rows(
        conn, "SELECT domain, target FROM dns_rewrite WHERE enabled=1")
    upstream_routes = []
    raw = _setting(conn, "openbox_deploy_state", "")
    if raw:
        try:
            upstream_routes = json.loads(raw).get("dns_upstream_routes", []) or []
        except ValueError:
            pass
    return {
        "autoRedirect": bool(tun_in.get("auto_redirect")) if tun_in else False,
        "buildInputs": {
            "subscriptions": len(_table_rows(conn, "SELECT id FROM subscriptions")),
            "nodes": len(_table_rows(conn, "SELECT id FROM nodes")),
            "siteSets": len(_table_rows(conn, "SELECT id FROM site_sets")),
            "groups": len(_table_rows(conn, "SELECT id FROM groups")),
            "chains": len(_table_rows(conn, "SELECT id FROM chains")),
            "rulesets": len(_table_rows(conn, "SELECT id FROM rulesets")),
            "stateRev": _setting(conn, "state_rev", "0"),
        },
        "dnsFilter": {
            "enabled": _setting(conn, "dns_filter_enabled", "0") == "1",
            "appliedAt": _setting(conn, "dns_filter_applied_at", ""),
            "lists": dns_filter_lists,
        },
        "dnsMode": dns_mode,
        "dnsPolicyClasses": {
            "direct": _setting(conn, "dns_direct", ""),
            "proxy": _setting(conn, "dns_proxy", ""),
        },
        "dnsPolicyMembers": upstream_routes,
        "dnsRewrite": [{"domain": d, "target": t} for d, t in rewrite_rows],
        "dnsRuleOwners": [d for d, _t in rewrite_rows],
        "dnsUpstreamRoutes": upstream_routes,
        "dnsmasqQueryLog": {"enabled": dns_mode == "dnsmasq"},
        "failover": _failover_list(conn),
        "firstLayer": {
            "entryMode": _setting(conn, "entry_mode", "whitelist"),
        },
        "flip": _flip(conn),
        "generatedAt": mtime,
        "hotAppliedAt": "",
        "routingHash": hashlib.sha256(config_bytes).hexdigest()
        if config_bytes else "",
    }


def _flip(conn) -> dict:
    flipped = [name for (name,) in _table_rows(
        conn, "SELECT name FROM site_sets WHERE flip != ''")]
    return {
        "bypass": flipped,
        "bypassMode": _setting(conn, "bypass_ports_mode", "black"),
        "entryMode": _setting(conn, "entry_mode", "whitelist"),
        "flags": [],
        "flippedAt": "",
        "mismatched": [],
        "mode": _setting(conn, "entry_mode", "whitelist"),
        "need": [],
    }


def _settings(conn, tun_auto: bool = False) -> dict:
    dns_direct = _setting(conn, "dns_direct", "")
    dns_proxy = _setting(conn, "dns_proxy", "")
    d_host, d_proto, d_port = _split_upstream(dns_direct)
    p_host, p_proto, p_port = _split_upstream(dns_proxy)
    front = _table_rows(
        conn, "SELECT id, domain, rtype, target, enabled, position "
        "FROM front_rules ORDER BY position, id")
    policies = [{"id": i, "domain": d, "rtype": r, "target": t,
                 "enabled": bool(e), "position": pos}
                for i, d, r, t, e, pos in front]
    return {
        "bypassPorts": _setting(conn, "bypass_ports", ""),
        "bypassPortsMode": _setting(conn, "bypass_ports_mode", "black"),
        "bypassPortsWhitelist": _setting(conn, "bypass_ports_white", ""),
        "clientRoutes": [],
        "directBypass": _setting(conn, "direct_bypass_kernel", "1") == "1",
        "directForNodes": _setting(conn, "sub_node_direct", "0") == "1",
        "dns": {
            "direct": d_host,
            "directExtras": [],
            "directPort": d_port,
            "directProtocol": d_proto,
            "fakeIpForProxy": _setting(conn, "dns_fakeip", "0") == "1",
            "filter": {
                "enabled": _setting(conn, "dns_filter_enabled", "0") == "1",
                "appliedAt": _setting(conn, "dns_filter_applied_at", ""),
            },
            "mode": _setting(conn, "dns_mode", "dnsmasq"),
            "proxy": p_host,
            "proxyExtras": [],
            "proxyPort": p_port,
            "proxyProtocol": p_proto,
            "region": _setting(conn, "dns_region", "auto"),
            "rewrite": {
                "enabled": bool(_table_rows(
                    conn, "SELECT id FROM dns_rewrite WHERE enabled=1 LIMIT 1")),
                "count": len(_table_rows(conn, "SELECT id FROM dns_rewrite")),
            },
            "split": _setting(conn, "dns_split", "1") == "1",
        },
        "ipv6": True,
        "rejectQuic": _setting(conn, "quic_block", "1") == "1",
        "routing": {
            "custom": {},
            "fallbackDefault": _setting(conn, "routing_fallback", "direct"),
            "fallbackIcon": "",
            "fallbackName": "",
            "policies": policies,
        },
        "tun": {
            "autoRedirect": tun_auto,
            "mtu": int(_setting(conn, "tun_mtu", "9000") or 9000),
            "stack": _setting(conn, "tun_stack", "mixed"),
            "tcpMss": int(_setting(conn, "mss_clamp", "0") or 0),
        },
    }


def collect(conn: sqlite3.Connection, manager, workdir: str) -> dict:
    """Build the support bundle. Raises only on assembly failure."""
    svc = manager.to_dict()
    config_path = os.path.join(workdir, "config.json") if workdir else ""
    config_bytes = b""
    config: dict = {}
    if config_path and os.path.isfile(config_path):
        with open(config_path, "rb") as f:
            config_bytes = f.read()
        try:
            config = json.loads(config_bytes)
        except ValueError:
            config = {}
    if not isinstance(config, dict):
        config = {}

    secrets, hosts = _collect_secrets_and_hosts(conn, config)
    scrubbed_config = config
    if config:
        scrubbed_text = _scrub(json.dumps(config, ensure_ascii=False),
                               secrets, hosts)
        try:
            scrubbed_config = json.loads(scrubbed_text)
        except ValueError:
            scrubbed_config = {}

    last = _last_deploy(conn)
    tun_auto = False
    if isinstance(config, dict):
        for ib in config.get("inbounds", []) or []:
            if isinstance(ib, dict) and ib.get("type") == "tun":
                tun_auto = bool(ib.get("auto_redirect"))
                break

    def _probe(fn):
        try:
            return fn()
        except Exception as e:  # probe failure renders as text, never 500
            return f"probe failed: {e}"

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_nft = ex.submit(_probe, lambda: _run(["nft", "list", "ruleset"]))
        f_ps = ex.submit(_probe, lambda: _ps())
        f_dns53 = ex.submit(_probe, _dns_port53)
        f_disk = ex.submit(
            _probe,
            lambda: _run(["df", "-h", workdir or "/"]).strip().splitlines()[-1])
        f_kernel_log = ex.submit(_probe, lambda: _tail(manager.log_path, 120))
        f_panel_log = ex.submit(
            _probe, lambda: _tail(os.environ.get("OBX_PANEL_LOG", ""), 120))
        nft_tables = f_nft.result()
        processes = f_ps.result()
        dns53 = f_dns53.result()
        disk = f_disk.result()
        kernel_log = f_kernel_log.result()
        panel_log = f_panel_log.result()

    if not isinstance(dns53, list):
        dns53 = []
    kernel_log_text = "\n".join(kernel_log) if isinstance(kernel_log, list) else str(kernel_log)
    panel_log_text = "\n".join(panel_log) if isinstance(panel_log, list) else str(panel_log)
    kernel_log_text = _scrub_secrets_only(kernel_log_text, secrets)
    panel_log_text = _scrub_secrets_only(panel_log_text, secrets)

    mem = _meminfo()
    running = bool(svc.get("running"))
    status = "running" if running else "stopped"
    if running and svc.get("uptime_s") is not None:
        status = f"running (uptime {int(svc['uptime_s'])}s)"

    return {
        "format": "json",
        "generatedAt": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "dnsPort53": dns53,
        "kernel": {
            "config": scrubbed_config,
            "configMeta": _config_meta(conn, config, config_path,
                                       config_bytes),
            "flip": _flip(conn),
            "nftTables": nft_tables if isinstance(nft_tables, str) else str(nft_tables),
            "processes": processes if isinstance(processes, str) else str(processes),
            "status": status,
        },
        "lastDeploy": last,
        "logs": {
            "kernel": kernel_log_text,
            "panel": panel_log_text,
        },
        "settings": _settings(conn, tun_auto),
        "system": {
            "arch": _platform.machine(),
            "board": _board(),
            "conflictingPlugins": [],
            "disk": disk if isinstance(disk, str) else str(disk),
            "memAvailable": _human_bytes(mem["MemAvailable"])
            if "MemAvailable" in mem else "",
            "memTotal": _human_bytes(mem["MemTotal"])
            if "MemTotal" in mem else "",
            "nodePreload": None,
            "tunDevice": os.path.exists("/dev/net/tun"),
            "uptimeSeconds": _uptime_seconds(),
        },
        "versions": {
            "builtAt": "",
            "node": "",
            "openBox": PANEL_VERSION,
            "singBox": svc.get("version") or "",
        },
    }


def _ps() -> str:
    out = _run(["ps", "-eo", "pid,etime,args"])
    if out.startswith("command failed"):
        return out
    lines = [l for l in out.splitlines()
             if "sing-box" in l or "openbox" in l.lower()]
    return "\n".join(lines)
