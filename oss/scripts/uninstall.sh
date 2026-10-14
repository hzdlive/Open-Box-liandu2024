#!/bin/sh
# openbox-oss uninstall script.
set -eu
PREFIX="${OBX_PREFIX:-/opt/openbox-oss}"
/etc/init.d/openbox-oss stop || true
/etc/init.d/openbox-oss disable || true
rm -f /etc/init.d/openbox-oss
echo "[openbox-oss] removing $PREFIX (config backup kept at ${PREFIX}.bak)"
mv "$PREFIX" "${PREFIX}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
echo "[openbox-oss] uninstalled"
