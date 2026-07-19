#!/bin/bash
# Developer ID署名・Apple公証・Tauri updater署名を行う正式配布ビルド。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
: "${APPLE_SIGNING_IDENTITY:?APPLE_SIGNING_IDENTITY is required}"
: "${TAURI_SIGNING_PRIVATE_KEY:?TAURI_SIGNING_PRIVATE_KEY is required}"
: "${TAURI_UPDATER_PUBLIC_KEY:?TAURI_UPDATER_PUBLIC_KEY is required}"

if [ -z "${APPLE_API_ISSUER:-}" ] || [ -z "${APPLE_API_KEY:-}" ] || [ -z "${APPLE_API_KEY_PATH:-}" ]; then
  : "${APPLE_ID:?APPLE_ID or App Store Connect API credentials are required}"
  : "${APPLE_PASSWORD:?APPLE_PASSWORD is required}"
  : "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required}"
fi

CONFIG_PATH="$ROOT_DIR/.tmp/tauri.release.conf.json"
python3 "$ROOT_DIR/scripts/create_macos_release_config.py" --output "$CONFIG_PATH" >/dev/null

cd "$ROOT_DIR/apps/desktop"
npm exec tauri -- build --ci --config "$CONFIG_PATH" --bundles app
npm exec tauri -- bundle --verbose --ci --config "$CONFIG_PATH" --bundles dmg
npm exec tauri -- bundle --ci --config "$CONFIG_PATH" --bundles app

exec "$ROOT_DIR/scripts/verify_macos_release.sh"
