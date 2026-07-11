#!/bin/bash
# Demo User A のLocal Coreを独立DB・独立鍵で起動する。
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR/services/local-core"

DATA_DIR="$ROOT_DIR/.tmp/demo-user-a"
mkdir -p "$DATA_DIR/cache" "$DATA_DIR/logs"

export TWINLINK_DATA_DIR="$DATA_DIR"
export TWINLINK_CACHE_DIR="$DATA_DIR/cache"
export TWINLINK_LOG_DIR="$DATA_DIR/logs"
export TWINLINK_LOCAL_TOKEN="${TWINLINK_LOCAL_TOKEN:-demo-token-a}"
export TWINLINK_RELAY_URL="${TWINLINK_RELAY_URL:-http://127.0.0.1:8870}"
export TWINLINK_RELAY_TOKEN="${TWINLINK_RELAY_TOKEN:-relay-token-a}"
PORT="${TWINLINK_LOCAL_PORT:-8871}"

echo "TwinLink Demo User A: http://127.0.0.1:${PORT} (token: ${TWINLINK_LOCAL_TOKEN})"
echo "data: ${DATA_DIR}"
exec uv run uvicorn twinlink_core.main:app --host 127.0.0.1 --port "$PORT"
