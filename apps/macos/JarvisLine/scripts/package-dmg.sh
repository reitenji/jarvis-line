#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Jarvis Line"
DMG_NAME="${DMG_NAME:-JarvisLine-macOS.dmg}"
DIST_DIR="$ROOT_DIR/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/$DMG_NAME"

detach_existing_image() {
  local device
  device="$(hdiutil info | awk -v target="$DMG_PATH" '
    index($0, "image-path") == 1 && index($0, target) > 0 { found = 1; next }
    found && $1 ~ /^\/dev\/disk[0-9]+$/ { print $1; exit }
  ')"
  if [[ -n "$device" ]]; then
    hdiutil detach "$device" -quiet || hdiutil detach "$device" -force -quiet
  fi
}

cd "$ROOT_DIR"
if [[ "${SKIP_APP_BUILD:-0}" != "1" ]]; then
  "$ROOT_DIR/scripts/package-app.sh"
fi
if [[ ! -d "$APP_DIR" ]]; then
  echo "Missing app bundle: $APP_DIR" >&2
  exit 1
fi

detach_existing_image
rm -rf "$DIST_DIR/dmg-root" "$DMG_PATH"
STAGE_DIR="$(mktemp -d "$DIST_DIR/dmg-root.XXXXXX")"
cleanup() {
  rm -rf "$STAGE_DIR"
}
trap cleanup EXIT

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
(
  cd "$DIST_DIR"
  shasum -a 256 "$DMG_NAME" > "$DMG_NAME.sha256"
)

echo "Created: $DMG_PATH"
echo "Checksum: $DMG_PATH.sha256"
echo "Install: open '$DMG_PATH', then drag '$APP_NAME.app' to Applications."
