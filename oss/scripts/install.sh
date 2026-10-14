#!/bin/sh
# openbox-oss install script (OpenWrt).
# Installs the sing-box kernel + panel files + procd init script.
# Usage: ./install.sh [--kernel-url URL] [--version VER]
# Environment overrides: OBX_PREFIX (default /opt/openbox-oss)
set -eu

PREFIX="${OBX_PREFIX:-/opt/openbox-oss}"
VERSION=""
KERNEL_URL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --kernel-url) KERNEL_URL="$2"; shift 2;;
    --version) VERSION="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) SARCH="arm64";;
  x86_64|amd64) SARCH="amd64";;
  *) echo "unsupported arch: $ARCH" >&2; exit 1;;
esac

if [ -z "$KERNEL_URL" ]; then
  echo "error: --kernel-url is required (no default upstream for the OSS branch)" >&2
  echo "hint: build from the GPL source bundle or point at your own release asset" >&2
  exit 1
fi

echo "[openbox-oss] installing to $PREFIX"
mkdir -p "$PREFIX/bin" "$PREFIX/etc" "$PREFIX/var"

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT
echo "[openbox-oss] downloading kernel: $KERNEL_URL"
wget -O "$TMPD/kernel.tar.gz" "$KERNEL_URL"
tar -xzf "$TMPD/kernel.tar.gz" -C "$TMPD"
BIN="$(find "$TMPD" -name 'sing-box' -type f | head -n 1)"
[ -n "$BIN" ] || { echo "sing-box binary not found in tarball" >&2; exit 1; }
install -m 0755 "$BIN" "$PREFIX/bin/sing-box"
"$PREFIX/bin/sing-box" version

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cp "$SCRIPT_DIR/openbox-oss.init" /etc/init.d/openbox-oss
chmod +x /etc/init.d/openbox-oss
/etc/init.d/openbox-oss enable

echo "[openbox-oss] installed. Next:"
echo "  1. start the panel: $PREFIX/panel/run.sh (or python3 panel/run.py)"
echo "  2. open the panel, configure, then 'apply config' to start the kernel"
