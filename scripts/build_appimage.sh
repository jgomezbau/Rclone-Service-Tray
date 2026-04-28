#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-1.0.0}"
APPDIR="$ROOT/build/appimage/RcloneServiceTray.AppDir"
DIST="$ROOT/dist"
PYTHON_BIN="${PYTHON_BIN:-python3}"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/python3/site-packages" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$DIST"

"$PYTHON_BIN" -m pip install --upgrade --target "$APPDIR/usr/lib/python3/site-packages" "$ROOT"
cp "$(command -v "$PYTHON_BIN")" "$APPDIR/usr/bin/python3"
cp "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/deb/rclone-service-tray.desktop" "$APPDIR/rclone-service-tray.desktop"
cp "$ROOT/packaging/deb/rclone-service-tray.desktop" "$APPDIR/usr/share/applications/rclone-service-tray.desktop"
cp "$ROOT/rclonetray/resources/icons/rclone-service-tray.svg" "$APPDIR/rclone-service-tray.svg"
cp "$ROOT/rclonetray/resources/icons/rclone-service-tray.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/rclone-service-tray.svg"
chmod +x "$APPDIR/AppRun"

if command -v appimagetool >/dev/null 2>&1; then
  appimagetool "$APPDIR" "$DIST/Rclone-Service-Tray-${VERSION}-x86_64.AppImage"
else
  tar -C "$APPDIR" -czf "$DIST/Rclone-Service-Tray-${VERSION}.AppDir.tar.gz" .
  echo "appimagetool no está instalado; se generó un tar.gz del AppDir en dist/."
fi
