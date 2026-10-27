"""Subscription fetching through the original's UA ladder.

Recorded ladder (third-party contract, product names verbatim; the
full versioned UA strings were not recorded in the contract, and
providers gate on these substrings):
    clash-verge / ClashMetaForAndroid / mihomo / clash-verge-rev /
    sing-box / Open-Box

Rules:
- Try each UA in order; any non-429 failure moves to the next UA.
- HTTP 429 stops the ladder immediately (no further UAs, no curl).
- Only when every UA is rejected, fall back to the system curl
  binary (a different HTTP/TLS stack, which is what unblocks
  providers that reject urllib).
- Downloads are capped at 32 MiB per attempt (our safety bound, not
  an original behavior): an over-cap response fails that attempt
  rather than truncating mid-stream into partial nodes.

Callers parse the returned text; a successful fetch that parses to
zero nodes is reported by the caller as "订阅是空的", never as an
HTTP failure, and must never wipe existing nodes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import urllib.error
import urllib.request

UA_LADDER = [
    "clash-verge",
    "ClashMetaForAndroid",
    "mihomo",
    "clash-verge-rev",
    "sing-box",
    "Open-Box",
]

MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024

_USERINFO_KEYS = ("upload", "download", "total", "expire")


class FetchError(Exception):
    """The whole ladder (plus curl fallback) failed, or hit 429."""


class _RateLimited(Exception):
    """Internal: a 429 was seen; the ladder stops immediately."""


def parse_userinfo(header_value: str) -> dict:
    """Parse a `subscription-userinfo` header value into ints."""
    info: dict = {}
    for part in (header_value or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k in _USERINFO_KEYS:
            try:
                info[k] = int(v)
            except ValueError:
                pass
    return info


def _fetch_urllib(url: str, ua: str, timeout: float) -> tuple[str, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_DOWNLOAD_BYTES + 1)
            if len(raw) > MAX_DOWNLOAD_BYTES:
                raise ValueError("订阅内容过大（超过 32 MiB）")
            info = parse_userinfo(r.headers.get("subscription-userinfo", ""))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise _RateLimited() from e
        raise ValueError(f"HTTP {e.code}") from e
    return raw.decode("utf-8", "replace"), info


def _parse_curl_output(data: bytes) -> tuple[str, dict]:
    """Split curl -D - output (headers + body + write-out trailer).

    The trailer is "\\n<http_code> <size_header>"; size_header is the
    exact byte length of all header blocks, so the body boundary is
    exact even with redirects and blank lines inside the body.
    """
    # Trailer offsets must be computed on bytes: decoding first would
    # shift offsets wherever the body holds non-UTF-8 bytes.
    m = re.search(rb"\n(\d{3}) (\d+)\s*$", data)
    if not m:
        raise ValueError("curl 输出无法解析")
    http_code = int(m.group(1))
    size_header = int(m.group(2))
    if http_code == 429:
        raise _RateLimited()
    if not 200 <= http_code < 300:
        raise ValueError(f"HTTP {http_code}")
    payload = data[:m.start()]
    headers_blob = payload[:size_header].decode("latin-1", "replace")
    body = payload[size_header:]
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError("订阅内容过大（超过 32 MiB）")
    info: dict = {}
    for match in re.finditer(r"(?im)^subscription-userinfo:\s*(.*)$",
                             headers_blob):
        info = parse_userinfo(match.group(1))
    return body.decode("utf-8", "replace"), info


def _fetch_curl(url: str, timeout: float) -> tuple[str, dict]:
    if not shutil.which("curl"):
        raise ValueError("系统无 curl 可用")
    proc = subprocess.run(
        ["curl", "-sSL", "--max-time", str(int(timeout)),
         "-D", "-",  # headers to stdout, ahead of the body
         "-w", "\n%{http_code} %{size_header}", url],
        capture_output=True, timeout=timeout + 10)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"curl 失败（exit {proc.returncode}）"
                         + (f": {err}" if err else ""))
    return _parse_curl_output(proc.stdout)


def fetch_subscription_text(url: str, timeout: float = 30.0) -> tuple[str, dict]:
    """Fetch one subscription URL through the UA ladder.

    Returns (text, userinfo). Raises FetchError when the ladder is
    stopped by a 429 or when every UA plus the curl fallback fails.
    """
    last_error: Exception | None = None
    for ua in UA_LADDER:
        try:
            return _fetch_urllib(url, ua, timeout)
        except _RateLimited:
            raise FetchError("触发限流（HTTP 429），已停止尝试")
        except Exception as e:  # noqa: BLE001 - any failure tries next UA
            last_error = e
    try:
        return _fetch_curl(url, timeout)
    except _RateLimited:
        raise FetchError("触发限流（HTTP 429），已停止尝试")
    except Exception as e:  # noqa: BLE001 - report the fallback failure
        raise FetchError(
            f"订阅拉取失败（{len(UA_LADDER)} 个 UA 均被拒，"
            f"curl 回退也失败）：{e}") from e
