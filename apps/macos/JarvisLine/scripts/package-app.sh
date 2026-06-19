#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Jarvis Line"
PRODUCT_NAME="JarvisLine"
CONFIGURATION="${CONFIGURATION:-release}"
BUILD_DIR="$ROOT_DIR/.build/$CONFIGURATION"
DIST_DIR="$ROOT_DIR/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"

cd "$ROOT_DIR"
swift build -c "$CONFIGURATION" --product "$PRODUCT_NAME"

rm -rf "$APP_DIR" "$DIST_DIR/JarvisLine.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cp "$ROOT_DIR/Resources/Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$ROOT_DIR/Resources/AppIcon.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"
cp "$BUILD_DIR/$PRODUCT_NAME" "$APP_DIR/Contents/MacOS/$PRODUCT_NAME"
chmod +x "$APP_DIR/Contents/MacOS/$PRODUCT_NAME"

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_DIR" >/dev/null
fi

echo "Created: $APP_DIR"
echo "Open with: open '$APP_DIR'"
