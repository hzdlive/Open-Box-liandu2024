"""Xboard/V2Board panel account login (v0.1.357).

Both panels expose the same public, documented standard endpoints:
  POST {site}/api/v1/passport/auth/login   {email, password} -> data.token
  GET  {site}/api/v1/client/subscribe?token=... -> subscription content
       (+ subscription-userinfo header: upload/download/total/expire)
  GET  {site}/api/v1/user/info (Bearer token, best-effort) -> plan/traffic

The password is used for exactly one login POST and is never stored,
logged, or returned. The subscription row keeps only the token-bearing
subscribe URL (the same kind of credential a plain subscription URL
already carries), so later refreshes work without the password and go
through the normal pinned-UA refresh path. Plan/traffic fields are
surfaced only when the panel's user-info endpoint provides them; a
missing or failing user-info endpoint never fails the login.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .subfetch import MAX_DOWNLOAD_BYTES, parse_userinfo

UA = "openbox-oss/1.0"


class LoginError(Exception):
    """Login or subscribe fetch failed. auth_failed marks bad credentials."""

    def __init__(self, message: str, auth_failed: bool = False):
        super().__init__(message)
        self.auth_failed = auth_failed


def _read_json(resp) -> dict:
    raw = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise LoginError("站点返回内容过大")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise LoginError("站点返回内容不是 JSON") from None
    return data if isinstance(data, dict) else {}


def _extract_token(body: dict) -> str | None:
    data = body.get("data")
    if not isinstance(data, dict):
        data = body
    for key in ("token", "auth_data", "access_token"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_plan(body: dict) -> dict | None:
    """Plan/traffic fields, only the keys the panel actually provides."""
    data = body.get("data")
    if not isinstance(data, dict):
        data = body
    plan: dict = {}
    name = None
    raw_plan = data.get("plan")
    if isinstance(raw_plan, dict):
        name = raw_plan.get("name")
    elif isinstance(raw_plan, str) and raw_plan.strip():
        name = raw_plan.strip()
    if not name:
        name = data.get("plan_name") or data.get("planName")
    if isinstance(name, str) and name.strip():
        plan["name"] = name.strip()
    elif data.get("plan_id") is not None:
        plan["plan_id"] = data.get("plan_id")
    for key, aliases in (
            ("upload", ("upload", "u")),
            ("download", ("download", "d")),
            ("total", ("total", "transfer_enable")),
            ("expire", ("expire", "expired_at", "expire_time"))):
        for alias in aliases:
            if data.get(alias) is not None:
                plan[key] = data.get(alias)
                break
    return plan or None


def login(site: str, email: str, password: str,
          timeout: float = 30.0) -> dict:
    """Log in and fetch the panel's subscribe content.

    Returns {subscribe_url, content, userinfo, plan}. The password
    leaves this function only inside the login POST body; it is never
    stored, logged, or included in the return value.
    """
    site = (site or "").strip().rstrip("/")
    if not site.startswith(("http://", "https://")):
        raise LoginError("站点地址须以 http:// 或 https:// 开头")
    login_url = site + "/api/v1/passport/auth/login"
    req = urllib.request.Request(
        login_url,
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = _read_json(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LoginError("站点拒绝登录（账号或密码错误）",
                             auth_failed=True) from e
        raise LoginError(f"登录失败：HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise LoginError(f"无法连接站点：{e.reason}") from e
    token = _extract_token(body)
    if not token:
        raise LoginError("站点登录未返回 token")
    subscribe_url = (site + "/api/v1/client/subscribe?token="
                     + urllib.parse.quote(token))
    req = urllib.request.Request(
        subscribe_url,
        headers={"User-Agent": UA, "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_DOWNLOAD_BYTES + 1)
            if len(raw) > MAX_DOWNLOAD_BYTES:
                raise LoginError("订阅内容过大（超过 32 MiB）")
            userinfo = parse_userinfo(
                resp.headers.get("subscription-userinfo", ""))
    except urllib.error.HTTPError as e:
        raise LoginError(f"订阅获取失败：HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise LoginError(f"订阅获取失败：{e.reason}") from e
    content = raw.decode("utf-8", "replace")
    if not content.strip():
        raise LoginError("站点返回的订阅内容为空")
    plan = None
    try:
        req = urllib.request.Request(
            site + "/api/v1/user/info",
            headers={"User-Agent": UA, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            plan = _extract_plan(_read_json(resp))
    except Exception:  # noqa: BLE001 - user-info is best-effort only
        plan = None
    return {"subscribe_url": subscribe_url, "content": content,
            "userinfo": userinfo, "plan": plan}
