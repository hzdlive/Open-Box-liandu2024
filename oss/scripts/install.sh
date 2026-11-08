#!/bin/sh
# openbox-oss install script (Debian + OpenWrt, amd64/arm64).
# Installs the sing-box kernel + oss-core binary + panel files +
# service (systemd on Debian, procd on OpenWrt).
# Usage: ./install.sh [--kernel-url URL] [--core-url URL]
#        [--panel-dir DIR] [--version VER]
#   --kernel-url / --core-url: direct download links for the target
#     arch's binaries (workflow artifacts: sing-box-tcp23-linux-<arch>
#     and oss-core-linux-<arch>). Both are required: there is no
#     default upstream for the OSS branch.
#   --panel-dir: panel source tree (default: the repo checkout this
#     script lives in, i.e. <script-dir>/..). Only the runtime set is
#     installed: core/, panel/, dashboard/zashboard-src/dist/,
#     requirements.txt.
# Environment overrides: OBX_PREFIX (default /opt/openbox-oss),
#   OBX_SKIP_GEODATA=1, OBX_SKIP_DEPS=1 (skip python/pip setup).
set -eu

PREFIX="${OBX_PREFIX:-/opt/openbox-oss}"
VERSION=""
KERNEL_URL=""
CORE_URL=""
PANEL_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --kernel-url) KERNEL_URL="$2"; shift 2;;
    --core-url) CORE_URL="$2"; shift 2;;
    --panel-dir) PANEL_DIR="$2"; shift 2;;
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

# OS + init system.
if [ -f /etc/openwrt_release ]; then
  OS="openwrt"
elif [ -f /etc/os-release ] && grep -qiE '^(ID|ID_LIKE)=.*debian' /etc/os-release; then
  OS="debian"
elif command -v systemctl >/dev/null 2>&1; then
  OS="debian"
else
  echo "unsupported OS: neither OpenWrt nor Debian/systemd detected" >&2
  exit 1
fi
echo "[openbox-oss] arch=$SARCH os=$OS prefix=$PREFIX"

if [ -z "$KERNEL_URL" ]; then
  echo "error: --kernel-url is required (no default upstream for the OSS branch)" >&2
  echo "hint: build from the GPL source bundle or point at your own release asset" >&2
  exit 1
fi
if [ -z "$CORE_URL" ]; then
  echo "error: --core-url is required (no default upstream for the OSS branch)" >&2
  echo "hint: build oss/core-go (see .github/workflows/core.yml) or point at your own release asset" >&2
  exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -z "$PANEL_DIR" ]; then
  PANEL_DIR="$SCRIPT_DIR/.."
fi
[ -d "$PANEL_DIR/core" ] && [ -d "$PANEL_DIR/panel" ] && [ -f "$PANEL_DIR/requirements.txt" ] || {
  echo "error: panel source not found at $PANEL_DIR (need core/, panel/, requirements.txt)" >&2
  echo "hint: run from a repo checkout or pass --panel-dir <oss/>" >&2
  exit 1
}

# Download helper: curl preferred, wget fallback (OpenWrt has wget).
download() {
  _url="$1"; _out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fSL --retry 3 "$_url" -o "$_out"
  else
    wget -O "$_out" "$_url"
  fi
}

# Install one binary from a URL. Accepts a bare binary or a gzip
# tarball containing it; verifies by running it afterwards.
install_binary() {
  _url="$1"; _name="$2"; _dest="$3"
  echo "[openbox-oss] downloading $_name: $_url"
  download "$_url" "$TMPD/$_name.download"
  if gzip -t "$TMPD/$_name.download" 2>/dev/null; then
    mkdir -p "$TMPD/$_name"
    tar -xzf "$TMPD/$_name.download" -C "$TMPD/$_name"
    _bin="$(find "$TMPD/$_name" -name "$_name" -type f | head -n 1)"
    [ -n "$_bin" ] || { echo "$_name not found in tarball" >&2; exit 1; }
  else
    _bin="$TMPD/$_name.download"
  fi
  install -m 0755 "$_bin" "$_dest"
}

echo "[openbox-oss] installing to $PREFIX"
mkdir -p "$PREFIX/bin" "$PREFIX/etc" "$PREFIX/var" "$PREFIX/panel"

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT
install_binary "$KERNEL_URL" "sing-box" "$PREFIX/bin/sing-box"
"$PREFIX/bin/sing-box" version
install_binary "$CORE_URL" "oss-core" "$PREFIX/bin/oss-core"
"$PREFIX/bin/oss-core" version
# Also on PATH for manual use (best effort).
if [ -d /usr/local/bin ] && [ -w /usr/local/bin ]; then
  ln -sf "$PREFIX/bin/oss-core" /usr/local/bin/oss-core
  ln -sf "$PREFIX/bin/sing-box" /usr/local/bin/sing-box
fi

# Panel files: only the runtime set (core/, panel/, the built Vue UI
# dashboard/zashboard-src/dist/, requirements.txt). The zabbix
# source + node_modules (~600M) stay out.
echo "[openbox-oss] installing panel files from $PANEL_DIR"
[ -d "$PANEL_DIR/dashboard/zashboard-src/dist" ] || {
  echo "error: built Vue UI not found at $PANEL_DIR/dashboard/zashboard-src/dist" >&2
  echo "hint: build it first (oss/panel/frontend or oss/dashboard/zabbix-src)" >&2
  exit 1
}
rm -rf "$PREFIX/panel"
mkdir -p "$PREFIX/panel"
(cd "$PANEL_DIR" && tar --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='node_modules' --exclude='.venv' \
  -cf - core panel dashboard/zashboard-src/dist requirements.txt) | (cd "$PREFIX/panel" && tar -xf -)

# Python deps in a venv.
if [ -z "${OBX_SKIP_DEPS:-}" ]; then
  if [ "$OS" = "debian" ]; then
    echo "[openbox-oss] installing python3 + venv (apt)"
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip
  else
    echo "[openbox-oss] installing python3 + pip (opkg)"
    opkg update
    opkg install python3 python3-pip
  fi
  if [ ! -x "$PREFIX/venv/bin/python" ]; then
    echo "[openbox-oss] creating venv at $PREFIX/venv"
    python3 -m venv "$PREFIX/venv" || {
      echo "error: python3 -m venv failed (on OpenWrt, python3-venv may be missing)" >&2
      exit 1
    }
  fi
  echo "[openbox-oss] installing panel python deps"
  "$PREFIX/venv/bin/pip" install -q -r "$PREFIX/panel/requirements.txt"
  "$PREFIX/venv/bin/python" -c "import flask, yaml, qrcode; print('panel deps ok')"
fi

# Service: systemd on Debian, procd on OpenWrt. The panel owns the
# kernel (autostart on boot); the kernel procd script is only a
# fallback for running sing-box standalone.
if [ "$OS" = "debian" ]; then
  echo "[openbox-oss] installing systemd unit"
  mkdir -p /etc/systemd/system
  sed "s|@PREFIX@|$PREFIX|g" "$SCRIPT_DIR/openbox-oss-panel.service" \
    > /etc/systemd/system/openbox-oss-panel.service
  systemctl daemon-reload
  systemctl enable openbox-oss-panel.service
else
  echo "[openbox-oss] installing procd inits"
  cp "$SCRIPT_DIR/openbox-oss.init" /etc/init.d/openbox-oss
  chmod +x /etc/init.d/openbox-oss
  /etc/init.d/openbox-oss enable
  cp "$SCRIPT_DIR/openbox-oss-panel.init" /etc/init.d/openbox-oss-panel
  chmod +x /etc/init.d/openbox-oss-panel
  /etc/init.d/openbox-oss-panel enable
fi

# Geodata (.srs rule-sets referenced by the default site sets). Best effort:
# the panel downloads missing files on demand anyway (see core/geodata.py).
if [ -z "${OBX_SKIP_GEODATA:-}" ]; then
  echo "[openbox-oss] downloading geodata (best effort)"
  OBX_PREFIX="$PREFIX" "$SCRIPT_DIR/fetch-geodata.sh" || echo "[openbox-oss] geodata download incomplete; the panel will retry on demand" >&2
fi

echo "[openbox-oss] installed. Next:"
if [ "$OS" = "debian" ]; then
  echo "  1. start the panel: systemctl start openbox-oss-panel"
  echo "  2. open http://127.0.0.1:8081/, configure, then 'apply config' to start the kernel"
else
  echo "  1. start the panel: /etc/init.d/openbox-oss-panel start"
  echo "  2. open http://127.0.0.1:8081/, configure, then 'apply config' to start the kernel"
fi
