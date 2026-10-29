"""openbox-core replica: stdio JSON process.

Reads one JSON object from stdin, writes one JSON object to stdout,
exits 0 always (errors ride in stdout, per core-protocol.json).

The wire protocol is MEASURED (core-protocol.json, 28 cases against
core v0.1.337), not assumed. Four distinct error sentences, in this
check order (fixture _meta: "trailing data is checked BEFORE protocol;
both are checked after the first decode"):

1. First decode: syntax + Go field types. Failures ->
   "invalid native-core request". (A string/float/bool protocol, a
   non-string license, a non-array geoTags/args, a non-string method,
   a non-object top-level value, a BOM, empty/blank input.)
   JSON null as the whole input decodes to the zero request (no error).
2. Trailing non-whitespace data after the first value ->
   "trailing native-core request data". (Trailing whitespace is EOF,
   not data.)
3. Protocol value (after a clean decode): absent/null -> 0, an int
   other than 1 -> "native-core protocol mismatch".
4. Method: absent/null/empty/unknown -> "unsupported native-core
   method". (Method names are case sensitive; field NAMES are matched
   case-insensitively, Go decoder semantics, exact match wins.)

Two deliberate divergences from the original (no impersonation):
- hello answers our own identity (implementation "oss-python",
  buildID our version, methods = what we actually support, currently
  empty) and omits bindingSha256 (its input is unknown; see README).
- Known-but-unimplemented methods answer "not implemented yet"
  (ours), and the licence family answers the out-of-scope error
  (ours). Only truly unknown names answer "unsupported native-core
  method" (measured).
"""

import json
import sys

VERSION = "oss-core-replica-0.1.0"

INVALID_REQUEST = "invalid native-core request"
TRAILING_DATA = "trailing native-core request data"
PROTOCOL_MISMATCH = "native-core protocol mismatch"
UNSUPPORTED_METHOD = "unsupported native-core method"
NOT_IMPLEMENTED = "not implemented yet"
LICENCE_OUT_OF_SCOPE = "licence methods are out of scope for this replica"

# Licence family: authorization/verification is out of scope for this
# project. These names are known, so they must NOT answer "unsupported
# native-core method"; they answer the out-of-scope error instead.
LICENCE_METHODS = {
    "activationState",
    "checkActivationCode",
    "verifyLicense",
    "authorizationState",
    "featureAccess",
}

# Implementable methods (golden corpus minus the licence family).
# hello is the handshake, not a method, and is handled separately.
IMPLEMENTABLE_METHODS = {
    "configDetailed",
    "normalizeRouting",
    "normalizePolicy",
    "normalizeCustom",
    "normalizeGroups",
    "builtinTags",
    "migrateStoredRouting",
    "routingFingerprint",
    "classes",
    "entryPlan",
    "bypassPlan",
    "forwardPlan",
    "emitGroups",
}


def _err(msg):
    return {"protocol": 1, "ok": False, "error": msg}


def _ok(value):
    return {"protocol": 1, "ok": True, "value": value}


def _hello(_args):
    # methods = what this replica actually supports (excluding the
    # handshake itself, as in the original's hello). Grows as methods
    # are implemented; it starts empty on purpose.
    return _ok({
        "implementation": "oss-python",
        "protocol": 1,
        "buildID": VERSION,
        "methods": sorted(_METHODS),
    })


# name -> implementation. Unimplemented implementable methods are
# absent here on purpose: absence means "not implemented yet".
_METHODS = {}


def _field(req, name):
    """Go decoder field lookup: exact match wins, else the first
    case-insensitive match. Returns (present, value); a JSON null
    counts as present-with-None (Go decodes null into the zero value
    without error)."""
    if name in req:
        return True, req[name]
    low = name.lower()
    for k, v in req.items():
        if isinstance(k, str) and k.lower() == low:
            return True, v
    return False, None


def _type_errors(req):
    """Phase 1 (first decode): Go field-type failures -> invalid.
    Returns True if any field fails its Go type."""
    present, p = _field(req, "protocol")
    if present and p is not None:
        if isinstance(p, bool) or not isinstance(p, int):
            return True
    present, lic = _field(req, "license")
    if present and lic is not None and not isinstance(lic, str):
        return True
    present, tags = _field(req, "geoTags")
    if present and tags is not None:
        if not isinstance(tags, list):
            return True
        if any(t is not None and not isinstance(t, str) for t in tags):
            return True
    present, a = _field(req, "args")
    if present and a is not None and not isinstance(a, list):
        return True
    present, m = _field(req, "method")
    if present and m is not None and not isinstance(m, str):
        return True
    return False


def handle(raw):
    """Handle one raw stdin payload (bytes or str) -> response dict."""
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _err(INVALID_REQUEST)
    else:
        text = raw
    if not text.strip():
        return _err(INVALID_REQUEST)
    # Phase 1: first decode (syntax). A whole-input null decodes to
    # the zero request (no error); any other non-object top-level
    # value fails Go struct decode. Leading whitespace is skipped
    # (json.loads does this before raw_decode; raw_decode alone does
    # not) -- the leading-newline case measures it as fine.
    import re as _re
    start = _re.match(r"\s*", text).end()
    try:
        req, end = json.JSONDecoder().raw_decode(text, start)
    except (json.JSONDecodeError, ValueError):
        return _err(INVALID_REQUEST)
    if req is None:
        req = {}
    elif not isinstance(req, dict):
        return _err(INVALID_REQUEST)
    if _type_errors(req):
        return _err(INVALID_REQUEST)
    # Phase 2: trailing data (before protocol, measured).
    if text[end:].strip():
        return _err(TRAILING_DATA)
    # Phase 3: protocol value. Absent/null -> 0 -> mismatch.
    _, p = _field(req, "protocol")
    if p is None or p != 1:
        return _err(PROTOCOL_MISMATCH)
    # Phase 4: method. Absent/null/empty/unknown -> unsupported.
    _, m = _field(req, "method")
    if m is None or m == "":
        return _err(UNSUPPORTED_METHOD)
    if m == "hello":
        present, a = _field(req, "args")
        args = a if (present and a is not None) else []
        try:
            return _hello(args)
        except Exception as e:  # never crash the process on a bad call
            return _err(str(e) or e.__class__.__name__)
    if m in LICENCE_METHODS:
        return _err(LICENCE_OUT_OF_SCOPE)
    if m in _METHODS:
        present, a = _field(req, "args")
        args = a if (present and a is not None) else []
        try:
            return _METHODS[m](args)
        except Exception as e:
            return _err(str(e) or e.__class__.__name__)
    if m in IMPLEMENTABLE_METHODS:
        return _err(NOT_IMPLEMENTED)
    return _err(UNSUPPORTED_METHOD)


def main():
    raw = sys.stdin.buffer.read()
    sys.stdout.write(json.dumps(handle(raw), ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
