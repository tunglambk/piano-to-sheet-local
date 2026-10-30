#!/usr/bin/env bash
# Make the bundled MuseScore able to render PDFs headlessly, without root.
#
# MuseScore 4 is an AppImage-like bundle that misses one system library
# (libpipewire-0.3) and, even when that is present, refuses to start with Qt's
# offscreen plugin. The bundle works under Xvfb, and the library can be unpacked
# into .tools/mscore-libs/ from the distribution package with dpkg-deb, which
# needs no privileges.
#
#   ./scripts/setup_musescore.sh
set -euo pipefail
cd "$(dirname "$0")/.."
libs=".tools/mscore-libs"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$libs"
missing="$(ldd .tools/mscore/bin/mscore4portable 2>/dev/null | awk '/not found/ {print $1}' || true)"
if [ -z "$missing" ]; then
  echo "no missing libraries"
else
  echo "missing: $missing"
fi
for name in $missing; do
  case "$name" in
    libpipewire-0.3.so.0) pkg=libpipewire-0.3-0 ;;
    libxcb-cursor.so.0) pkg=libxcb-cursor0 ;;
    *) echo "no mapping for $name; install it manually with root" >&2; continue ;;
  esac
  ( cd "$tmp" && apt-get download "$pkg" >/dev/null 2>&1 )
  deb="$(ls "$tmp"/*.deb | head -1)"
  dpkg-deb -x "$deb" "$tmp/root"
  cp -a "$tmp"/root/usr/lib/x86_64-linux-gnu/*.so* "$libs/"
  rm -f "$tmp"/*.deb && rm -rf "$tmp/root"
done
if command -v xvfb-run >/dev/null 2>&1; then
  echo "xvfb-run present"
else
  echo "install xvfb (needs root: apt-get install xvfb) — MuseScore needs an X display" >&2
fi
LD_LIBRARY_PATH="$PWD/$libs" xvfb-run -a .tools/mscore/AppRun --version 2>&1 | head -1
