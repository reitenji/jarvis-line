#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Jarvis Line"
DMG_NAME="${DMG_NAME:-JarvisLine-macOS.dmg}"
DIST_DIR="$ROOT_DIR/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
STAGE_DIR="$DIST_DIR/dmg-root"
DMG_PATH="$DIST_DIR/$DMG_NAME"

cd "$ROOT_DIR"
"$ROOT_DIR/scripts/package-app.sh"

rm -rf "$STAGE_DIR" "$DMG_PATH"
mkdir -p "$STAGE_DIR"

cp -R "$APP_DIR" "$STAGE_DIR/$APP_NAME.app"
ln -s /Applications "$STAGE_DIR/Applications"

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH" >/dev/null

hdiutil verify "$DMG_PATH" >/dev/null

echo "Created: $DMG_PATH"
echo "Install: open '$DMG_PATH', then drag '$APP_NAME.app' to Applications."
