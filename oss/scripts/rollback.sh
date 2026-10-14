#!/bin/sh
# openbox-oss rollback script: restores the previous kernel binary.
set -eu
PREFIX="${OBX_PREFIX:-/opt/openbox-oss}"
[ -x "$PREFIX/bin/sing-box.prev" ] || { echo "no rollback copy found" >&2; exit 1; }
/etc/init.d/openbox-oss stop || true
mv "$PREFIX/bin/sing-box.prev" "$PREFIX/bin/sing-box"
/etc/init.d/openbox-oss start
echo "[openbox-oss] rolled back to: $("$PREFIX/bin/sing-box" version | head -n 1)"
