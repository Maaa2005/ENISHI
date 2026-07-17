#!/bin/bash
# TauriのbeforeBuildCommand: UIとLocal Coreサイドカーを配布用に準備する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR/apps/desktop"
npm run build

exec "$ROOT_DIR/scripts/build_core_sidecar.sh"
