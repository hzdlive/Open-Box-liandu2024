# openbox-core replica (Python, stdio JSON)

A clean-room reimplementation of the openbox-core process's **observable
wire behaviour**: one JSON object on stdin, one on stdout, spawnSync per
call. It is written for our own stack (our panel does not shell out to
a core today); it is not a drop-in for the original panel.

## Envelope (from panel-contract/core-state-schema.json)

- Request: `{"protocol": 1, "method": "<name>", "args": [...],
  "license"?: "<string>", "geoTags"?: ["<string>", ...]}`
- Response: `{"protocol": 1, "ok": true, "value": <any>}` or
  `{"protocol": 1, "ok": false, "error": "<string>"}`
- Limits (original): input 32 MiB, output 64 MiB, timeout 30 s.
  The limits are **not enforced yet** (unmeasured error behaviour for
  oversize input; see open items).
- The process exits 0 even for invalid requests; the error rides in
  stdout (core-protocol.json, 28 cases).

## Method inventory (19, from core-golden.json byMethod, 212 cases)

Implementable (14):

| Method | Golden cases | Notes |
|---|---|---|
| hello | 1 | Handshake. Returns our own implementation/buildID (below). |
| normalizeRouting | 8 | Pure routing normalizer. |
| normalizeGroups | 9 | Pure groups normalizer. |
| builtinTags | 2 | Returns {direct, block} tags. |
| emitGroups | 121 | The bulk: group -> outbound emission matrix. |
| normalizePolicy | 2 | |
| normalizeCustom | 2 | Not in state-schema's 15; present in golden. |
| routingFingerprint | 8 | String hash of routing; algorithm to be derived from pairs. |
| migrateStoredRouting | 3 | RPC name -> engine migrateRouting. |
| classes | 2 | routing + members + builtin + selections -> policy map. |
| entryPlan | 3 | Plan: mode/reason/needSets/needCidrs/directAnswer. |
| bypassPlan | 3 | Plan: sets + pending (hashed by panel into nativeBypassPlanKey). |
| forwardPlan | 3 | Plan with rewriteDomains. |
| configDetailed | 25 | The monster: full 18-field state -> config + dnsRuleOwners + directHosts + failover. Last. |

Excluded (5, licence family — authorization/verification is out of
scope for this project, same boundary as the panel):

- activationState, checkActivationCode, verifyLicense,
  authorizationState, featureAccess

For these the replica answers a distinct out-of-scope error, never
licence logic and never a forged success.

## Error states (distinct, never conflated)

Measured (core-protocol.json, 28 cases against core v0.1.337), in
check order (fixture _meta: "trailing data is checked BEFORE protocol;
both are checked after the first decode"):

- `invalid native-core request`: first-decode failures (syntax, a
  non-object top-level value, a mistyped field: string/float/bool
  protocol, non-string license, non-array geoTags/args, non-string
  method, a BOM, empty/blank input).
- `trailing native-core request data`: non-whitespace data after the
  first value. (Trailing whitespace is EOF, not data.)
- `native-core protocol mismatch`: protocol value after a clean decode
  (absent/null -> 0, any int other than 1).
- `unsupported native-core method`: method after a clean decode with
  good protocol (absent/null/empty/unknown; names are case sensitive).
  NOTE: an earlier static note claimed the string was "unknown method";
  the measured fixture says "unsupported native-core method" and
  measurement wins.
- `not implemented yet`: a known implementable method with no
  implementation yet. Ours, not the original's.
- `licence methods are out of scope for this replica`: the 5 excluded
  methods. Ours, not the original's.

Field names are matched case-insensitively (Go decoder semantics,
exact match wins); `args` may be absent or null (both mean []).
All four measured sentences are user-visible: the panel's rpc wrapper
throws on body.error and the /api handler copies it into a 500 {error}.

## hello and the panel pin (open item)

The original's hello value (measured) is:

```json
{"bindingSha256": "1a985f…", "buildID": "ad37b934…",
 "implementation": "go-native",
 "methods": ["configDetailed", "normalizeRouting", "normalizePolicy",
   "normalizeCustom", "classes", "entryPlan", "bypassPlan",
   "forwardPlan", "emitGroups", "checkActivationCode", "verifyLicense",
   "authorizationState", "featureAccess"],
 "protocol": 1}
```

This replica answers hello with its own values:

- `implementation`: `oss-python` (not `go-native`; we do not impersonate)
- `buildID`: `oss-core-replica-0.1.0`
- `methods`: what this replica actually supports (excluding the
  handshake itself, as in the original's list); it starts empty and
  grows as methods are implemented
- `bindingSha256`: omitted. Its input is unknown (possibly a hash of
  the panel binding), and forging the original's hash would be
  impersonation. Our stack does not check it.

Consequence: this replica is **not** a drop-in for the original panel
(the original panel pins the core's buildID and reportedly throws
`原生核心与面板组件版本不匹配` on mismatch; a third-party note says
"warns" instead of "throws" — unresolved, and it does not block our
stack, which does not pin). It is a behavioural equivalent for our
own stack.

## Harness

`harness.py --golden <core-golden.json> [--method NAME]` feeds each
case's args through `main.handle` and diffs (ok, value/error). Diff
output masks credential-like keys (password, token, secret, uuid,
cert, tlsCert, …): it reports paths, never values, for those keys.
The golden corpus itself is **not** copied into the repo (35 MB, and
it is a snapshot of a live install's app_storage): pass its path
explicitly when running the harness.

## Queue (after this slice)

1. DONE (2026-10-29): normalizeRouting / normalizeGroups /
   normalizePolicy / normalizeCustom — 21/21 golden cases via
   harness.py (8+9+2+2). Rules in methods/normalize.py; anything not
   directly measured is marked INFERRED there (activePolicies =
   enabled policies; ruleUrls count as rule content; urltest
   idleTimeout default "12h"; unknown group types -> selector;
   positional policy id/name defaults by analogy with groups).
2. DONE (2026-10-29): builtinTags — 2/2 golden cases
   (methods/tags.py). Identification is by group id; renamed or
   disabled builtins are INFERRED (both measured cases use the
   defaults with enabled true).
3. OPEN: routingFingerprint — see below. Deliberately NOT
   implemented with a guessed hash: a wrong fingerprint silently
   breaks change detection, while "not implemented yet" fails loudly.
4. DONE (2026-10-29): emitGroups — 121/121 golden cases
   (methods/emit.py). Rules: normalize-then-emit in group order;
   builtins short-circuit to direct/block outbounds; disabled user
   groups skipped; selector/urltest members resolve against
   allOutbounds tags (empty -> placeholder [directTag]); urltest
   intervals kept RAW while failover intervals go through
   strict+salvage validation ([5s, 24h], salvage extracts the first
   duration token or bare seconds, whitespace -> bad); failover
   lanes dedup, mode single/urltest/empty by valid count, sub
   idle_timeout = max(interval, 12h) with idleTimeout ignored;
   mode "dynamic" groups expand to ALL allOutbounds tags; dropped
   is always [] in the corpus; args[2] (chain outbounds) has no
   measured effect on validity.
5. DONE (2026-10-29): classes (2/2), entryPlan (3/3), bypassPlan
   (3/3), forwardPlan (3/3) — methods/plans.py. classes resolves
   each policy + the fallback through live selections (direct /
   block builtins, else proxy). entry/bypass share the entry
   gating (enabled flag, FakeIP, fallback class) with fixed
   Chinese reason strings; entryPlan whitelist collects proxy/block
   geoip sets + cidrs (custom first, deduped); bypassPlan lists
   direct policies with geoip sets as pending against earlier
   proxy/block IP conditions (templated reason); forwardPlan
   collects proxy domains + geosite expansions (+ rewriteDomains
   last), mode all vs domains by fallback class.
6. migrateStoredRouting.
7. configDetailed (25 cases, 18-field state, 9 sections — last).

## routingFingerprint: derivation status (OPEN, not guessed)

Values are 16 hex chars (64-bit). Proven constraints from the 8
golden pairs (equivalence classes, hash-function independent):

- empty == nullValue == noPolicies == garbage (all d8a2998b77cba36e).
  noPolicies differs from empty ONLY in fallback.default
  ("direct" vs "") after normalization, so fallback.default is
  EXCLUDED from the hash input.
- garbage == empty: mistyped policies/fallbackName normalize to the
  defaults, so the hash input is normalized, not raw.
- real != duplicateNames with IDENTICAL custom and fallback fields:
  policies DEFINITIVELY enter the hash.
- real != fallbackMissing (differ in custom + fallback icon):
  custom or fallback icon enters.
- policyWithoutRules != empty: consistent with custom entering
  (it carries the real custom rules); it does not by itself prove
  ruleless policies survive normalization.

Ruled out for the empty case (hash implementations verified against
known vectors: FNV-1a, xxhash64, Murmur3): every JSON serialization
(sorted / insertion-order / all key permutations, compact / spaced /
2-space indent, UTF-8 / ASCII, Go HTML-escaped, omitempty, with or
without trailing newline) of the normalized routing and its subsets
(full, policies+custom, policies+custom+fallback-name/icon,
custom-only), times FNV-1a, FNV-1, xxhash64, xxh3_64, xxh128,
CRC64-ISO/ECMA, SHA-256, MD5, SHA-1, BLAKE2b-8, SHA-512 (first 8
bytes, big- and little-endian), FNV-1a-128, Murmur3 x64_128;
Go %v struct formats; and 16 constant prefixes. None matches
d8a2998b77cba36e.

Next experiment to crack it (needs a new capture, not more guessing):
vary ONE field at a time from the empty routing — add one minimal
policy; rename custom; change fallback icon; change fallback
default — and record which variations change the hash. That pins
down exactly which fields enter, after which the serialization can
be re-attacked with the field set known.
