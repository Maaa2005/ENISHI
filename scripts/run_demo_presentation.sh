#!/bin/bash
# 先生向けデモ: 新規データで2ノード・Relay・画面をまとめて起動する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export ENISHI_DEMO_UI=1
exec "$ROOT_DIR/scripts/run_demo_all.sh"
