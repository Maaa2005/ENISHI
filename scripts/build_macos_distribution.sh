#!/bin/bash
# Local Coreを同梱した未署名macOSアプリとDMGを再現可能な手順で生成する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR/apps/desktop"
# `.app`生成とDMG作成を分離する。create-dmgが失敗した場合に、サイドカーを
# 再生成せず詳細なhdiutil/Finderログを残してDMG工程だけ再実行できるようにする。
npm exec tauri -- build --ci --config src-tauri/tauri.bundle.conf.json --no-sign --bundles app
npm exec tauri -- bundle --verbose --ci --config src-tauri/tauri.bundle.conf.json --no-sign --bundles dmg
# DMG bundlerは入力に使った一時`.app`をcleanするため、配布物として残す`.app`を
# 最後に再bundleする（Rust/sidecarの再ビルドは発生しない）。
npm exec tauri -- bundle --ci --config src-tauri/tauri.bundle.conf.json --no-sign --bundles app

exec "$ROOT_DIR/scripts/verify_macos_bundle.sh"
