"""Route-test: "what actually happens when I open this site?" by measurement.

POST /api/openbox/penetration answers by *prediction* (it walks the
config the panel would build). This module answers by *measurement*: it
dials the panel's own mixed inbound, asks it to CONNECT to the target,
optionally completes a TLS handshake, reads the status line and headers
off the raw socket, and then looks in the kernel's /connections for the
connection that carried the flow — so the chain, the matched rule and
the policy owner come from the running kernel rather than from a model
of it. The two answers are allowed to disagree, and that is the point:
a prediction that has drifted from the running config is exactly what
this route exposes.

Adaptations from the reference (v8 #34, Mihomo) to our sing-box stack:

- sing-box reports chains leaf-first (["node", "group", "flip-11"]),
  where Mihomo reports them outermost-first, so the chains are NOT
  reversed here. A reversal would invert the reported exit.
- sing-box's connection entries carry the matched rule as text
  ("rule_set=geosite-youtube => route(JPAC...)" or "final") and an
  (usually empty) rulePayload; there are no share guards to strip, so
  no guard-stripping step and no noDomain flag.
- The DNS half is evaluated against the *deployed* config file (not a
  rebuilt model): a config that was never generated is a 503, not a
  reason to build one. The runtime chain is walked from live Clash
  selection only — no DB fallback, because the deployed file is the
  authority here.
- The probe socket stays open while the poller runs and is closed
  only after the poll settles: a GET whose remote side closes first
  vanishes from /connections within milliseconds, so polling after
  the probe would race the very lookup the route exists to perform.
- Response says `exit` / `exit6` per family, never `reachable`: only
  the first address of each family is probed.

Only `probe_inbound` and `resolve_local` touch the network; both are
injectable, so the suite stays offline.
"""

import ipaddress
import re
import socket
import ssl
import threading
import time

from core.models import AppConfig
from core.route_oracle import (
    FAKEIP_V4,
    FAKEIP_V6,
    Ctx,
    Target,
    _eval_rule,
    parse_target,
)

PROBE_METHODS = ("GET", "HEAD", "TCP", "TLS")
PROBE_TIMEOUT_S = 10.0
PROBE_MAX_HEAD_BYTES = 16_384
# Six backoff tiers between /connections rounds; the first fetch runs
# immediately (round 0, before any delay).
CONNECTIONS_POLL_DELAYS_S = (0.1, 0.2, 0.3, 0.5, 0.8, 1.0)
CONNECTIONS_SETTLE_ROUNDS = 3


class RouteTestError(Exception):
    """An unexpected failure (the route's 500); probe failures are
    results (exit.ok False), not exceptions."""


def normalize_method(method) -> str:
    """None -> GET; anything else is uppercased and must be one of the
    four probe methods."""
    if method is None:
        return "GET"
    m = str(method).strip().upper()
    if m not in PROBE_METHODS:
        raise ValueError("method must be GET, HEAD, TCP or TLS")
    return m


def _read_head(sock, deadline: float) -> bytes:
    """Read until the header terminator, the byte cap, or the deadline
    (socket.timeout propagates to the caller)."""
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < PROBE_MAX_HEAD_BYTES:
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf[:PROBE_MAX_HEAD_BYTES]


def _parse_head(head: bytes):
    """-> (status:int|None, headers:dict lowercased, duplicates joined)."""
    try:
        text = head.decode("latin1")
    except Exception:
        return None, {}
    lines = text.split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        return None, {}
    parts = lines[0].split(" ", 2)
    try:
        status = int(parts[1])
    except (IndexError, ValueError):
        return None, {}
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        headers[name] = f"{headers[name]}, {value}" if name in headers else value
    return status, headers


def detect_challenge(status, headers) -> str:
    """Only Cloudflare's challenge marker, as in the reference."""
    if headers and str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return "cloudflare"
    return ""


def probe_inbound(target: str, *, port: int, secure: bool, connect_to: str,
                  method: str, mixed_host: str, mixed_port: int,
                  timeout: float = PROBE_TIMEOUT_S):
    """One CONNECT probe through the mixed inbound.

    Returns (result, close): result is {ok, status, ms, error?,
    headers?}; close() destroys the socket and must be called only
    after the connections poll settles. Network failures are results
    (ok False with a staged error: "inbound: …" for the dial,
    "proxy: …" for a non-200 CONNECT, "tls: …", "http: …"), never
    raised — the route stays 200 when the probe fails.
    """
    started = time.monotonic()
    deadline = started + timeout
    sock = None

    def close():
        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass

    def fail(stage: str, err) -> tuple[dict, object]:
        return ({"ok": False, "status": None,
                 "ms": int((time.monotonic() - started) * 1000),
                 "error": f"{stage}: {err}"}, close)

    try:
        sock = socket.create_connection(
            (mixed_host, mixed_port),
            timeout=max(0.1, deadline - time.monotonic()))
    except Exception as e:
        return fail("inbound", e)
    host = connect_to or target
    try:
        sock.settimeout(max(0.1, deadline - time.monotonic()))
        sock.sendall(
            f"CONNECT {host}:{port} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n\r\n".encode())
        head = _read_head(sock, deadline)
    except Exception as e:
        return fail("proxy", e)
    status, _ = _parse_head(head)
    if status != 200:
        line = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
        return fail("proxy", line or "connection closed")
    if method == "TCP":
        return ({"ok": True, "status": None,
                 "ms": int((time.monotonic() - started) * 1000)}, close)
    if method == "TLS" or secure:
        try:
            ctx = ssl.create_default_context()
            # Routing is what is measured, not trust: any cert is fine.
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(
                sock,
                server_hostname=target if _is_domain(target) else None)
            sock.settimeout(max(0.1, deadline - time.monotonic()))
        except Exception as e:
            return fail("tls", e)
        if method == "TLS":
            return ({"ok": True, "status": None,
                     "ms": int((time.monotonic() - started) * 1000)}, close)
    try:
        default_port = 443 if secure else 80
        host_hdr = target if port == default_port else f"{target}:{port}"
        sock.sendall(
            f"{method} / HTTP/1.1\r\nHost: {host_hdr}\r\n"
            f"Connection: close\r\n\r\n".encode())
        head = _read_head(sock, deadline)
    except Exception as e:
        return fail("http", e)
    status, headers = _parse_head(head)
    if status is None:
        return fail("http", "no HTTP response")
    return ({"ok": True, "status": status, "headers": headers,
             "ms": int((time.monotonic() - started) * 1000)}, close)


def _is_domain(s: str) -> bool:
    try:
        return parse_target(s).kind == "domain"
    except Exception:
        return False


def resolve_local(target: str):
    """System-resolver lookup. Returns (answers4, answers6, ms) with
    the first address of each family first; raises on failure. No TTL:
    getaddrinfo does not expose one."""
    started = time.monotonic()
    infos = socket.getaddrinfo(target, None, socket.AF_UNSPEC,
                               socket.SOCK_STREAM)
    v4: list[str] = []
    v6: list[str] = []
    for info in infos:
        addr = info[4][0]
        if ":" in addr:
            if addr not in v6:
                v6.append(addr)
        elif addr not in v4:
            v4.append(addr)
    return v4, v6, int((time.monotonic() - started) * 1000)


def _is_fakeip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip in (FAKEIP_V4 if ip.version == 4 else FAKEIP_V6)


def dns_half(deployed: dict, target: str, proxies, geosite_split=None,
             geoip_expand=None) -> dict:
    """Evaluate the deployed config's dns rules for the target.

    First hit wins; unknown rules are skipped with an assumption (the
    kernel may answer differently — the deployed final is what the
    kernel falls back to, so the result stays useful, not wrong).
    """
    dns_cfg = deployed.get("dns") or {}
    rules = dns_cfg.get("rules") or []
    ctx = Ctx(Target("domain", target), network="tcp", ip_version=None,
              resolved_ips=[], fakeip_dns=False, cfg=AppConfig(),
              geosite_split=geosite_split, geoip_expand=geoip_expand)
    assumptions: list[str] = []
    rule_index = None
    for i, rule in enumerate(rules):
        try:
            status, _ = _eval_rule(rule, ctx, dns_mode=True)
        except Exception:
            status = "unknown"
        if status == "hit":
            rule_index = i
            break
        if status == "unknown":
            assumptions.append(f"dns 规则 #{i} 未展开")
    if rule_index is not None:
        tag = (rules[rule_index] or {}).get("server")
    else:
        tag = dns_cfg.get("final")
    server: dict = {"tag": tag}
    for entry in dns_cfg.get("servers") or []:
        if isinstance(entry, dict) and entry.get("tag") == tag:
            if entry.get("detour"):
                server["detour"] = entry["detour"]
            break
    out: dict = {"ruleIndex": rule_index, "server": server,
                 "viaProxy": tag == "dns-proxy"}
    if assumptions:
        out["assumptions"] = assumptions
    if server.get("detour") and proxies is not None:
        chain = live_chain(server["detour"], proxies)
        out["runtimeChain"] = chain
        out["runtimeLeaf"] = chain[-1]
    return out


def live_chain(tag: str, proxies: dict) -> list[str]:
    """Walk live Clash selection from a tag: follow each group's
    current `now` until a leaf, a missing link, or a cycle."""
    chain = [tag]
    cur = tag
    while len(chain) < 16:
        entry = (proxies or {}).get(cur)
        nxt = entry.get("now") if isinstance(entry, dict) else None
        if not nxt or nxt in chain:
            break
        chain.append(nxt)
        cur = nxt
    return chain


def parse_rule_text(text: str):
    """Parse a kernel rule text into (conditions, outbound).

    "rule_set=geosite-youtube => route(X)" -> ({"rule_set":
    ["geosite-youtube"]}, "X"); "final" -> ({"final": True}, None).
    Unparseable left-hand sides yield ({}, outbound) so attribution
    can still fall back to the outbound alone.
    """
    if not text:
        return {}, None
    if text.strip() == "final":
        return {"final": True}, None
    m = re.match(r"^(.*) => route\((.*)\)$", text.strip())
    if not m:
        return {}, None
    lhs, outbound = m.group(1), m.group(2)
    conds: dict[str, list[str]] = {}
    i = 0
    while i < len(lhs):
        m2 = re.match(r"([A-Za-z_]+)=", lhs[i:])
        if not m2:
            break
        key = m2.group(1)
        i += len(m2.group(0))
        if i < len(lhs) and lhs[i] == "[":
            j = lhs.find("]", i)
            if j < 0:
                break
            conds[key] = lhs[i + 1:j].split()
            i = j + 1
        else:
            j = lhs.find(" ", i)
            if j < 0:
                j = len(lhs)
            conds[key] = [lhs[i:j]]
            i = j
        while i < len(lhs) and lhs[i] == " ":
            i += 1
    return conds, outbound


def _owner_for_outbound(outbound: str, deployed: dict,
                        flip_map: dict) -> dict:
    if outbound in (flip_map or {}):
        return {"kind": "siteset", "name": flip_map[outbound]}
    if outbound == "direct":
        return {"kind": "direct", "name": "direct"}
    if outbound == "block":
        return {"kind": "block", "name": "block"}
    for entry in deployed.get("outbounds") or []:
        if isinstance(entry, dict) and entry.get("tag") == outbound:
            t = entry.get("type", "")
            if t in ("selector", "urltest", "loadbalance", "smart",
                     "failover"):
                return {"kind": "group", "name": outbound}
            return {"kind": "node", "name": outbound}
    return {"kind": "outbound", "name": outbound}


def attribute_owner(rule_text: str, deployed: dict, flip_map: dict):
    """Attribute a kernel rule text to a policy owner.

    rule_set + outbound must match a deployed route rule exactly
    (rule_set tags are unique per site set, so this is unambiguous);
    other rules match by outbound + condition keys when unique, and
    otherwise fall back to the outbound itself. "final" attributes to
    the deployed route.final. Returns None when nothing can be said.
    """
    conds, outbound = parse_rule_text(rule_text)
    if conds.get("final"):
        final = (deployed.get("route") or {}).get("final")
        return {"kind": "final", "name": final} if final else None
    if not outbound:
        return None
    route_rules = (deployed.get("route") or {}).get("rules") or []
    cands = [r for r in route_rules
             if isinstance(r, dict) and r.get("outbound") == outbound]
    if "rule_set" in conds:
        want = set(conds["rule_set"])
        exact = [r for r in cands
                 if set(r.get("rule_set") or []) == want]
        if len(exact) == 1:
            return _owner_for_outbound(outbound, deployed, flip_map)
    elif conds:
        keys = set(conds)
        # Only count rules whose condition keys are exactly the text's
        # keys (plus outbound); truncated values ("...") make value
        # matching unreliable, so keys + unique outbound win.
        same_keys = [r for r in cands
                     if set(k for k in r.keys() if k != "outbound") == keys]
        if len(same_keys) == 1:
            return _owner_for_outbound(outbound, deployed, flip_map)
    return _owner_for_outbound(outbound, deployed, flip_map)


def _poll_connections(connections_fn, is_settled, matches_target,
                      matches_inbound):
    """The /connections poller: immediate first fetch, then the six
    backoff tiers; after the probe settles, a type-less candidate is
    a hit, and three quiet rounds mean "not seen"."""
    total = 0
    sample: list[str] = []
    settle_rounds = 0
    round_no = 0
    while True:
        try:
            conns = connections_fn()
        except Exception as e:
            return {"hit": None, "total": total, "sample": sample,
                    "error": str(e)}
        conns = [c for c in (conns or [])
                 if isinstance(c, dict) and isinstance(c.get("metadata"),
                                                       dict)]
        total = len(conns)
        sample = [f"{c['metadata'].get('host', '')}|"
                  f"{c['metadata'].get('destinationIP', '')}"
                  for c in conns[-5:]]
        cands = sorted(
            (c for c in conns if matches_target(c["metadata"])),
            key=lambda c: str(c.get("start", "")), reverse=True)
        inbound = next((c for c in cands
                        if matches_inbound(c["metadata"])), None)
        if inbound is not None:
            return {"hit": inbound, "total": total, "sample": sample}
        if is_settled():
            pending = next((c for c in cands
                            if not c["metadata"].get("type")), None)
            if pending is not None:
                return {"hit": pending, "total": total, "sample": sample}
            settle_rounds += 1
            if settle_rounds >= CONNECTIONS_SETTLE_ROUNDS:
                return {"hit": None, "total": total, "sample": sample}
        time.sleep(CONNECTIONS_POLL_DELAYS_S[
            min(round_no, len(CONNECTIONS_POLL_DELAYS_S) - 1)])
        round_no += 1


def _probe_one(target, *, port, secure, connect_to, method, mixed_host,
               mixed_port, mixed_tag, match_ips, probe_fn,
               connections_fn):
    """Run one family's probe + poll concurrently; close the socket
    only after the poll settles.

    match_ips is the set of destination IPs this family's flow may
    legitimately show (the CONNECT authority plus same-family
    answers); None means "no address was resolved, match by name".
    Family-scoped matching matters: without it, a lingering v4 flow
    from the exit probe would match the exit6 poll (same target,
    same inbound, same port) and report a v4 destination as the v6
    result — exactly the misattribution a measurement route must not
    make.
    """
    url_host = f"[{target}]" if ":" in target else target
    if method in ("TCP", "TLS"):
        url = f"{method.lower()}://{url_host}:{port}"
    else:
        default_port = 443 if secure else 80
        url = (f"{'https' if secure else 'http'}://{url_host}"
               f"{'' if port == default_port else f':{port}'}/")
    exit_: dict = {"url": url, "method": method}
    if connect_to:
        exit_["connectTo"] = connect_to
    settled = threading.Event()
    found: dict = {}

    def _matches_target(md: dict) -> bool:
        if match_ips is not None:
            return md.get("destinationIP") in match_ips
        return (str(md.get("host") or "").lower() == target.lower()
                or md.get("destinationIP") == target)

    def _matches_inbound(md: dict) -> bool:
        return (mixed_tag is not None
                and md.get("type") == f"mixed/{mixed_tag}"
                and str(md.get("destinationPort")) == str(port))

    poller = threading.Thread(
        target=lambda: found.update(_poll_connections(
            connections_fn, settled.is_set, _matches_target,
            _matches_inbound)),
        daemon=True)
    poller.start()
    try:
        result, close = probe_fn(
            target, port=port, secure=secure, connect_to=connect_to,
            method=method, mixed_host=mixed_host, mixed_port=mixed_port)
    finally:
        settled.set()
    try:
        poller.join(timeout=PROBE_TIMEOUT_S + 10)
    except Exception:
        pass
    if not found:
        found = {"hit": None, "total": 0, "sample": [],
                 "error": "poll timeout"}
    try:
        close()
    except Exception:
        pass
    exit_.update({"ok": result.get("ok"), "status": result.get("status"),
                  "ms": result.get("ms")})
    if not result.get("ok"):
        exit_["error"] = result.get("error", "")
    headers = result.get("headers")
    if headers:
        exit_["headers"] = headers
        challenge = detect_challenge(result.get("status"), headers)
        if challenge:
            exit_["challenge"] = challenge
    hit = found.get("hit")
    if found.get("error"):
        exit_["connectionsError"] = found["error"]
    if hit is not None:
        md = hit.get("metadata") or {}
        chains = hit.get("chains") or []
        exit_["chains"] = chains  # sing-box is already leaf-first
        exit_["rule"] = hit.get("rule") or ""
        exit_["rulePayload"] = hit.get("rulePayload") or ""
        exit_["destinationIP"] = md.get("destinationIP") or ""
        if chains:
            leaf = chains[0]
            exit_["viaProxy"] = leaf not in ("direct", "block")
    else:
        exit_["debug"] = {"connections": found.get("total", 0),
                          "sample": found.get("sample", [])}
    return exit_


def run_route_test(body: dict, *, deployed, mixed_host: str,
                   mixed_port: int, mixed_tag, proxies, flip_map: dict,
                   probe_fn=None, resolve_fn=None, connections_fn=None,
                   geosite_split=None, geoip_expand=None):
    """The route, minus HTTP: returns (status, body).

    400 = the request was wrong (target/method); 503 = no deployed
    config; 200 even when the probe failed (exit.ok carries it).
    probe_fn/resolve_fn/connections_fn are the test seams (defaults
    are the live implementations).
    """
    probe_fn = probe_fn or probe_inbound
    resolve_fn = resolve_fn or resolve_local
    if connections_fn is None:
        from core.clashapi import list_connections

        def connections_fn():
            ok, conns = list_connections()
            if not ok:
                raise RuntimeError("读取 /connections 失败")
            return conns

    target_raw = str(body.get("target") or "").strip().lower()
    try:
        parsed = parse_target(target_raw)
    except Exception:
        return 400, {"message": "target must be a domain or IP"}
    target = parsed.value
    literal = parsed.kind == "ip"
    try:
        method = normalize_method(body.get("method"))
    except ValueError as e:
        return 400, {"message": str(e)}
    if deployed is None:
        return 503, {"message": "还没有生成过配置（内核没启动过）"}

    out: dict = {"target": target}
    source_ip = body.get("sourceIp")
    if isinstance(source_ip, str):
        try:
            ipaddress.ip_address(source_ip.strip())
            out["sourceIp"] = source_ip.strip()
        except ValueError:
            pass  # malformed sourceIp is treated as absent

    if literal:
        out["dns"] = {"skipped": True}
        answers: list[str] = []
        answers6: list[str] = []
    else:
        try:
            out["dns"] = dns_half(deployed, target, proxies,
                                  geosite_split=geosite_split,
                                  geoip_expand=geoip_expand)
        except Exception as e:
            out["dns"] = {"error": str(e)}
        try:
            answers, answers6, ms = resolve_fn(target)
            resolve: dict = {"answers": answers, "ok": True, "ms": ms}
            if answers6:
                resolve["answers6"] = answers6
                resolve["ok6"] = True
            if any(_is_fakeip(a) for a in answers + answers6):
                resolve["fakeIp"] = True
            detour = (out["dns"] or {}).get("server", {}).get("detour")
            if detour and ms < 20 and answers:
                resolve["cached"] = True
            out["resolve"] = resolve
        except Exception as e:
            out["resolve"] = {"ok": False, "answers": [], "ms": 0,
                              "error": str(e)}
            answers, answers6 = [], []

    typed_port = body.get("port")
    try:
        typed_port = int(typed_port) if typed_port is not None else None
    except (TypeError, ValueError):
        typed_port = None
    if parsed.port is not None and typed_port is None:
        typed_port = parsed.port
    port = typed_port if (typed_port is not None
                          and 1 <= typed_port <= 65535) else (
                              80 if literal else 443)
    secure = method == "TLS" or (method != "TCP" and port != 80)

    def _owner_for(exit_):
        if exit_.get("rule"):
            owner = attribute_owner(exit_["rule"], deployed, flip_map or {})
            if owner:
                exit_["owner"] = owner

    if literal:
        if parsed.version == 6:
            out["exit6"] = _probe_one(
                target, port=port, secure=secure, connect_to="",
                method=method, mixed_host=mixed_host,
                mixed_port=mixed_port, mixed_tag=mixed_tag,
                match_ips={target}, probe_fn=probe_fn,
                connections_fn=connections_fn)
            _owner_for(out["exit6"])
        else:
            out["exit"] = _probe_one(
                target, port=port, secure=secure, connect_to="",
                method=method, mixed_host=mixed_host,
                mixed_port=mixed_port, mixed_tag=mixed_tag,
                match_ips={target}, probe_fn=probe_fn,
                connections_fn=connections_fn)
            _owner_for(out["exit"])
    else:
        if not answers:
            # No answers (resolve failed or empty): probe the name
            # itself and let the kernel resolve it.
            out["exit"] = _probe_one(
                target, port=port, secure=secure, connect_to="",
                method=method, mixed_host=mixed_host,
                mixed_port=mixed_port, mixed_tag=mixed_tag,
                match_ips=None, probe_fn=probe_fn,
                connections_fn=connections_fn)
            _owner_for(out["exit"])
        else:
            out["exit"] = _probe_one(
                target, port=port, secure=secure, connect_to=answers[0],
                method=method, mixed_host=mixed_host,
                mixed_port=mixed_port, mixed_tag=mixed_tag,
                match_ips={answers[0]} | set(answers), probe_fn=probe_fn,
                connections_fn=connections_fn)
            _owner_for(out["exit"])
        if answers6:
            out["exit6"] = _probe_one(
                target, port=port, secure=secure, connect_to=answers6[0],
                method=method, mixed_host=mixed_host,
                mixed_port=mixed_port, mixed_tag=mixed_tag,
                match_ips={answers6[0]} | set(answers6), probe_fn=probe_fn,
                connections_fn=connections_fn)
            _owner_for(out["exit6"])
    return 200, out
