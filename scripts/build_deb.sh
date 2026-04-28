#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-1.0.0}"
BUILD="$ROOT/build/deb/rclone-service-tray_${VERSION}_all"
DIST="$ROOT/dist"

rm -rf "$BUILD"
install -d -m 0755 "$BUILD/DEBIAN" "$BUILD/usr/bin" "$BUILD/usr/lib/rclone-service-tray" \
  "$BUILD/usr/share/applications" "$BUILD/usr/share/icons/hicolor/scalable/apps" "$DIST"

cp "$ROOT/packaging/deb/control" "$BUILD/DEBIAN/control"
sed -i "s/^Version:.*/Version: ${VERSION}/" "$BUILD/DEBIAN/control"
tar -C "$ROOT" \
  --exclude='*/__pycache__' \
  --exclude='*.py[co]' \
  -cf - rclonetray | tar -C "$BUILD/usr/lib/rclone-service-tray/" -xf -
cp "$ROOT/requirements.txt" "$ROOT/pyproject.toml" "$BUILD/usr/lib/rclone-service-tray/"
cp "$ROOT/packaging/deb/rclone-service-tray.desktop" "$BUILD/usr/share/applications/rclone-service-tray.desktop"
cp "$ROOT/rclonetray/resources/icons/rclone-service-tray.svg" "$BUILD/usr/share/icons/hicolor/scalable/apps/rclone-service-tray.svg"

cat > "$BUILD/usr/bin/rclone-service-tray" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/usr/lib/rclone-service-tray"
if ! python3 -c "import PySide6" >/dev/null 2>&1; then
  echo "PySide6 no está instalado. Instala python3-pyside6 o ejecuta: python3 -m pip install --user PySide6" >&2
  exit 1
fi
export PYTHONPATH="$APP_DIR:${PYTHONPATH:-}"
exec python3 -m rclonetray "$@"
EOF
find "$BUILD" -type d -exec chmod 0755 {} +
find "$BUILD" -type f -exec chmod 0644 {} +
chmod 0755 "$BUILD/usr/bin/rclone-service-tray"
dpkg-deb --root-owner-group --build "$BUILD" "$DIST/rclone-service-tray_${VERSION}_all.deb"
