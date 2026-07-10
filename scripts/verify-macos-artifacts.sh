#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="$ROOT_DIR/apps/macos/JarvisLine"
APP_PATH="$APP_ROOT/dist/Jarvis Line.app"
DMG_PATH="$APP_ROOT/dist/JarvisLine-macOS.dmg"
MOUNT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-line-dmg.XXXXXX")"
ATTACHED=0

cleanup() {
  if [[ "$ATTACHED" -eq 1 ]]; then
    hdiutil detach "$MOUNT_DIR" -quiet || true
  fi
  rmdir "$MOUNT_DIR" 2>/dev/null || true
}
trap cleanup EXIT

"$APP_ROOT/scripts/package-app.sh"
plutil -lint "$APP_PATH/Contents/Info.plist"
test -x "$APP_PATH/Contents/MacOS/JarvisLine"
codesign --verify --deep --strict "$APP_PATH"

SKIP_APP_BUILD=1 "$APP_ROOT/scripts/package-dmg.sh"
test -s "$DMG_PATH"
test -s "$DMG_PATH.sha256"
hdiutil attach "$DMG_PATH" -nobrowse -readonly -mountpoint "$MOUNT_DIR" -quiet
ATTACHED=1

APP_COUNT="$(find "$MOUNT_DIR" -maxdepth 1 -type d -name '*.app' | wc -l | tr -d ' ')"
if [[ "$APP_COUNT" != "1" || ! -d "$MOUNT_DIR/Jarvis Line.app" ]]; then
  echo "Expected exactly one Jarvis Line.app in the DMG, found $APP_COUNT." >&2
  exit 1
fi

hdiutil detach "$MOUNT_DIR" -quiet
ATTACHED=0
(
  cd "$(dirname "$DMG_PATH")"
  shasum -a 256 -c "$(basename "$DMG_PATH").sha256"
)

echo "macos_artifacts_ok"
