#!/bin/bash
# ENISHI Desktopを開発モードで起動する（Rust + Node が必要）
set -eu
cd "$(dirname "$0")/.."

./scripts/check_macos_env.sh
cd apps/desktop
exec npm run tauri dev
