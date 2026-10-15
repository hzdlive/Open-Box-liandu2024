#!/bin/sh
# Download the .srs geodata files referenced by the default site sets.
# Upstream: SagerNet/sing-geosite and SagerNet/sing-geoip (public CDN).
# See oss/THIRD_PARTY_NOTICES.md for data licenses/attribution.
set -u

GEODIR="${OBX_GEODATA:-$HOME/.openbox-oss/geodata}"
mkdir -p "$GEODIR"

# rule-sets referenced by the seeded site sets (keep in sync with db.py seeds)
# NOTE: geoip-private is expanded inline (core/geodata.py INLINE_RULE_SETS);
# geoip-twitter is no longer published upstream and is skipped with a warning.
NAMES="geosite-category-ai-!cn geosite-youtube geosite-tiktok geosite-tiktok@!cn
geosite-netflix geosite-github geosite-google geosite-microsoft geosite-apple
geosite-steam geosite-sony geosite-gfw geosite-cn
geoip-netflix geoip-cloudflare geoip-facebook geoip-cloudfront geoip-fastly
geoip-google geoip-telegram geoip-tor geoip-cn"

fail=0
for n in $NAMES; do
  dest="$GEODIR/$n.srs"
  if [ -s "$dest" ]; then echo "ok: $n"; continue; fi
  case "$n" in
    geosite-*)
      urls="https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/$n.srs
https://ghfast.top/https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/$n.srs";;
    geoip-*)
      urls="https://cdn.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set/$n.srs
https://ghfast.top/https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/$n.srs";;
  esac
  got=0
  for u in $urls; do
    if wget -q -T 60 -O "$dest.part" "$u" && [ -s "$dest.part" ]; then
      mv "$dest.part" "$dest"; got=1; echo "fetched: $n"; break
    fi
    rm -f "$dest.part"
  done
  [ "$got" -eq 1 ] || { echo "FAIL: $n" >&2; fail=1; }
done
exit $fail
