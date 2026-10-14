#!/bin/sh
# openbox-oss upgrade script: replaces the kernel binary, keeps a rollback copy.
# Usage: ./upgrade.sh --kernel-url URL
# On failure the previous binary is restored automatically.
set -eu

PREFIX="${OBX_PREFIX:-/opt/openbox-oss}"
KERNEL_URL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --kernel-url) KERNEL_URL="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done
[ -n "$KERNEL_URL" ] || { echo "--kernel-url is required" >&2; exit 1; }
[ -x "$PREFIX/bin/sing-box" ] || { echo "not installed at $PREFIX" >&2; exit 1; }

echo "[openbox-oss] backing up current kernel"
cp "$PREFIX/bin/sing-box" "$PREFIX/bin/sing-box.prev"

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT
echo "[openbox-oss] downloading new kernel"
if ! wget -O "$TMPD/kernel.tar.gz" "$KERNEL_URL"; then
  echo "download failed, keeping current version" >&2; exit 1
fi
tar -xzf "$TMPD/kernel.tar.gz" -C "$TMPD"
BIN="$(find "$TMPD" -name 'sing-box' -type f | head -n 1)"
[ -n "$BIN" ] || { echo "sing-box binary not found in tarball" >&2; exit 1; }
install -m 0755 "$BIN" "$PREFIX/bin/sing-box.new"

echo "[openbox-oss] validating new kernel"
/etc/init.d/openbox-oss stop || true
if ! "$PREFIX/bin/sing-box.new" check -c "$PREFIX/etc/config.json"; then
  echo "new kernel failed config check, rolling back" >&2
  mv "$PREFIX/bin/sing-box.prev" "$PREFIX/bin/sing-box"
  rm -f "$PREFIX/bin/sing-box.new"
  /etc/init.d/openbox-oss start || true
  exit 1
fi

mv "$PREFIX/bin/sing-box.new" "$PREFIX/bin/sing-box"
/etc/init.d/openbox-oss start
echo "[openbox-oss] upgraded: $("$PREFIX/bin/sing-box" version | head -n 1)"
echo "rollback available via ./rollback.sh"
