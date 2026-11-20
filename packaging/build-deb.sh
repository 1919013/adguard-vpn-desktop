#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=${1:-0.2.0~dev}
ARCH=all
PKG="adguard-vpn-desktop_${VERSION}_${ARCH}"
STAGE="$ROOT/build/$PKG"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib/adguard-vpn-desktop" \
    "$STAGE/usr/bin" "$STAGE/usr/share/applications"

sed "s/^Version: .*/Version: $VERSION/" "$ROOT/packaging/control" > "$STAGE/DEBIAN/control"
install -m 0755 "$ROOT/packaging/adguard-vpn-desktop" "$STAGE/usr/bin/adguard-vpn-desktop"
install -m 0644 "$ROOT/packaging/adguard-vpn-desktop.desktop" \
    "$STAGE/usr/share/applications/adguard-vpn-desktop.desktop"

for directory in core modules services ui; do
    cp -a "$ROOT/$directory" "$STAGE/usr/lib/adguard-vpn-desktop/"
done
install -m 0644 "$ROOT/main.py" "$ROOT/config.py" "$STAGE/usr/lib/adguard-vpn-desktop/"

find "$STAGE/usr/lib/adguard-vpn-desktop" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGE/usr/lib/adguard-vpn-desktop" -type f -name '*.pyc' -delete

mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$STAGE" "$ROOT/dist/$PKG.deb"
printf 'Built package: %s\n' "$ROOT/dist/$PKG.deb"
