#!/bin/bash
# 署名、公証staple、updater署名まで正式配布物を検証する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_DIR="$ROOT_DIR/apps/desktop/src-tauri/target/release/bundle"
APP_PATH="$BUNDLE_DIR/macos/ENISHI.app"
CORE_BINARY="$APP_PATH/Contents/MacOS/enishi-core"
UPDATER_ARCHIVE="$BUNDLE_DIR/macos/ENISHI.app.tar.gz"
UPDATER_SIGNATURE="$UPDATER_ARCHIVE.sig"
DMG_PATH="$(find "$BUNDLE_DIR/dmg" -name '*.dmg' -type f -print -quit)"

"$ROOT_DIR/scripts/verify_macos_bundle.sh"

for path in "$APP_PATH" "$CORE_BINARY" "$UPDATER_ARCHIVE" "$UPDATER_SIGNATURE"; do
  if [ ! -e "$path" ]; then
    echo "Missing signed release artifact: $path" >&2
    exit 1
  fi
done

codesign --verify --deep --strict --verbose=2 "$APP_PATH"
codesign --verify --strict --verbose=2 "$CORE_BINARY"
if ! codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep -q "Authority=Developer ID Application:"; then
  echo "Developer ID Application signature not found." >&2
  exit 1
fi
spctl --assess --type execute --verbose=2 "$APP_PATH"
xcrun stapler validate "$APP_PATH"
xcrun stapler validate "$DMG_PATH"

if [ ! -s "$UPDATER_SIGNATURE" ]; then
  echo "Updater signature is empty." >&2
  exit 1
fi

echo "Signed macOS release verified:"
echo "  App: $APP_PATH"
echo "  Updater: $UPDATER_ARCHIVE"
