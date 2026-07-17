#!/bin/bash
# 現在のmacOSアーキテクチャ向けLocal CoreをTauri externalBin形式で生成する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CORE_DIR="$ROOT_DIR/services/local-core"
TARGET_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
OUTPUT_DIR="$ROOT_DIR/apps/desktop/src-tauri/binaries"
OUTPUT_PATH="$OUTPUT_DIR/enishi-core-$TARGET_TRIPLE"

case "$TARGET_TRIPLE" in
  aarch64-apple-darwin|x86_64-apple-darwin) ;;
  *)
    echo "Unsupported distribution target: $TARGET_TRIPLE" >&2
    exit 1
    ;;
esac

mkdir -p "$OUTPUT_DIR"
cd "$CORE_DIR"
uv run --group distribution pyinstaller --noconfirm --clean enishi-core.spec
cp "dist/enishi-core" "$OUTPUT_PATH"
chmod 755 "$OUTPUT_PATH"
echo "Local Core sidecar: $OUTPUT_PATH"
