#!/bin/bash
# 生成したmacOS配布物に、実行可能なDesktop/Coreと必要なmetadataがあることを確認する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_DIR="$ROOT_DIR/apps/desktop/src-tauri/target/release/bundle"
APP_PATH="$BUNDLE_DIR/macos/ENISHI.app"
INFO_PLIST="$APP_PATH/Contents/Info.plist"
DESKTOP_BINARY="$APP_PATH/Contents/MacOS/enishi-desktop"
CORE_BINARY="$APP_PATH/Contents/MacOS/enishi-core"
TARGET_ARCH="$(uname -m)"

case "$TARGET_ARCH" in
  arm64) DMG_ARCH="aarch64" ;;
  x86_64) DMG_ARCH="x64" ;;
  *)
    echo "Unsupported macOS architecture: $TARGET_ARCH" >&2
    exit 1
    ;;
esac

for path in "$INFO_PLIST" "$DESKTOP_BINARY" "$CORE_BINARY"; do
  if [ ! -e "$path" ]; then
    echo "Missing distribution artifact: $path" >&2
    exit 1
  fi
done

VERSION="$(plutil -extract CFBundleShortVersionString raw "$INFO_PLIST")"
DMG_PATH="$BUNDLE_DIR/dmg/ENISHI_${VERSION}_${DMG_ARCH}.dmg"
if [ ! -e "$DMG_PATH" ]; then
  echo "Missing distribution artifact: $DMG_PATH" >&2
  exit 1
fi

if [ ! -x "$DESKTOP_BINARY" ] || [ ! -x "$CORE_BINARY" ]; then
  echo "Bundled Desktop or Local Core is not executable." >&2
  exit 1
fi

if [ "$(plutil -extract CFBundleIdentifier raw "$INFO_PLIST")" != "com.enishi.desktop" ]; then
  echo "Unexpected bundle identifier." >&2
  exit 1
fi

if [ "$(plutil -extract LSMinimumSystemVersion raw "$INFO_PLIST")" != "13.0" ]; then
  echo "Unexpected minimum macOS version." >&2
  exit 1
fi

for binary in "$DESKTOP_BINARY" "$CORE_BINARY"; do
  if ! file "$binary" | grep -q "Mach-O 64-bit executable"; then
    echo "Bundled executable format is invalid: $binary" >&2
    exit 1
  fi
done

echo "macOS distribution verified:"
echo "  App: $APP_PATH"
echo "  DMG: $DMG_PATH"
echo "  SHA-256: $(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
