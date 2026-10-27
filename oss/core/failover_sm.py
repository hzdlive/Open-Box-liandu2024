"""Failover state machine - panel-side implementation.

Based on REA report §24 (Open-Box v0.1.330 reverse engineering):
- Five-stage pipeline: failoverInit → failoverPlan → failoverObserve
  → assessLane → failoverDecide → failoverFinish
- State structure from §24.4 (reconstructed from Go string constants)
- Defaults from §24.9
- Decision reasons: all-failed, lane-failed, initial, etc.

This is a clean-room implementation of the publicly observable behavior:
the panel runs health probes and decides which lane should be active,
then applies the decision via sing-box's public Clash API.

The sing-box config renders a failover group's lanes as `urltest`
(multi-member) and the group itself as a top-level `selector`
(see singbox.py); the panel's state machine drives that selector via
the Clash API, providing the intelligent lane switching that urltest
alone cannot (priority order, fail streaks, restore hold).
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
from dataclasses import dataclass, field, asdict


# ---- Defaults from REA §24.9 ----
DEFAULT_PROBE_INTERVAL_S = 300    # 探测间隔
DEFAULT_TOLERANCE_MS = 100        # 通道内容差
DEFAULT_PROBE_TIMEOUT_MS = 5000  # 探测超时
DEFAULT_FAIL_THRESHOLD = 2        # 失败阈值（连续失败次数）
DEFAULT_RESTORE_PRIMARY = True    # 恢复主通道
DEFAULT_RESTORE_HOLD_MS = 60000   # 恢复保持
DEFAULT_MAX_LANES = 3


def lane_display_name(lane: dict, index: int) -> str:
    """Display name for a lane: custom name if set, else Primary/Backup n.
    
    Args:
        lane: lane config dict with optional 'name' key
        index: 0-based position (0=primary)
    """
    name = (lane.get("name") or "").strip()
    if name:
        return name
    return "主用" if index == 0 else f"备用{index}"


def failover_lane_tag(group_name: str, lane: dict, index: int) -> str:
    """Unified lane tag generation (single source of truth).
    
    - Single member: use member tag directly
    - Multi-member: {group_name}#{display_name}
    
    Both singbox.py and failover_sm.py must use this function.
    """
    members = lane.get("members", []) or []
    if len(members) == 1:
        return members[0]
    return f"{group_name}#{lane_display_name(lane, index)}"


def generate_lane_id() -> str:
    """Generate stable random lane id (aligned with original format)."""
    import time
    ts = int(time.time() * 1000)
    # base36 timestamp + 5 random chars
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    b36 = ""
    n = ts
    while n > 0:
        n, r = divmod(n, 36)
        b36 = chars[r] + b36
    rand = uuid.uuid4().hex[:5]
    return f"lane-{b36}-{rand}"             # 最大通道数


# ---- Decision reasons (from REA §24.5) ----
# i18n codes from panel: initial, lane-failed, restore, priority,
#                        recovered, all-failed
REASON_INITIAL = "initial"          # 初始选择
REASON_LANE_FAILED = "lane-failed"  # 上一个通道不可达
REASON_RESTORE = "restore"          # 主通道已恢复
REASON_PRIORITY = "priority"        # 按新顺序重新选择
REASON_RECOVERED = "recovered"      # 候选已恢复
REASON_ALL_FAILED = "all-failed"    # 所有通道均不可达
REASON_HEALTHY = "healthy"          # 当前通道健康，保持
# Backward compat alias
REASON_PRIMARY_RESTORED = REASON_RESTORE

# A round whose probes never reached the kernel (Clash API itself
# unreachable for every lane) is a failed round, not a lane verdict.
ROUND_FAILED_INFRA = "probe-infrastructure-failed"
# A urltest lane with no kernel selection yet is "unconfirmed": it is
# neither up nor down. After this many consecutive unconfirmed rounds
# (5 min at the 60s tick, well past the ~2 min worst-case urltest
# convergence seen live) it counts as failed, so a never-converging
# lane cannot pin the group forever.
UNCONFIRMED_MAX_ROUNDS = 5

# ---- Probe failure reasons (REA §26.4: 11 codes, must not be merged) ----
FAIL_CLOSED = "closed"          # 连接已关闭
FAIL_DNS = "dns"                # DNS 查找失败
FAIL_ERROR = "error"            # 连接失败
FAIL_INVALID = "invalid"        # 节点配置无效
FAIL_NOT_FOUND = "notFound"     # 已不在订阅中
FAIL_REFUSED = "refused"        # 连接被拒绝
FAIL_STATUS = "status"          # 意外状态
FAIL_TIMEOUT = "timeout"        # 超时
FAIL_TLS = "tls"                # TLS 握手失败
FAIL_UNREACHABLE = "unreachable"  # 网络不可达
FAIL_UNSTABLE = "unstable"      # 时断时续


def parse_expected_status(text: str) -> list[tuple[int, int]]:
    """Parse expected status text (REA §24.6, tcp19).

    Accepts "204", "200-299", "200,204", "200/204", "200-299/302".
    Separators / and , are interchangeable. Returns list of (lo, hi).
    Empty or "*" means any status is accepted.
    """
    text = (text or "").strip()
    if not text or text == "*":
        return []  # any
    ranges = []
    # split on / or ,
    parts = re.split(r"[/,]", text)
    for p in parts:
        p = p.strip()
        if not p:
            continue
        m = re.match(r"^(\d{3})(?:\s*-\s*(\d{3}))?$", p)
        if not m:
            raise ValueError(f"invalid expected status: {text}")
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if not (100 <= lo <= 599 and 100 <= hi <= 599 and lo <= hi):
            raise ValueError(f"invalid expected status: {text}")
        ranges.append((lo, hi))
    return ranges


def status_matches(status: int, ranges: list[tuple[int, int]]) -> bool:
    """Check if HTTP status matches expected ranges. Empty = any."""
    if not ranges:
        return True
    return any(lo <= status <= hi for lo, hi in ranges)


def parse_duration(text: str) -> int:
    """Parse duration text (REA §24.6). Returns milliseconds.

    Format: (\\d+(?:\\.\\d+)?)(ms|h|m|s), e.g. "5000ms", "5s", "1.5m".
    """
    text = (text or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)(ms|h|m|s)$", text)
    if not m:
        raise ValueError(f"invalid duration: {text}")
    val = float(m.group(1))
    unit = m.group(2)
    mult = {"ms": 1, "s": 1000, "m": 60000, "h": 3600000}[unit]
    return int(val * mult)


@dataclass
class LaneState:
    """Per-lane state (REA §24.4)."""
    id: str = ""
    index: int = 0
    tag: str = ""           # sing-box outbound tag for this lane
    name: str = ""
    members: list = field(default_factory=list)
    valid: bool = True
    health: str = "unknown"  # ok | degraded | failed | unknown
    ok: bool = False
    mode: str = "auto"       # auto | manual
    up_since: str | None = None
    since: str | None = None
    fail_streak: int = 0
    reason: str = ""
    evaluated: bool = False
    at: str | None = None
    status: str = "unknown"


@dataclass
class FailoverState:
    """Top-level failover state (REA §24.4)."""
    group_name: str = ""
    # Current selection
    current_lane_id: str = ""
    current_id: str = ""
    current_since: str | None = None
    lane_order: list = field(default_factory=list)
    last_switch: str | None = None
    last_reason: str = REASON_INITIAL
    # Lanes
    lanes: list = field(default_factory=list)  # list[LaneState] as dicts
    # Round accounting (§24.4: cheap vs full rounds)
    last_round_at: str | None = None
    last_full_round_at: str | None = None  # 上次完整轮次
    next_round_at: str | None = None
    last_round_id: str = ""
    last_round_result: str = ""
    plan_full: bool = False  # 当前/上次是否为完整轮次
    # Logs (recent switch history)
    logs: list = field(default_factory=list)
    # Last kernel-switch attempt that failed read-back verification
    # ("" when the last switch, if any, applied cleanly).
    last_switch_error: str = ""
    # Settings
    settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FailoverState":
        return cls(
            group_name=d.get("group_name", ""),
            current_lane_id=d.get("current_lane_id", ""),
            current_id=d.get("current_id", ""),
            current_since=d.get("current_since"),
            lane_order=d.get("lane_order", []),
            last_switch=d.get("last_switch"),
            last_reason=d.get("last_reason", REASON_INITIAL),
            lanes=d.get("lanes", []),
            last_round_at=d.get("last_round_at"),
            last_full_round_at=d.get("last_full_round_at"),
            next_round_at=d.get("next_round_at"),
            last_round_id=d.get("last_round_id", ""),
            last_round_result=d.get("last_round_result", ""),
            plan_full=d.get("plan_full", False),
            logs=d.get("logs", []),
            last_switch_error=d.get("last_switch_error", ""),
            settings=d.get("settings", {}),
        )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def failover_init(group_name: str, lanes_config: list[dict],
                  settings: dict | None = None) -> FailoverState:
    """Build/normalize persistent state (REA: failoverInit).

    lanes_config: [{"name": ..., "members": [...], "mode": "auto"|"manual"}, ...]
    """
    st = FailoverState(group_name=group_name)
    st.settings = {
        "probe_interval_s": (settings or {}).get("probe_interval_s", DEFAULT_PROBE_INTERVAL_S),
        "tolerance_ms": (settings or {}).get("tolerance_ms", DEFAULT_TOLERANCE_MS),
        "probe_timeout_ms": (settings or {}).get("probe_timeout_ms", DEFAULT_PROBE_TIMEOUT_MS),
        "fail_threshold": (settings or {}).get("fail_threshold", DEFAULT_FAIL_THRESHOLD),
        "restore_primary": (settings or {}).get("restore_primary", DEFAULT_RESTORE_PRIMARY),
        "restore_hold_ms": (settings or {}).get("restore_hold_ms", DEFAULT_RESTORE_HOLD_MS),
        "max_lanes": DEFAULT_MAX_LANES,
    }

    lanes = []
    for i, lc in enumerate(lanes_config[:DEFAULT_MAX_LANES]):
        # id: 优先取配置中的稳定 id，无则生成（不再用位置式 lane-{i}）
        lane_id = lc.get("id") or generate_lane_id()
        # tag: 使用统一函数（单成员→成员tag，多成员→{group}#{display}）
        lane_tag = failover_lane_tag(group_name, lc, i)
        lanes.append({
            "id": lane_id,
            "index": i,
            "tag": lane_tag,
            # name: 保持原样（空即空），不再伪造"通道N"
            "name": lc.get("name") or "",
            "display_name": lane_display_name(lc, i),
            "members": lc.get("members", []),
            "valid": bool(lc.get("members")),
            "health": "unknown",
            "ok": False,
            "mode": lc.get("mode", "auto"),
            "up_since": None,
            "since": None,
            "fail_streak": 0,
            "reason": "",
            "evaluated": False,
            "at": None,
            "status": "unknown",
            "unconfirmed_streak": 0,
        })
    st.lanes = lanes
    st.lane_order = [l["id"] for l in lanes]

    # Initial selection: first valid lane
    for lane in lanes:
        if lane["valid"]:
            st.current_lane_id = lane["id"]
            st.current_id = lane["tag"]
            st.current_since = _now_iso()
            st.last_reason = REASON_INITIAL
            break

    return st


def failover_plan(state: FailoverState, full: bool = False) -> dict:
    """Open a probe round (REA: failoverPlan).

    full=False: cheap round — only probe lanes needing recheck
                (failed lanes, current lane if unhealthy).
    full=True:  full round — probe every valid lane.

    Returns: {"roundId": ..., "startedAt": ..., "plan": [...], "planFull": bool}
    """
    round_id = f"r{int(time.time() * 1000)}"
    started_at = _now_iso()
    plan = []
    for lane in state.lanes:
        if not lane["valid"]:
            continue
        if not full:
            # Cheap round: skip healthy non-current lanes
            is_current = (lane["id"] == state.current_lane_id)
            is_healthy = lane.get("ok", False)
            if is_healthy and not is_current:
                continue
        plan.append({
            "laneId": lane["id"],
            "tag": lane["tag"],
            "members": lane["members"],
            "mode": lane["mode"],
        })
    state.last_round_id = round_id
    state.last_round_at = started_at
    state.plan_full = full
    if full:
        state.last_full_round_at = started_at
    return {"roundId": round_id, "startedAt": started_at,
            "plan": plan, "planFull": full}


def probe_lane(api_base: str, secret: str, lane: dict,
               timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS) -> dict:
    """Probe a single lane's health via Clash API.

    Returns: {"ok": bool, "latency_ms": int|None, "reason": str} plus
    optional flags: "infra" (the Clash API itself could not be reached,
    so this is not a lane verdict at all) and "unconfirmed" (a urltest
    lane with no kernel selection yet: neither up nor down).
    """
    # For urltest lanes, query the Clash API for the lane's latency
    # For single-member lanes, check the member directly
    tag = lane["tag"]
    try:
        url = f"{api_base}/proxies/{urllib.parse.quote(tag)}"
        req = urllib.request.Request(url, headers=_auth_headers(secret))
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000) as r:
            data = json.loads(r.read())
            # urltest lane with no kernel selection yet: only the node
            # the kernel actually selected counts as up, so an
            # unconverged urltest is "unconfirmed", not failed.
            if str(data.get("type", "")).lower() == "urltest" \
                    and not data.get("now"):
                return {"ok": False, "unconfirmed": True,
                        "latency_ms": None, "reason": "unconfirmed"}
            # Always run a fresh delay test; cached history may be stale
            # (e.g. from before a failure) and would mask real outages.
            return _delay_test(api_base, secret, tag, timeout_ms)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "latency_ms": None, "reason": FAIL_NOT_FOUND}
        if e.code >= 500:
            return {"ok": False, "infra": True,
                    "latency_ms": None, "reason": FAIL_ERROR}
        return {"ok": False, "latency_ms": None, "reason": FAIL_ERROR}
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        if "refused" in reason.lower():
            return {"ok": False, "infra": True,
                    "latency_ms": None, "reason": FAIL_REFUSED}
        if "name" in reason.lower() or "dns" in reason.lower():
            return {"ok": False, "infra": True,
                    "latency_ms": None, "reason": FAIL_DNS}
        return {"ok": False, "infra": True,
                "latency_ms": None, "reason": FAIL_UNREACHABLE}
    except Exception:
        return {"ok": False, "infra": True,
                "latency_ms": None, "reason": FAIL_ERROR}


def _delay_test(api_base: str, secret: str, tag: str,
                timeout_ms: int) -> dict:
    """Run a Clash API delay test for a proxy."""
    import urllib.parse
    try:
        url = (f"{api_base}/proxies/{urllib.parse.quote(tag)}/delay"
               f"?timeout={timeout_ms}&url=http://www.gstatic.com/generate_204")
        req = urllib.request.Request(url, headers=_auth_headers(secret))
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000 + 2) as r:
            data = json.loads(r.read())
            delay = data.get("delay", 0)
            return {"ok": delay > 0, "latency_ms": delay,
                    "reason": "" if delay > 0 else FAIL_TIMEOUT}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "latency_ms": None, "reason": FAIL_NOT_FOUND}
        return {"ok": False, "latency_ms": None, "reason": FAIL_STATUS}
    except socket.timeout:
        return {"ok": False, "latency_ms": None, "reason": FAIL_TIMEOUT}
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        rl = reason.lower()
        if "refused" in rl:
            # The API socket itself is down: infrastructure, not lane.
            return {"ok": False, "infra": True,
                    "latency_ms": None, "reason": FAIL_REFUSED}
        if "tls" in rl or "ssl" in rl or "certificate" in rl:
            return {"ok": False, "latency_ms": None, "reason": FAIL_TLS}
        if "name" in rl or "dns" in rl:
            return {"ok": False, "infra": True,
                    "latency_ms": None, "reason": FAIL_DNS}
        return {"ok": False, "infra": True,
                "latency_ms": None, "reason": FAIL_UNREACHABLE}
    except Exception:
        return {"ok": False, "latency_ms": None, "reason": FAIL_ERROR}


def _auth_headers(secret: str) -> dict:
    h = {}
    if secret:
        h["Authorization"] = f"Bearer {secret}"
    return h


def failover_observe(state: FailoverState, results: list[dict],
                     round_id: str | None = None) -> None:
    """Ingest probe results (REA: failoverObserve).

    results: [{"laneId": ..., "ok": bool, "latency_ms": ..., "reason": ...}, ...]
    round_id: staleness token — results from any round other than the
    current one are ignored, so a late round can never clobber newer
    state. "infra" results (Clash API unreachable) are not lane
    verdicts and leave streak/health untouched; "unconfirmed" results
    (urltest without a kernel selection yet) only advance the
    unconfirmed streak, which assess_lane bounds.
    """
    if round_id is not None and round_id != state.last_round_id:
        return
    result_map = {r["laneId"]: r for r in results}
    for lane in state.lanes:
        r = result_map.get(lane["id"])
        if not r:
            continue
        if r.get("infra"):
            continue
        if r.get("unconfirmed"):
            lane["unconfirmed_streak"] = lane.get("unconfirmed_streak", 0) + 1
            lane["at"] = _now_iso()
            continue
        lane["unconfirmed_streak"] = 0
        lane["evaluated"] = True
        lane["at"] = _now_iso()
        if r["ok"]:
            lane["fail_streak"] = 0
            lane["ok"] = True
            lane["health"] = "ok"
            if not lane["up_since"]:
                lane["up_since"] = _now_iso()
            lane["reason"] = ""
        else:
            lane["fail_streak"] = lane.get("fail_streak", 0) + 1
            lane["reason"] = r.get("reason", "probe-failed")
            # Don't mark as failed until threshold reached (handled in assess)
        lane["status"] = "ok" if r["ok"] else "failed"


def assess_lane(state: FailoverState) -> None:
    """Grade each lane (REA: assessLane).

    Sets health, valid, ok, upSince, failStreak based on probe results.
    """
    threshold = state.settings.get("fail_threshold", DEFAULT_FAIL_THRESHOLD)
    for lane in state.lanes:
        if not lane["valid"]:
            lane["health"] = "invalid"
            lane["ok"] = False
            continue
        # A urltest lane that never converges is effectively dead, but
        # only after the grace window: before that it keeps its previous
        # health (checked before "evaluated", so never-evaluated lanes
        # are covered too).
        if lane.get("unconfirmed_streak", 0) >= UNCONFIRMED_MAX_ROUNDS:
            lane["health"] = "failed"
            lane["ok"] = False
            lane["fail_streak"] = max(lane.get("fail_streak", 0), threshold)
            lane["up_since"] = None
            continue
        if not lane.get("evaluated"):
            lane["health"] = "unknown"
            continue
        if lane["fail_streak"] >= threshold:
            lane["health"] = "failed"
            lane["ok"] = False
            lane["up_since"] = None
        elif lane["fail_streak"] > 0:
            lane["health"] = "degraded"
            lane["ok"] = True  # Still usable, but degrading
        else:
            lane["health"] = "ok"
            lane["ok"] = True


def failover_decide(state: FailoverState) -> dict:
    """Choose target lane (REA: failoverDecide).

    Returns: {"target": lane_id, "switchTo": tag, "reason": ..., "reorderMove": ...}
    """
    valid_lanes = [l for l in state.lanes if l["valid"]]
    healthy_lanes = [l for l in valid_lanes if l["ok"]]

    current = next((l for l in state.lanes if l["id"] == state.current_lane_id), None)

    # Case 1: No healthy lanes -> all-failed
    # REA §24.5: does NOT silently fall back to direct; switches to
    # the __fo:reject outbound and retries every minute.
    if not healthy_lanes:
        return {
            "target": "__fo:reject",
            "switchTo": "__fo:reject",
            "reason": REASON_ALL_FAILED,
            "reorderMove": None,
            "recheckRound": True,
            "retryInMs": 60000,  # 每分钟重试
        }

    # Case 2: Current lane is healthy - keep it (with restore logic)
    if current and current["ok"]:
        # Check if primary has recovered and we should switch back
        if state.settings.get("restore_primary", DEFAULT_RESTORE_PRIMARY):
            primary = valid_lanes[0] if valid_lanes else None
            if (primary and primary["id"] != current["id"] and primary["ok"]):
                hold_ms = state.settings.get("restore_hold_ms", DEFAULT_RESTORE_HOLD_MS)
                # Check if primary has been up long enough
                if primary.get("up_since"):
                    up_time = _parse_iso(primary["up_since"])
                    if up_time and (time.time() - up_time) * 1000 >= hold_ms:
                        return {
                            "target": primary["id"],
                            "switchTo": primary["tag"],
                            "reason": REASON_RESTORE,
                            "reorderMove": None,
                            "recheckRound": False,
                        }
        return {
            "target": current["id"],
            "switchTo": current["tag"],
            "reason": REASON_HEALTHY,
            "reorderMove": None,
            "recheckRound": False,
        }

    # Case 3: Current lane failed - move to next healthy lane in priority order
    for lane in valid_lanes:
        if lane["ok"]:
            return {
                "target": lane["id"],
                "switchTo": lane["tag"],
                "reason": REASON_LANE_FAILED,
                "reorderMove": None,
                "recheckRound": False,
            }

    # Fallback (shouldn't reach here due to Case 1)
    return {
        "target": state.current_lane_id,
        "switchTo": state.current_id,
        "reason": REASON_ALL_FAILED,
        "reorderMove": None,
        "recheckRound": True,
    }


def failover_finish(state: FailoverState, decision: dict) -> dict:
    """Commit decision (REA: failoverFinish).

    Returns: {"switched": bool, "currentLaneId": ..., "logs": [...]}
    """
    switched = decision["target"] != state.current_lane_id
    now = _now_iso()

    if switched:
        old_lane = next((l for l in state.lanes if l["id"] == state.current_lane_id), {})
        new_lane = next((l for l in state.lanes if l["id"] == decision["target"]), {})
        state.last_switch = now
        state.current_lane_id = decision["target"]
        state.current_id = decision["switchTo"]
        state.current_since = now
        # Log the switch
        state.logs.append({
            "at": now,
            "from": old_lane.get("display_name") or old_lane.get("name", "?"),
            "to": new_lane.get("display_name") or new_lane.get("name", "?"),
            "reason": decision["reason"],
        })
        # Keep only last 50 logs
        state.logs = state.logs[-50:]

    state.last_reason = decision["reason"]
    state.last_round_result = decision["reason"]
    if not switched:
        # No switch attempted this round: any earlier switch error is
        # stale (the lane either recovered or the next switch attempt
        # will set it fresh).
        state.last_switch_error = ""

    # Schedule next round
    interval_s = state.settings.get("probe_interval_s", DEFAULT_PROBE_INTERVAL_S)
    # If recheck needed (all failed), use shorter interval (60s per REA)
    if decision.get("recheckRound"):
        interval_s = 60
    state.next_round_at = time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + interval_s))

    return {
        "switched": switched,
        "currentLaneId": state.current_lane_id,
        "currentTag": state.current_id,
        "reason": decision["reason"],
    }


def _parse_iso(s: str) -> float | None:
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def run_round(state: FailoverState, api_base: str, secret: str) -> dict:
    """Run a complete failover round (all five stages).

    Returns the finish result with switch info.
    """
    # Stage 1: Plan
    plan = failover_plan(state)

    # Stage 2: Probe and Observe
    results = []
    for item in plan["plan"]:
        lane = next(l for l in state.lanes if l["id"] == item["laneId"])
        probe = probe_lane(api_base, secret, lane,
                          state.settings.get("probe_timeout_ms", DEFAULT_PROBE_TIMEOUT_MS))
        results.append({"laneId": item["laneId"],
                        "roundId": plan["roundId"], **probe})
    # Failed round: the Clash API itself was unreachable for every
    # probe. That round must not switch anything (the kernel keeps
    # routing; only our observation failed), so no state change and
    # next_round_at stays due for a prompt retry next tick.
    if results and all(r.get("infra") for r in results):
        state.last_round_result = ROUND_FAILED_INFRA
        return {
            "switched": False,
            "currentLaneId": state.current_lane_id,
            "currentTag": state.current_id,
            "reason": ROUND_FAILED_INFRA,
            "roundFailed": True,
            "decision": None,
            "probe_results": results,
        }
    failover_observe(state, results, round_id=plan["roundId"])

    # Stage 3: Assess
    assess_lane(state)

    # Stage 4: Decide
    decision = failover_decide(state)

    # Stage 5: Finish
    result = failover_finish(state, decision)
    result["decision"] = decision
    result["probe_results"] = results
    return result


def apply_switch(api_base: str, secret: str, group_tag: str,
                 target_tag: str) -> tuple[bool, str]:
    """Apply a lane switch via Clash API, with read-back verification.

    Failover groups are rendered as selector (top-level), so we use
    PUT /proxies/{group} to force the switch to the target lane.
    A 200/204 alone is not proof: the selector's actual choice is read
    back, and a mismatch is reported as
    "切换失败:切到 B 后读回的是 A".

    Returns (ok, message).
    """
    try:
        url = f"{api_base}/proxies/{urllib.parse.quote(group_tag)}"
        data = json.dumps({"name": target_tag}).encode()
        req = urllib.request.Request(url, data=data, method="PUT",
                                     headers={"Content-Type": "application/json", **_auth_headers(secret)})
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status not in (200, 204):
                return False, f"switch failed: API returned {r.status}"
    except Exception as e:
        return False, f"switch failed: {e}"
    try:
        url = f"{api_base}/proxies/{urllib.parse.quote(group_tag)}"
        req = urllib.request.Request(url, headers=_auth_headers(secret))
        with urllib.request.urlopen(req, timeout=10) as r:
            now = json.loads(r.read()).get("now")
        if now == target_tag:
            return True, f"switched {group_tag} -> {target_tag}"
        return False, (f"切换失败:切到 {target_tag} 后读回的是 "
                       f"{now if now else '（无选择）'}")
    except Exception as e:
        return False, f"切换失败:切到 {target_tag} 后读回失败: {e}"


def snapshot_switch(state: FailoverState) -> dict:
    """Snapshot the switch-related fields before a round, so a kernel
    switch that fails verification can be rolled back in memory."""
    return {
        "current_lane_id": state.current_lane_id,
        "current_id": state.current_id,
        "current_since": state.current_since,
        "last_switch": state.last_switch,
        "logs_len": len(state.logs),
    }


def revert_switch(state: FailoverState, snapshot: dict) -> None:
    """Roll back a decided-but-unapplied switch (see snapshot_switch).

    The decision reason stays (the lane really did fail); only the
    selection, switch time and the success log entry are reverted, so
    the persisted state keeps matching what the kernel serves."""
    state.current_lane_id = snapshot["current_lane_id"]
    state.current_id = snapshot["current_id"]
    state.current_since = snapshot["current_since"]
    state.last_switch = snapshot["last_switch"]
    state.logs = state.logs[:snapshot["logs_len"]]


def apply_decided_switch(state: FailoverState, snapshot: dict,
                         group_tag: str, api_base: str,
                         secret: str) -> tuple[bool, str]:
    """Apply the switch a round just decided (state.current_id), with
    read-back verification. On failure the in-memory state is reverted
    to the snapshot and last_switch_error records the detail; on
    success the error is cleared. Callers persist the state after this
    returns, so the DB never claims a switch the kernel did not make."""
    ok, msg = apply_switch(api_base, secret, group_tag, state.current_id)
    if ok:
        state.last_switch_error = ""
        return True, msg
    revert_switch(state, snapshot)
    state.last_switch_error = msg
    return False, msg
