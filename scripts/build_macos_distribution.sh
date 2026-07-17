#!/bin/bash
# Local Coreを同梱した未署名macOSアプリとDMGを再現可能な手順で生成する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR/apps/desktop"
npm exec tauri -- build --ci --config src-tauri/tauri.bundle.conf.json --no-sign

exec "$ROOT_DIR/scripts/verify_macos_bundle.sh"
